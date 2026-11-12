"""The driver over the Codex CLI (`story_run.py --host codex`, CX1-15): launch, lifecycle, dispatch identity, reuse, money and
failure handling, with `codex` replaced by a stub that speaks the `codex exec --json` event stream of codex-cli 0.158.0
(`thread.started`, `item.completed`, `turn.completed`, `turn.failed`; a `resume` answers with the same stream, as the
subcommand takes `--json`). Nothing here starts a model or the real CLI.

What is pinned, scenario by scenario:
  * K-1 `codex_parser`: the event stream becomes the result shape `run_claude` reads (thread id, last agent message, steps as
    `num_turns`, summed usage); the last terminal event decides (`turn.failed`, an `error` before `turn.completed`); a stream
    with no terminal event, a resume answered in another thread, an empty stream and non-JSON lines are named, never a success.
  * K-2 `codex_command_and_prompt`: the argv of a fresh call and of a continuation, `-m` ALWAYS (the named model, else the
    data's `default_model.codex`), the project's sandbox and `-c` overrides, the role block and rule layer in a fresh prompt and
    NOT in a continuation; the Claude path is untouched.
  * K-3 `codex_lifecycle`: one dispatch through `run_claude`: the thread id is the session of the dispatch, the journal rows carry
    `host`, `usage`, the model actually used and the price with its label (or "price unknown", never `$0`), the in-flight record
    is cleared, a continuation of the SAME dispatch is `codex exec resume <thread>`, a NEW dispatch is a fresh thread; a login
    failure stops the driver as `auth` (the session is not stored), a broken stream is retried once, a CLI error or an
    incomplete stream no row knows comes back as the call's own error; a role without Bash is named.
  * K-4 `codex_story_s1`: the real driver process over the seeded project, S1 end to end.
  * K-5 `claude_path_is_as_it_was`: the argv, the stdin and the journal rows of a Claude call carry no `host`, `usage` or `cost_basis`.
  * K-6 `host_is_read_only_where_the_node_says`: `self.host` appears in the members of `Driver` listed here and nowhere else.
  * K-7 `host_battery`: `--host` / `driver.host` at and beyond the boundary of `HOSTS`; the start refusals (no default model,
    F-5 the other host's sessions) and their doors.
  * K-8 `no_codex_executable`: no `codex` on an empty PATH stops the first call before any journal row.
  * K-9 the end row the driver writes on Codex is read by `dispatch_liveness.driver_session_end` (in K-3).
  * Fix round t-1135 (critic t-1133): K-10 `codex_pricer` (F-2: ONE pricer, `cost_capture.value_usage`; the critic's control usage at the
    long tier, AT and BEYOND the threshold, rates read from the rates file; unknown / fractional / odd counts are `price unknown`),
    K-11 `codex_thread_total` (F-1: `total_cost_usd` is the thread's running total, `call_cost_usd` the call's price; a cheaper
    second call, an unpriced call, a first call unpriced, a rerun), K-12 `stale_host_key` (m-1), K-13 `codex_label_on_pages` (F-3: the
    dashboard's story card and the retro print the tariff label once, nothing on a Claude story); F-4 in K-1 and K-3 (`no_events`);
    m-2 / m-13 in K-7.
"""
import ast
import contextlib
import html
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
import story_run_common as T  # noqa: E402
from story_run_common import GOOD_MANIFEST, SCOUT_DIGEST, run_scenarios, seed, set_control, stub_calls  # noqa: E402

TERRA = "gpt-5.6-terra"
LABEL = "estimate: default tariffs (references/model-rates.json); long-context tier by the turn's sum"

# The stub `codex`: argv is `exec [resume <id>] ... -`, the prompt is stdin. A role is read back from the block the driver puts
# first in a fresh prompt (`# Factory role instructions: <role>`); a continuation has no such block, so the stub sees it as a
# resume by the `resume` subcommand alone. `control["stream"]` bends the success path: incomplete (no terminal event), empty,
# noise (a non-JSON line before the events), wrong_thread (a resume answered in another thread), error_then_complete.
CODEX_STUB = r'''
import hashlib, json, os, re, sys
from pathlib import Path
argv = sys.argv[1:]
control = json.loads(Path(os.environ["STUB_CONTROL"]).read_text(encoding="utf-8"))
log = Path(os.environ["STUB_LOG"])
prompt = sys.stdin.buffer.read().decode("utf-8")
resume = argv[argv.index("resume") + 1] if "resume" in argv else ""
role_m = re.search(r"^# Factory role instructions: (\S+)", prompt, re.M)
role = role_m.group(1) if role_m else ""
kind = "resume" if resume else ("role" if role else "conductor")
earlier = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
index = len([e for e in earlier if e["kind"] == kind and e["role"] == role])
fail = control.get("fail") or {}
tag = str(fail.get("tag") or "fail")
failures_so_far = len([e for e in earlier if e.get("failed") == tag])
row = {"kind": kind, "role": role, "prompt": prompt, "resume": resume, "argv": argv, "cwd": os.getcwd()}
def pick(value):
    if isinstance(value, list):
        return value[min(index, len(value) - 1)]
    return value
def receipt(thread):
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    project = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if not (plugin and project and thread) or control.get("receipt") == "none":
        return
    root = str(Path(plugin).resolve())
    try:
        version = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version", "")
    except Exception:
        version = ""
    path = Path(project) / "qa-factory" / "state" / "host-receipts" / (
        "package-" + hashlib.sha256(thread.encode("utf-8")).hexdigest()[:16] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": thread, "roots": [dict(plugin_root=root, version=version,
                                first_hook="SessionStart")], "observed_at": "stub"}), encoding="utf-8")
if kind == "role":
    dispatch_m = re.search(r"Dispatch: (\S+)\.", prompt)
    dispatch = dispatch_m.group(1) if dispatch_m else "unknown"
    task_m = re.search(r"Artifacts dir: (\S+)", prompt)
    spec = control.get("roles", {}).get(role, {})
    if task_m:
        task_dir = Path(task_m.group(1))
        for rel, content in (spec.get("files") or {}).items():
            p = task_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    result, thread = pick(spec.get("result", "")), "thr-" + dispatch
elif kind == "resume":
    result, thread = pick(control.get("resume", {}).get("result", "")), resume
else:
    spec = control.get("conductor", {})
    verdict = {"action": pick(spec.get("action", "continue")), "did": spec.get("did", "stub"),
               "question": spec.get("question", "")}
    result, thread = spec.get("text", "I looked.") + "\n" + json.dumps(verdict), "thr-conductor-%d" % (index + 1)
failing = bool(fail) and failures_so_far < int(fail.get("times", 1))
row["failed"] = tag if failing else ""
with log.open("a", encoding="utf-8") as h:
    h.write(json.dumps(row) + "\n")
receipt(thread)
if failing:
    if fail.get("shape") == "exit":
        print(fail.get("message", "boom"), file=sys.stderr)
        sys.exit(2)
    print(json.dumps({"type": "thread.started", "thread_id": thread}))
    print(json.dumps({"type": "turn.failed", "error": {"message": fail.get("message", "stream disconnected before completion")}}))
    sys.exit(1)
stream = control.get("stream")
def emit(event):
    print(json.dumps(event))
if stream == "empty":
    sys.exit(0)
if stream == "plain":
    print("here is my answer in plain words, with no event at all")
    sys.exit(0)
if stream == "noise":
    print("this line is not JSON at all")
emit({"type": "thread.started", "thread_id": "thr-other" if stream == "wrong_thread" and kind == "resume" else thread})
emit({"type": "turn.started"})
if kind != "resume":
    emit({"type": "item.completed", "item": {"id": "item_0", "type": "command_execution", "command": "git status"}})
if stream == "error_then_complete":
    emit({"type": "error", "message": "reconnecting 1/5"})
emit({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": result}})
if stream == "incomplete":
    sys.exit(0)
usage = {"input_tokens": 300, "cached_input_tokens": 280, "output_tokens": 20} if kind == "resume" else \
    {"input_tokens": 1200, "cached_input_tokens": 800, "output_tokens": 50}
if control.get("usages"):          # the usage of the Nth call of the run (a list), the last one for every later call
    usage = control["usages"][min(len(earlier), len(control["usages"]) - 1)]
emit({"type": "turn.completed", "usage": usage})
'''


def codex_env(root: Path, env: dict) -> dict:
    stub = root / "fake_codex.py"
    stub.write_text(CODEX_STUB, encoding="utf-8")
    return dict(env, STORY_RUN_CODEX=str(stub))


def codex_driver(root: Path, env: dict, task: str, **overrides):
    os.environ["STORY_RUN_CODEX"] = env["STORY_RUN_CODEX"]
    return T.driver_for(root, env, task, **dict({"host": "codex", "model": None}, **overrides))


def role_prompt(task_root: Path, dispatch: str) -> str:
    return (f"You are qa-scout. Ticket: QA-1. Dispatch: {dispatch}.\nArtifacts dir: {task_root}\n"
            "Inputs:\n  none\nYour final message is the handoff form only.")


def rows_of(task_root: Path) -> list:
    return [json.loads(l) for l in (task_root / "state/driver-runs.jsonl").read_text(encoding="utf-8").splitlines()]


def set_config(root: Path, **driver) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["driver"] = driver
    path.write_text(json.dumps(cfg), encoding="utf-8")


# --- K-1 the parser ---------------------------------------------------------------------------
def codex_parser() -> None:
    import story_run
    stream = "\n".join([
        '{"type":"thread.started","thread_id":"thr-1"}',
        '{"type":"turn.started"}',
        '{"type":"item.completed","item":{"id":"i1","type":"command_execution","command":"ls"}}',
        '{"type":"item.completed","item":{"id":"i2","type":"agent_message","text":"first words"}}',
        '{"type":"item.completed","item":{"id":"i3","type":"agent_message","text":"qa-scout S1 QA-1 · ok"}}',
        '{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":7}}',
        '{"type":"turn.completed","usage":{"input_tokens":50,"cached_input_tokens":50,"output_tokens":3}}'])
    got = story_run.parse_codex_jsonl(stream)
    check_eq("parser: the thread id is the session", got["session_id"], "thr-1")
    check_eq("parser: the LAST agent message is the result", got["result"], "qa-scout S1 QA-1 · ok")
    check_eq("parser: completed items are the turns", got["num_turns"], 3)
    check_eq("parser: usage is summed over the turns", got["usage"], {"input_tokens": 150, "cached_input_tokens": 90, "output_tokens": 10})
    check("parser: a completed turn is no error", not got["is_error"] and got["subtype"] == "success")
    failed = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t2"}\n'
                                         '{"type":"turn.failed","error":{"message":"Please run codex login"}}')
    check("parser: turn.failed is an error with its message as the text",
          failed["is_error"] and failed["subtype"] == "turn_failed" and failed["result"] == "Please run codex login")
    check_eq("parser: a failed turn keeps the thread id", failed["session_id"], "t2")
    after = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t3"}\n'
                                        '{"type":"item.completed","item":{"type":"agent_message","text":"Checking the repo first"}}\n'
                                        '{"type":"turn.failed","error":{"message":"You have hit your usage limit. resets at 14:00"}}')
    check_eq("parser: a failure AFTER agent text is the result (what the classifier reads), the text is partial",
             (after["is_error"], after["result"], after.get("partial")),
             (True, "You have hit your usage limit. resets at 14:00", "Checking the repo first"))
    cut = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t4"}\n'
                                      '{"type":"item.completed","item":{"type":"agent_message","text":"half an answer"}}')
    check_eq("parser E-3/F-10: a stream with no terminal event is an error, the agent text is partial, never the result",
             (cut["is_error"], cut["subtype"], cut["result"], cut.get("partial")),
             (True, "turn_incomplete", story_run.INCOMPLETE_STREAM, "half an answer"))
    import infra_failure
    rules, _notes = infra_failure.rules()
    check_eq("parser F-10: and that call is `unclassified` to the infrastructure rows, on Codex too",
             infra_failure.classify({"is_error": True, "exit_code": 0, "result": cut["result"], "stderr": ""}, rules, "codex"),
             {"kind": "unclassified", "rule": ""})
    mixed = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t5"}\n'
                                        '{"type":"error","message":"reconnecting 1/5"}\n'
                                        '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n'
                                        '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}')
    check_eq("parser E-5: an error event before turn.completed is a note of the stream, the turn is a success",
             (mixed["is_error"], mixed["result"], mixed["errors"]), (False, "done", ["reconnecting 1/5"]))
    only_error = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t6"}\n{"type":"error","message":"boom"}')
    check_eq("parser S-7: an error event and no terminal event is the failure, its message the result",
             (only_error["is_error"], only_error["result"], only_error["subtype"]), (True, "boom", "error_event"))
    same = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"thr-9"}\n'
                                       '{"type":"item.completed","item":{"type":"agent_message","text":"repaired"}}\n'
                                       '{"type":"turn.completed","usage":{}}', resume="thr-9")
    check_eq("parser: a resume answered in its own thread is a success", (same["session_id"], same["is_error"]), ("thr-9", False))
    other = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"thr-NEW"}\n'
                                        '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n'
                                        '{"type":"item.completed","item":{"type":"agent_message","text":"hello again"}}\n'
                                        '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}', resume="thr-9")
    check_eq("parser E-7: a resume answered in ANOTHER thread is resume_mismatch under the requested session, the new id in errors",
             (other["is_error"], other["subtype"], other["session_id"], other["errors"], other["num_turns"]),
             (True, "resume_mismatch", "thr-9", ["thr-NEW"], 0))
    plain = story_run.parse_codex_jsonl("the answer\nin two lines", resume="thr-9")
    check_eq("parser F-4: a stream of text with no event is unknown (`no_events`), never completed: the driver's phrase is the result, "
             "the text is kept apart as `partial`, the session is the requested one",
             (plain["session_id"], plain["is_error"], plain["subtype"], plain["result"], plain.get("partial"), plain["events"], plain["noise"],
              plain["num_turns"]),
             ("thr-9", True, "no_events", story_run.NO_EVENTS_STREAM, "the answer\nin two lines", False, 2, None))
    check_not_in("parser F-4: the text is never the result", "the answer", plain["result"])
    # the sibling that stays as it was: nothing at all (blank lines too) is not an error and not a result
    for blank in ("", "\n\n  \n"):
        check_eq(f"parser E-6: {blank!r} (no text, no event) is no error, no result, no partial",
                 (story_run.parse_codex_jsonl(blank)["is_error"], story_run.parse_codex_jsonl(blank)["result"],
                  "partial" in story_run.parse_codex_jsonl(blank)), (False, "", False))
    # JSON that is no event is text too: {"a": 1} has neither `type` nor `thread_id`
    check_eq("parser F-4: JSON lines that are no event count as text", story_run.parse_codex_jsonl('{"a": 1}')["subtype"], "no_events")
    check_eq("parser F-4: and the text of a no_events stream is not a result to the infrastructure rows either (`unclassified`)",
             infra_failure.classify({"is_error": True, "exit_code": 0, "result": plain["result"], "stderr": ""}, rules, "codex"),
             {"kind": "unclassified", "rule": ""})
    # m-12: an error object with no `message` is read as JSON, not as a Python repr
    objects = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t9"}\n'
                                          '{"type":"turn.failed","error":{"code":"E1","detail":"x"}}')
    check_eq("parser m-12: an error object with no message becomes its JSON text", objects["result"], '{"code": "E1", "detail": "x"}')
    empty = story_run.parse_codex_jsonl("")
    check("parser E-6: nothing in is nothing out, not an error",
          empty["result"] == "" and not empty["is_error"] and not empty["events"] and empty["num_turns"] is None)
    noisy = story_run.parse_codex_jsonl('garbage {\n{"type":"thread.started","thread_id":"t7"}\n{broken json\n'
                                        '{"type":"item.completed","item":{"type":"agent_message","text":"x"}}\n'
                                        '{"type":"turn.completed","usage":{}}')
    check_eq("parser: lines that are no event are counted, the events around them still read", (noisy["noise"], noisy["result"]), (2, "x"))
    content = story_run.parse_codex_jsonl('{"type":"item.completed","item":{"type":"agent_message",'
                                          '"content":[{"type":"output_text","text":"from content"}]}}\n{"type":"turn.completed"}')
    check_eq("parser: a content list is read as text", content["result"], "from content")
    verdict = story_run.parse_codex_jsonl('{"type":"thread.started","thread_id":"t8"}\n'
                                          '{"type":"item.completed","item":{"type":"agent_message","text":"I looked.\\n{\\"action\\": \\"continue\\"}"}}\n'
                                          '{"type":"turn.completed"}')
    check_in("parser: a conductor's verdict line inside the message text survives", '{"action": "continue"}', verdict["result"])


# --- K-2 the command and the prompt ----------------------------------------------------------
def codex_command_and_prompt() -> None:
    task = "QA-1"
    root, task_root, env = seed(task)
    env = codex_env(root, env)
    try:
        driver = codex_driver(root, env, task)
        check_eq("the host is codex", driver.host, "codex")
        check_eq("with no --model the model is the data's default, the latest Terra", (driver.model, driver.model_explicit), (TERRA, False))
        stub = [sys.executable, env["STORY_RUN_CODEX"]]
        check_eq("a fresh call: codex exec --json -C <project> --skip-git-repo-check -m <default> -",
                 driver.codex_cmd(), stub + ["exec", "--json", "-C", str(driver.project), "--skip-git-repo-check", "-m", TERRA, "-"])
        check_eq("a continuation: codex exec resume <thread> --json --skip-git-repo-check -m <default> - (no -C, no -s)",
                 driver.codex_cmd(resume="thr-1"), stub + ["exec", "resume", "thr-1", "--json", "--skip-git-repo-check", "-m", TERRA, "-"])
        check_eq("claude_cmd delegates to codex_cmd on this host", driver.claude_cmd("p", agent="qa-scout"), driver.codex_cmd())
        empty = codex_driver(root, env, task, model="")
        check_eq("`--model \"\"` is no name: the default model, and it is passed", (empty.model, empty.codex_cmd()[-3:-1]), (TERRA, ["-m", TERRA]))
        named = codex_driver(root, env, task, model="gpt-5.3-codex")
        cmd = named.codex_cmd()
        check_eq("a named model wins over the default and is the one passed", (named.model, cmd[cmd.index("-m") + 1], cmd.count("-m")),
                 ("gpt-5.3-codex", "gpt-5.3-codex", 1))
        named.codex_cfg = {"sandbox": "workspace-write",
                           "config": {"approval_policy": '"never"', "a": 1, "features.x": True, "list": ["a"]}}
        cmd = named.codex_cmd()
        check("the project's sandbox goes as -s on a fresh call", cmd[cmd.index("-s") + 1] == "workspace-write")
        check_eq("and its -c overrides, sorted, as key=value (a string as given, anything else as JSON/TOML)",
                 [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"], ["a=1", 'approval_policy="never"', "features.x=true", 'list=["a"]'])
        check("a continuation carries no sandbox (resume has no -s)", "-s" not in named.codex_cmd(resume="t"))
        # the prompt
        layer = driver.system_file("qa-scout", "S1-qa-scout-1", [])
        sent = driver.host_prompt("do the task", agent="qa-scout", system_file=layer)
        check("a fresh prompt starts with the role's own definition (the hook's heading, one function)",
              sent.startswith("# Factory role instructions: qa-scout\n"))
        check_not_in("the frontmatter is not in it (no `name:` line)", "\nname: qa-scout", sent)
        check_in("then the rule layer the driver built, under the heading run_role's text relies on", "\n\n# Rule layer (your system prompt)\n", sent)
        check_in("then the task, last", "\n\n# Task\ndo the task", sent)
        check("the role is before the layer, the layer before the task",
              sent.index("# Factory role instructions") < sent.index("# Rule layer") < sent.index("# Task\n"))
        check_not_in("a Bash-less role gets no Desktop tool block in a `codex exec` prompt (F-8)", "Codex Desktop",
                     driver.host_prompt("x", agent="qa-case-critic"))
        check_eq("a continuation gets the prompt alone", driver.host_prompt("go on", agent="qa-scout", resume="thr-1", system_file=layer), "go on")
        conductor = driver.host_prompt("judge this", system_file=driver.plugin / "references" / "conductor.md")
        check("the conductor has no role block, only the rule layer and the task",
              conductor.startswith("# Rule layer (your system prompt)\n") and conductor.endswith("# Task\njudge this"))
        check_eq("no role file, no block", driver.host_prompt("x", agent="no-such-role"), "# Task\nx")
        # continue_command
        check_in("continue_command names the host when the flag named it", "--host codex", codex_driver(root, env, task).continue_command())
        check_not_in("and repeats no model that was not named", "--model", driver.continue_command())
        check_in("a named model on Codex is repeated", "--model gpt-5.3-codex", named.continue_command())
        # the Claude path is as it was
        plain = T.driver_for(root, env, task)
        check_eq("no --host: the host is claude", (plain.host, plain.model), ("claude", "sonnet"))
        check_eq("and the prompt is passed as it is", plain.host_prompt("p", agent="qa-scout", system_file=layer), "p")
        check_eq("and claude_cmd is claude -p ... --model sonnet", (plain.claude_cmd("p")[2], plain.claude_cmd("p").index("--model")),
                 ("-p", plain.claude_cmd("p").index("--model")))
        check_not_in("and continue_command names no host", "--host", plain.continue_command())
        check_in("a Claude run started with --host claude repeats it (E-15)", "--host claude",
                 T.driver_for(root, env, task, host="claude").continue_command())
    finally:
        harness.cleanup(root)


# --- K-3 one dispatch through run_claude -----------------------------------------------------
def codex_lifecycle() -> None:
    import story_run
    import dispatch_liveness
    task = "QA-1"
    root, task_root, env = seed(task)
    env = codex_env(root, env)
    try:
        driver = codex_driver(root, env, task)
        set_control(root, {"roles": {"qa-scout": {"result": "first answer"}}, "resume": {"result": "repaired answer"}})
        dispatch = "S1-qa-scout-1"
        result = driver.run_claude("role", role_prompt(task_root, dispatch), role="qa-scout", dispatch=dispatch,
                                   stage="S1", system_file=driver.system_file("qa-scout", dispatch, []))
        check_eq("the thread id is the dispatch's session", result["session_id"], "thr-" + dispatch)
        check_eq("the last agent message is the result", result["result"], "first answer")
        check_eq("two completed items are two turns: the session worked", result["num_turns"], 2)
        check_eq("usage travels with the result", result.get("usage"), {"input_tokens": 1200, "cached_input_tokens": 800, "output_tokens": 50})
        check_eq("the price is a number from the default tariffs (400 in x 2 + 800 cached x 0.2 + 50 out x 12, per million)",
                 (round(result["total_cost_usd"], 8), result["cost_basis"]), (0.00156, LABEL))
        check_eq("the session is stored for the dispatch, with the host it belongs to (F-5)",
                 (driver.state["sessions"].get(dispatch), driver.state.get("host")), ("thr-" + dispatch, "codex"))
        check("nothing stays in flight", "in_flight" not in driver.state)
        calls = stub_calls(root)
        check_eq("one role call", [c["kind"] for c in calls], ["role"])
        check_eq("launched as codex exec --json -C <project>", calls[0]["argv"][:4], ["exec", "--json", "-C", str(driver.project)])
        check_eq("the prompt comes on stdin (argv ends in -), and the model is passed", (calls[0]["argv"][-1], TERRA in calls[0]["argv"]), ("-", True))
        check_in("the role block is in the prompt", "# Factory role instructions: qa-scout", calls[0]["prompt"])
        rows = rows_of(task_root)
        check_eq("the journal: a launched row, then the call's row", [r["kind"] for r in rows], ["launched", "role"])
        check_eq("both rows name the host and the model actually used", [(r.get("host"), r.get("model")) for r in rows],
                 [("codex", TERRA), ("codex", TERRA)])
        check_eq("the call's row carries the usage, the price and its label", (rows[1].get("usage", {}).get("input_tokens"),
                 round(rows[1]["total_cost_usd"], 8), rows[1]["cost_basis"]), (1200, 0.00156, LABEL))
        check_eq("F-1: the FIRST row of a thread has its call's price as the total and as the call (nothing before it)",
                 (round(rows[1]["call_cost_usd"], 9), rows[1]["total_cost_usd"] == rows[1]["call_cost_usd"]), (0.00156, True))
        # K-9: the end row is read by the liveness reader as a return with exit 0
        end = dispatch_liveness.driver_session_end(root, task, dispatch)
        check("K-9: dispatch_liveness reads the Codex end row as a return with exit 0", bool(end) and end[1] == 0, repr(end))
        # continuity: the same dispatch goes on in its own thread
        again = driver.run_claude("role", "repair your handoff", role="qa-scout", dispatch=dispatch, stage="S1",
                                  resume=result["session_id"], resume_reason="the exit gate refused the form")
        calls = stub_calls(root)
        check_eq("the continuation is codex exec resume <thread> --json", calls[1]["argv"][:4], ["exec", "resume", "thr-" + dispatch, "--json"])
        check_eq("its prompt is the words alone (no role block, no rule layer)", calls[1]["prompt"], "repair your handoff")
        check_eq("its answer is the result under the same session", (again["session_id"], again["result"]), ("thr-" + dispatch, "repaired answer"))
        check_eq("the journal marks the resume and its reason", (rows_of(task_root)[-1]["resumed"], rows_of(task_root)[-1].get("resume_reason")),
                 (True, "the exit gate refused the form"))
        # F-1: `total_cost_usd` is the thread's running total in every row, the call's own price is `call_cost_usd`; the resume
        # (300 in, 280 cached, 20 out: $0.000336) is CHEAPER than the first call ($0.00156), which is not 'unknown'
        import driver_journal as DJ
        thread = [r for r in rows_of(task_root) if r.get("session_id") == "thr-" + dispatch and r["kind"] == "role"]
        check_eq("F-1: the thread's two rows carry its running total and each call's own price",
                 [(round(r["total_cost_usd"], 9), round(r["call_cost_usd"], 9)) for r in thread],
                 [(0.00156, 0.00156), (0.001896, 0.000336)])
        check_eq("F-1: the result of the resume says the same (the total of the thread, then the call)",
                 (round(again["total_cost_usd"], 9), round(again["call_cost_usd"], 9)), (0.001896, 0.000336))
        charged, unknown = DJ.root_charged({"thr-" + dispatch: {"rows": thread, "journals": [task]}})
        check_eq("F-1: the reader prices the thread at the sum of its calls even though the second call is cheaper",
                 ({k: round(v, 9) for k, v in charged.items()}, unknown), ({"thr-" + dispatch: 0.001896}, []))
        check_eq("F-1: and its increments are the two calls' prices", [round(v, 9) for v in DJ.row_increments(thread)], [0.00156, 0.000336])
        # a new dispatch is a new session
        other = driver.run_claude("role", role_prompt(task_root, "S4-qa-case-designer-2"), role="qa-scout",
                                  dispatch="S4-qa-case-designer-2", stage="S4")
        check_eq("a new dispatch id gets its own thread", other["session_id"], "thr-S4-qa-case-designer-2")
        check_not_in("and starts fresh (no resume)", "resume", stub_calls(root)[-1]["argv"])
        # a resume answered in another thread is an error to the caller, never a new session (E-7)
        set_control(root, {"stream": "wrong_thread", "resume": {"result": "x"}})
        moved = driver.run_claude("role", "go on", role="qa-scout", dispatch=dispatch, stage="S1", resume="thr-" + dispatch,
                                  resume_reason="a caller's resume")
        check_eq("E-7: the caller's resume answered in another thread comes back as resume_mismatch under the requested session",
                 (moved["is_error"], moved["subtype"], moved["session_id"]), (True, "resume_mismatch", "thr-" + dispatch))
        check_eq("and the dispatch's stored session is still the requested one", driver.state["sessions"][dispatch], "thr-" + dispatch)
        # a login refusal stops the driver as `auth` and records the cut-off call; classify runs BEFORE the session is stored
        set_control(root, {"roles": {"qa-scout": {"result": "never"}},
                           "fail": {"tag": "auth", "message": "Error: Please run `codex login` first", "times": 1}})
        try:
            driver.run_claude("role", role_prompt(task_root, "S2-qa-requirements-tester-1"), role="qa-scout",
                              dispatch="S2-qa-requirements-tester-1", stage="S2")
            check("a login refusal stops the driver", False, "no InfraStop was raised")
        except story_run.InfraStop as stop:
            check_eq("as an auth failure", stop.kind, "auth")
        record = driver.state.get("interrupted", {}).get("S2-qa-requirements-tester-1") or {}
        check_eq("the cut-off call is recorded with its kind", record.get("kind"), "auth")
        check("and is not stored as the dispatch's session", "S2-qa-requirements-tester-1" not in driver.state["sessions"])
        # a broken stream is retried once, and the retry's answer is taken
        slept = []
        driver.sleep = slept.append
        set_control(root, {"roles": {"qa-scout": {"result": "after the retry"}},
                           "fail": {"tag": "stream", "message": "stream disconnected before completion", "times": 1}})
        third = driver.run_claude("role", role_prompt(task_root, "S3-qa-test-strategist-1"), role="qa-scout",
                                  dispatch="S3-qa-test-strategist-1", stage="S3")
        check_eq("the retry's answer is the result", third["result"], "after the retry")
        check("the driver waited between the two calls", len(slept) == 1)
        s3 = [r for r in rows_of(task_root) if r.get("dispatch") == "S3-qa-test-strategist-1" and r["kind"] == "role"]
        check_eq("the journal: one transient failure, then the retry", [(r.get("infra"), r["retry"]) for r in s3], [("transient", 0), (None, 1)])
        # a CLI error no row knows is the role's own failure: returned, not raised
        set_control(root, {"roles": {"qa-scout": {"result": "x"}},
                           "fail": {"tag": "cli", "shape": "exit", "message": "error: unexpected argument '--nope'", "times": 1}})
        fourth = driver.run_claude("role", role_prompt(task_root, "S5-qa-automator-1"), role="qa-scout", dispatch="S5-qa-automator-1", stage="S5")
        check("an unknown CLI failure comes back as an error result", fourth["is_error"] and fourth["exit_code"] == 2)
        check_in("with the CLI's words as the text", "unexpected argument", fourth["result"])
        # F-10, E-3: a stream with no terminal event is the call's error, unclassified, and its price is unknown, not $0
        set_control(root, {"stream": "incomplete", "roles": {"qa-scout": {"result": "half"}}})
        cut = driver.run_claude("role", role_prompt(task_root, "S6-qa-test-runner-1"), role="qa-scout", dispatch="S6-qa-test-runner-1", stage="S6")
        check_eq("F-10: an incomplete stream is an error result, classified `unclassified`, the agent text kept apart",
                 (cut["is_error"], cut["subtype"], (cut["infra"] or {}).get("kind"), cut["result"]),
                 (True, "turn_incomplete", "unclassified", story_run.INCOMPLETE_STREAM))
        check_eq("and it has no price: the usage counts are in the row, the cost field says unknown, never 0",
                 (cut["total_cost_usd"], cut["cost_basis"].startswith("price unknown")), (None, True))
        # (vi) an empty stream and a non-JSON line are named in the driver journal
        set_control(root, {"stream": "empty", "roles": {"qa-scout": {"result": "x"}}})
        empty = driver.run_claude("role", role_prompt(task_root, "S7-qa-test-runner-1"), role="qa-scout", dispatch="S7-qa-test-runner-1", stage="S7")
        check_eq("E-6: an EMPTY stream with exit 0 claims nothing: no error, an empty result, a note row (the rows below)",
                 (empty["is_error"], empty["subtype"], empty["result"]), (False, "", ""))
        # F-4: text and no event is a claim the driver cannot read: unknown, never a success - and the text is kept as evidence
        set_control(root, {"stream": "plain", "roles": {"qa-scout": {"result": "x"}}})
        text_only = driver.run_claude("role", role_prompt(task_root, "S7-qa-test-runner-2"), role="qa-scout", dispatch="S7-qa-test-runner-2", stage="S7")
        check_eq("F-4: a stream of plain text and no event, exit 0, is an error result `no_events`, unclassified, the driver's phrase as the text",
                 (text_only["is_error"], text_only["subtype"], (text_only["infra"] or {}).get("kind"), text_only["result"], text_only["exit_code"]),
                 (True, "no_events", "unclassified", story_run.NO_EVENTS_STREAM, 0))
        check_eq("F-4: its price is unknown (no usage was read), never 0", (text_only["total_cost_usd"], text_only["call_cost_usd"]), (None, None))
        check("F-4: and it is not stored as the dispatch's session", "S7-qa-test-runner-2" not in driver.state["sessions"])
        evidence = [r["note"] for r in rows_of(task_root) if r["kind"] == "note" and r.get("dispatch_id") == "S7-qa-test-runner-2"]
        check("F-4: the text it printed is kept in a note row of the journal as evidence",
              len(evidence) == 1 and "here is my answer in plain words" in evidence[0] and "no event" in evidence[0], repr(evidence))
        set_control(root, {"stream": "noise", "roles": {"qa-scout": {"result": "fine"}}})
        noisy = driver.run_claude("role", role_prompt(task_root, "S8-qa-test-runner-1"), role="qa-scout", dispatch="S8-qa-test-runner-1", stage="S8")
        notes = [r["note"] for r in rows_of(task_root) if r["kind"] == "note"]
        check("(vi): the empty stream is named in the driver journal", any("stream was empty" in n for n in notes), repr(notes))
        check("(vi): and so is a line that was no event", any("not events" in n for n in notes), repr(notes))
        check_eq("and the events around the noise are still read", noisy["result"], "fine")
        # E-5: an error event before a completed turn does not fail the call
        set_control(root, {"stream": "error_then_complete", "roles": {"qa-scout": {"result": "done anyway"}}})
        done = driver.run_claude("role", role_prompt(task_root, "S9-qa-test-runner-1"), role="qa-scout", dispatch="S9-qa-test-runner-1", stage="S9")
        check_eq("E-5: the completed turn is the result", (done["is_error"], done["result"]), (False, "done anyway"))
        # F-8: a role without Bash runs as is, and the gap is named in the driver journal
        set_control(root, {"roles": {"qa-case-critic": {"result": "ok"}}})
        driver.run_claude("role", role_prompt(task_root, "S4-qa-case-critic-1").replace("qa-scout", "qa-case-critic"), role="qa-case-critic",
                          dispatch="S4-qa-case-critic-1", stage="S4", system_file=None)
        gaps = [r for r in rows_of(task_root) if r["kind"] == "note" and "qa-case-critic" in r["note"] and "lists no Bash" in r["note"]]
        check_eq("F-8: the role without Bash runs and the gap is a note row of its dispatch", [g["dispatch_id"] for g in gaps], ["S4-qa-case-critic-1"])
        # money: a model with no tariff is `price unknown`, a named model with one is priced, the usage counts stay
        unknown = codex_driver(root, env, task, model="gpt-9-unheard-of")
        set_control(root, {"roles": {"qa-scout": {"result": "y"}}})
        priced_not = unknown.run_claude("role", role_prompt(task_root, "S1-qa-scout-9"), role="qa-scout", dispatch="S1-qa-scout-9", stage="S1")
        check_eq("(iii) no tariff for the model: the cost line says so, the counts stay, the number is None",
                 (priced_not["total_cost_usd"], priced_not["cost_basis"], priced_not["usage"]["input_tokens"]),
                 (None, "price unknown: no tariff for gpt-9-unheard-of", 1200))
        rows = rows_of(task_root)
        last = [r for r in rows if r.get("dispatch") == "S1-qa-scout-9" and r["kind"] == "role"][-1]
        check_eq("and the journal row carries the model that was named", (last["model"], last["total_cost_usd"]), ("gpt-9-unheard-of", None))
    finally:
        harness.cleanup(root)


# --- K-4 the real driver process, S1 end to end ----------------------------------------------
def codex_story_s1() -> None:
    task = "QA-9"
    root, task_root, env = seed(task)
    env = codex_env(root, env)
    try:
        set_control(root, {"roles": {"qa-scout": {
            "files": {"work/context-manifest.json": json.dumps(GOOD_MANIFEST).replace("{task}", task),
                      "work/context-bundle.json": "{}"},
            "result": "I have collected the sources and everything went well. The manifest is written."}},
            "resume": {"result": SCOUT_DIGEST.replace("{task}", task)}})
        out = T.run_driver(root, env, "--task", task, "--max-boundaries", "1", "--host", "codex")
        T.eq("S1 under codex ends in a done stage", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        calls = stub_calls(root)
        check_eq("one role call and one resume", [c["kind"] for c in calls], ["role", "resume"])
        check_eq("the role was a fresh codex exec, with the default model", (calls[0]["argv"][:2], TERRA in calls[0]["argv"]), (["exec", "--json"], True))
        check_in("with its role block", "# Factory role instructions: qa-scout", calls[0]["prompt"])
        check_in("and the rule layer", "# Rule layer (your system prompt)", calls[0]["prompt"])
        check_eq("the handoff was resumed in the SAME thread, with the event stream on", calls[1]["argv"][:4],
                 ["exec", "resume", "thr-S1-qa-scout-1", "--json"])
        check_in("asking for the form", "print your handoff in the exact form", calls[1]["prompt"])
        check_not_in("without the role block again", "# Factory role instructions", calls[1]["prompt"])
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        check_eq("S1 is done on the resumed digest", pipeline["stages"]["S1"]["status"], "done")
        check_eq("bind recorded the thread id as the dispatch's agent id", pipeline["stages"]["S1"].get("agent_id"), "thr-S1-qa-scout-1")
        import host_dispatch
        binding = json.loads(Path(host_dispatch.binding_path(root, "thr-S1-qa-scout-1")).read_text(encoding="utf-8"))
        check_eq("and the host binding names the dispatch the thread ran", (binding.get("dispatch_id"), binding.get("agent_id"), binding.get("task_id")),
                 ("S1-qa-scout-1", "thr-S1-qa-scout-1", task))
        runs = T.jsonl(task_root / "state/driver-runs.jsonl")
        check_eq("driver-runs.jsonl: the role, then its resume", [(r["kind"], r["resumed"]) for r in runs if r["kind"] != "note"],
                 [("role", False), ("role", True)])
        check_eq("both under the codex host, the model actually used", [(r.get("host"), r.get("model")) for r in runs], [("codex", TERRA)] * len(runs))
        state = json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8"))
        check_eq("the dispatch's session is the thread, and the story belongs to the codex host",
                 (state.get("sessions", {}).get("S1-qa-scout-1"), state.get("host")), ("thr-S1-qa-scout-1", "codex"))
        check("nothing stays in flight after the process ended", "in_flight" not in state)
        # F-5 in the real process: the story now holds Codex sessions, a Claude run is refused with its door
        back = T.run_driver(root, env, "--task", task, "--max-boundaries", "1", "--host", "claude")
        check_eq("F-5: a Claude run of a story with Codex sessions is refused, exit 1, no traceback",
                 (back.returncode, "Traceback" in back.stderr), (1, False))
        check_in("naming the door: the host the story started on", "--host codex", back.stdout)
    finally:
        harness.cleanup(root)


# --- K-5 the Claude path is as it was -----------------------------------------------------------
def claude_path_is_as_it_was() -> None:
    task = "QA-1"
    root, task_root, env = seed(task)
    try:
        driver = T.driver_for(root, env, task)
        set_control(root, {"roles": {"qa-scout": {"result": "an answer"}}})
        driver.run_claude("role", role_prompt(task_root, "S1-qa-scout-1"), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        call = stub_calls(root)[0]
        argv = call["argv"]
        check_eq("K-5: argv is claude -p --output-format json --permission-mode acceptEdits --model sonnet --allowedTools ...",
                 argv[:7], ["-p", "--output-format", "json", "--permission-mode", "acceptEdits", "--model", "sonnet"])
        check_eq("K-5: the prompt on stdin is the prompt as given", call["prompt"].splitlines(), role_prompt(task_root, "S1-qa-scout-1").splitlines())
        rows = rows_of(task_root)
        check("K-5: no row of a Claude call carries host, usage or cost_basis",
              not any(k in r for r in rows for k in ("host", "usage", "cost_basis")) and not any(r["kind"] == "note" for r in rows), repr(rows))
        check_eq("K-5: the price is what the CLI said", rows[-1]["total_cost_usd"], 0.0123)
        check("K-5: and the state has no host key", "host" not in driver.state)
    finally:
        harness.cleanup(root)


# --- K-6 I-1: the host is read only where the node says -------------------------------------------
def host_is_read_only_where_the_node_says() -> None:
    allowed = {"__init__", "host_refusal", "claude_cmd", "host_prompt", "host_note", "run_claude", "continue_command", "describe", "codex_cmd",
               "mark_host", "host_window_reason"}
    tree = ast.parse((harness.SCRIPTS / "story_run.py").read_text(encoding="utf-8"))
    driver = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Driver")
    readers = {fn.name for fn in driver.body if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(fn)
               if isinstance(n, ast.Attribute) and n.attr == "host" and isinstance(n.value, ast.Name) and n.value.id == "self"}
    check_eq("I-1: `self.host` is read only by the members the node lists (run_role, handoff, resume_role, conductor, delivery: none)",
             sorted(readers - allowed), [])
    check("and the node's own members do read it", {"claude_cmd", "run_claude", "host_prompt"} <= readers, repr(sorted(readers)))


# --- K-7 the host battery --------------------------------------------------------------------------
def host_battery() -> None:
    import story_run
    import infra_failure
    task = "QA-1"
    root, task_root, env = seed(task)
    env = codex_env(root, env)
    try:
        def build(**kw):
            try:
                return codex_driver(root, env, task, **dict({"host": None}, **kw))
            except story_run.Stop as stop:
                return stop
        for value, expected in (("codex", "codex"), (" codex ", "codex"), ("claude", "claude")):
            set_config(root, host=value)
            check_eq(f"config driver.host {value!r}", getattr(build(model="sonnet"), "host", None), expected)
        set_config(root)
        check_eq("config with no host: claude (the default)", build(model="sonnet").host, "claude")
        set_config(root, host=None)
        check_eq("config driver.host null is no word: claude", build(model="sonnet").host, "claude")
        for value in ("Codex", 7, "", "gemini", "c" + chr(0x43E) + "dex", "x" * 10000):
            set_config(root, host=value)
            got = build(model="sonnet")
            check(f"config driver.host {str(value)[:12]!r} (beyond HOSTS) is a Stop with the hosts listed, exit 1",
                  isinstance(got, story_run.Stop) and got.code == 1 and "claude, codex" in got.reason, repr(got))
        set_config(root, host="codex")
        check_eq("the flag wins over the config: --host claude with driver.host codex is claude", build(host="claude", model="sonnet").host, "claude")
        check_eq("and the rerun repeats it", "--host claude" in build(host="claude", model="sonnet").continue_command(), True)
        set_config(root, codex="not an object", host="codex")
        got = build()
        check("E-17: `driver.codex` that is no object is ignored (the default model, no sandbox)", got.host == "codex" and got.codex_cfg["config"] == {})
        set_config(root, codex={"config": ["not", "an", "object"], "sandbox": "danger-full-access"}, host="codex")
        got = build()
        check_eq("E-17: a `config` that is no object is ignored, the sandbox is passed as given", (got.codex_cfg["config"], got.codex_cfg["sandbox"]),
                 ({}, "danger-full-access"))
        # m-2: `-c key=value` takes a TOML value: an object and null have no one-line form, so they are left out WITH a note
        # (the project's word is never changed silently); strings, numbers, booleans and lists go as they did
        set_config(root, codex={"config": {"s": "text", "n": 3, "t": True, "l": ["a"], "nul": None, "obj": {"x": 1}, "empty": {}}, "sandbox": "read-only"},
                   host="codex")
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            got = build()
        check_eq("m-2: an object / null value of `driver.codex.config` is not passed, the others are",
                 sorted(got.codex_cfg["config"]), ["l", "n", "s", "t"])
        check("m-2: and the note names each key left out, and why",
              all(f"driver.codex.config.{k}` in config.json is {w}" in said.getvalue() for k, w in (("nul", "null"), ("obj", "an object"), ("empty", "an object"))),
              said.getvalue())
        cmd = got.codex_cmd()
        check_eq("m-2: the argv carries only the kept pairs", [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"], ["l=[\"a\"]", "n=3", "s=text", "t=true"])
        set_config(root)
        # E-18: `driver` that is no object
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["driver"] = ["x"]
        path.write_text(json.dumps(cfg), encoding="utf-8")
        check_eq("E-18: `driver` that is no object reads as no key", build(model="sonnet").host, "claude")
        set_config(root)
        # (i) TEMPORAL: the default_model key absent (an old data file)
        saved = infra_failure.rules
        try:
            infra_failure.rules = lambda: ({"failures": []}, [])
            refused = build(host="codex")
            check("(i) --model absent and `default_model` absent: a refusal, exit 2, naming the key and the file",
                  isinstance(refused, story_run.Stop) and refused.code == 2 and "default_model.codex" in refused.reason
                  and "references/driver-infra.json" in refused.reason, repr(refused))
            check_eq("(i) with `--model X` given the same old data file starts, X wins", (build(model="gpt-5.3-codex").model),
                     "gpt-5.3-codex")
            check_eq("(i) and the Claude host is not touched by the missing key", build(host="claude", model="sonnet").model, "sonnet")
            infra_failure.rules = lambda: ({"failures": [], "default_model": {"codex": 7}}, [])
            refused = build(host="codex")
            check("m-13: a `default_model.codex` that is present but no string is 'not a model name', not 'missing'",
                  isinstance(refused, story_run.Stop) and refused.code == 2 and "is not a model name in references/driver-infra.json" in refused.reason
                  and "is missing" not in refused.reason, repr(refused))
            infra_failure.rules = lambda: ({"failures": []}, [])
            check("m-13: and an absent one is still 'missing'", "is missing from references/driver-infra.json" in build(host="codex").reason, "")
        finally:
            infra_failure.rules = saved
        # F-5 both ways, and the legacy state (sessions, no host key = claude)
        state_path = task_root / "state" / "driver-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({"sessions": {"S1-qa-scout-1": "sess-1"}}), encoding="utf-8")
        got = build(host="codex")
        check("(iv) F-5: sessions of a state with no host key are Claude's: a Codex run is refused, the door `--host claude`",
              isinstance(got, story_run.Stop) and got.code == 1 and "--host claude" in got.reason and "new story" in got.reason, repr(got))
        check_eq("(iv) and the Claude run goes on", build(host="claude", model="sonnet").host, "claude")
        state_path.write_text(json.dumps({"sessions": {"S1-qa-scout-1": "thr-1"}, "host": "codex"}), encoding="utf-8")
        got = build(host="claude", model="sonnet")
        check("(iv) F-5: a state with Codex sessions refuses a Claude run, the door `--host codex`",
              isinstance(got, story_run.Stop) and "--host codex" in got.reason, repr(got))
        state_path.write_text(json.dumps({"interrupted": {"S2-x-1": {"kind": "auth", "session_id": "thr-2"}}, "host": "codex"}), encoding="utf-8")
        check("(iv) F-5: a cut-off call's session counts too",
              isinstance(build(host="claude", model="sonnet"), story_run.Stop))
        state_path.write_text(json.dumps({"sessions": {}, "host": "codex"}), encoding="utf-8")
        check_eq("(iv) F-5: a state with no session at all lets either host start", build(host="claude", model="sonnet").host, "claude")
        state_path.unlink()
        # argparse: the process, no traceback
        for args, code in ((["--host", "CODEX"], 2), (["--host", ""], 2), (["--host", "x" * 10000], 2), (["--host", "c" + chr(0x43E) + "dex"], 2),
                           (["--host", "gemini"], 2)):
            out = T.run_driver(root, env, "--task", task, "--dry-run", *args)
            check_eq(f"flag {args[1][:8]!r}: argparse refuses, exit {code}, no traceback", (out.returncode, "Traceback" in out.stderr), (code, False))
        for args in (["--host", "codex"], ["--host=codex"], ["--hos", "codex"], ["--host", "claude", "--host", "codex"]):
            out = T.run_driver(root, env, "--task", task, "--dry-run", *args)
            check(f"flag {' '.join(args)[:24]!r} is the codex host", out.returncode == 0 and "codex command shape:" in out.stdout,
                  out.stdout[-400:] + out.stderr[-400:])
        out = T.run_driver(root, env, "--task", task, "--dry-run", "--host", "codex", "--host", "claude")
        check("the last --host wins", out.returncode == 0 and "claude command shape:" in out.stdout, out.stdout[-300:])
        set_config(root, host="gemini")
        out = T.run_driver(root, env, "--task", task, "--dry-run")
        check_eq("a config host beyond HOSTS in the process: exit 1, the hosts listed, no traceback",
                 (out.returncode, "Traceback" in out.stderr, "claude, codex" in out.stdout), (1, False, True))
        set_config(root)
        out = T.run_driver(root, env, "--task", task, "--dry-run", "--host", "codex")
        check_in("describe names the model and where it came from", f"model {TERRA} (default_model.codex of references/driver-infra.json)", out.stdout)
    finally:
        harness.cleanup(root)


# --- K-8 E-1 -----------------------------------------------------------------------------------------
def no_codex_executable() -> None:
    import story_run
    task = "QA-1"
    root, task_root, env = seed(task)
    saved = {k: os.environ.get(k) for k in ("PATH", "STORY_RUN_CODEX")}
    try:
        os.environ.pop("STORY_RUN_CODEX", None)
        os.environ["PATH"] = str(root / "no-such-bin")
        harness.remember_cwd()
        import types as _t
        ns = _t.SimpleNamespace(task=task, answer=None, until="end", dry_run=False, model=None, plugin_dir=None, project=str(root), mr=None,
                                branch=None, commit=None, ungrounded=False, ticket_file=None, env=None, branch_suffix="", max_boundaries=10,
                                host="codex")
        driver = story_run.Driver(ns)
        check_eq("E-1: the driver starts with no codex executable (a dry run says so)", driver.claude, [])
        try:
            driver.run_claude("role", "p", role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
            check("E-1: the first call stops", False, "no Stop")
        except story_run.Stop as stop:
            check_eq("E-1: Stop(EXIT_ERROR) naming the host and its variable",
                     (stop.code, "no `codex` executable on PATH and STORY_RUN_CODEX is not set" in stop.reason), (1, True))
        check("E-1: and no journal row was written for a call that never happened", not (task_root / "state/driver-runs.jsonl").exists())
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        harness.cleanup(root)


# --- K-10 F-2 the one pricer ----------------------------------------------------------------------
def tariff_entry() -> dict:
    catalogue = json.loads((harness.SCRIPTS.parent / "references" / "model-rates.json").read_text(encoding="utf-8"))
    return next(e for e in catalogue["entries"] if e["model_id"] == TERRA and not e.get("valid_to"))


def by_hand(rates: dict, fresh: int, cached: int, out: int) -> float:
    """What `usage` costs at `rates` ($ per million), worked here from the rates FILE: nothing in this test is a typed-in tariff."""
    from decimal import Decimal
    return float(sum((Decimal(n) * Decimal(str(rates[k])) / Decimal(1000000) for n, k in ((fresh, "input"), (cached, "cache_read"), (out, "output"))),
                     Decimal(0)))


def codex_pricer() -> None:
    import cost_capture
    import story_run
    entry = tariff_entry()
    short, long_tier, threshold = entry["rates"], entry["long_context"]["rates"], entry["long_context"]["threshold_input_tokens"]
    price = lambda usage, model=TERRA, cfg=None: story_run.codex_call_cost(usage, model, cfg)   # noqa: E731
    # the critic's control usage: 1,000,000 in (400,000 of them cached), 100,000 out - over the threshold, so the LONG tier
    control = {"input_tokens": 1000000, "cached_input_tokens": 400000, "output_tokens": 100000}
    low, high = by_hand(short, 600000, 400000, 100000), by_hand(long_tier, 600000, 400000, 100000)
    check("F-2: the control usage is over the long-context threshold, and the two tiers price it differently",
          control["input_tokens"] > threshold and low < high, f"{low} {high} {threshold}")
    got, text = price(control)
    check_eq(f"F-2: the control usage ({control['input_tokens']:,} in) is priced at the LONG tier, ${high:.2f} (not the short tier's ${low:.2f})",
             (round(got, 9), text), (round(high, 9), LABEL))
    # AT and BEYOND the threshold: the tier is chosen by the sum of the input tokens (fresh + cached), `>` the threshold
    at = price({"input_tokens": threshold, "cached_input_tokens": 0, "output_tokens": 1000})[0]
    beyond = price({"input_tokens": threshold + 1, "cached_input_tokens": 0, "output_tokens": 1000})[0]
    check_eq("F-2: an input AT the threshold is the short tier", round(at, 9), round(by_hand(short, threshold, 0, 1000), 9))
    check_eq("F-2: one token beyond it is the long tier", round(beyond, 9), round(by_hand(long_tier, threshold + 1, 0, 1000), 9))
    check_eq("F-2: cached tokens count toward the threshold (fresh 100,000 + cached 200,000 = 300,000 > 272,000)",
             round(price({"input_tokens": 300000, "cached_input_tokens": 200000, "output_tokens": 0})[0], 9),
             round(by_hand(long_tier, 100000, 200000, 0), 9))
    # ONE pricer: the call goes through `cost_capture.value_usage`, once; the driver keeps no second multiplication
    seen, real = [], cost_capture.value_usage
    cost_capture.value_usage = lambda *a, **k: (seen.append(a[1]), real(*a, **k))[1]
    try:
        price(control)
    finally:
        cost_capture.value_usage = real
    check_eq("F-2: a Codex call is valued by cost_capture.value_usage, once, for the model of the call", seen, [TERRA])
    # the project's own table first, as for Claude: an override replaces the catalogue's rates (and has no long tier)
    own = {"rate_overrides": [{"model_id": TERRA, "rates": {"input": 1, "output": 1, "cache_read": 1}}]}
    check_eq("F-2: a project's rate_overrides price the call (the same list as everywhere)", round(price(control, cfg=own)[0], 9), 1.1)
    # unknowns are named, never 0 (FR-41), and float / odd counts are not truncated into a price (m-3)
    unknowns = {
        "no usage": ({}, "price unknown: the stream carried no usage for " + TERRA),
        "all zero": ({"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}, "price unknown: the stream carried no usage for " + TERRA),
        "fractional output": ({"input_tokens": 10, "output_tokens": 10.9}, "price unknown: the usage of this call is not countable for " + TERRA),
        "bool count": ({"input_tokens": True, "output_tokens": 1}, "price unknown: the usage of this call is not countable for " + TERRA),
        "negative": ({"input_tokens": -5, "output_tokens": 1}, "price unknown: the usage of this call is not countable for " + TERRA),
        "string": ({"input_tokens": "10", "output_tokens": 1}, "price unknown: the usage of this call is not countable for " + TERRA),
        "cached above input": ({"input_tokens": 10, "cached_input_tokens": 11, "output_tokens": 1}, "price unknown: the usage of this call is not countable for " + TERRA),
        "reasoning above output": ({"input_tokens": 10, "output_tokens": 5, "reasoning_output_tokens": 6}, "price unknown: the usage of this call is not countable for " + TERRA),
        "a cache write": ({"input_tokens": 10, "output_tokens": 5, "cache_write_input_tokens": 3}, "price unknown: the usage of this call is not countable for " + TERRA)}
    for name, (usage, why) in unknowns.items():
        check_eq(f"F-2/m-3: {name} is `price unknown`, the number None", price(usage), (None, why))
    check_eq("F-2: a model with no tariff is `price unknown: no tariff`", price(control, model="gpt-9-unheard-of"),
             (None, "price unknown: no tariff for gpt-9-unheard-of"))
    check_eq("m-3: a float that is a whole number is that count (10.0 = 10)",
             price({"input_tokens": 10.0, "cached_input_tokens": 0.0, "output_tokens": 5.0}), price({"input_tokens": 10, "output_tokens": 5}))
    check_eq("F-2: the label is the fact (an estimate, from which tariffs, how the tier is chosen)", story_run.CODEX_COST_LABEL,
             "estimate: default tariffs (references/model-rates.json); long-context tier by the turn's sum")


# --- K-11 F-1 the running total of a thread, through the driver ---------------------------------------
def codex_thread_total() -> None:
    import driver_journal as DJ
    task = "QA-1"
    root, task_root, env = seed(task)
    env = codex_env(root, env)
    out_rate = tariff_entry()["rates"]["output"]

    def spend(dollars: float) -> dict:             # an output-only usage that costs about `dollars` at the tariff file's output rate
        return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": round(dollars / out_rate * 1000000)}

    def worth(usage: dict) -> float:               # what that usage costs, worked from the rates FILE
        return round(by_hand(tariff_entry()["rates"], 0, 0, usage["output_tokens"]), 9)
    try:
        driver = codex_driver(root, env, task)
        dispatch = "S1-qa-scout-1"
        # the critic's probe: ~$0.30, then ~$0.45 in one thread, then a call that costs LESS than the one before it (~$0.10)
        u1, u2, u3 = spend(0.30), spend(0.45), spend(0.10)
        c1, c2, c3 = worth(u1), worth(u2), worth(u3)
        t2, t3 = round(c1 + c2, 9), round(c1 + c2 + c3, 9)
        set_control(root, {"roles": {"qa-scout": {"result": "first"}}, "resume": {"result": "again"}, "usages": [u1, u2, u3, {}]})
        first = driver.run_claude("role", role_prompt(task_root, dispatch), role="qa-scout", dispatch=dispatch, stage="S1")
        thread = first["session_id"]
        resumed = [driver.run_claude("role", "go on", role="qa-scout", dispatch=dispatch, stage="S1", resume=thread, resume_reason="a test")
                   for _ in range(3)]
        got = [(round(r["total_cost_usd"], 9), None if r["call_cost_usd"] is None else round(r["call_cost_usd"], 9)) for r in [first] + resumed]
        check("F-1: the probe's calls are about $0.30, $0.45 and $0.10 (the third cheaper than the second)",
              abs(c1 - 0.30) < 0.001 and abs(c2 - 0.45) < 0.001 and abs(c3 - 0.10) < 0.001 and c3 < c2, repr((c1, c2, c3)))
        check_eq("F-1: four calls of one thread - the running total in `total_cost_usd`, the call's own price in `call_cost_usd`; the last call "
                 "carried no usage: its price is None and the total is the one before it",
                 got, [(c1, c1), (t2, c2), (t3, c3), (t3, None)])
        check_in("F-1: the unpriced call says so in `cost_basis` and that the thread's total does not hold it", "does not include this call",
                 resumed[2]["cost_basis"])
        check_in("and still names why it is unknown", "price unknown: the stream carried no usage", resumed[2]["cost_basis"])
        rows = [r for r in rows_of(task_root) if r["kind"] == "role"]
        check_eq("F-1: the journal rows say the same", [(round(r["total_cost_usd"], 9), r["call_cost_usd"] is None) for r in rows],
                 [(c1, False), (t2, False), (t3, False), (t3, True)])
        charged, unknown = DJ.root_charged({thread: {"rows": rows, "journals": [task]}})
        check_eq("F-1: driver_journal.root_charged reads the thread at the SUM of its calls (after two, and after the cheaper third)",
                 ({k: round(v, 9) for k, v in charged.items()}, unknown), ({thread: t3}, []))
        check_eq("F-1: row_increments are the calls' prices; the unpriced call adds 0",
                 [round(v, 9) for v in DJ.row_increments(rows)], [c1, c2, c3, 0.0])
        check_eq("F-1: the two-call thread alone (~$0.30, ~$0.45) is the sum and its increments the two prices (not [0.30, 0.15])",
                 ({k: round(v, 9) for k, v in DJ.root_charged({thread: {"rows": rows[:2], "journals": [task]}})[0].items()},
                  [round(v, 9) for v in DJ.row_increments(rows[:2])]), ({thread: t2}, [c1, c2]))
        # the FIRST row of a thread whose first call is unpriced has no total (nothing before it to repeat), and a later priced call
        # then stands alone: the earlier row's own basis keeps saying that its call is not in the total
        past = [{}] * len(stub_calls(root))        # the stub reads `usages` by the index of the call in the whole run
        u4, u5 = spend(0.20), spend(0.05)
        set_control(root, {"roles": {"qa-scout": {"result": "x"}}, "resume": {"result": "y"}, "usages": past + [{}, u4]})
        other = "S2-qa-requirements-tester-1"
        bare = driver.run_claude("role", role_prompt(task_root, other), role="qa-scout", dispatch=other, stage="S2")
        check_eq("F-1 edge: the first call of a new thread with no usage - total None, call None, no 'does not include' (there is no total)",
                 (bare["total_cost_usd"], bare["call_cost_usd"], "does not include" in bare["cost_basis"]), (None, None, False))
        late = driver.run_claude("role", "go on", role="qa-scout", dispatch=other, stage="S2", resume=bare["session_id"], resume_reason="a test")
        check_eq("F-1 edge: a priced call after it stands alone as the total", (round(late["total_cost_usd"], 9), round(late["call_cost_usd"], 9)), (worth(u4), worth(u4)))
        # a driver started again over the same task (a rerun) goes on from the journal, not from its memory
        again = codex_driver(root, env, task)
        set_control(root, {"resume": {"result": "z"}, "usages": [{}] * len(stub_calls(root)) + [u5]})
        rerun = again.run_claude("role", "go on", role="qa-scout", dispatch=dispatch, stage="S1", resume=thread, resume_reason="a rerun")
        check_eq("F-1: a new driver process continues the thread's total from the journal (the earlier rows + this call)",
                 round(rerun["total_cost_usd"], 9), round(t3 + worth(u5), 9))
    finally:
        harness.cleanup(root)


# --- K-12 m-1 a stale `host` word of the state --------------------------------------------------------------
def stale_host_key() -> None:
    import story_run
    task = "QA-1"
    root, task_root, env = seed(task)
    env = codex_env(root, env)
    try:
        state_path = task_root / "state" / "driver-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        # the trace of the critic: a Codex call was cut off, its record left with the run, and `host: codex` stayed behind
        state_path.write_text(json.dumps({"sessions": {}, "host": "codex"}), encoding="utf-8")
        claude = T.driver_for(root, env, task)
        check_eq("m-1: a state with `host: codex` and no session starts a Claude run", claude.host, "claude")
        set_control(root, {"roles": {"qa-scout": {"result": "an answer"}}})
        claude.run_claude("role", role_prompt(task_root, "S1-qa-scout-1"), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        stored = json.loads(state_path.read_text(encoding="utf-8"))
        check_eq("m-1: the host word follows the stored session: it says claude now", (bool(stored["sessions"]), stored.get("host")), (True, "claude"))
        check_eq("m-1: the next Claude run is not refused", T.driver_for(root, env, task).host, "claude")
        try:
            codex_driver(root, env, task)
            check("m-1: a Codex run of a story holding Claude sessions is refused", False, "no Stop")
        except story_run.Stop as stop:
            check("m-1: the refusal names BOTH hosts - the stored sessions' (claude) and this run's (codex) - and the door for the first",
                  all(t in stop.reason for t in ("sessions of the claude host", "this run is codex", "`--host claude`")), stop.reason)
        # and the legacy story, no host key at all, keeps its bytes (no key written on Claude)
        state_path.write_text(json.dumps({"sessions": {}}), encoding="utf-8")
        legacy = T.driver_for(root, env, task)
        legacy.run_claude("role", role_prompt(task_root, "S1-qa-scout-2"), role="qa-scout", dispatch="S1-qa-scout-2", stage="S1")
        check("m-1: a Claude story with no host key still has none after a call", "host" not in json.loads(state_path.read_text(encoding="utf-8")))
    finally:
        harness.cleanup(root)


# --- K-13 F-3 the tariff label on the pages ---------------------------------------------------------------
def codex_label_on_pages() -> None:
    import retro_numbers as RN
    import test_dashboard_task_binding as B
    import test_dashboard_task_price as P
    import tempfile
    needle = "Codex calls are priced by the factory"
    files = P.files_for("proj", ("a1", "a2"))

    def card_sub(rows: list) -> str:
        with tempfile.TemporaryDirectory() as td:
            driver, spread = B.read_driver(td, {B.TASK: rows})
        return P.card_of(html.unescape(B.cost_page(files, driver, spread)), B.TASK)[1]
    plain = P.journal_for(files)
    one = [dict(plain[0], host="codex", cost_basis=LABEL, call_cost_usd=plain[0]["total_cost_usd"])] + plain[1:]
    sub = card_sub(one)
    check_eq("F-3: the dashboard's story card prints the tariff label once for a journal with one Codex row", (sub.count(needle), sub.count(LABEL)), (1, 1))
    two = [dict(r, host="codex", cost_basis=LABEL, call_cost_usd=r["total_cost_usd"]) for r in plain]
    sub = card_sub(two)
    check_eq("F-3: and still once for a journal of six Codex rows with the same basis", (sub.count(needle), sub.count(LABEL)), (1, 1))
    check_not_in("F-3: a journal with no Codex row prints nothing new on the card", needle, card_sub(plain))
    unpriced = [dict(plain[0], host="codex", cost_basis="price unknown: no tariff for gpt-9"), dict(plain[1], host="codex", cost_basis=LABEL)] + plain[2:]
    sub = card_sub(unpriced)
    check("F-3: a row whose price is unknown says so beside the label", "price unknown: no tariff for gpt-9" in sub and LABEL in sub, sub)
    # the retro: the same helper, the facts, and the render
    check_eq("F-3: no Codex row, no line", (RN.codex_tariff_label(plain), RN.codex_tariff_label([]), RN.codex_tariff_label(None)), ("", "", ""))
    check_eq("F-3: a `launched` row (host codex, no basis) adds no text", RN.codex_tariff_label([{"kind": "launched", "host": "codex"}]), "")
    root = harness.temp_dir("qa-retro-codex-")
    try:
        base = root / "qa-factory"
        troot = base / "artifacts" / "QA-1"
        (base / "state" / "cost").mkdir(parents=True)
        (troot / "work").mkdir(parents=True)
        (troot / "state").mkdir(parents=True)
        (base / "config.json").write_text("{}", encoding="utf-8")
        (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "size": "M", "stages": {}}), encoding="utf-8")
        (troot / "work" / "test-plan.json").write_text("[]", encoding="utf-8")
        journal = troot / "state" / "driver-runs.jsonl"
        codex_row = {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1", "session_id": "thr-1", "num_turns": 2,
                     "total_cost_usd": 0.5, "call_cost_usd": 0.5, "host": "codex", "cost_basis": LABEL, "ts": "2026-10-20T10:00:00+00:00"}
        journal.write_text(json.dumps(codex_row) + "\n", encoding="utf-8")
        text = RN.render(RN.numbers("QA-1", base, troot))
        check_eq("F-3: the retro prints the tariff label once for a journal with one Codex row", (text.count(needle), text.count(LABEL)), (1, 1))
        journal.write_text(json.dumps(dict(codex_row, host=None, cost_basis=None)) + "\n", encoding="utf-8")
        check_not_in("F-3: and nothing new for a journal without one", needle, RN.render(RN.numbers("QA-1", base, troot)))
        check_not_in("F-3: nor for facts written before the key existed", needle,
                     RN.render({k: v for k, v in RN.numbers("QA-1", base, troot).items() if k != "codex_tariff"}))
    finally:
        harness.cleanup(root)


def main() -> None:
    codex_parser()
    codex_pricer()
    host_is_read_only_where_the_node_says()
    run_scenarios([codex_story_s1], [codex_command_and_prompt, codex_lifecycle, claude_path_is_as_it_was, host_battery, no_codex_executable,
                                     codex_thread_total, stale_host_key, codex_label_on_pages])
    harness.finish("test_story_run_codex")


if __name__ == "__main__":
    main()
