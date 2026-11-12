"""The doctor's live allow/deny probe must be able to verify on Claude Code.

It could not. `hooks/hooks.json` ran the guard directly, past `telemetry_hook.py` — the one
place that writes a hook receipt and marks the probe — it never wired `host_probe.py` on
PostToolUse, and `host_call_present` understood only the Codex transcript row. So `checks`
stayed `{}` on every Claude Code session, `host_hooks` was `unknown` for ever, and a doctor
that could not get its evidence went reading the plugin's source instead of reporting.

This test runs the command lines of the Claude manifest, exactly as written, with events in
the shape Claude Code sends them and a transcript in the shape Claude Code writes it."""
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_project

sys.path.insert(0, str(SCRIPTS))
import host_probe  # noqa: E402
from event_store import EventStore  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"


def manifest_commands(event_name: str, tool: str) -> list:
    data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    commands = []
    for entry in data["hooks"].get(event_name, []):
        matcher = entry.get("matcher") or ""
        if matcher == "" or tool in matcher.split("|"):
            commands += [h["command"] for h in entry["hooks"]]
    return commands


def run_manifest_line(command: str, event: dict, root) -> int:
    """`"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" a.py b.py --flag` -> python a.py b.py --flag."""
    args = command.split("run-py.cmd\"", 1)[1].split()
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-B", str(SCRIPTS / args[0]), *args[1:]],
                          input=json.dumps(event), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)
    return done.returncode


def pair_events(root, session=SESSION):
    """A prepared store of `session`, a Claude-shaped transcript holding the pair's two calls, and the four events of
    the documented pair (guard + execution of ALLOW, guard of DENY). Returns (events, commands, transcript)."""
    allow_cmd, deny_cmd = host_probe.prepare(root, session)["commands"]
    transcript = root / ("pair-" + session[:8] + ".jsonl")
    rows = [{"type": "assistant", "sessionId": session, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}}]}}
        for call, command in (("toolu_allow", allow_cmd), ("toolu_deny", deny_cmd))]
    transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def event(hook, call, command):
        return {"hook_event_name": hook, "session_id": session, "tool_name": "Bash", "tool_use_id": call,
                "tool_input": {"command": command}, "transcript_path": str(transcript), "cwd": str(root)}
    events = {"allow_pre": event("PreToolUse", "toolu_allow", allow_cmd),
              "allow_post": event("PostToolUse", "toolu_allow", allow_cmd),
              "deny_pre": event("PreToolUse", "toolu_deny", deny_cmd)}
    return events, (allow_cmd, deny_cmd), transcript


def stored(root):
    return json.loads((root / "qa-factory/state/host-probe.json").read_text(encoding="utf-8"))


def meeting(name, tolerant, seconds=10):
    """Replace `host_probe.<name>` by a function that waits for a second caller first (a Barrier of 2). `tolerant`: a
    caller that never gets a partner (because the other one is held up by the lock under test) goes on after `seconds`
    instead of failing, so the same rendezvous kills a missing lock and costs a short wait when the lock is there.
    Returns the function that puts the original back. Never a wall-clock race (FR-31): the rendezvous forces the
    overlap, the lock decides."""
    gate = threading.Barrier(2, timeout=seconds)    # rule 13: a partner that never comes ends the wait by name, never a hang
    real = getattr(host_probe, name)

    def meet(*args, **kwargs):
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            if not tolerant:
                raise
        return real(*args, **kwargs)
    setattr(host_probe, name, meet)
    return lambda: setattr(host_probe, name, real)


def concurrent_pair(root, events, rendezvous_name="fingerprint", tolerant=False):
    """Run the ALLOW guard and the DENY guard observations in two threads that meet INSIDE one step they share (the
    package walk, or the read of the store), so both have read before either writes - the overlap two parallel hooks of
    one message can have. Never stress with real processes (FR-31); the rendezvous is the whole point. Returns the results."""
    results = {}

    def run(name, event, code):
        try:
            results[name] = host_probe.observe(root, event, "guard_pre_tool.py", code)
        except BaseException as exc:  # noqa: BLE001 - what escapes is the result
            results[name] = repr(exc)
    restore = meeting(rendezvous_name, tolerant, 1.5 if tolerant else 10)
    try:
        threads = [threading.Thread(target=run, args=("allow", events["allow_pre"], 0)),
                   threading.Thread(target=run, args=("deny", events["deny_pre"], 2))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
    finally:
        restore()
    return results


def n1_pin():
    """N1-0: a pin of the read-modify-write defect, red on the code before the lock (red by construction: the
    rendezvous forces the overlap). It does NOT show that this overlap is what happened in project 14857 (the live
    discriminator of the spec, section 7, does)."""
    root = temp_project("qa-probe-pin-")
    try:
        events, _commands, _transcript = pair_events(root)
        results = concurrent_pair(root, events)
        check_eq("N1-0: two observations that overlap both return (nothing raised, nothing asks the guard to block)",
                 results, {"allow": False, "deny": False})
        check_eq("N1-0: two observations that overlap keep BOTH facts",
                 sorted(stored(root)["checks"]), ["allow_guard", "deny_guard"])
    finally:
        cleanup(root)


def hold_briefly(root, seconds):
    """Another writer of the probe store, in a thread: takes its lock, says so, lets go after `seconds`."""
    ready = threading.Event()

    def run():
        with EventStore(root / "qa-factory/state/host-probe-lock").lock():
            ready.set()
            time.sleep(seconds)
    thread = threading.Thread(target=run)
    thread.start()
    ready.wait(10)
    return thread


def wait_patched(seconds):
    """host_probe.STORE_LOCK_WAIT_S set to `seconds`; returns the function that puts the real value back."""
    real = host_probe.STORE_LOCK_WAIT_S
    host_probe.STORE_LOCK_WAIT_S = seconds
    return lambda: setattr(host_probe, "STORE_LOCK_WAIT_S", real)


def sc2_36_lock():
    """SC2-36 N1: the facts of a pair of parallel hooks all land; a busy lock costs a fact, never a decision."""
    root = temp_project("qa-probe-lock-")
    try:
        events, _commands, _transcript = pair_events(root)
        check_eq("the wait of a writer on the probe store is 5 s (spec pin)", host_probe.STORE_LOCK_WAIT_S, 5)
        # The rendezvous is inside the lock's own critical section (the read of the store): without a lock both reads
        # precede both writes and a fact is lost; with it the second reader waits its turn.
        results = concurrent_pair(root, events, "_read_dict", tolerant=True)
        host_probe.observe(root, events["allow_post"], "host_probe.py", 0)
        check_eq("pair at once: all three facts on record, verified",
                 (results, sorted(stored(root)["checks"]), host_probe.inspect(root)["status"]),
                 ({"allow": False, "deny": False}, ["allow_executed", "allow_guard", "deny_guard"], "verified"))

        # --prepare while an observation walks the package: the old nonce writes nothing into the new store.
        events, _commands, _transcript = pair_events(root)
        real_fingerprint, midway = host_probe.fingerprint, []

        def prepare_midway(path):
            if not midway:
                midway.append(1)
                host_probe.prepare(root, SESSION)      # the pair of the new store has another nonce
            return real_fingerprint(path)
        host_probe.fingerprint = prepare_midway
        try:
            got = host_probe.observe(root, events["allow_pre"], "guard_pre_tool.py", 0)
        finally:
            host_probe.fingerprint = real_fingerprint
        after = stored(root)
        check_eq("prepare during observe: the old nonce writes nothing",
                 (got, after["checks"], events["allow_pre"]["tool_input"]["command"].endswith(after["nonce"])),
                 (False, {}, False))

        # --- the lock held beyond the wait: no fact, no exception, the guard's decision untouched (E1) ---------------
        events, _commands, _transcript = pair_events(root)
        restore = wait_patched(20)
        holder = hold_briefly(root, 0.4)
        try:
            got = host_probe.observe(root, events["allow_pre"], "guard_pre_tool.py", 0)
        finally:
            holder.join(10)
            restore()
        check_eq("lock held inside the wait: observe waits its turn and the fact is on record",
                 (got, sorted(stored(root)["checks"])), (False, ["allow_guard"]))
        restore = wait_patched(0.2)
        try:
            with EventStore(root / "qa-factory/state/host-probe-lock").lock():
                try:
                    busy = host_probe.observe(root, events["deny_pre"], "guard_pre_tool.py", 2)
                    raised = ""
                except Exception as exc:  # noqa: BLE001 - the exception is what is asserted against
                    busy, raised = None, type(exc).__name__
                blocks = host_probe.observe(root, events["deny_pre"])   # the guard's own question: no lock, no write
        finally:
            restore()
        check_eq("lock held beyond the wait: observe returns False, DENY still exit 2",
                 (busy, raised, blocks, sorted(stored(root)["checks"])), (False, "", True, ["allow_guard"]))

        # --- a store that cannot be read as one: nothing observed, the guard goes on (E5) ---------------------------
        path = root / "qa-factory/state/host-probe.json"
        good = path.read_bytes()
        for label, text in (("not JSON", "{not json"), ("not an object", "[1, 2]"), ("empty", ""),
                            ("no nonce", json.dumps({k: v for k, v in json.loads(good).items() if k != "nonce"})),
                            ("checks is a list", json.dumps(dict(json.loads(good), checks=[1])))):
            path.write_text(text, encoding="utf-8")
            try:
                got = host_probe.observe(root, events["allow_pre"], "guard_pre_tool.py", 0)
                raised = ""
            except Exception as exc:  # noqa: BLE001
                got, raised = None, type(exc).__name__
            check_eq(f"an unreadable store: observe returns False, the guard goes on ({label})",
                     (got, raised, path.read_text(encoding="utf-8")), (False, "", text))
        path.write_bytes(good)
        # one retry when a reader meets another process's os.replace (Windows PermissionError)
        real_read, refused = Path.read_text, []

        def flaky(self, *args, **kwargs):
            if self.name == "host-probe.json" and not refused:
                refused.append(1)
                raise PermissionError("seam: the file is being replaced")
            return real_read(self, *args, **kwargs)
        Path.read_text = flaky
        try:
            host_probe.observe(root, events["allow_pre"], "guard_pre_tool.py", 0)
        finally:
            Path.read_text = real_read
        check_eq("a store read refused once is read again: the fact is on record",
                 (len(refused), "allow_guard" in stored(root)["checks"]), (1, True))

        # --- the other writers of the store, with the lock busy (E1) ---------------------------------------------
        events, _commands, _transcript = pair_events(root)
        diag = {"session_id": SESSION, "tool_use_id": "spawn", "tool_input": {"prompt": "QA_FACTORY_CONTEXT_PROBE"},
                "transcript_path": str(root / "parent.jsonl")}
        check_in("positive control: a free store gives the challenge text", "Return exactly",
                 host_probe.injection_marker(root, diag))
        check_eq("positive control: and binds the child", host_probe.bind_injection(root, diag, "child"), True)
        challenge = stored(root)["injection"]["challenge"]
        child = root / "child.jsonl"
        child.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": host_probe.CHALLENGE_PREFIX + challenge + "_END"}]}}) + "\n", encoding="utf-8")
        stop = {"agent_id": "child", "agent_transcript_path": str(child)}
        before = path.read_bytes()
        restore = wait_patched(0.2)
        argv, out, err = sys.argv, io.StringIO(), io.StringIO()
        try:
            with EventStore(root / "qa-factory/state/host-probe-lock").lock():
                sys.argv = ["host_probe.py", "--prepare", "--root", str(root), "--session", SESSION]
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    try:
                        code, raised = host_probe.main(), ""
                    except BaseException as exc:  # noqa: BLE001
                        code, raised = None, type(exc).__name__
                try:
                    host_probe.prepare(root, SESSION)
                    direct = ""
                except Exception as exc:  # noqa: BLE001
                    direct = type(exc).__name__
                marker = host_probe.injection_marker(root, diag)
                bound = host_probe.bind_injection(root, diag, "other-child")
                host_probe.check_child(root, stop)
        finally:
            sys.argv = argv
            restore()
        check_eq("store busy: prepare says so without a traceback, injection_marker gives ''",
                 (code, raised, "the probe store is busy, run --prepare again" in err.getvalue(),
                  "Traceback" in err.getvalue(), out.getvalue(), direct, marker, bound, path.read_bytes() == before),
                 (1, "", True, False, "", "StateConflict", "", False, True))
        host_probe.check_child(root, stop)
        check_eq("positive control: with the store free the same stop is judged", stored(root)["injection"]["status"], "delivered")
    finally:
        cleanup(root)


def sc2_36_parse():
    """SC2-36 N1: parallel Write and Bash recorders, a guard that raises, the condition naming another session's hooks."""
    root = temp_project("qa-probe-parse-")
    try:
        bash = {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": "Bash", "tool_use_id": "toolu_b",
                "tool_input": {"command": "ls"}, "cwd": str(root)}
        write = dict(bash, tool_name="Write", tool_use_id="toolu_w",
                     tool_input={"file_path": str(root / "qa-factory" / "state" / "x.txt"), "content": "x"})
        restore = meeting("_read_dict", True, 1.5)
        try:
            threads = [threading.Thread(target=host_probe.note_guard_parse, args=(root, event, "guard_pre_tool.py", 0))
                       for event in (bash, write)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
        finally:
            restore()
        families = host_probe.guard_parse(root, SESSION)["families"]
        check_eq("parallel Write and Bash: both families on record",
                 (families["bash"]["status"], families["write"]["status"]), ("verified", "verified"))

        # --- other_session_hooks: named, never a status of its own ---------------------------------------------
        probe_root = temp_project("qa-probe-other-")
        try:
            host_probe.prepare(probe_root, SESSION)
            clean = host_probe.inspect(probe_root)
            check_eq("no guard-parse files: the condition is absent",
                     ("other_session_hooks" in [m["id"] for m in clean["missing"]], clean["status"]), (False, "unverified"))
            host_probe.note_guard_parse(probe_root, dict(bash, session_id="another-session", cwd=str(probe_root)),
                                        "guard_pre_tool.py", 0)
            got = host_probe.inspect(probe_root)
            ids = [m["id"] for m in got["missing"]]
            check_eq("other session's hooks ran: other_session_hooks is named, status unchanged",
                     (ids[-1], ids[:-1] == [m["id"] for m in clean["missing"]], got["status"]),
                     ("other_session_hooks", True, clean["status"]))
            check_in("...and the reason names the way out", "run --prepare and the pair again in one session",
                     next(m["reason"] for m in got["missing"] if m["id"] == "other_session_hooks"))
            other = host_probe._guard_parse_path(probe_root, "another-session")
            row = json.loads(other.read_text(encoding="utf-8"))
            row["families"]["bash"]["observed_at"] = "2020-01-01T00:00:00+00:00"
            other.write_text(json.dumps(row), encoding="utf-8")
            check_eq("other_session_hooks: a receipt observed before --prepare is not named",
                     "other_session_hooks" in [m["id"] for m in host_probe.inspect(probe_root)["missing"]], False)
            other.write_text("{not json", encoding="utf-8")
            check_eq("other_session_hooks: an unreadable receipt is not named, nothing raised",
                     "other_session_hooks" in [m["id"] for m in host_probe.inspect(probe_root)["missing"]], False)
            row["families"]["bash"]["observed_at"] = datetime.now(timezone.utc).isoformat()
            other.write_text(json.dumps(row), encoding="utf-8")
            host_probe.note_guard_parse(probe_root, dict(bash, cwd=str(probe_root)), "guard_pre_tool.py", 0)
            check_eq("other_session_hooks: this session's own receipt is never another session",
                     "other_session_hooks" in [m["id"] for m in host_probe.inspect(probe_root)["missing"]], True)
            events, _commands, _transcript = pair_events(probe_root)
            host_probe.observe(probe_root, events["deny_pre"], "guard_pre_tool.py", 2)
            check_eq("other_session_hooks: a fact of this session's own guard removes it",
                     "other_session_hooks" in [m["id"] for m in host_probe.inspect(probe_root)["missing"]], False)
        finally:
            cleanup(probe_root)

        # --- a guard that RAISES is a fact too (H3): exit 1 recorded, the exception still leaves ----------------
        crash_root = temp_project("qa-probe-crash-")
        try:
            events, _commands, _transcript = pair_events(crash_root)
            fake = crash_root / "fake" / "guard_pre_tool.py"
            fake.parent.mkdir()
            fake.write_text("raise RuntimeError('seam: the guard failed in its tail')\n", encoding="utf-8")
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(crash_root), PYTHONDONTWRITEBYTECODE="1")
            done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "telemetry_hook.py"), str(fake)],
                                  input=json.dumps(events["allow_pre"]), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", cwd=str(crash_root), env=env, timeout=120)
            allow = stored(crash_root)["checks"].get("allow_guard") or {}
            check_eq("the guard raises on ALLOW: allow_guard on record with exit 1, the exception still leaves",
                     (allow.get("exit_code"), done.returncode != 0, "RuntimeError" in done.stderr),
                     (1, True, True))
            ok_script = crash_root / "fake" / "ok" / "guard_pre_tool.py"
            ok_script.parent.mkdir()
            ok_script.write_text("pass\n", encoding="utf-8")
            subprocess.run([sys.executable, "-B", str(SCRIPTS / "telemetry_hook.py"), str(ok_script)],
                           input=json.dumps(events["deny_pre"]), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=str(crash_root), env=env, timeout=120)
            check_eq("a guard that finished is recorded with its own exit code, not as a failure",
                     (stored(crash_root)["checks"].get("deny_guard") or {}).get("exit_code"), 0)
        finally:
            cleanup(crash_root)
    finally:
        cleanup(root)


def sc2_36_dispatch():
    """SC2-36 N1, E7: the context-probe dispatch follows the verified pair of THIS session only (pin; stage_guard is not changed)."""
    import hooklib
    import stage_guard as SG
    # The guard looks the project root up through a cache that lives as long as this process; the root the checks above
    # resolved is gone, and the dispatch must be judged against THIS project (a test of the pin, not of the cache).
    hooklib._PROJECT_ROOT_CACHE = None
    root = temp_project("qa-probe-dispatch-")
    try:
        events, _commands, _transcript = pair_events(root)
        for key, code in (("allow_pre", 0), ("deny_pre", 2)):
            host_probe.observe(root, events[key], "guard_pre_tool.py", code)
        host_probe.observe(root, events["allow_post"], "host_probe.py", 0)
        diag = {"tool_name": "Agent", "cwd": str(root), "session_id": SESSION,
                "tool_input": {"subagent_type": "qa-scout", "prompt": "QA_FACTORY_CONTEXT_PROBE"}}

        def dispatch(event):
            with contextlib.redirect_stderr(io.StringIO()):
                return SG.check_dispatch(event)
        check_eq("positive control: the pair is verified", host_probe.inspect(root)["status"], "verified")
        check_eq("verified pair in this session: check_dispatch allows the diagnostic", dispatch(diag), 0)
        check_eq("verified pair of another session: check_dispatch refuses",
                 dispatch(dict(diag, session_id="another-session")), 2)
    finally:
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(root)


def main():
    n1_pin()
    sc2_36_lock()
    sc2_36_parse()
    root = temp_project("qa-claude-probe-")
    try:
        pre = manifest_commands("PreToolUse", "Bash")
        post = manifest_commands("PostToolUse", "Bash")
        check("the guard on a shell call goes through the telemetry wrapper",
              any("telemetry_hook.py guard_pre_tool.py" in c for c in pre), str(pre))
        check("the probe is wired on PostToolUse for a shell call",
              any("telemetry_hook.py host_probe.py --hook" in c for c in post), str(post))

        probe = host_probe.prepare(root, SESSION)
        allow_cmd, deny_cmd = probe["commands"]
        transcript = root / "claude-transcript.jsonl"
        rows = [{"type": "user", "sessionId": SESSION, "message": {"role": "user", "content": "doctor"}}]
        for call, command in (("toolu_allow", allow_cmd), ("toolu_deny", deny_cmd)):
            rows.append({"type": "assistant", "sessionId": SESSION, "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": call, "name": "Bash", "input": {"command": command}}]}})
        transcript.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

        def event(hook, call, command):
            return {"hook_event_name": hook, "session_id": SESSION, "tool_name": "Bash",
                    "tool_use_id": call, "tool_input": {"command": command},
                    "transcript_path": str(transcript), "cwd": str(root)}

        guard = next(c for c in pre if "guard_pre_tool.py" in c)
        executed = next(c for c in post if "host_probe.py" in c)
        check_eq("the harmless ALLOW echo passes the guard",
                 run_manifest_line(guard, event("PreToolUse", "toolu_allow", allow_cmd), root), 0)
        check_eq("and its execution is observed",
                 run_manifest_line(executed, event("PostToolUse", "toolu_allow", allow_cmd), root), 0)
        check_eq("the DENY echo is blocked with the blocking exit code",
                 run_manifest_line(guard, event("PreToolUse", "toolu_deny", deny_cmd), root), 2)

        checks = json.loads((root / "qa-factory/state/host-probe.json").read_text(encoding="utf-8"))["checks"]
        check_eq("all three facts are on record", sorted(checks), ["allow_executed", "allow_guard", "deny_guard"])
        result = host_probe.inspect(root)
        check_eq("the probe verifies on Claude Code", result["status"], "verified")

        # The directory also holds receipts of other shapes (pretool-*, package-*, guard-parse-*) that
        # carry no `script`: `.get`, because glob order is the file system's - sorted on NTFS, arbitrary
        # on Linux (CI, B-301 a), where a bare `r["script"]` met one of them before the one sought.
        receipts = [json.loads(p.read_text(encoding="utf-8"))
                    for p in (root / "qa-factory/state/host-receipts").glob("*.json")]
        check("the guard leaves a receipt on this host",
              any(r.get("script") == "guard_pre_tool.py" and r.get("host") == "claude-code" for r in receipts))

        # A receipt is evidence only of the call it names.
        rows_now = host_probe._transcript_rows(transcript)
        check("a call id the transcript does not contain is not evidence",
              not host_probe.claude_call_present(rows_now, "toolu_forged", allow_cmd, SESSION))
        check("nor the right id with another command",
              not host_probe.claude_call_present(rows_now, "toolu_allow", "echo something else", SESSION))
        check("nor the right call in another session",
              not host_probe.claude_call_present(rows_now, "toolu_allow", allow_cmd, "another-session"))

        # --- the guard must still PARSE ordinary events, not only fire on them ------------
        # The allow/deny pair above proves the guard fires. PT-unparsed-event /
        # PT-patch-unchecked refuse fail-closed when it no longer reads what this host sends,
        # and their escalation ends in "run /qa-factory:qa-doctor" — so the doctor must have
        # a check of its own for it.
        parse = host_probe.guard_parse(root, SESSION)
        check_eq("an ordinary shell call is already clean evidence",
                 parse["families"]["bash"]["status"], "verified")
        check_eq("but a file write has not been seen yet", parse["status"], "unverified")
        check_in("and the doctor is told what to make happen", "Write of one temp file", parse["reason"])

        write_guard = next(c for c in manifest_commands("PreToolUse", "Write")
                           if "guard_pre_tool.py" in c)
        scratch = root / "qa-factory" / "state" / "doctor-guard-probe.txt"
        write_event = {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": "Write",
                       "tool_use_id": "toolu_write", "transcript_path": str(transcript),
                       "cwd": str(root), "tool_input": {"file_path": str(scratch),
                                                        "content": "qa-factory guard parse probe\n"}}
        check_eq("an ordinary Write passes the guard", run_manifest_line(write_guard, write_event, root), 0)
        parse = host_probe.guard_parse(root, SESSION)
        check_eq("both event shapes are now on record", parse["status"], "verified")
        check_eq("the write family names the tool it saw",
                 parse["families"]["write"]["tool_name"], "Write")

        # Codex emits apply_patch (also namespaced), never Write/Edit. Run the real guard line so
        # only a patch the guard actually READ and let through (exit 0) certifies the write family.
        for native_name in ("apply_patch", "functions.apply_patch"):
            native_session = SESSION + "-" + native_name
            native_event = dict(write_event, session_id=native_session, tool_name=native_name,
                                tool_input={"command": "*** Begin Patch\n*** Add File: " + str(scratch)
                                            + "\n+native guard probe\n*** End Patch"})
            check_eq("a native patch passes the guard: " + native_name,
                     run_manifest_line(write_guard, native_event, root), 0)
            native_parse = host_probe.guard_parse(root, native_session)
            check_eq("a native patch is write evidence: " + native_name,
                     native_parse["families"]["write"]["status"], "verified")
            check_eq("a native patch alone never certifies shell handling: " + native_name,
                     native_parse["families"]["bash"]["status"], "unverified")

        refused_session = SESSION + "-refused-patch"
        refused_event = dict(write_event, session_id=refused_session, tool_name="apply_patch",
                             tool_input={"command": "not a patch"})
        check_eq("a malformed native patch is still refused by the guard",
                 run_manifest_line(write_guard, refused_event, root), 2)
        check_eq("and a refused patch never certifies write handling",
                 host_probe.guard_parse(root, refused_session)["families"]["write"]["status"],
                 "unverified")

        # The receipt is about THIS guard: change the guard and the evidence is about another.
        stored = json.loads(host_probe._guard_parse_path(root, SESSION).read_text(encoding="utf-8"))
        stored["guard_hash"] = "0" * 64
        (host_probe._guard_parse_path(root, SESSION)).write_text(json.dumps(stored), encoding="utf-8")
        check_eq("evidence left by a different guard build does not count",
                 host_probe.guard_parse(root, SESSION)["status"], "unverified")
        (host_probe._guard_parse_path(root, SESSION)).write_text(
            json.dumps(dict(stored, guard_hash=host_probe._guard_hash())), encoding="utf-8")

        # A fail-closed refusal on record outranks any amount of clean handling.
        sys.path.insert(0, str(SCRIPTS))
        import guard_pre_tool  # noqa: E402
        counter = guard_pre_tool._escalation_path({"cwd": str(root)}, SESSION)
        check_eq("the doctor looks where the guard actually writes its counter",
                 host_probe.escalation_record_path(root, SESSION).resolve(), counter.resolve())
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text(json.dumps({"refusal": "PT-unparsed-event", "count": 2,
                                       "call": "pid-1", "at": "2026-09-21T10:00:00+00:00"}),
                           encoding="utf-8")
        parse = host_probe.guard_parse(root, SESSION)
        check_eq("a fail-closed refusal makes the check red", parse["status"], "guard_defect")
        check_eq("owned by the factory, never by the person", parse["owner"], "factory")
        check_in("and names the refusal", "PT-unparsed-event", parse["reason"])
        check_in("with nothing asked of the person", "nothing here is the person's to repair",
                 parse["reason"])
        check_eq("the doctor's own report carries the check",
                 host_probe.inspect(root)["guard_parse"]["status"], "guard_defect")

        # --- a probe file that cannot be judged is one answer, never a traceback ------------
        # `inspect` read `data["created_at"]` outside the guarded read: a file holding a JSON list, no
        # `created_at`, a time that is not ISO, or one with no UTC offset ended the doctor in a traceback.
        probe_path = root / "qa-factory/state/host-probe.json"
        good = probe_path.read_bytes()
        parsed = json.loads(good)
        cases = {
            "JSON that is not an object": json.dumps(["created_at"]),
            "an object with no created_at": json.dumps({k: v for k, v in parsed.items() if k != "created_at"}),
            "a created_at that is not an ISO time": json.dumps(dict(parsed, created_at="the other day")),
            "a naive created_at (no UTC offset)": json.dumps(
                dict(parsed, created_at=datetime.now().replace(tzinfo=None).isoformat())),
            "a created_at that is not a string": json.dumps(dict(parsed, created_at=1727780000)),
            "a file that is not JSON (the shape that always worked)": "{not json",
        }
        for label, text in cases.items():
            probe_path.write_text(text, encoding="utf-8")
            try:
                got = host_probe.inspect(root)
            except Exception as exc:  # noqa: BLE001 - the traceback is what is asserted against
                got = {"status": f"traceback: {exc!r}", "reason": ""}
            check_eq(f"{label}: unverified, and the reason names the way to a fresh probe",
                     (got["status"], "host_probe.py --prepare" in got["reason"]), ("unverified", True))
        probe_path.write_bytes(good)
        check_eq("positive control: the good file still inspects", host_probe.inspect(root)["status"], "verified")

        # --- a package that cannot be read is neither `verified` nor `stale` (collect/2 CL2-1; FR-41, AR-28) -------------
        # The probe is bound to the package's bytes; bytes that were not read measure no change, so nothing is judged
        # against them. The survivor's seam (`release_fingerprint._read_bytes`) simulates the unreadable file, never chmod.
        import release_fingerprint as RF
        real_read = RF._read_bytes
        stored = json.loads(good)
        deny_event = {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": "Bash",
                      "tool_use_id": "toolu_deny_unread", "tool_input": {"command": stored["commands"][1]}}

        def unreadable(path):
            raise PermissionError("seam: unreadable " + str(path))
        RF._read_bytes = unreadable
        try:
            got = host_probe.inspect(root)                 # the store that verified a moment ago, the package now unread
            check_eq("an unread package: a store that verified is `unverified`, never `verified`, never `stale`",
                     got["status"], "unverified")
            check_in("...and the detail names what could not be read", "package_unreadable", got.get("fingerprint_detail", ""))
            check_in("...and the way out", "--prepare", got.get("fingerprint_detail", ""))
            check("...and the detail names the files (a long list cut at 10, saying how much it hid), not only 'fix the file'",
                  "the files that could not be read: " in got.get("fingerprint_detail", "") and "agents/qa-automator.md" in got.get("fingerprint_detail", "")
                  and "more)" in got.get("fingerprint_detail", ""), got.get("fingerprint_detail", ""))
            check_in("...the reason states the evidence was not judged (FR-10: it does not say 'missing evidence')",
                     "package files could not be read; the evidence was not judged", got.get("reason", ""))
            check("...and no longer tells the doctor the allow/deny evidence is missing", "Missing live" not in got.get("reason", ""), got.get("reason", ""))
            check_eq("...the next action is a fresh probe", got["next_action"], "prepare_probe")
            try:
                blocked = host_probe.observe(root, deny_event)
                raised = ""
            except Exception as exc:  # noqa: BLE001 - nothing may escape the hook wrapper's try block
                blocked, raised = None, type(exc).__name__
            check_eq("an unread package: observe raises nothing", raised, "")
            check_eq("...and does not ask the guard to block the DENY echo", blocked, False)
            check_eq("...nor does the guard's receipt land", host_probe.observe(root, deny_event, "guard_pre_tool.py", 2), False)
            check_eq("...no receipt was written", json.loads(probe_path.read_text(encoding="utf-8"))["checks"], stored["checks"])
            fresh = host_probe.prepare(root, SESSION)      # prepare on an unread package stores a value no read can equal
            check("...prepare stores an `unknown:` fingerprint (the nonce), not a hash", fresh["fingerprint"].startswith("unknown:package_unreadable:"))
            after = host_probe.inspect(root)
            check_eq("...and a probe prepared on unread bytes is `unverified` with the detail",
                     (after["status"], "package_unreadable" in after.get("fingerprint_detail", "")), ("unverified", True))
        finally:
            RF._read_bytes = real_read

        def only_hooklib(path):
            if os.path.basename(str(path)) == "hooklib.py":
                raise PermissionError("seam: unreadable hooklib.py")
            return real_read(path)
        RF._read_bytes = only_hooklib
        try:
            one = host_probe.inspect(root)
            check_in("one unreadable package file is named, once, with no cut", "the files that could not be read: scripts/hooklib.py.",
                     one.get("fingerprint_detail", ""))
        finally:
            RF._read_bytes = real_read
        # a walk that fails other than by an OSError names nothing and passes nothing (FR-41)
        def broken(path):
            raise RuntimeError("seam: the walk failed")
        RF._read_bytes = broken
        try:
            odd = host_probe.inspect(root)
            check_eq("a walk failing otherwise: `unverified`, and the detail says it could not list them",
                     (odd["status"], "the files that could not be read: could not list them." in odd.get("fingerprint_detail", "")),
                     ("unverified", True))
        finally:
            RF._read_bytes = real_read
        # E6: a store made by the old recipe (any other 64-hex value) reads `stale`, once - the safe direction, never `verified`
        probe_path.write_text(json.dumps(dict(stored, fingerprint="0" * 64)), encoding="utf-8")
        old_recipe = host_probe.inspect(root)
        check_eq("a store bound to another fingerprint is `stale` (as before), with no unread-bytes detail",
                 (old_recipe["status"], "fingerprint_detail" in old_recipe), ("stale", False))
        probe_path.write_bytes(good)
        again = host_probe.inspect(root)
        check_eq("positive control: with the seam restored the same store verifies", again["status"], "verified")
        check("...and carries no fingerprint_detail", "fingerprint_detail" not in again)
        check_eq("...and the DENY echo blocks again", host_probe.observe(root, deny_event), True)

        # --- RH1-11 (FB-6): the result names EVERY unmet condition of the conjunction, in its order ---------------------
        # One test per condition: it makes exactly that condition fail and asserts the whole list of ids (a co-failure that
        # the mutation itself causes is named in the expected list). `verified` is untouched: same status on every input.
        probe_path.write_bytes(good)

        def unmet(mutate):
            data = json.loads(good)
            mutate(data)
            probe_path.write_text(json.dumps(data), encoding="utf-8")
            got = host_probe.inspect(root)
            return got, [m["id"] for m in got["missing"]]

        def at(**fields):
            def apply(data):
                for key, value in fields.items():
                    data[key] = value
            return apply

        def set_check(name, **fields):
            def apply(data):
                data["checks"][name] = dict(data["checks"][name], **fields)
            return apply

        got, ids = unmet(lambda data: None)
        check_eq("RH1-11: verified -> `missing` is present and EMPTY (a list, not absent)",
                 (got["status"], got["missing"], got["reason"]), ("verified", [], "Host allow/deny behavior verified"))
        check_eq("RH1-11: one unmet condition per test - a changed fingerprint",
                 unmet(at(fingerprint="0" * 64))[1], ["fingerprint_changed"])
        RF._read_bytes = unreadable
        try:
            got, ids = unmet(lambda data: None)
            check_eq("RH1-11: unread package bytes are `fingerprint_unread`, not `fingerprint_changed`", (got["status"], ids),
                     ("unverified", ["fingerprint_unread"]))
        finally:
            RF._read_bytes = real_read
        # the 24 h boundary: a pair just INSIDE and just BEYOND it (the clock moves, so a few seconds either side)
        from datetime import timedelta, timezone
        stamp = lambda delta: (datetime.now(timezone.utc) + delta).isoformat()
        got, ids = unmet(at(created_at=stamp(timedelta(hours=-24, seconds=30))))
        check_eq("RH1-11/24h: 30 s inside the window still verifies, `missing` empty", (got["status"], ids), ("verified", []))
        got, ids = unmet(at(created_at=stamp(timedelta(hours=-24, seconds=-30))))
        check_eq("RH1-11/24h: 30 s beyond the window is `stale` and names `probe_expired` only", (got["status"], ids),
                 ("stale", ["probe_expired"]))
        check_eq("RH1-11/24h: a probe dated in the future is not current either", unmet(at(created_at=stamp(timedelta(hours=1))))[1],
                 ["probe_expired"])
        check_eq("RH1-11: the guard did not record exit 0 for ALLOW", unmet(set_check("allow_guard", exit_code=1))[1],
                 ["allow_guard_not_allowed"])
        check_eq("RH1-11: the guard did not record exit 2 for DENY", unmet(set_check("deny_guard", exit_code=0))[1],
                 ["deny_guard_not_blocked"])
        check_eq("RH1-11: the executed call has another id than the ALLOW receipt (and that id is not in the transcript)",
                 unmet(set_check("allow_executed", tool_use_id="toolu_other"))[1],
                 ["allow_executed_id_differs", "allow_executed_not_in_transcript"])
        check_eq("RH1-11: DENY was executed", unmet(lambda data: data["checks"].update(deny_executed=True))[1], ["deny_was_executed"])
        for name in ("allow_guard", "deny_guard", "allow_executed"):
            check_eq(f"RH1-11: `{name}` names a transcript that is not there -> `{name}_no_transcript`",
                     unmet(set_check(name, transcript_path=str(root / "no-such-transcript.jsonl")))[1], [f"{name}_no_transcript"])
            check_eq(f"RH1-11: `{name}` with a command the transcript never held -> `{name}_not_in_transcript`",
                     unmet(set_check(name, command="echo something else"))[1], [f"{name}_not_in_transcript"])
        check_eq("RH1-11: a missing ALLOW receipt id is named (and the id differs from the executed call's)",
                 unmet(lambda data: data["checks"]["allow_guard"].pop("tool_use_id"))[1],
                 ["allow_executed_id_differs", "allow_guard_no_receipt"])
        # fix 2 killer: the sentence names both ids, and "none" for an absent one (FR-41), never an id that is not there
        real_allow_id = json.loads(good)["checks"]["allow_guard"]["tool_use_id"]
        got, ids = unmet(lambda data: data["checks"]["allow_guard"].pop("tool_use_id"))
        text = next(m["reason"] for m in got["missing"] if m["id"] == "allow_executed_id_differs")
        check("RH1-11/ids: an absent ALLOW receipt id is named `none`, not claimed", "receipt id (none)" in text, text)
        got, ids = unmet(set_check("allow_executed", tool_use_id="toolu_other"))
        text = next(m["reason"] for m in got["missing"] if m["id"] == "allow_executed_id_differs")
        check("RH1-11/ids: both ids are named when both exist",
              "(toolu_other)" in text and f"receipt id ({real_allow_id})" in text, text)
        # fix 3 killer: valid JSON of the wrong shape is judged as empty, listed as unmet, never a crash
        none_receipt = ["allow_guard_not_allowed", "allow_executed_id_differs", "allow_guard_no_receipt"]
        for label, mutate, want in (
                ("`checks` is a list", at(checks=[1]), None),
                ("`checks` is a string", at(checks="x"), None),
                ("a receipt is null", lambda data: data["checks"].update(allow_guard=None), none_receipt),
                ("a receipt is a list", lambda data: data["checks"].update(allow_guard=[1]), none_receipt),
                ("a receipt is a number", lambda data: data["checks"].update(allow_guard=7), none_receipt)):
            got, ids = unmet(mutate)
            check_eq(f"RH1-11/shape: {label}: `unverified`, no crash", got["status"], "unverified")
            # No fact of the pair AND the native-patch sessions above left guard-parse receipts after --prepare: the
            # SC2-36 condition `other_session_hooks` is true here, and comes last (it never removes another one).
            check_eq(f"RH1-11/shape: {label}: the unmet ids are listed",
                     ids, want or ["allow_guard_not_allowed", "deny_guard_not_blocked", "allow_guard_no_receipt",
                                   "deny_guard_no_receipt", "allow_executed_no_receipt", "other_session_hooks"])
        check_eq("RH1-11: no checks at all: every condition that fails is named, none skipped",
                 unmet(lambda data: data.update(checks={}))[1],
                 ["allow_guard_not_allowed", "deny_guard_not_blocked", "allow_guard_no_receipt", "deny_guard_no_receipt",
                  "allow_executed_no_receipt", "other_session_hooks"])
        # THE mutation-killer ("drop the second unmet condition from the list"): two failures, both must be listed, in order
        got, ids = unmet(lambda data: (set_check("allow_guard", exit_code=1)(data), set_check("deny_guard", exit_code=0)(data)))
        check_eq("RH1-11: TWO unmet conditions are BOTH listed, in the order of the conjunction", ids,
                 ["allow_guard_not_allowed", "deny_guard_not_blocked"])
        check_eq("RH1-11: ...with a human sentence each", all(m["reason"] for m in got["missing"]), True)
        check("RH1-11: ...the reason keeps its first sentence and lists the unmet ids after it",
              got["reason"].startswith("Missing live allow/deny evidence; no synthetic probe certifies host activation.")
              and "Unmet: allow_guard_not_allowed (" in got["reason"] and "; deny_guard_not_blocked (" in got["reason"], got["reason"])
        # an unknown is never a pass: no file, a file that is not a probe - each is its own named condition, no traceback
        probe_path.unlink()
        got = host_probe.inspect(root)
        check_eq("RH1-11: no probe file -> `no_probe_file`", (got["status"], [m["id"] for m in got["missing"]]),
                 ("unverified", ["no_probe_file"]))
        check_in("RH1-11: ...and its reason keeps the door and lists the condition", "host_probe.py --prepare", got["reason"])
        probe_path.write_text("{not json", encoding="utf-8")
        check_eq("RH1-11: a file that is not JSON -> `probe_file_unreadable`", [m["id"] for m in host_probe.inspect(root)["missing"]],
                 ["probe_file_unreadable"])
        probe_path.write_bytes(good)
        check_eq("RH1-11: positive control: the good store verifies again", host_probe.inspect(root)["missing"], [])
    finally:
        cleanup(root)
    sc2_36_dispatch()
    finish("test_claude_host_probe")


if __name__ == "__main__":
    main()
