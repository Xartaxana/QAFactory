# -*- coding: utf-8 -*-
"""Fresh-install smoke — an IN-CODE check that the plugin works out of the box.

Run: python install_smoke.py (directly; onboarding Step 0 and the doctor call it with python).

Root split note: a project never carries its own copy of the plugin's code — there is
nothing to "copy into a sandbox" any more. Instead this builds a SYNTHETIC PROJECT (a
temp directory, `git init`ed, with a qa-factory/config.json seeded from
references/templates/config.json — the same shape onboarding generates, so the sandbox
is a fresh project rather than a shape no project has) and runs the plugin against it
with CLAUDE_PROJECT_DIR pointed at the sandbox. Exercises: the dashboard on empty data
(a fresh onboard without state/), the exit gate with no artifacts, the journal (a
gate_block event and a risk_transfer gate), the cost hook on a synthetic transcript, the
dashboard again with data, **every hooks.json command line through hooks/run-py.cmd**
(the only step that crosses the boundary the harness actually crosses), external-writes
liveness for whatever delivery the config declares, the external_writes.py units, the
form validator self-test, the PreToolUse guard self-test, and the audit. The real project
this happens to run inside is never touched.
Every check prints PASS, INFO or FAIL. INFO is an observation the install is allowed to have
(a step that does not apply here, e.g. a markdown-only project) and never fails the smoke.
Exit 0 = no FAIL = the install works; any FAIL must be fixed before the first task.
Born from the 09-01 lesson: the dashboard crashed on a fresh clone because state/
did not exist.
"""
import json
import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"

# This smoke imports and spawns the package from inside the package, and every one of those
# children would write __pycache__ into it. What lies in the package is what a marketplace
# with a local-directory source installs, so the litter would be shipped (see LEFTOVERS).
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Development litter this package is known to produce, and a marketplace whose source is a
# local directory installs whatever lies in that directory. `selftest.py --hygiene` is the
# precise check, but it needs the git clone; an installed copy has none, and an install is
# exactly where nobody would look. Top level only. Bytecode caches are deliberately NOT on
# this list: the hook layer runs these scripts from the installed directory, so __pycache__
# appears there from ordinary use and would say nothing about the copy it arrived in.
LEFTOVERS = ("docs", "*.log", ".pytest_cache", "pytest-cache-files-*", ".test-tmp", ".tmp-test",
             ".context-test-tmp", ".*-test", ".*-test-*", "test-tmp-*", "qa-controller-*",
             "qa-reducer-recovery-*")


def check_leftovers() -> bool:
    found = sorted({p.relative_to(PLUGIN_ROOT).as_posix()
                    for pattern in LEFTOVERS for p in PLUGIN_ROOT.glob(pattern)})
    good = not found
    print(("PASS" if good else "FAIL"),
          "the installed package carries no development leftovers"
          + ("" if good else " | copied in from the source clone: " + ", ".join(found[:8])
             + (f" (+{len(found) - 8} more)" if len(found) > 8 else "")))
    return good


def project_above(path: Path) -> Path | None:
    """The onboarded project `path` sits inside, by hooklib's one marker rule — or None.

    A plugin root inside a project is a legal layout (a marketplace clone under `<project>/<clone>/`), and the smoke has to know about it rather than walk into it."""
    try:
        from hooklib import _nearest_project
        return _nearest_project(path)
    except Exception:
        return None


def plugin_version() -> str:
    """The version of the plugin this smoke is running from.

    Nothing printed it anywhere until 0.2.0, so "which build is installed here" was a
    question nobody could answer from a report — and after a release that changes artifact
    names and locations, that is the first question. Worse, a check that only EXISTS in the
    newer build is simply absent from an older one's output, and absence reads as a pass;
    naming the version is what turns that silence back into a fact."""
    manifests = (".claude-plugin", ".codex-plugin", ".kimi-plugin", ".plugin")
    if os.environ.get("CODEX_THREAD_ID") or ".codex" in PLUGIN_ROOT.parts:
        manifests = (".codex-plugin", ".claude-plugin", ".kimi-plugin", ".plugin")
    for manifest in manifests:
        try:
            data = json.loads((PLUGIN_ROOT / manifest / "plugin.json").read_text(encoding="utf-8"))
            if data.get("version"):
                return str(data["version"])
        except Exception:
            continue
    return "unknown"


def main() -> None:
    ok = True
    print(f"PLUGIN: qa-factory {plugin_version()} — {PLUGIN_ROOT}")
    print("SCOPE: isolated source/launcher smoke; does not certify installed hook trust or live Codex parity")
    with tempfile.TemporaryDirectory(prefix="qa-factory-smoke-") as td:
        proj = Path(td) / "project"
        proj.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=proj, capture_output=True)

        qf = proj / "qa-factory"
        qf.mkdir()
        # The template onboarding generates from — not scripts/config.example.json, whose
        # shape drifted from it. A sandbox shaped unlike any real project is a smoke that
        # can pass while the install it is standing in for cannot work.
        seed = PLUGIN_ROOT / "references" / "templates" / "config.json"
        if seed.exists():
            shutil.copyfile(seed, qf / "config.json")
        else:
            raise FileNotFoundError("Canonical onboarding config template is missing")

        # A directory with no project marker in any ancestor — the cwd every script
        # self-test gets. It used to be PLUGIN_ROOT, which assumed the plugin root lies in
        # no project; on the macOS 0.7.11 install it lay inside one
        # (`<project>/<clone>/.../qa-factory`), so `project_root()`
        # walked up from there into the user's REAL stories and four self-tests read and
        # wrote against them: `FileNotFoundError calls.log`, 14 guard mismatches,
        # `evidence_dir ... expected True, got False`, `no pipeline.json at .../QA-1`.
        # Scripts are addressed by absolute path, so cwd carries no other meaning here.
        neutral = Path(td) / "neutral-cwd"
        neutral.mkdir()
        inside = project_above(PLUGIN_ROOT)
        if inside:
            print("INFO the plugin root sits inside the onboarded project "
                  f"{inside} — a legal layout, not a defect; the smoke ran its script "
                  "self-tests from a neutral directory so they resolve their own temp "
                  "project instead of this one")

        py = sys.executable
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(proj)

        def run(label: str, script: str, args: list | None = None, inp: str | None = None,
                *, isolated: bool = False) -> None:
            nonlocal ok
            child_env = dict(env)
            # Twin of the driver's own child reader (`Driver.py` in the driver set): every child's text is decoded as utf-8 below. Only
            # run() children; the hook and probe children keep the harness's own environment.
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_cwd = proj
            if isolated:
                # Script self-tests build their own project roots and markers. Inheriting the
                # smoke project's override makes hooklib ignore those roots and can turn a
                # valid unit into a false failure (or make the audit judge smoke artifacts).
                child_env.pop("CLAUDE_PROJECT_DIR", None)
                child_cwd = neutral
            p = subprocess.run([py, str(SCRIPTS / script)] + (args or []), cwd=child_cwd, input=inp,
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=child_env)
            good = p.returncode == 0
            output = "\n".join(part.strip() for part in (p.stdout, p.stderr) if part.strip())
            lines = output.splitlines()
            print(("PASS" if good else "FAIL"),
                  label + ("" if good or not lines else " | " + lines[-1][:120]))
            if not good and output:
                print(f"--- {script} full output ---")
                print(output)
                print(f"--- end {script} output ---")
            ok = ok and good

        run("dashboard on empty data (fresh onboard)", "factory_dashboard.py")
        run("exit gate with no artifacts", "exit_gate.py", inp=json.dumps({"session_id": "smoke"}))
        run("journal: a gate_block event", "log_append.py",
            ["--event", "gate_block", "--agent", "exit_gate", "--notes", "install smoke", "--seeded"])
        run("journal: a risk_transfer gate", "log_append.py",
            ["--event", "gate", "--task", "SMOKE-1", "--gate", "risk_transfer",
             "--decision", "smoke", "--seeded"])
        tr = proj / "smoke-transcript.jsonl"
        tr.write_text(json.dumps({
            "type": "assistant", "timestamp": "2026-01-01T10:00:00Z", "requestId": "r1",
            "isSidechain": False,
            "message": {"model": "claude-sonnet-5",
                        "usage": {"input_tokens": 100, "output_tokens": 500,
                                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                        "content": [{"type": "text", "text": "x"}]}}) + "\n", encoding="utf-8")
        run("cost hook on a synthetic transcript", "cost_capture.py",
            inp=json.dumps({"session_id": "smoke", "transcript_path": str(tr)}))
        cost = qf / "state" / "cost" / "smoke.json"
        print(("PASS" if cost.exists() else "FAIL"), "cost file written by the Stop hook")
        ok = ok and cost.exists()
        run("dashboard with cost data", "factory_dashboard.py")

        # --- the hooks, the way the harness runs them ---------------------------------
        # Every check above runs a SCRIPT, directly, with this interpreter. The harness does
        # none of that: it runs the command line written in hooks/hooks.json, through
        # hooks/run-py.cmd, with the event JSON on stdin. A smoke that never crosses that
        # boundary reports PASSED while every hook in the session is failing — the pilot's
        # "SMOKE: PASSED while hooks were failing" — and the two known ways it breaks live
        # exactly there: ${CLAUDE_PLUGIN_ROOT} not expanding, and no Python on PATH for a
        # launcher that does not inherit this process's sys.executable.
        hook_events = {
            "PreToolUse": {"tool_name": "Read", "tool_input": {"file_path": "README.md"}},
            "PostToolUse": {"tool_name": "Read", "tool_input": {"file_path": "README.md"},
                            "tool_response": {}},
            "SubagentStop": {},
            "Stop": {"transcript_path": str(tr)},
            "PreCompact": {},
            "SessionStart": {"source": "compact"},
        }
        # RN1-1 B-2 (FR-33): the entries whose matcher names `Agent` get the launch of the doctor's probe child, the host's real
        # answer (`agentId`), over a prepared probe store: the Claude hook (`agent_autobind`) must BIND it. Asserted below.
        probe_input = {"subagent_type": "qa-factory:qa-scout", "prompt": "QA_FACTORY_CONTEXT_PROBE"}
        agent_events = {
            # The PRE hook gets a benign non-factory dispatch: the stage guard refuses the probe launch itself until the guard is
            # VERIFIED in the host session (SG-probe-evidence), and this smoke has no host session to verify it in (t-772).
            "PreToolUse": {"tool_name": "Agent", "tool_use_id": "smoke-pre",
                           "tool_input": {"subagent_type": "general-purpose", "prompt": "install smoke: a benign dispatch"}},
            "PostToolUse": {"tool_name": "Agent", "tool_use_id": "smoke-spawn", "tool_input": probe_input,
                            "tool_response": {"isAsync": True, "status": "async_launched", "agentId": "smoke-agent"}},
        }
        probe_store = proj / "qa-factory" / "state" / "host-probe.json"
        probe_store.parent.mkdir(parents=True, exist_ok=True)
        probe_store.write_text(json.dumps({"session_id": "smoke", "injection": {
            "challenge": "0" * 32, "status": "emitted", "tool_use_id": "smoke-spawn"}}), encoding="utf-8")
        try:
            hooks_json = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        except Exception as e:
            hooks_json = {}
            print("FAIL hooks.json is unreadable |", e)
            ok = False
        for event, entries in (hooks_json.get("hooks") or {}).items():
            for entry in entries:
                names_agent = "Agent" in str(entry.get("matcher") or "").split("|")
                payload = dict((agent_events.get(event) if names_agent else None) or hook_events.get(event) or {})
                payload["session_id"] = "smoke"
                payload["hook_event_name"] = event
                payload["cwd"] = str(proj)
                for hook in entry.get("hooks") or []:
                    line = str(hook.get("command") or "").strip()
                    if not line:
                        continue
                    cmd = line.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_ROOT))
                    script = line.split()[-1]
                    p = subprocess.run(cmd, shell=True, cwd=proj, input=json.dumps(payload),
                                       capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", env=env, timeout=60)
                    # 0 = ran and allowed. 2 = ran and BLOCKED, which is also a working hook,
                    # but not on a benign Read of README.md — so it is a failure here.
                    good = p.returncode == 0
                    detail = (p.stderr or p.stdout or "").strip().splitlines()
                    print(("PASS" if good else "FAIL"),
                          f"hook {event} -> {script} (via run-py.cmd, event on stdin)"
                          + ("" if good else f" | exit {p.returncode}"
                             + (" | " + detail[-1][:100] if detail else "")))
                    ok = ok and good

        # B-2: the Agent launch above reached the Claude hook, and the probe is bound to the id the host's answer names.
        try:
            bound = json.loads(probe_store.read_text(encoding="utf-8"))["injection"].get("agent_id")
        except Exception:
            bound = None
        print(("PASS" if bound == "smoke-agent" else "FAIL"),
              f"hook PostToolUse Agent|Task bound the probe to the launch id (injection.agent_id = {bound!r})")
        ok = ok and bound == "smoke-agent"

        # A non-login hook often has no user tool directories on PATH. The wrapper's
        # configured interpreter must still start without depending on shell profiles.
        minimal_env = dict(env)
        # The minimal PATH is the platform's own: System32 on Windows, /usr/bin:/bin on
        # POSIX. Until 0.7.16 the Windows value was used everywhere, so on macOS the probe
        # ran the launcher with a PATH that held nothing and reported a broken launcher
        # that every real hook contradicted (the 0.7.16 macOS install, Klim).
        minimal_env["PATH"] = (str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
                               if os.name == "nt" else "/usr/bin:/bin")
        minimal_env["QA_FACTORY_PYTHON"] = sys.executable
        launcher = PLUGIN_ROOT / "hooks" / "run-py.cmd"
        # ONE quoted string, built exactly the way the hooks.json loop above builds its
        # command. With shell=True a LIST is not a command line on POSIX: CPython runs
        # ["/bin/sh", "-c"] + args, so "subagent_journal.py" lands in the shell's $0 and the
        # launcher gets zero arguments — SCRIPT_NAME="$1" empty, the path collapsing to
        # `.../hooks/../scripts/` ("path-join error resolving ../scripts/", exit 2). That is
        # the macOS 0.7.11 install where this probe was red while every real hook was green.
        # shell=True stays: on Windows the .cmd needs cmd.exe.
        probe = subprocess.run(
            f'"{launcher}" subagent_journal.py', cwd=proj,
            input=json.dumps({"hook_event_name": "SubagentStop", "session_id": "minimal-path"}),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=minimal_env, shell=True, timeout=60,
        )
        good = probe.returncode == 0
        print(("PASS" if good else "FAIL"),
              "hook launcher uses configured interpreter with a non-login minimal PATH"
              + ("" if good else f" | exit {probe.returncode}: {(probe.stderr or probe.stdout)[-120:]}"))
        ok = ok and good

        # Injection actually DELIVERS, and for the id the harness really sends.
        # The loop above only proves a hook exits 0 — and exit 0 is exactly what
        # inject_context.py returns when its roster guard finds no such role. The pilot
        # (TP1-13958) ran every one of its twelve dispatches with `qa-factory:<role>`,
        # which matched nothing in inject-map.json: zero bytes injected, all session long,
        # silently. A green hook line is not a green injection; this checks the bytes.
        for probe_role in ("qa-factory:qa-scout", "qa-scout"):
            payload = {"hook_event_name": "PreToolUse", "session_id": "smoke", "cwd": str(proj),
                       "tool_name": "Agent",
                       "tool_input": {"subagent_type": probe_role, "prompt": "You are a role. Ticket: QA-1."}}
            try:
                p = subprocess.run([sys.executable, str(PLUGIN_ROOT / "scripts" / "inject_context.py")],
                                   cwd=proj, input=json.dumps(payload), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=env, timeout=60)
                good = p.returncode == 0 and "updatedInput" in (p.stdout or "")
            except Exception as e:
                good, p = False, None
                print("FAIL injection probe could not run |", e)
            print(("PASS" if good else "FAIL"),
                  f"injection delivers to '{probe_role}'"
                  + ("" if good else " | nothing injected — the role did not match inject-map.json"))
            ok = ok and good

        # The child's answer comes back through the host's handback call, not as text (OH3-13): the probe judges a
        # synthetic child transcript whose only assistant row is that call. The call's name is read from the host's report
        # forms through the one reader, never typed here, so the smoke is no greener than the live host (FR-33, AR-5).
        try:
            sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
            import host_adapter
            import host_probe
            forms, why = host_adapter.report_forms()
            challenge = "0123456789abcdef0123456789abcdef"
            answer = host_probe.CHALLENGE_PREFIX + challenge + "_END"
            state = proj / "qa-factory" / "state"
            state.mkdir(parents=True, exist_ok=True)
            store, transcript = state / "host-probe.json", proj / "child-handback.jsonl"
            store.write_text(json.dumps({"session_id": "smoke", "injection": {
                "agent_id": "smoke-child", "challenge": challenge, "status": "emitted"}}), encoding="utf-8")
            transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [{
                "type": "tool_use", "id": "toolu_smoke",
                "name": forms["claude"]["handback_tool"] if forms else "no-forms",
                "input": {"message": answer}}]}}) + chr(10), encoding="utf-8")
            host_probe.check_child(proj, {"agent_id": "smoke-child", "session_id": "smoke",
                                          "agent_transcript_path": str(transcript)})
            status = json.loads(store.read_text(encoding="utf-8"))["injection"].get("status")
            good = forms is not None and status == "delivered"
            detail = "" if good else f" | status {status!r}; forms: {why or 'read'}"
        except Exception as e:
            good, detail = False, f" | could not run: {type(e).__name__}: {e}"
        print(("PASS" if good else "FAIL"), "probe child's answer through the host's handback call is delivered" + detail)
        ok = ok and good

        # OH3-16: a Claude Code worker that handed its report back reads as `returned`, and one resumed after the handback does
        # not. A synthetic project holds the host's own shapes (transcript, sidecar, story_step receipt, the hook's stop line);
        # every name comes from the report forms through the one reader, so the smoke is no greener than the live host (FR-33).
        try:
            import hashlib
            import time
            from datetime import datetime, timezone
            sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
            import dispatch_liveness
            import host_adapter
            import worker_lifecycle
            forms, why = host_adapter.report_forms(host="claude")
            claude = (forms or {}).get("claude") or {}
            ack, marker = claude.get("handback_ack") or {}, claude.get("finished_marker") or {}
            now, ticket, dispatch, agent = time.time(), "SMOKE-1", "S5-qa-code-critic-1", "asmoke0000000001"

            def row(kind, ago, **fields):
                when = datetime.fromtimestamp(now - ago, timezone.utc)
                return dict(fields, type=kind, timestamp=when.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            verdicts = {}
            for resumed in (False, True):
                base = proj / ("claude-resumed" if resumed else "claude-returned")
                for part in ("state/host-dispatches", "state/cost", "records"):
                    (base / "qa-factory" / part).mkdir(parents=True)
                (base / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
                rows = [row("user", 3000, message={"role": "user", "content":
                                                   f"You are qa-code-critic. Ticket: {ticket}\nDispatch id: {dispatch}\n"}),
                        row("assistant", 701, message={"role": "assistant", "content": [{
                            "type": "tool_use", "id": "toolu_s", "name": claude.get("handback_tool"), "input": {"message": "report"}}]}),
                        row("user", 700, message={"role": "user", "content": [{
                            "type": "tool_result", "tool_use_id": "toolu_s", "content": [{
                                "type": "text", "text": json.dumps({ack.get("field"): ack.get("value")})}]}]})]
                if resumed:
                    rows.append(row("assistant", 5, message={"role": "assistant", "content": [{"type": "text", "text": "again"}]}))
                transcript = base / "sessions" / "s1" / "subagents" / f"agent-{agent}.jsonl"
                transcript.parent.mkdir(parents=True)
                transcript.write_text("".join(json.dumps(r) + chr(10) for r in rows), encoding="utf-8")
                transcript.with_name(transcript.stem + str(marker.get("file_suffix"))).write_text(
                    json.dumps({marker.get("field"): True}), encoding="utf-8")
                (base / "qa-factory" / "state" / "cost" / "s1.json").write_text(
                    json.dumps({"transcript": str(base / "sessions" / "s1.jsonl")}), encoding="utf-8")
                receipt = base / "qa-factory" / "state" / "host-dispatches" / (hashlib.sha256(agent.encode()).hexdigest() + ".json")
                receipt.write_text(json.dumps({"agent_id": agent, "agent_type": "qa-code-critic", "task_id": ticket,
                                               "dispatch_id": dispatch, "status": "running", "bound_by": "story_step",
                                               "bound_at": now - 900}), encoding="utf-8")
                (base / "qa-factory" / "records" / "journal.jsonl").write_text(json.dumps({
                    "ts": datetime.fromtimestamp(now - 697, timezone.utc).isoformat(timespec="seconds"), "event": "subagent_stop",
                    "agent": "qa-factory:qa-code-critic", "task": ticket, "dispatch": dispatch, "status": "completed",
                    "dispatch_receipt": receipt.name}) + chr(10), encoding="utf-8")
                verdicts[resumed] = (dispatch_liveness.state(base, ticket, {"id": dispatch, "role": "qa-code-critic"})["state"],
                                     worker_lifecycle.active_binding(base, dispatch, ticket) is None)
            good = forms is not None and verdicts[False] == (dispatch_liveness.RETURNED, True)
            detail = "" if good else f" | liveness {verdicts.get(False)}; forms: {why or 'read'}"
            good_resumed = forms is not None and verdicts[True][0] != dispatch_liveness.RETURNED and not verdicts[True][1]
            detail_resumed = "" if good_resumed else f" | liveness {verdicts.get(True)}; forms: {why or 'read'}"
        except Exception as e:
            good = good_resumed = False
            detail = detail_resumed = f" | could not run: {type(e).__name__}: {e}"
        print(("PASS" if good else "FAIL"), "host return reads as returned (claude)" + detail)
        print(("PASS" if good_resumed else "FAIL"), "host return: a row after the handback is not a return (claude)" + detail_resumed)
        ok = ok and good and good_resumed

        # External writes: the liveness of whatever delivery the project actually declared.
        # No vendor name belongs in this file: the factory ships no tracker CLI and depends
        # on none. What it can check is whether the command the PROJECT declared exists here.
        # (The old branch keyed on `external_writes.tool == "dmtools"`, a key that exists only
        # in scripts/config.example.json — so it never ran anywhere, while printing a line
        # that read like a completed check.)
        try:
            ew_cfg = json.loads((qf / "config.json").read_text(encoding="utf-8"))
        except Exception:
            ew_cfg = {}
        ew = ew_cfg.get("external_writes") or {}
        commands = {name: cmd for name, cmd in (ew.get("commands") or {}).items() if str(cmd or "").strip()}
        for name, delivery in (ew.get("channels") or {}).items():
            if isinstance(delivery, dict) and str(delivery.get("command") or "").strip():
                commands[name] = delivery["command"]
        agent_channels = [name for name, d in (ew.get("channels") or {}).items()
                          if isinstance(d, dict) and str(d.get("method") or "") in ("agent", "skill")]
        if commands:
            for name, cmd in sorted(commands.items()):
                exe = str(cmd).split()[0].strip('"').strip("'") if str(cmd).strip() else ""
                found = shutil.which(exe) if exe else None
                print(("PASS" if found else "FAIL"),
                      f"external writes: channel `{name}` delivers with `{exe}`"
                      + (f" ({found})" if found else f" | `{exe}` is not on PATH — the channel is "
                         "declared but dead; install it or set the channel to markdown"))
                ok = ok and bool(found)
        if agent_channels:
            print("INFO external writes: channels " + ", ".join(sorted(agent_channels)) +
                  " are delivered by a session agent — no script can dispatch one, so the "
                  "orchestrator's courier loop (external_writes.py exit 4) is the check, not this step")
        if not commands and not agent_channels:
            print("INFO external writes: markdown only — nothing external to reach")

        run("external_writes.py units (--selftest, a stubbed delivery command)", "external_writes.py", ["--selftest"], isolated=True)
        run("validator form rules (form_selftest: register/plan/case/bug/charter/PTR/ledger)", "form_selftest.py", isolated=True)
        run("PreToolUse guard (guard_pre_tool --selftest: write marker, prefilter, boundary, secrets)",
            "guard_pre_tool.py", ["--selftest"], isolated=True)
        run("run_suite mechanics (--selftest: junitxml parsing, per-test rows, evidence dir)",
            "run_suite.py", ["--selftest"], isolated=True)
        run("archive flag (--selftest: candidates, open items refuse, --force, --undo)",
            "archive_task.py", ["--selftest"], isolated=True)
        run("ticket adapter (--selftest: the normalized schema and every access method)",
            "ticket_adapter.py", ["--selftest"], isolated=True)
        run("diff pass (--selftest: hunk parsing, new-file line numbers, capping)",
            "diff_pass.py", ["--selftest"], isolated=True)
        run("stage bookkeeping (--selftest: stamping, digest, one journal event)",
            "stage_done.py", ["--selftest"], isolated=True)
        run("turn budget (--selftest: intervals, per-session counting, notice text)",
            "turn_budget.py", ["--selftest"], isolated=True)
        run("diff scope (--selftest: comment-only vs code, mixed diffs)",
            "diff_scope.py", ["--selftest"], isolated=True)
        run("manifest slices (--selftest: case, window, unresolved, summary)",
            "manifest_view.py", ["--selftest"], isolated=True)
        run("manifest merge (--selftest: by case, append-only lists, moves)",
            "manifest_put.py", ["--selftest"], isolated=True)
        run("gate waivers (--selftest: append, replace, per-gate records)",
            "waiver.py", ["--selftest"], isolated=True)
        # Installing is migrating (t-232): an old-generation project put through the one apply path ends
        # with the tree a fresh install makes. The same `onboard_apply.compare_trees` the test file uses.
        if (SCRIPTS / "tests" / "test_reinstall_equals_fresh.py").is_file():
            run("reinstall equals fresh (--smoke: compare_trees over tests/fixtures/old-generation-project vs a fresh install)",
                "tests/test_reinstall_equals_fresh.py", ["--smoke"], isolated=True)
        else:
            print("INFO reinstall equals fresh: this copy ships no tests/, so the old-generation comparison did not run")
        # The repository is English, whoever the reader is. `selftest.py --lang` is the check;
        # it is run from here because this is the entry point that actually gets run — the
        # rule went unenforced for a release while selftest.py sat red and unopened.
        run("language (selftest --lang: no Cyrillic anywhere in the package)",
            "selftest.py", ["--lang"], isolated=True)
        run("audit after the smoke", "audit_factory.py")
        ok = check_leftovers() and ok
    print("=== INSTALL SMOKE:",
          "PASSED — the plugin works out of the box" if ok else "FAILED — fix before the first task",
          "===")
    sys.exit(0 if ok else 1)


def package_fingerprint() -> str:
    """The installed package's behaviour-bearing bytes, by the one recipe runtime_paths.py binds a
    dispatch to (`release_fingerprint.py`, which also says why `design/` is outside it). Same
    fingerprint = the same code a passed smoke already exercised."""
    import release_fingerprint
    return release_fingerprint.package_fingerprint(PLUGIN_ROOT)


def reusable_report(path: Path, hours: float) -> dict | None:
    """A passed report of THIS package, written beside `path` within `hours`. The doctor ran
    the 50-second smoke five times in one day over an unchanged installation."""
    import json
    from datetime import datetime, timedelta, timezone
    if hours <= 0 or not path.parent.is_dir():
        return None
    fingerprint = package_fingerprint()
    horizon = datetime.now(timezone.utc) - timedelta(hours=hours)
    best = None
    for candidate in path.parent.glob("doctor-install-smoke-*.json"):
        try:
            report = json.loads(candidate.read_text(encoding="utf-8"))
            done = datetime.fromisoformat(str(report.get("completed_at")))
        except Exception:
            continue
        if (report.get("status") == "passed" and report.get("package_fingerprint") == fingerprint
                and report.get("plugin_root") == str(PLUGIN_ROOT) and done >= horizon
                and (best is None or done > best[0])):
            best = (done, candidate, report)
    if not best:
        return None
    return {"reused_from": best[1].name, "completed_at": best[2].get("completed_at"),
            "report": best[2]}


def run_report(path: Path) -> None:
    """Persist terminal evidence even when the caller loses a shell session handle."""
    from datetime import datetime, timezone
    from event_store import atomic_json
    report = {"schema_version": 1, "status": "running", "exit_code": None,
              "plugin_root": str(PLUGIN_ROOT), "plugin_version": plugin_version(),
              "package_fingerprint": package_fingerprint(),
              "started_at": datetime.now(timezone.utc).isoformat()}
    atomic_json(path, report)
    output = io.StringIO()
    console = sys.stdout

    class Tee:
        def write(self, text):
            output.write(text)
            return console.write(text)

        def flush(self):
            console.flush()

    code = 1
    try:
        with contextlib.redirect_stdout(Tee()):
            main()
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        raise
    except BaseException as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        lines = output.getvalue().splitlines()
        required = [f"PASS injection delivers to '{role}'" for role in ("qa-factory:qa-scout", "qa-scout")]
        failures = [line for line in lines if line.startswith("FAIL ")]
        plugin_line = next((line for line in lines if line.startswith("PLUGIN:")), None)
        passed = code == 0 and bool(plugin_line) and not failures and all(line in lines for line in required)
        report.update(status="passed" if passed else "failed", exit_code=code,
                      completed_at=datetime.now(timezone.utc).isoformat(),
                      plugin_line=plugin_line,
                      injection_checks=[line for line in lines if "injection delivers to '" in line],
                      failures=failures, output=output.getvalue())
        atomic_json(path, report)


if __name__ == "__main__":
    # First statement, before argparse can print the docstring's dash and before the PLUGIN
    # line: the console may be cp1251/cp866/ascii (B-413). Line buffering stays (FR-43).
    try:
        import console_io
        console_io.utf8_stdio(line_buffering=True)
    except ImportError:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="persist running/terminal smoke evidence as JSON")
    parser.add_argument("--reuse-within", type=float, default=0.0, metavar="HOURS",
                        help="with --report: skip the run when a passed report of this exact "
                             "package (same fingerprint and root) is younger than HOURS")
    args = parser.parse_args()
    reused = reusable_report(args.report, args.reuse_within) if args.report else None
    if reused:
        from event_store import atomic_json
        atomic_json(args.report, dict(reused["report"], reused_from=reused["reused_from"]))
        print(f"PLUGIN: qa-factory {plugin_version()} — {PLUGIN_ROOT}")
        print(f"SMOKE REUSED: {reused['reused_from']} passed at {reused['completed_at']} on this "
              "exact package fingerprint; nothing changed since, so nothing was re-run")
    elif args.report:
        run_report(args.report)
    else:
        main()
