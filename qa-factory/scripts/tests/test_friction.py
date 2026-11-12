#!/usr/bin/env python3
"""Friction with the factory's own code is measured in the S9 retro, from the roles' transcripts (FR-55).

TP1-13797 run 5: friction was 15.5 % of turns, 44.2 % for the code critic, and it was measured
only when someone ran `experiments/measurers/code_friction.py` by hand. This file holds the measurer
(FR-28): one synthetic transcript with a turn of every kind, priced by the package's own valuation;
the journal and the transcript lookup around it; and the retro section that must say `unknown`
wherever the evidence is missing (FR-41) and never a share of 0.0 %.

Every name below that starts with `edge_` answers one line of the B-011 EDGES list.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir, temp_project)

sys.path.insert(0, str(SCRIPTS))
import cost_capture  # noqa: E402
import friction as F  # noqa: E402
import retro_numbers as RN  # noqa: E402

TASK = "T-1"
PRICED = "claude-sonnet-5-5"          # in 2 / out 10 USD per Mtok in references/model-rates.json
UNKNOWN = "claude-mystery-9"          # in no catalogue
USAGE = {"input_tokens": 1000, "output_tokens": 100}
TURN_USD = 0.003                      # 1000 * 2 / 1e6 + 100 * 10 / 1e6
TRACEBACK = ('Traceback (most recent call last):\n  File "scripts/probe.py", line 9, in main\n'
             "KeyError: 'source_sha'")


def assistant(mid, model=PRICED, calls=(), usage=USAGE, text="working"):
    content = [{"type": "text", "text": text}]
    for call_id, name, arg in calls:
        key = "command" if name == "Bash" else "file_path"
        content.append({"type": "tool_use", "id": call_id, "name": name, "input": {key: arg}})
    return {"type": "assistant",
            "message": {"id": mid, "model": model, "usage": usage, "content": content}}


def result(call_id, text, as_list=False):
    body = [{"type": "text", "text": text}] if as_list else text
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": body}]}}


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def scout_transcript():
    """Twelve turns: crash, stand, guard (unpriced model), usage, validator, success, a Write of a
    helper, a retry of a script that refused (no result recorded), a plain turn on an unknown model,
    a Bash helper, a numbered listing of a document about refusals, and a repeated line of turn 1."""
    first = assistant("m1", calls=[("c1", "Bash", "python scripts/probe.py")])
    return [
        first,
        result("c1", TRACEBACK, as_list=True),
        first,                                            # the same streamed message, again
        assistant("m2", calls=[("c2", "Bash", "python scripts/run_suite.py")]),
        result("c2", '{"execution_status": "broken_run", "error_head": "ModuleNotFoundError"}\n'
                     + TRACEBACK),
        assistant("m3", model=UNKNOWN, calls=[("c3", "Bash", "python scripts/manifest_put.py")]),
        result("c3", "PRE-TOOL GUARD refused the call: a person's word is not recorded"),
        assistant("m4", calls=[("c4", "Bash", "python scripts/ticket_adapter.py")]),
        result("c4", "usage: ticket_adapter.py [-h] {get,diff} ...\nticket_adapter.py: error: bad"),
        assistant("m5", calls=[("c5", "Bash", "python scripts/check_x.py")]),
        result("c5", "Story artifact is not ready: work/test-plan.json missing required key"),
        assistant("m6", calls=[("c6", "Bash", "python scripts/ok.py")]),
        result("c6", '{"ok": true}'),
        assistant("m7", calls=[("c7", "Write", "work/_patch_manifest.py")]),
        result("c7", "File created successfully at work/_patch_manifest.py"),
        assistant("m8", calls=[("c8", "Bash", "python scripts/probe.py --fix")]),   # no result
        assistant("m9", model=UNKNOWN, calls=[], text="thinking"),
        assistant("m10", calls=[("c10", "Bash", "python work/_try_rows.py")]),
        result("c10", "3 rows"),
        assistant("m11", calls=[("c11", "Read", "references/human-questions.md")]),
        result("c11", "1\tThis document refuses a question with no answer form.\n2\t..."),
        assistant("m12", calls=[("c12", "Write", "work/_patch_manifest.py")]),      # same helper again
        result("c12", "File overwritten"),
    ]


def journal_row(role, sid, dispatch, resumed=False, kind="role", stage="S1"):
    return {"kind": kind, "role": role, "dispatch": dispatch, "stage": stage, "session_id": sid,
            "resumed": resumed, "num_turns": 5, "total_cost_usd": 9.99, "model": PRICED,
            "ts": "2026-09-29T10:00:00"}


def build(root, roles):
    """A temp project with one story: `roles` is [(role, sid, [transcript rows] or None, via)]; `via`
    is "cost" (a cost file names the transcript) or "host" (only the host folder has it)."""
    base = root / "qa-factory"
    troot = base / "artifacts" / TASK
    (troot / "state").mkdir(parents=True)
    home = root / "home"
    slug = cost_capture.project_slug(root)
    rows = []
    for role, sid, transcript, via in roles:
        rows.append(journal_row(role, sid, f"S1-{role}-1"))
        if transcript is None:
            continue
        if via == "cost":
            cost_file_transcript(root, base, sid, transcript)
        else:
            write_jsonl(home / ".claude" / "projects" / slug / f"{sid}.jsonl", transcript)
    return base, troot, home, rows


def cost_file_transcript(root, base, sid, transcript):
    """A transcript under `elsewhere/` that only the session's cost file knows about."""
    target = root / "elsewhere" / f"{sid}.jsonl"
    write_jsonl(target, transcript)
    (base / "state" / "cost").mkdir(parents=True, exist_ok=True)
    (base / "state" / "cost" / f"{sid}.json").write_text(json.dumps(
        {"session_id": sid, "transcript": str(target), "by_task": {TASK: {"cost": 1.0}}}),
        encoding="utf-8")


def write_journal(troot, rows):
    (troot / "state" / "driver-runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def priced():
    return F.package_price({})


def classification_of_every_kind_and_its_boundaries():
    m = F.load_markers()
    check_eq("a traceback is a crash", F.classify(TRACEBACK, m), "crash")
    check_eq("a traceback inside a typed broken_run result is the stand", F.classify(
        '{"execution_status": "broken_run"}\n' + TRACEBACK, m), "stand")
    check_eq("a pre-tool guard refusal is the guard", F.classify("PRE-TOOL GUARD: no", m), "guard")
    check_eq("a hook error is the guard", F.classify("Hook error: exit 2", m), "guard")
    check_eq("argparse's own dump is usage", F.classify("usage: probe_by_code.py [-h] --x", m), "usage")
    check_eq("a hand-written usage line with an angle bracket is the form, not friction",
             F.classify("usage: ticket_adapter.py <get|diff> --old <path>", m), None)
    check_eq("a validator refusal in the head", F.classify("The plan is not ready: x", m), "validator")
    check_eq("a numbered file listing is never a validator refusal",
             F.classify("1\tthis reference refuses things", m), None)
    check_eq("a result that is not friction", F.classify('{"ok": true}', m), None)
    check_eq("nothing at all is not friction", F.classify(None, m), None)
    at = "x" * (300 - len("refuses")) + "refuses"           # the phrase ends AT the 300th character
    beyond = "x" * (301 - len("refuses")) + "refuses"        # and one character BEYOND it
    check_eq("a validator phrase ending at character 300 counts", F.classify(at, m), "validator")
    check_eq("one ending at character 301 does not", F.classify(beyond, m), None)
    check("the story's own tests are not ours", F.is_project_test("test_login.py", m)
          and F.is_project_test("login_test.py", m) and not F.is_project_test("probe.py", m))


def the_synthetic_transcript_is_measured():
    root = temp_dir("qa-friction-")
    try:
        path = root / "scout.jsonl"
        write_jsonl(path, scout_transcript())
        f = F.friction(path, priced())
        check_eq("twelve unique turns, the repeated streamed line counted once", f["turns"], 12)
        check_eq("one turn of each kind; three turns wrote or ran a helper (two distinct scripts)",
                 dict(f["tally"]), {"crash": 1, "stand": 1, "guard": 1, "usage": 1, "validator": 1,
                                    "adhoc": 3, "recovery": 1})
        check_eq("nine friction turns of twelve", f["fric_turns"], 9)
        check_eq("the success turn, the plain turn and the listing are not friction (one kind each)",
                 sum(f["tally"].values()), 9)
        check_eq("two turns on a model the catalogue does not hold are unpriced", f["unpriced"], 2)
        check_eq("priced dollars are the ten priced turns", round(f["cost"], 6), round(10 * TURN_USD, 6))
        check_eq("friction dollars leave the unpriced guard turn out: 8 priced friction turns",
                 round(f["fric_cost"], 6), round(8 * TURN_USD, 6))
        check_eq("the Write of work/_patch_manifest.py and the Bash helper are listed once each",
                 sorted((h["path"], h["call"]) for h in f["helpers"]),
                 [("work/_patch_manifest.py", "Write"), ("work/_try_rows.py", "Bash")])
        check("a Read of a document is never listed as a helper",
              all("human-questions" not in h["path"] for h in f["helpers"]))
        check_eq("an unpriced friction turn is still a friction turn: the guard is in the tally",
                 f["tally"]["guard"], 1)
    finally:
        cleanup(root)


def pricing_never_turns_an_unknown_into_zero():
    price = priced()
    check_eq("a known model is priced by the package's own valuation", round(price(PRICED, USAGE), 9),
             TURN_USD)
    check_eq("an unknown model is None, never 0.0", price(UNKNOWN, USAGE), None)
    check_eq("no model at all is None", price(None, USAGE), None)
    check_eq("a synthetic marker with tokens is unpriced", price("<synthetic>", USAGE), None)
    check_eq("a turn that used no tokens costs nothing whatever its model", price("<synthetic>", {
        "input_tokens": 0, "output_tokens": 0}), 0.0)
    partial = F.package_price({"rate_overrides": [{"model_id": "m-half", "rates": {"input": 1}}]})
    check_eq("a rate entry without a key the turn uses is unpriced",
             partial("m-half", {"input_tokens": 10, "output_tokens": 10}), None)
    check_eq("and priced when the turn uses only the keys it has",
             round(partial("m-half", {"input_tokens": 10}), 9), 0.00001)


def edge_no_journal_is_unknown_never_zero_percent():
    root = temp_project()
    try:
        base = root / "qa-factory"
        troot = base / "artifacts" / TASK
        (troot / "state").mkdir(parents=True)
        data = F.story_friction(troot, base, root, {})
        check_eq("no driver journal -> unknown", data["status"], "unknown")
        text = "\n".join(F.section_lines(data, RN.money))
        check_in("the retro says so in the spec's words",
                 "Friction: unknown — this story has no driver journal", text)
        check_not_in("and never prints a share", "%", text)
        empty = troot / "state" / "driver-runs.jsonl"
        empty.write_text(json.dumps(journal_row("", "", "", kind="conductor")) + "\n", encoding="utf-8")
        check_eq("a journal with no role session is unknown too",
                 F.story_friction(troot, base, root, {})["status"], "unknown")
    finally:
        cleanup(root)


def edge_a_resumed_duplicate_session_counts_once_and_two_roads_to_a_transcript():
    root = temp_project()
    try:
        base, troot, home, rows = build(root, [
            ("qa-scout", "sess-scout", scout_transcript(), "cost"),
            ("qa-automator", "sess-host", [assistant("h1", calls=[("k1", "Bash", "python x.py")]),
                                           result("k1", "fine"), assistant("h2")], "host")])
        # the scout's session appears again as a resume, and once more as a repeated row
        rows.append(journal_row("qa-scout", "sess-scout", "S1-qa-scout-1", resumed=True))
        rows.append(journal_row("qa-scout", "sess-scout", "S1-qa-scout-1", resumed=True))
        # A real conductor row carries a REAL session id and role "" (kind is what says it is not a
        # role's); its transcript exists, so a measurer that let it in would count its turns.
        cost_file_transcript(root, base, "sess-conductor", [assistant("k1"), assistant("k2")])
        rows.append(journal_row("", "sess-conductor", "", kind="conductor"))
        # The same kind test must hold on its own, whatever the role field says.
        cost_file_transcript(root, base, "sess-conductor-2", [assistant("q1")])
        rows.append(journal_row("qa-ghost", "sess-conductor-2", "S1-qa-ghost-1", kind="conductor"))
        # One session present on BOTH roads with different content: the cost file's transcript (2
        # turns) must be the one read, not the host folder's (3 turns) - F11-2's order.
        both = [assistant("b1"), assistant("b2")]
        cost_file_transcript(root, base, "sess-both", both)
        write_jsonl(home / ".claude" / "projects" / cost_capture.project_slug(root) / "sess-both.jsonl",
                    both + [assistant("b3")])
        rows.append(journal_row("qa-both", "sess-both", "S1-qa-both-1"))
        write_journal(troot, rows)
        data = F.story_friction(troot, base, root, {}, home=home)
        scout = data["roles"]["qa-scout"]
        check_eq("all sessions reachable -> ok", data["status"], "ok")
        check_eq("a resumed / repeated session id is read once: 12 turns, not 36", scout["turns"], 12)
        check_eq("one session, one dispatch for the scout", (scout["sessions"], scout["dispatches"]),
                 (1, 1))
        check_eq("a conductor's session is not a role's, with role '' or with a role named",
                 sorted(data["roles"]), ["qa-automator", "qa-both", "qa-scout"])
        check_eq("a session on both roads is read through the cost file: 2 turns, not 3",
                 data["roles"]["qa-both"]["turns"], 2)
        check_eq("the cost file was the first road, the host folder the second and both are printed",
                 data["sources"], {"cost file": 2, "host projects folder": 1})
        check_eq("turn share is friction turns over all turns, one decimal", scout["turn_share"], 75.0)
        check_eq("money share is friction dollars over priced dollars: 8 of 10 priced turns",
                 scout["money_share"], 80.0)
        check_eq("the unpriced turns are counted for the role", scout["unpriced"], 2)
        automator = data["roles"]["qa-automator"]
        check_eq("a clean role reads 0 friction turns of 2 - a measured zero, not an unknown",
                 (automator["turns"], automator["fric_turns"], automator["turn_share"]), (2, 0, 0.0))
        check_eq("the journal's total_cost_usd (9.99) is not the money used",
                 scout["priced_cost"], round(10 * TURN_USD, 6))
        check_eq("totals are over the same reachable sessions", data["total"]["turns"], 16)
        lines = "\n".join(F.section_lines(data, RN.money))
        check_in("the section names the method and its record", "not from the CLI's", lines)
        check_in("the section prints the unpriced count", "Unpriced turns: 2", lines)
        check_in("the helper scripts are named with their role",
                 "qa-scout — work/_patch_manifest.py", lines)
        check_in("and the sources", "via cost file", lines)
    finally:
        cleanup(root)


def edge_a_missing_transcript_is_partial_or_unknown_and_never_a_zero():
    root = temp_project()
    try:
        base, troot, home, rows = build(root, [
            ("qa-scout", "sess-scout", scout_transcript(), "cost"),
            ("qa-code-critic", "sess-gone", None, "cost")])
        write_journal(troot, rows)
        data = F.story_friction(troot, base, root, {}, home=home)
        check_eq("one of two sessions unreachable -> partial", data["status"], "partial")
        check_eq("n of m is counted", (data["sessions_unreachable"], data["sessions"]), (1, 2))
        check_eq("the role whose transcript is missing has no reachable session",
                 data["roles"]["qa-code-critic"]["reachable"], 0)
        check_eq("shares are over the reachable session only", data["total"]["turns"], 12)
        text = "\n".join(F.section_lines(data, RN.money))
        check_in("the unreachable count is printed", "1 of 2 sessions unreachable", text)
        check_in("the role's row says unknown", "| qa-code-critic | unknown |", text)
        check("no zero share is printed for the unreachable role (a bare 0.0%, not the tail of 80.0%)",
              not re.search(r"(?<![0-9.])0\.0%", text), text)
        only = [r for r in rows if r["role"] == "qa-code-critic"]
        write_journal(troot, only)
        data = F.story_friction(troot, base, root, {}, home=home)
        check_eq("every session unreachable -> unknown", data["status"], "unknown")
        text = "\n".join(F.section_lines(data, RN.money))
        check_in("the text says unknown", "unknown", text)
        check_not_in("and never 0.0%", "0.0%", text)
        check_eq("locate names what it tried", F.locate("sess-gone", base, root, home=home)[0], None)
        check_in("its source says where it looked",
                 "absent", F.locate("sess-gone", base, root, home=home)[1])
    finally:
        cleanup(root)


def edge_no_priced_turn_leaves_the_money_share_unknown_and_the_turn_share_printed():
    root = temp_project()
    try:
        transcript = [assistant("u1", model=UNKNOWN, calls=[("a", "Bash", "python scripts/x.py")]),
                      result("a", TRACEBACK), assistant("u2", model=UNKNOWN)]
        base, troot, home, rows = build(root, [("qa-scout", "sess-u", transcript, "cost")])
        write_journal(troot, rows)
        data = F.story_friction(troot, base, root, {}, home=home)
        scout = data["roles"]["qa-scout"]
        check_eq("an unpriced friction turn counts in turns", (scout["turns"], scout["fric_turns"]), (2, 1))
        check_eq("turn share is printed", scout["turn_share"], 50.0)
        check_eq("money share is unknown", scout["money_share"], None)
        check_eq("and no dollar figure exists", (scout["priced_cost"], scout["fric_cost"]), (None, None))
        text = "\n".join(F.section_lines(data, RN.money))
        check_in("the row prints the turn share", "1 (50.0%)", text)
        check_in("and unknown for the dollar share", "not priced (unknown)", text)
        check_in("and the unpriced count", "Unpriced turns: 2", text)
    finally:
        cleanup(root)


def the_markers_are_data_and_their_absence_is_reported_with_what_is_expected():
    m = json.loads((SCRIPTS.parent / "references" / "friction-markers.json").read_text(encoding="utf-8"))
    check("the marker file holds every key the spec names", all(k in m for k in (
        "traceback", "stand_markers", "guard_markers", "usage_regex", "validator_head_phrases",
        "validator_head_chars", "listing_prefix", "adhoc_path_regexes", "project_test_regex")))
    check("the file is English (FR-30)", all(ord(ch) < 128 for ch in json.dumps(m, ensure_ascii=False)))
    root = temp_dir("qa-friction-markers-")
    try:
        try:
            F.load_markers(root / "absent.json")
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in("an absent marker file says what was expected (FR-1)", "expected the package file", raised)
        # a marker changed in data changes the classification: nothing is decided in code (FR-13)
        custom = root / "m.json"
        custom.write_text(json.dumps(dict(m, guard_markers=["custom refusal"])), encoding="utf-8")
        check_eq("a spelling added to the data file is recognised", F.classify(
            "Custom Refusal here", F.load_markers(custom)), "guard")
        check_eq("and the shipped table does not know it", F.classify("Custom Refusal here"), None)
    finally:
        cleanup(root)


def edge_the_retro_carries_the_section_and_friction_never_fails_it():
    root = temp_project()
    try:
        base, troot, home, rows = build(root, [("qa-scout", "sess-scout", scout_transcript(), "cost")])
        write_journal(troot, rows)
        data = RN.numbers(TASK, base, troot)
        check_eq("numbers carries the measurement", data["friction"]["status"], "ok")
        check_eq("of the transcript the cost file named", data["friction"]["roles"]["qa-scout"]["turns"], 12)
        text = RN.render(data)
        check_in("the render carries the section", "Friction with the factory's own code", text)
        check_in("with the role's row", "| qa-scout | 12 | 9 (75.0%) |", text)
        check_in("and the helper line", "Helper scripts a role wrote for itself: qa-scout — "
                 "work/_patch_manifest.py; qa-scout — work/_try_rows.py.", text)
        json.dumps(data)                                    # the facts file must stay serialisable
        check_eq("a story with no journal prints unknown in the retro", "Friction: unknown — this "
                 "story has no driver journal" in RN.render(dict(data, friction={
                     "status": "unknown", "reason": "this story has no driver journal"})), True)
        check_in("numbers computed before the section existed still render it, as unknown",
                 "Friction: unknown", RN.render({k: v for k, v in data.items() if k != "friction"}))

        real = F.locate

        def failing(*args, **kwargs):
            raise RuntimeError("the transcript folder cannot be listed")
        F.locate = failing
        try:
            broken = RN.numbers(TASK, base, troot)
        finally:
            F.locate = real
        check_eq("a failing locate does not raise out of numbers: unknown", broken["friction"]["status"],
                 "unknown")
        check_in("with its reason", "RuntimeError: the transcript folder cannot be listed",
                 broken["friction"]["reason"])
        check_eq("the other numbers are intact", broken["story"], data["story"])
        check_in("and the retro says why", "Friction: unknown — RuntimeError", RN.render(broken))

        real_markers = F.MARKERS_PATH
        F.MARKERS_PATH = root / "no-such-markers.json"
        try:
            gone = RN.numbers(TASK, base, troot)
        finally:
            F.MARKERS_PATH = real_markers
        check_eq("an absent marker file is unknown with what is expected too", gone["friction"]["status"],
                 "unknown")
        check_in("naming the file", "friction-markers.json", gone["friction"]["reason"])
    finally:
        cleanup(root)


def edge_the_real_reason_a_transcript_is_unreachable_is_printed():
    root = temp_project()
    try:
        base, troot, home, rows = build(root, [
            ("qa-scout", "sess-scout", scout_transcript(), "cost"),
            ("qa-code-critic", "sess-del", None, "cost")])
        cost_file_transcript(root, base, "sess-del", [assistant("d1")])
        (root / "elsewhere" / "sess-del.jsonl").unlink()          # the cost file now names a deleted file
        write_journal(troot, rows)
        text = "\n".join(F.section_lines(F.story_friction(troot, base, root, {}, home=home), RN.money))
        check_in("partial line names the file the cost file points at", "sess-del.jsonl", text)
        check_in("and says it is absent", "is absent", text)
        check_in("and which role's session it was", "qa-code-critic: session sess-del", text)
        write_journal(troot, [r for r in rows if r["role"] == "qa-code-critic"])
        text = "\n".join(F.section_lines(F.story_friction(troot, base, root, {}, home=home), RN.money))
        check_in("the unknown line carries the same reason", "Friction: unknown", text)
        check_in("naming the missing file", "elsewhere", text)
        check_not_in("and not the old fixed sentence", "no cost file names one", text)
    finally:
        cleanup(root)


def edge_the_configs_cost_block_prices_a_model_only_an_override_knows():
    root = temp_project()
    try:
        transcript = [assistant("o1", model=UNKNOWN), assistant("o2", model=UNKNOWN)]
        base, troot, home, rows = build(root, [("qa-scout", "sess-o", transcript, "cost")])
        write_journal(troot, rows)
        check_eq("without an override the model is unpriced",
                 RN.numbers(TASK, base, troot)["friction"]["unpriced"], 2)
        cfg = json.loads((base / "config.json").read_text(encoding="utf-8"))
        cfg["cost"] = {"rate_overrides": [{"model_id": UNKNOWN, "rates": {"input": 2, "output": 10}}]}
        (base / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        got = RN.numbers(TASK, base, troot)["friction"]
        check_eq("cost.rate_overrides from config.json prices it: 0 unpriced", got["unpriced"], 0)
        check_eq("at the override's rate: 2 turns of $0.003", got["roles"]["qa-scout"]["priced_cost"],
                 round(2 * TURN_USD, 6))
    finally:
        cleanup(root)


def edge_the_rendered_retro_of_a_story_with_no_reachable_transcript_says_unknown():
    root = temp_project()
    try:
        base, troot, home, rows = build(root, [("qa-scout", "sess-gone-9", None, "cost")])
        write_journal(troot, rows)
        text = RN.render(RN.numbers(TASK, base, troot))
        section = text.split("**Friction with the factory's own code**")[1].split("| Stage |")[0]
        check_in("the section is there and says unknown", "Friction: unknown —", section)
        check_not_in("and prints no 0.0%", "0.0%", section)
    finally:
        cleanup(root)


def main():
    classification_of_every_kind_and_its_boundaries()
    the_synthetic_transcript_is_measured()
    pricing_never_turns_an_unknown_into_zero()
    edge_no_journal_is_unknown_never_zero_percent()
    edge_a_resumed_duplicate_session_counts_once_and_two_roads_to_a_transcript()
    edge_a_missing_transcript_is_partial_or_unknown_and_never_a_zero()
    edge_no_priced_turn_leaves_the_money_share_unknown_and_the_turn_share_printed()
    the_markers_are_data_and_their_absence_is_reported_with_what_is_expected()
    edge_the_retro_carries_the_section_and_friction_never_fails_it()
    edge_the_real_reason_a_transcript_is_unreachable_is_printed()
    edge_the_configs_cost_block_prices_a_model_only_an_override_knows()
    edge_the_rendered_retro_of_a_story_with_no_reachable_transcript_says_unknown()
    finish("test_friction")


if __name__ == "__main__":
    main()
