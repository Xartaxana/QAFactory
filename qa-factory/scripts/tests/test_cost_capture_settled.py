"""DP-3 (HF7-3): a session that has ended is final without a person; one logic stamp; the state of a session is
worked out at the render, never stored (cost_capture.session_verdict / _stale_kind / recapture_*; factory_dashboard
session_marks / task_completeness / stale_files / main).

Time is moved with `now` (and `os.utime` well away from any boundary), never with a real wait (FR-31). Fixtures are
synthetic (`fixtures/synthetic-settled/`, see its README): no money, no personal path.
"""
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
import dispatch_liveness as DL
import factory_dashboard as D
import hooklib as HL
import host_adapter as HA
import retro_numbers as RNS
import task_price as TP
import test_dashboard_task_binding as B
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project

FIX = Path(__file__).resolve().parent / "fixtures" / "synthetic-settled"
TAILS = json.loads((FIX / "tails.json").read_text(encoding="utf-8"))
LIMITS = (C.final_idle_s({}), C.final_open_s({}))     # (1800, 86400): the defaults
MONEY_KEY = re.compile(r"(?:^|_)(?:cost|usd)(?:_|$)|subtotal|reconciliation|priced_subtotal|total_cost", re.I)
DOLLAR_DIGIT = re.compile(r"\$\s?\d")


def write_rows(path: Path, rows, torn=False, age=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r) + "\n" for r in rows)
    path.write_text(text.rstrip("\n") if torn else text, encoding="utf-8")
    if age is not None:
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
    return path


def usage_row(text="placeholder answer"):
    usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0,
             "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}
    return {"type": "assistant", "isSidechain": False, "requestId": "req-1", "uuid": "u1", "timestamp": "2026-09-20T19:00:00Z",
            "message": {"model": "claude-sonnet-5", "usage": usage, "content": [{"type": "text", "text": text}]}}


def fixture_doc(name, transcript, **over):
    doc = json.loads((FIX / name).read_text(encoding="utf-8").replace("{transcripts}", str(transcript.parent).replace("\\", "/")))
    doc["transcript"] = str(transcript)
    doc.update(over)
    return doc


def verdict(rows, age, now=None, torn=False, open_s=None):
    """session_settled over a temp transcript whose mtime is `age` seconds before the clock (or before `now`)."""
    folder = temp_dir("settled-")
    try:
        clock = time.time() if now is None else now
        path = write_rows(folder / "s.jsonl", rows, torn=torn)
        os.utime(path, (clock - age, clock - age))
        return C.session_settled(path, LIMITS[0], open_s or LIMITS[1], clock)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def money_problems(folder: Path) -> list:
    """F15: no money field with a non-zero value and no `$`+digit in any file of the fixture folder."""
    found = []

    def walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                if MONEY_KEY.search(str(key)) and item not in (None, 0, "0", "0.0", {}, [], False):
                    found.append(f"{where}:{key}")
                walk(item, where)
        elif isinstance(value, list):
            for item in value:
                walk(item, where)
    for path in sorted(folder.glob("*")):
        text = path.read_text(encoding="utf-8")
        if DOLLAR_DIGIT.search(text):
            found.append(f"{path.name}: dollar+digit")
        if path.suffix == ".json":
            walk(json.loads(text), path.name)
        if "C:\\Users" in text or "\\Users\\" in text:
            found.append(f"{path.name}: personal path")
    return found


def page_of(root, *flags):
    out = Path(root).parent / f"page-{len(list(Path(root).parent.glob('page-*.html')))}.html"
    with contextlib.redirect_stdout(io.StringIO()):
        D.main(["--root", str(root), "--out", str(out), *flags])
    import html
    return html.unescape(out.read_text(encoding="utf-8"))


def main() -> None:
    # --- K4 (B2): one stamp ------------------------------------------------------------------------------------------
    check("K4 the stamp is not the old one and names this release", C.READER_STAMP != "iterations-1" and C.READER_STAMP == "capture-0.10.7")

    root = temp_project()
    use_project(root)
    work = temp_dir("settled-work-")
    try:
        os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
        cost_dir = root / "qa-factory" / "state" / "cost"
        cost_dir.mkdir(parents=True, exist_ok=True)
        activity = root / "qa-factory" / "state" / "activities" / "none.json"
        transcripts = root / "transcripts"

        # F15 control of the fixture itself
        check_eq("K0 the fixture folder holds no money and no personal path", money_problems(FIX), [])
        probe = temp_dir("settled-money-")
        try:
            for name in ("tails.json", "README.txt", "cost-0.10.4-provisional.json"):
                shutil.copy(FIX / name, probe / name)
            (probe / "cost-0.10.4-provisional.json").write_text(json.dumps({"subtotal_usd": "1.5", "note": "$1.00"}), encoding="utf-8")
            check("K0 control: one non-zero subtotal_usd and a `$1.00` text turn the check red", len(money_problems(probe)) >= 2)
        finally:
            shutil.rmtree(probe, ignore_errors=True)

        # --- K1: the world before (0.10.4 files) ------------------------------------------------------------------
        main_t = transcripts / "old-provisional.jsonl"
        write_rows(main_t, [{"type": "user", "promptId": "p", "message": {"content": "placeholder"}}, usage_row()], age=7200)
        doc = fixture_doc("cost-0.10.4-provisional.json", main_t, session_id="old-provisional")
        check_eq("K1 rule (i): a file with no capture_logic and a transcript is `logic`",
                 C._stale_kind(doc, activity, limits=LIMITS)[0], "logic")
        done_t = transcripts / "old-complete.jsonl"
        write_rows(done_t, [{"type": "user", "promptId": "p", "message": {"content": "placeholder"}}, usage_row()], age=7200)
        for sid, name, tr in (("old-provisional", "cost-0.10.4-provisional.json", main_t), ("old-complete", "cost-0.10.4-complete.json", done_t)):
            (cost_dir / f"{sid}.json").write_text(json.dumps(fixture_doc(name, tr, session_id=sid)), encoding="utf-8")
        results = {r["session_id"]: r for r in C.recapture_stale(root)}
        check_eq("K1 the pass recomputes both files of the old logic (one pass, not two)",
                 sorted((s, r["status"]) for s, r in results.items() if s.startswith("old-")),
                 [("old-complete", "recomputed"), ("old-provisional", "recomputed")])
        for sid in ("old-provisional", "old-complete"):
            after = json.loads((cost_dir / f"{sid}.json").read_text(encoding="utf-8"))
            check_eq(f"K1 {sid}: complete, stamped, final by rule `settled`",
                     (after["usage_completeness"], after["capture_logic"], (after["usage_final"] or {}).get("rule")),
                     ("complete", C.READER_STAMP, "settled"))
        check_eq("K1 the second pass finds nothing to do", [r for r in C.recapture_stale(root) if r["session_id"].startswith("old-")], [])

        # --- K2 (B1): no transcript -> no alarm ---------------------------------------------------------------------
        ghost = fixture_doc("cost-0.10.4-provisional.json", transcripts / "gone.jsonl", session_id="old-ghost")
        check_eq("K2 rule (i) is silent without a transcript", C._stale_kind(ghost, activity, limits=LIMITS), ("", ""))
        ghost_path = cost_dir / "old-ghost.json"
        ghost_path.write_text(json.dumps(ghost), encoding="utf-8")
        before = ghost_path.read_bytes()
        check_eq("K2 the pass does not return it", [r for r in C.recapture_stale(root) if r["session_id"] == "old-ghost"], [])
        check("K2 and the file is byte for byte as it was", ghost_path.read_bytes() == before)
        check_eq("K2 control: the same file WITH a transcript is flagged",
                 C._stale_kind(dict(ghost, transcript=str(main_t)), activity, limits=LIMITS)[0], "logic")
        check_eq("K2 no `transcript` key at all is not an exception", C._stale_kind({k: v for k, v in ghost.items() if k != "transcript"}, activity, limits=LIMITS), ("", ""))
        check_eq("K2 `transcript: null` is not an exception either", C._stale_kind(dict(ghost, transcript=None), activity, limits=LIMITS), ("", ""))

        # --- K3 (B1, E10): parent and live are `kept`, never an alarm -----------------------------------------------
        slug = C.project_slug(root)
        parent_t = root / "projects" / "some-other-project" / "old-parent.jsonl"
        write_rows(parent_t, [usage_row()], age=7200)
        (cost_dir / "old-parent.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", parent_t, session_id="old-parent")), encoding="utf-8")
        live_t = root / "projects" / slug / "old-live.jsonl"
        write_rows(live_t, [usage_row()], age=20)
        (cost_dir / "old-live.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", live_t, session_id="old-live")), encoding="utf-8")
        results = C.recapture_stale(root)
        by = {r["session_id"]: r for r in results}
        check_eq("K3 parent and live files of the old logic are `kept`", (by["old-parent"]["status"], by["old-live"]["status"]), ("kept", "kept"))
        check_in("K3 and say why in the pass's words", "captured by an older capture logic", by["old-live"]["reason"])
        check_eq("K3 `stale_outcomes` does not carry `kept`", {k for k in D.stale_outcomes(results) if k in ("old-parent", "old-live")}, set())
        parent_doc = fixture_doc("cost-0.10.4-provisional.json", parent_t, session_id="old-parent", capture_logic=C.READER_STAMP)
        check_eq("K3 (ii) never reads a parent's transcript: provisional + parent -> current",
                 C._stale_kind(parent_doc, activity, limits=LIMITS, slug=slug), ("", ""))
        check_eq("K3 control: the same document of this project IS stale once its session ended",
                 C._stale_kind(dict(parent_doc, transcript=str(main_t)), activity, limits=LIMITS, slug=slug)[0], "stale")
        check("K3 a parent is `skipped` (the door), not `kept`, when the file is stale for another reason",
              C._recapture_skip(parent_doc, slug, 64.0, False)["code"] == "parent")

        # --- K4 (B2): the document and the key carry the stamp ------------------------------------------------------
        cap_t = transcripts / "cap.jsonl"
        write_rows(cap_t, [usage_row()], age=7200)
        event = {"hook_event_name": "Stop", "session_id": "cap", "transcript_path": str(cap_t), "cwd": str(root)}
        check("K4 a first capture writes", C._capture(event) is True)
        written = json.loads((cost_dir / "cap.json").read_text(encoding="utf-8"))
        check_eq("K4 the document carries `capture_logic` == READER_STAMP; a hook capture is provisional, `usage_final` null",
                 (written["capture_logic"], written["usage_completeness"], written["usage_final"]), (C.READER_STAMP, "provisional", None))
        check("K4 an unchanged capture is skipped", not C._capture(event))
        real_stamp = C.READER_STAMP
        C.READER_STAMP = "capture-test-other"
        try:
            check("K4 another stamp changes the key: the capture writes again", C._capture(event) is True)
        finally:
            C.READER_STAMP = real_stamp

        # --- K5: a turn left open ---------------------------------------------------------------------------------
        open_t = transcripts / "open.jsonl"
        write_rows(open_t, [usage_row()] + TAILS["main_tool_use_then_noise_open"], age=7200)
        state, why = C.session_settled(open_t, *LIMITS)
        check_eq("K5 an open turn younger than the open limit is `open`", state, "open")
        check_in("K5 and the reason names the file", "open.jsonl", why)
        (cost_dir / "open.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", open_t, session_id="open", capture_logic=C.READER_STAMP)), encoding="utf-8")
        check_eq("K5 (ii) does not fire on an open session", C._stale_kind(json.loads((cost_dir / "open.json").read_text(encoding="utf-8")), activity, limits=LIMITS)[0], "")
        check_eq("K5 --recapture --session of it is provisional, usage_final null (F-4)",
                 (C.recapture_session(root, "open")["status"],
                  json.loads((cost_dir / "open.json").read_text(encoding="utf-8"))["usage_completeness"],
                  json.loads((cost_dir / "open.json").read_text(encoding="utf-8"))["usage_final"]), ("recomputed", "provisional", None))

        # --- K5a: the real shapes of a tail --------------------------------------------------------------------------
        shapes = (("main_tool_use_then_noise_open", "open"), ("main_tool_result_last_open", "open"),
                  ("main_two_tool_use_one_result_open", "open"), ("main_text_then_noise_closed", "settled"),
                  ("main_meta_user_after_answer_closed", "settled"))
        for name, expected in shapes:
            check_eq(f"K5a main file `{name}` -> {expected}", verdict(TAILS[name], 7200)[0], expected)
        for name, expected in (("role_handback_closed", "settled"), ("role_foreign_call_open", "open")):
            folder = temp_dir("settled-role-")
            try:
                main_f = write_rows(folder / "sess.jsonl", TAILS["main_text_then_noise_closed"], age=7200)
                write_rows(folder / "sess" / "subagents" / "agent-1.jsonl", TAILS[name], age=7200)
                check_eq(f"K5a role file `{name}` -> {expected}", C.session_settled(main_f, *LIMITS)[0], expected)
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        # a role file with the handback call, when the host's forms name no handback tool: the safe side, open
        real_forms = HA.REPORT_FORMS_FILE
        bad = work / "no-forms.json"
        bad.write_text("{}", encoding="utf-8")
        folder = temp_dir("settled-role-")
        try:
            main_f = write_rows(folder / "sess.jsonl", TAILS["main_text_then_noise_closed"], age=7200)
            write_rows(folder / "sess" / "subagents" / "agent-1.jsonl", TAILS["role_handback_closed"], age=7200)
            HA.REPORT_FORMS_FILE = bad
            try:
                check_eq("K5a with no readable handback form a handed-back role file stays `open` (AR-28)", C.session_settled(main_f, *LIMITS)[0], "open")
            finally:
                HA.REPORT_FORMS_FILE = real_forms
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        # --- K6 (F5): AT / BEYOND the open limit, with `now` -------------------------------------------------------------
        open_s = LIMITS[1]
        for delta, expected in ((-1, "open"), (0, "settled"), (1, "settled")):
            got = verdict(TAILS["main_tool_use_then_noise_open"], open_s + delta, now=1_700_000_000)
            check_eq(f"K6 open turn, age = open limit {delta:+d} s -> {expected}", got[0], expected)
            if expected == "settled":
                check_in("K6 the reason says `timed out`", "ended mid-turn (timed out)", got[1])
        timed_t = transcripts / "timed.jsonl"
        write_rows(timed_t, TAILS["main_tool_use_then_noise_open"] + [usage_row()][:0], age=25 * 3600)
        (cost_dir / "timed.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", timed_t, session_id="timed")), encoding="utf-8")
        check_eq("K6 the pass recomputes it", [r["status"] for r in C.recapture_stale(root) if r["session_id"] == "timed"], ["recomputed"])
        timed_doc = json.loads((cost_dir / "timed.json").read_text(encoding="utf-8"))
        check_eq("K6 complete, `usage_final.rule` = timed_out", (timed_doc["usage_completeness"], timed_doc["usage_final"]["rule"]), ("complete", "timed_out"))
        marks = D.session_marks([timed_doc], {}, {})
        text, cls, is_finding = D.task_completeness({"session_ids": {"timed"}, "provisional_sessions": set(), "ok": True}, marks)
        check_eq("K6 the row says it ended mid-turn; information, not a finding", ("ended mid-turn" in text, is_finding), (True, False))
        check_eq("K6 the class is `skip` and no `reconciled` stands beside the words (F1)", (cls, "reconciled" in text), ("skip", False))

        # --- K7: the limits ---------------------------------------------------------------------------------------------
        closed = TAILS["main_text_then_noise_closed"]
        for delta, expected in ((-1, "live"), (0, "settled"), (1, "settled")):
            check_eq(f"K7 age = idle limit {delta:+d} s -> {expected}", verdict(closed, LIMITS[0] + delta, now=1_700_000_000)[0], expected)
        check_eq("K7 299 s in the config is raised to the 300 s floor (BEYOND)", C.final_idle_s({"usage_final_after_idle_min": 299 / 60}), 300)
        check_eq("K7 5 minutes stays 300 (AT)", C.final_idle_s({"usage_final_after_idle_min": 5}), 300)
        check_eq("K7 the floor is the pass's own live window", C.final_idle_s({"usage_final_after_idle_min": 0}), C.RECAPTURE_LIVE_WINDOW_S)
        check_eq("K7 open below idle is raised to idle", C.final_open_s({"usage_final_after_open_h": 0.01, "usage_final_after_idle_min": 60}), 3600)
        for label, cfg in (("not a number", {"usage_final_after_idle_min": "x"}), ("bool", {"usage_final_after_idle_min": True}),
                           ("negative", {"usage_final_after_idle_min": -5}), ("NaN", {"usage_final_after_idle_min": float("nan")}),
                           ("Infinity", {"usage_final_after_idle_min": float("inf")}), ("huge int", {"usage_final_after_idle_min": 10 ** 400}),
                           ("null", {"usage_final_after_idle_min": None}), ("cost not an object", [1, 2]), ("absent", {})):
            noise = io.StringIO()
            with contextlib.redirect_stderr(noise):
                got = C.final_idle_s(cfg)
            check_eq(f"K7 {label}: the default (30 min) {'' if label == 'absent' else 'and a line on stderr'}",
                     (got, bool(noise.getvalue())), (1800, label != "absent"))
        check_eq("K7 open: NaN and negative give the default 24 h", (C.final_open_s({"usage_final_after_open_h": float("nan")}), C.final_open_s({"usage_final_after_open_h": -1})), (86400, 86400))
        noise = io.StringIO()
        with contextlib.redirect_stderr(noise):
            C.final_limits({"usage_final_after_idle_min": "x", "usage_final_after_open_h": "y"})
        check_eq("K7 one line on stderr per read, not one per key", noise.getvalue().count("\n"), 1)
        # the same window through the callers: pass, marks, `recapture_session`, a BOM config
        cfg_path = root / "qa-factory" / "config.json"
        base_cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        quiet_t = transcripts / "quiet.jsonl"
        write_rows(quiet_t, [usage_row()] + closed, age=2400)       # 40 minutes quiet: ended by default, not yet at 60
        (cost_dir / "quiet.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", quiet_t, session_id="quiet", capture_logic=C.READER_STAMP)), encoding="utf-8")
        for bom in ("", "\ufeff"):
            cfg_path.write_text(bom + json.dumps(dict(base_cfg, cost=dict(base_cfg.get("cost") or {}, usage_final_after_idle_min=60),
                                                      retro={"orchestrator_share_max": 0.5})), encoding="utf-8")
            quiet_doc = json.loads((cost_dir / "quiet.json").read_text(encoding="utf-8"))
            pass_says = [r for r in C.recapture_stale(root) if r["session_id"] == "quiet"]
            marks_say = D.session_marks([quiet_doc], C.project_cost_block(root), {})["quiet"]["state"]
            C.recapture_session(root, "quiet")
            after = json.loads((cost_dir / "quiet.json").read_text(encoding="utf-8"))["usage_completeness"]
            label = "BOM" if bom else "plain"
            # the capture's own config reader (`hooklib.load_config`) and the price's read the same file at the same rates
            check_eq(f"K7 {label} config: `hooklib.load_config` reads the file (a BOM is not a project that is not onboarded)",
                     (HL.load_config().get("cost") or {}).get("usage_final_after_idle_min"), 60)
            check_eq(f"K7 {label} config: `retro_numbers.share_limit_percent` reads its own key (50), not the default",
                     RNS.share_limit_percent(cfg_path.parent), 50.0)
            check_eq(f"K7 {label} config, idle 60 min, 40 min quiet: pass leaves it, marks say live, recapture stays provisional",
                     (pass_says, marks_say, after), ([], "live", "provisional"))
        cfg_path.write_text(json.dumps(base_cfg), encoding="utf-8")
        check_eq("K7 without the key the same 40 minutes are final", (C.recapture_session(root, "quiet")["status"], json.loads((cost_dir / "quiet.json").read_text(encoding="utf-8"))["usage_completeness"]), ("recomputed", "complete"))

        # --- K9 (F6) and K10: positions ---------------------------------------------------------------------------
        codex_doc = dict(fixture_doc("cost-0.10.4-provisional.json", quiet_t, session_id="cx", capture_logic=C.READER_STAMP), usage_completeness="partial")
        check_eq("K9 Codex `partial` + an ended session is not stale (no recompute on every render)", C._stale_kind(codex_doc, activity, limits=LIMITS), ("", ""))
        check_eq("K9 control: `provisional` there is", C._stale_kind(dict(codex_doc, usage_completeness="provisional"), activity, limits=LIMITS)[0], "stale")
        lost_doc = fixture_doc("cost-0.10.4-provisional.json", quiet_t, session_id="lost", scan_checkpoints={
            str(quiet_t.resolve()): {"offset": quiet_t.stat().st_size}, str(work / "no-such-file.jsonl"): {"offset": 3}})
        check_eq("K10 a lost stream wins over the old logic (position invariant)", C._stale_kind(lost_doc, activity, limits=LIMITS)[0], "lost")
        check_eq("K10 and over the ended session", C._stale_kind(dict(lost_doc, capture_logic=C.READER_STAMP), activity, limits=LIMITS)[0], "lost")
        (cost_dir / "lost.json").write_text(json.dumps(lost_doc), encoding="utf-8")
        lost_out = [r for r in C.recapture_stale(root) if r["session_id"] == "lost"]
        check_eq("K10 the pass `skipped` it with the door", (lost_out[0]["status"], "--recapture --session" in lost_out[0]["reason"]), ("skipped", True))

        # --- K11: unreadable and awkward inputs -----------------------------------------------------------------------
        for delta, expected in ((-1, "unknown"), (0, "settled"), (1, "settled")):
            got = verdict(closed, open_s + delta, now=1_700_000_000, torn=True)
            check_eq(f"K11 torn last line, age = open limit {delta:+d} s -> {expected}", got[0], expected)
            if expected == "settled":
                check_in("K11 the reason says so", "ended with an unreadable last line (timed out)", got[1])
        real_rows = C._last_chain_rows
        def boom(*args, **kw):
            raise OSError("denied")
        C._last_chain_rows = boom
        try:
            check_eq("K11 OSError on the tail is `unknown` with NO timeout (even at 100 h)", verdict(closed, 100 * 3600)[0], "unknown")
        finally:
            C._last_chain_rows = real_rows
        real_cap = DL._LAST_ROW_CAP_BYTES
        DL._LAST_ROW_CAP_BYTES = 200
        try:
            long_row = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 400}]}}]
            check_eq("K11 a last line longer than the cap before the limit: unknown", verdict(long_row, 3600)[0], "unknown")
            check_eq("K11 and at the limit: settled, as a torn line", verdict(long_row, open_s + 1)[0], "settled")
        finally:
            DL._LAST_ROW_CAP_BYTES = real_cap
        check_eq("K11 a clock in the future is age 0: live", verdict(closed, -3600)[0], "live")
        check_eq("K11 an empty file has no turn open", verdict([], 7200)[0], "settled")
        check_eq("K11 a gone transcript is unknown", C.session_settled(work / "nope.jsonl", *LIMITS)[0], "unknown")
        # B2 (AR-28): input that is not a name, or bytes that are not text, is `unknown` and never an exception
        for label, bad_name in (("an int", 123), ("a list", ["x"]), ("a dict", {"a": 1}), ("a float", 1.5), ("True", True), ("an empty string", "")):
            check_eq(f"K11 a transcript name that is {label} is unknown, no exception", C.session_verdict(bad_name, *LIMITS)[0], "unknown")
        bin_t = transcripts / "undecodable.jsonl"
        bin_t.parent.mkdir(parents=True, exist_ok=True)
        bin_t.write_bytes(b"\xff\xfe{not}\n")
        os.utime(bin_t, (time.time() - 7200, time.time() - 7200))
        check_eq("K11 a transcript of undecodable bytes (aged 2 h) is unknown, with NO timeout",
                 C.session_verdict(bin_t, *LIMITS)[::2], ("unknown", None))
        check_eq("K11 the same at 100 h stays unknown (a file that cannot be read is not a session that died)",
                 C.session_verdict(bin_t, LIMITS[0], LIMITS[1], time.time() + 100 * 3600)[0], "unknown")
        bin_doc = fixture_doc("cost-0.10.4-provisional.json", bin_t, session_id="undecodable", capture_logic=C.READER_STAMP)
        check_eq("K11 `_stale_kind` rule (ii) on it: current, no exception", C._stale_kind(bin_doc, activity, limits=LIMITS), ("", ""))
        check_eq("K11 `_stale_kind` rule (ii) with a transcript name that is not a string: current, no exception",
                 C._stale_kind(dict(bin_doc, transcript=123), activity, limits=LIMITS), ("", ""))
        # one bad file never loses the pass: the good session beside it is still recomputed
        (cost_dir / "undecodable.json").write_text(json.dumps(bin_doc), encoding="utf-8")
        good_t = transcripts / "good-beside-bad.jsonl"
        write_rows(good_t, [usage_row()] + closed, age=7200)
        (cost_dir / "good-beside-bad.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", good_t, session_id="good-beside-bad", capture_logic=C.READER_STAMP)), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            pass_out = {r["session_id"]: r["status"] for r in C.recapture_stale(root)}
        check_eq("K11 the pass still recomputes the good session beside the undecodable one", pass_out.get("good-beside-bad"), "recomputed")
        check("K11 and the undecodable one is not recomputed", pass_out.get("undecodable") != "recomputed")
        check_eq("K11 `usage_final` that is not an object: a mark without the note, no crash",
                 D.session_marks([{"session_id": "z", "usage_completeness": "complete", "usage_final": "x"}], {}, {})["z"]["final_rule"], None)
        check_eq("K11 a missing/unknown completeness is `unknown` with its word", D.session_marks([{"session_id": "q"}], {}, {})["q"]["reason"], "usage None")

        # --- K12: marks=None is today's text; the agreed sessions leave first -------------------------------------------
        row = {"incomplete_agents": set(), "provisional_sessions": {"s1", "s2"}, "session_ids": {"s1", "s2"}, "sessions": 2, "ok": None}
        check_eq("K12 marks=None: today's cell", D.task_completeness(row), ("incomplete — 2 sessions provisional", "warn", True))
        agree = dict(row, price={"status": TP.AGREES, "sessions": [{"session": "s1", "verdict": TP.V_AGREES}]})
        live_marks = {"s1": {"state": "unknown"}, "s2": {"state": "live"}}
        check_eq("K12 agreed leaves FIRST, the marks divide the rest: s1 agreed, s2 live -> no finding", D.provisional_count(agree, live_marks), 0)
        check_eq("K12 control: s2 unknown -> one finding", D.provisional_count(agree, {"s1": {"state": "live"}, "s2": {"state": "unknown"}}), 1)
        check_eq("K12 a session with no mark at all is a finding (an unknown is never information)", D.provisional_count(row, {"s1": {"state": "live"}}), 1)
        check_eq("K12 a live session: information, class skip, no finding",
                 D.task_completeness(row, {"s1": {"state": "live"}, "s2": {"state": "live"}}), ("2 sessions still being written", "skip", False))

        # --- K13: Codex ---------------------------------------------------------------------------------------------------
        meta = {"type": "session_meta", "payload": {"id": "cx-1"}}
        done = {"type": "event_msg", "payload": {"type": "task_complete"}}
        for label, rows, expected in (("completion event last", [meta, done], "settled"),
                                      ("another last event", [meta, done, {"type": "event_msg", "payload": {"type": "agent_message"}}], "open")):
            check_eq(f"K13 Codex rollout, {label} -> {expected}", verdict(rows, 7200)[0], expected)
        folder = temp_dir("settled-codex-")
        try:
            path = write_rows(folder / "r.jsonl", [meta, done], age=7200)
            HA.REPORT_FORMS_FILE = bad
            try:
                check_eq("K13 the host's form not read -> unknown", C.session_settled(path, *LIMITS)[0], "unknown")
            finally:
                HA.REPORT_FORMS_FILE = real_forms
            packed = folder / "r.jsonl.zst"
            packed.write_bytes(b"\x28\xb5\x2f\xfd")
            os.utime(packed, (time.time() - 7200,) * 2)
            check_eq("K13 a .zst rollout -> unknown", C.session_settled(packed, *LIMITS)[0], "unknown")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        # --- the retry guard (F-5): one recompute, not one per render --------------------------------------------------------
        stuck_t = transcripts / "stuck.jsonl"
        write_rows(stuck_t, [usage_row()], age=7200)
        (cost_dir / "stuck.json").write_text(json.dumps(fixture_doc("cost-0.10.4-provisional.json", stuck_t, session_id="stuck")), encoding="utf-8")
        calls = []
        real_session = C.recapture_session
        C.recapture_session = lambda *a, **k: calls.append(1) or {"session_id": "stuck", "status": "not_recomputed", "reason": "boom"}
        try:
            C.recapture_stale(root)
            C.recapture_stale(root)
            check_eq("F-5 a failed recompute of an old-logic file is tried once, not on every pass", len(calls), 1)
            os.utime(stuck_t, (time.time() - 7100,) * 2)
            with open(stuck_t, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(usage_row()) + "\n")
            os.utime(stuck_t, (time.time() - 7100,) * 2)
            C.recapture_stale(root)
            check_eq("F-5 and again once the transcript size changed", len(calls), 2)
        finally:
            C.recapture_session = real_session

        # --- K8 (B4, B-b, B-d): the whole page ----------------------------------------------------------------------------
        with tempfile.TemporaryDirectory() as td:
            slug2 = B.slug_of(td)
            sess = B.carry("live1", slug2, tags=("TP1-9",))
            tpath = Path(td) / "t" / ".claude" / "projects" / slug2 / "live1.jsonl"
            write_rows(tpath, [usage_row()], age=60)
            sess["transcript"] = str(tpath)
            sess["generated"] = "2020-01-01T00:00:00+00:00"        # older than the transcript: the pass flags it as grown
            root2 = B.write_root(td, [sess])
            os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
            try:
                page = page_of(root2)                                # the REAL pass, the real marks, both tabs
            finally:
                os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
            check_in("K8 live session: the row says it is still being written", "1 session still being written", page)
            check_not_in("K8 no block of findings, no `Stale cost files`", "Factory findings — cost capture", page)
            check_not_in("K8 no finding line on the Factory tab", "cost incomplete for", page)
            check_not_in("K8 the reconciliation note links no block that is not there", "see the cost-capture finding above", page)
            check_not_in("K8 the pass's refusal of a live session is no stale alert", "Stale cost files", page)
            check_in("K8 the row cell is information (class skip)", "class='skip'>1 session still being written", page)
            check_eq("K8 the Factory list is empty with the same marks", D.cost_capture_findings([sess], root2, None, None, None, D.session_marks([sess], {}, {})), [])
            # the same session, its tail cut mid-line an hour ago: unknown -> a finding, the block is there, the link is true
            write_rows(tpath, [usage_row()], torn=True, age=3600)
            torn_page = page_of(root2, "--read-only")
            check_in("K8 unknown end: the block of findings is there", "Factory findings — cost capture", torn_page)
            check_in("K8 and the note refers to it", "see the cost-capture finding above", torn_page)
            check_in("K8 and the Factory tab names the finding", "cost incomplete for", torn_page)
        print("note: the task_price caller of the limits (K7, the third caller) arrives with DP-5 (HF7-5)")
    finally:
        os.environ.pop("QA_FACTORY_SKIP_DASHBOARD_REFRESH", None)
        shutil.rmtree(work, ignore_errors=True)
        cleanup(root)
    finish("test_cost_capture_settled")


if __name__ == "__main__":
    main()
