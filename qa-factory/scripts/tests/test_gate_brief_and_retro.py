"""The gate A brief built by code, and the retro's numbers computed by code.

Both exist for the same reason. The gate brief was assembled out of the orchestrator's
context, so on TP1-15045 it did not fit in what the window had left and the person got
a restart command instead of the gate question. The retro's numbers were derived by an
agent reading journals, so one pilot's retro passed 114k tokens before a person stopped it.
Arithmetic and file reading are the cheapest thing a machine does.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import gate_brief  # noqa: E402
import retro_numbers  # noqa: E402

PLAN = [
    {"id": "TS-1", "level": "e2e-ui", "disposition": "automate"},
    {"id": "TS-2", "level": "e2e-ui", "disposition": "automate", "impact": "severe"},
    {"id": "TS-3", "level": "api", "disposition": "automate"},
    {"id": "TS-4", "level": "manual", "disposition": "manual-human"},
]


def story(prefix: str) -> Path:
    base = temp_dir(prefix) / "qa-factory"
    task_root = base / "artifacts" / "TP1-15045"
    (task_root / "work" / "test-cases" / "workflows").mkdir(parents=True)
    (task_root / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (base / "config.json").write_text("{}", encoding="utf-8")
    (task_root / "work" / "test-plan.json").write_text(json.dumps(PLAN), encoding="utf-8")
    (task_root / "work" / "test-cases" / "workflows" / "critic-findings.md").write_text(
        "# Critic findings - round 2 (final) prepended above round 1\n\n"
        "Verdict: approve_with_concerns (2 concerns, 0 fail), confidence: medium.\n\n"
        # The `reviewed` column is the field the gate reads. Run 5's own file said it in the
        # status cell's prose and that is what FR-12 took out of the code: a critic who worded
        # the cell differently was counted as having reviewed the row.
        "## Roll-call\n\n"
        "| TS | case | reviewed | status |\n|---|---|---|---|\n"
        "| TS-1 | TC-001 | yes | found |\n"
        "| TS-2 | TC-002 | no | found, not read yet |\n"
        "| TS-3 | TC-003 | no | found, not read yet |\n"
        "| TS-4 | TC-004 | yes | found; sound |\n\n"
        "# Round 1\n\nVerdict round 1: reject.\n", encoding="utf-8")
    (task_root / "state" / "story-case-links.json").write_text(json.dumps(
        {"task_id": "TP1-15045",
         "links": [{"case_id": f"TC-00{n}"} for n in range(1, 5)]}), encoding="utf-8")
    (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(
        {"open_questions": [{"question": "Where must a removed node appear with no layout meta?",
                             "severity": "minor", "owner_role": "po_ba"}],
         "register": {"total": 15}}), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps({
        "ticket": "TP1-15045", "size": "L",
        "warnings": ["case_store not_configured: cases stay per story (not a defect)"],
        "gate_waivers": [],
        "stage_overrides": [{"stage": "S1", "match": "video",
                             "decision": "go on without the video and the external links"}],
        "stages": {"S0": {"status": "done", "started": "2026-09-20T19:25:21+00:00"},
                   "S4": {"status": "done", "role": "qa-case-critic",
                          "agent_id": "afd55942eeff88cea",
                          "started": "2026-09-20T21:12:20+00:00",
                          "finished": "2026-09-20T21:29:39+00:00"}},
        "halts": [{"stage": "S1", "at": "2026-09-20T19:31:56+00:00", "resolved": True,
                   "resolved_at": "2026-09-20T20:00:44+00:00"}],
    }), encoding="utf-8")
    return base


def test_hf8_12_a_capability_the_story_proved_after_s0_leaves_the_brief() -> None:
    """HF8-12, W-4/W-5, edges E8-E9, E22-E25: the gate does not carry as "not verified" what the story has since proved. A line
    goes only when its capability was proved AFTER S0 finished, and an unknown never lifts one (AR-28)."""
    from datetime import datetime, timedelta, timezone
    from unittest import mock
    import vcs_evidence as VE
    now = datetime.now(timezone.utc)
    vcs = "S0 vcs_api: unknown - API access is not verified; run readiness.py --probe-vcs"
    hooks = "S0 host_hooks: unknown (role-context delivery not yet verified)"
    other = ["case_store not_configured: cases stay per story (not a defect)"] + [f"filler warning {n}" for n in range(1, 5)]
    base = story("qa-gate-proved-")
    task_root = base / "artifacts" / "TP1-15045"
    project = base.parent
    pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))

    def arrange(lines, finished=now - timedelta(hours=1)):
        pipeline["warnings"] = lines
        pipeline["stages"]["S0"]["finished"] = finished.isoformat() if finished else None
        if finished is None:
            del pipeline["stages"]["S0"]["finished"]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    def read(host="gitlab.example.com", error=None, age=timedelta(0)):
        VE.record_api_receipt(project, {"host": host, "status": "read", "api_authenticated": True} if not error
                              else {"host": host, "status": "unavailable", "error": error})
        if age:
            for path in (project / "qa-factory/state/host-receipts").glob("vcs-api-*.json"):
                row = json.loads(path.read_text(encoding="utf-8"))
                row["observed_at"] = (now - age).isoformat()
                path.write_text(json.dumps(row), encoding="utf-8")

    def brief():
        return gate_brief.collect("TP1-15045", task_root)

    def held(data):
        """every line the packet did not call proved: shown at gate A, or held as not established (OH1-11)"""
        return [n["line"] for n in data["not_established"]] + data["warnings"]

    real_which = __import__("shutil").which
    try:
        with mock.patch("shutil.which", lambda name, *a, **k: "glab" if name == "glab" else real_which(name, *a, **k)):
            arrange([vcs] + other)
            check_eq("the same line with no receipt is not proved (it is held as not established, OH1-11)",
                     (vcs in held(brief()), brief()["proved_warnings"], brief()["warnings"]), (True, [], other))
            read()
            data = brief()
            check_eq("proved vcs_api warning leaves the brief, the proof is named",
                     (vcs in data["warnings"], [(p["capability"], p["line"]) for p in data["proved_warnings"]]),
                     (False, [("vcs_api", vcs)]))
            check_eq("dropped line frees a place in the first five (the selection runs before the cut)",
                     data["warnings"], other)
            text = gate_brief.render(data)
            check_in("...so the fifth other line reaches the person", "filler warning 4", text)
            check_not_in("...and the proved line is not shown", "vcs_api", text)

            arrange(["WARN vcs_api: unknown", "stand x: vcs_api: unknown", "tracker vcs_api: unknown", "S0 VCS_API: unknown",
                     "vcs_apix: unknown", "S0 host_hooks_extra: unknown"])
            check_eq("vcs_api in the middle of a line, another case or a longer name stays; a `WARN ` prefix is read",
                     brief()["warnings"], ["stand x: vcs_api: unknown", "tracker vcs_api: unknown", "S0 VCS_API: unknown",
                                           "vcs_apix: unknown", "S0 host_hooks_extra: unknown"])
            check_eq("...and the `WARN ` line is the one that left (here proved by the receipt read above, so it is not `not_established`)",
                     ([p["line"] for p in brief()["proved_warnings"]], brief()["not_established"]), (["WARN vcs_api: unknown"], []))

            arrange([vcs] + other, finished=now + timedelta(hours=1))
            check_eq("a receipt older than S0 leaves the line unproved", (vcs in held(brief()), brief()["proved_warnings"]), (True, []))
            arrange([vcs] + other, finished=None)
            check_eq("no S0.finished leaves the line unproved", (vcs in held(brief()), brief()["proved_warnings"]), (True, []))
            arrange([vcs] + other, finished=None)
            pipeline["stages"]["S0"]["finished"] = "2026-10-29T10:00:00"
            (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            check_eq("an S0 time with no UTC offset leaves the line unproved", (vcs in held(brief()), brief()["proved_warnings"]), (True, []))
            arrange([vcs] + other)
            read(age=timedelta(days=8))
            check_eq("a receipt past its term leaves the line unproved", (vcs in held(brief()), brief()["proved_warnings"]), (True, []))
            read()
            read(host="other.example.com", error="unauthenticated")
            check_eq("a fresh denial on another host forbids ok: the line stays unproved", (vcs in held(brief()), brief()["proved_warnings"]), (True, []))
            read(host="other.example.com")
            with mock.patch("vcs_evidence.read_api_receipts", side_effect=RuntimeError("boom")):
                check_eq("a raising reader leaves the line, no traceback", (vcs in held(brief()), brief()["proved_warnings"]), (True, []))
            loose = temp_dir("qa-gate-proved-loose-") / "TP1-15045"
            try:
                loose.mkdir()
                (loose / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
                check_eq("a task root that is not <project>/qa-factory/artifacts/<T>: every line stays",
                         gate_brief._proved_warnings(loose, [vcs]), ([vcs], []))
            finally:
                cleanup(loose.parent)

            arrange([hooks] + other)
            proved = {"story_ready": False, "guard_probe": {"status": "verified"},
                      "role_context": {"host": "claude-code", "observed_at": now.isoformat()}}
            with mock.patch("host_capabilities.inspect", return_value=proved):
                data = brief()
                check_eq("proved host_hooks warning leaves the brief", (hooks in data["warnings"], [p["capability"] for p in data["proved_warnings"]]),
                         (False, ["host_hooks"]))
            for label, answer in {
                    "no real dispatch seen": dict(proved, role_context=None),
                    "a Codex dispatch": dict(proved, role_context=dict(proved["role_context"], host="codex")),
                    "an unverified guard": dict(proved, guard_probe={"status": "unverified"}),
                    "a dispatch before S0 finished": dict(proved, role_context=dict(proved["role_context"], observed_at=(now - timedelta(hours=3)).isoformat())),
                    "a receipt time with no offset": dict(proved, role_context=dict(proved["role_context"], observed_at="2026-10-30T10:00:00"))}.items():
                with mock.patch("host_capabilities.inspect", return_value=answer):
                    check_eq(f"host_hooks: {label}: the line stays unproved", (hooks in held(brief()), brief()["proved_warnings"]), (True, []))
            with mock.patch("host_capabilities.inspect", side_effect=RuntimeError("boom")):
                check_eq("host_hooks: a raising reader leaves the line unproved", (hooks in held(brief()), brief()["proved_warnings"]), (True, []))
            arrange(other)
            with mock.patch("host_capabilities.inspect", return_value=proved) as asked:
                brief()
                check_eq("no capability line: the host is not asked (AR-12)", asked.call_count, 0)
    finally:
        cleanup(base.parent)


def test_oh1_11_an_unknown_probe_is_not_shown_at_gate_a() -> None:
    """OH1-11, E9-E16: a `vcs_api` / `host_hooks` / `base_slice` line whose status is `unknown` leaves the text gate A shows and is
    listed under `not_established`; every other line stays; `pipeline.json` is never rewritten (AR-28, FR-45)."""
    from datetime import datetime, timedelta, timezone
    from unittest import mock
    import vcs_evidence as VE
    leave = ["S0 vcs_api: unknown - Run readiness.py --probe-vcs ...",
             "WARN vcs_api: unknown — the API did not answer (owner: orchestrator)",
             "host_hooks: unknown (live guard evidence incomplete; role-context delivery not yet verified)",
             "base_slice: unknown x3 (docs/superpowers/a.md, docs/superpowers/b.md): repo unresolved: no remote",
             "vcs_api:unknown",
             "base_slice: unknown - S3 preparation: base_slice.py exited 2 (boom): no base slice for this story"]
    stay = ["vcs_api: missing - unknown token", "vcs_api: not_configured", "S0 vcs_api: denied", "host_hooks: missing",
            "stand x: vcs_api: unknown", "tracker vcs_api: unknown", "VCS_API: unknown", "vcs_api_extra: unknown",
            "vcs_api: unknown-ish", "environment: unknown", "tracker_write: unknown",
            "env_probe: 14 integration credential rows are 'unknown' (no probe)",
            "S3 preparation: base_slice.py exited 2 (boom): no base slice for this story; the planner reads before: unknown"]
    ordinary = "case_store not_configured: cases stay per story (not a defect)"
    base = story("qa-gate-notest-")
    task_root = base / "artifacts" / "TP1-15045"
    pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))

    def arrange(lines, **extra):
        pipeline["warnings"] = lines
        pipeline.update(extra)
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    try:
        arrange(leave + [ordinary])
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("K-N1: only the ordinary line is left in the warnings", data["warnings"], [ordinary])
        check_eq("K-N1: the removed lines are listed with their capability, order kept",
                 [(n["capability"], n["line"]) for n in data["not_established"]],
                 [("vcs_api", leave[0]), ("vcs_api", leave[1]), ("host_hooks", leave[2]), ("base_slice", leave[3]),
                  ("vcs_api", leave[4]), ("base_slice", leave[5])])
        text = gate_brief.render(data)
        for line in leave:
            check_not_in(f"K-N1: the packet does not show `{line[:30]}`", line[:30], text)
        check_in("K-N1: the ordinary warning is still shown", ordinary, text)

        arrange(leave)
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("E10: only unknown lines: no warnings at all", data["warnings"], [])
        check_not_in("E10: ...and no Warnings heading", "## Warnings", gate_brief.render(data))

        arrange(stay)
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("K-N2: every line that is not a plain `unknown` status of the three names stays, in order", data["warnings"], stay)
        check_eq("K-N2: ...and nothing is listed as not established", data["not_established"], [])

        arrange([f"ordinary {n}" for n in range(1, 6)] + leave[:3])
        check_eq("K-N4: five ordinary + three unknown: all five ordinary are shown",
                 [f"ordinary {n}" for n in range(1, 6)] == [l[2:] for l in gate_brief.render(gate_brief.collect("TP1-15045", task_root)).splitlines()
                                                           if l.startswith("- ordinary ")], True)
        arrange([f"ordinary {n}" for n in range(1, 7)] + leave[:3])
        shown = [l[2:] for l in gate_brief.render(gate_brief.collect("TP1-15045", task_root)).splitlines() if l.startswith("- ordinary ")]
        check_eq("K-N4: six ordinary + three unknown: the cap of five is unchanged, the unknowns took no place",
                 shown, [f"ordinary {n}" for n in range(1, 6)])

        # K-N3 (position): a line proved after S0 is reported as proved, not as not established
        now = datetime.now(timezone.utc)
        vcs = "S0 vcs_api: unknown - API access is not verified"
        pipeline["stages"]["S0"]["finished"] = (now - timedelta(hours=1)).isoformat()
        arrange([vcs, ordinary])
        VE.record_api_receipt(base.parent, {"host": "gitlab.example.com", "status": "read", "api_authenticated": True})
        real_which = __import__("shutil").which
        with mock.patch("shutil.which", lambda name, *a, **k: "glab" if name == "glab" else real_which(name, *a, **k)):
            data = gate_brief.collect("TP1-15045", task_root)
        check_eq("K-N3: proved after S0 -> proved_warnings, not not_established",
                 ([p["capability"] for p in data["proved_warnings"]], data["not_established"], data["warnings"]),
                 (["vcs_api"], [], [ordinary]))

        # K-N5 (AR-28): the reader writes nothing
        arrange(leave + stay + [ordinary])
        before = (task_root / "pipeline.json").read_bytes()
        gate_brief.render(gate_brief.collect("TP1-15045", task_root))
        check_eq("K-N5: pipeline.json bytes are unchanged by collect and render", (task_root / "pipeline.json").read_bytes(), before)

        # E9: absent / empty / not a list
        for label, value in (("absent", None), ("empty", []), ("not a list", "vcs_api: unknown")):
            if value is None:
                pipeline.pop("warnings", None)
                (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            else:
                arrange(value)
            data = gate_brief.collect("TP1-15045", task_root)
            check_eq(f"E9: warnings {label}: the key `not_established` is a list and nothing raised", isinstance(data["not_established"], list), True)
    finally:
        cleanup(base.parent)
    check_eq("K-N6: not a list -> nothing raised, nothing removed", gate_brief._not_established(None), ([], []))
    check_eq("K-N6: a non-string item stays, a string unknown leaves",
             gate_brief._not_established([7, None, "vcs_api: unknown", {"a": 1}]),
             ([7, None, {"a": 1}], [{"capability": "vcs_api", "line": "vcs_api: unknown"}]))
    check_eq("K-N6: a string is iterated as lines of characters, none matches: all kept", gate_brief._not_established("vcs_api: unknown")[1], [])


def test_oh1_11_s0_says_unknown_is_not_shown_at_gate_a() -> None:
    """OH1-11 N5: s0.md (the producer text) and gate A agree: refusals are said now, `unknown` is recorded and not shown."""
    text = (SCRIPTS.parent / "skills" / "qa-story" / "phases" / "s0.md").read_text(encoding="utf-8")
    check_in("s0.md names the `not_established` key of `gate_brief.py --json`", "not_established", text)
    check_in("s0.md says an unknown line is not said to the person now", "NOT said to the person", text)


def test_an_answer_is_read_against_the_packet() -> None:
    """P3: the decision keeps the whole answer, and what it does not name is printed as not named.

    `pipeline.gates.A.authorization_source` came out 215 characters long on TP1-15045 while
    the six readings the person had signed lived in `stage_overrides[]` and
    `state/driver-answers.jsonl`. Nothing checked that each item of the packet had a record — it
    worked only because the wordings happened to match the cards.
    """
    base = story("qa-gate-attrib-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        items = gate_brief.packet_items(task_root, "A")
        check("the packet's items are the ids it puts to the person",
              {"TC-001", "TC-002"} <= set(items), str(items))
        said = gate_brief.attribute(items, "approve. TC-001 as written; TC-002 I am not sure about "
                                           "yet — ask me after the run")
        check_eq("what the answer names is named", said["named"][:2], ["TC-001", "TC-002"])
        said = gate_brief.attribute(items, "approved, one story, the critic's verdict stands")
        check_eq("an answer that names no item names none", said["named"], [])
        check("and every item is reported as not named, never as settled",
              set(items) == set(said["not_named"]), str(said))
        # The ids are ids, not wording: a sentence about "the second case" settles nothing.
        said = gate_brief.attribute(["TC-001", "TS-2"], "the second case is fine")
        check_eq("prose about an item is not an answer to it", said["named"], [])
    finally:
        cleanup(base.parent if base.name == "qa-factory" else base)


def test_gate_a_brief() -> None:
    base = story("qa-gate-brief-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("the pyramid counts every plan row", data["pyramid"]["total"], 4)
        check_eq("by level", data["pyramid"]["by_level"],
                 {"e2e-ui": 2, "api": 1, "manual": 1})
        check_eq("by disposition", data["pyramid"]["by_disposition"],
                 {"automate": 3, "manual-human": 1})
        check_eq("the critic's latest verdict wins over the earlier round",
                 data["critic_verdict"], "approve_with_concerns")
        check_eq("the rows the critic did not review semantically are named",
                 data["roll_call"]["unreviewed"], ["TS-2 (TC-002)", "TS-3 (TC-003)"])
        check_eq("the pinned cases are counted", len(data["pinned_cases"]), 4)

        text = gate_brief.render(data)
        check_eq("an e2e row automated without a highest-risk reason is named for the person",
                 data["unearned_automation"], ["TS-1"])
        check_in("and the brief says so for information", "without a highest-risk field (1), for your information", text)
        check("the brief fits one screen", len(text.splitlines()) <= gate_brief.MAX_LINES)
        check_in("it shows the pyramid the automate rule is argued from",
                 "e2e-ui/automate 2", text)
        check_in("it repeats the block the person already passed",
                 "go on without the video", text)
        check_in("it carries the open question", "removed node", text)
        check_in("and the warning the factory is holding", "case_store not_configured", text)
        check_in("the long documents are linked, not summarised",
                 "critic-findings.md", text)
        check_not_in("the critic's prose is not copied into the brief",
                     "confidence: medium", text)

        # The owner's rule of 21.09: the packet says what happens AFTER the approval, because a
        # gate whose approval the factory cannot act on is not a gate. TP1-15045 answered
        # that question four times, each one after the person had already said yes.
        check_in("the packet says what happens after the approval",
                 "## After your approval", text)
        check_in("in the words of the stage the approval unlocks", "S5", text)
        check("the rehearsal never pushes the brief past its cap",
              len(text.splitlines()) <= gate_brief.MAX_LINES)
        check_eq("and the brief carries the rehearsal itself for a caller that wants all of it",
                 data["rehearsal"]["next_stage"], "S5")

        # A machine-readable roll-call, when present, is preferred.
        (task_root / "work" / "test-cases" / "workflows" / "critic-roll-call.json").write_text(
            json.dumps({"rows": [{"case": "TC-001", "reviewed": True},
                                 {"case": "TC-002", "reviewed": False}]}), encoding="utf-8")
        check_eq("a machine-readable roll-call replaces the parsed table",
                 gate_brief.collect("TP1-15045", task_root)["roll_call"]["unreviewed"],
                 ["TC-002"])
    finally:
        cleanup(base.parent)


def test_gate_a_brief_obeys_the_human_text_rules() -> None:
    """B-009 part 2 (critic t-039 F3): twelve case ids of a gate A brief were journalled as
    unexplained. The Lead's decision: an id linked to the case file the person can open, on the
    same line, is explained by that file; every other id keeps the rule. The brief now writes the
    link (or, for a plan row, what the row verifies) where it used to write a bare id."""
    import human_text
    base = story("qa-gate-brief-links-")
    task_root = base / "artifacts" / "TP1-15045"
    head = "# Driver question — TP1-15045\nkind: gate_A\nstage: S4\ndispatch: \nasked_at: 2026-09-30\n\n"
    tail = "\n\n---\nAnswer: write your words to a file and run\n  python story_run.py --task TP1-15045 --answer <file>\n"
    try:
        cases = [f"TC-{n:03d}" for n in range(1, 13)]
        rows = [{"id": f"TS-{n}", "level": "e2e-ui", "disposition": "automate", "impact": "minor",
                 "likelihood": "low", "verification_depth": "standard",
                 "what_we_verify": f"the import limit of the case group {n} (as the ticket words it), "
                                   "checked against the size the code allows today"} for n in (1, 2)]
        (task_root / "work" / "test-plan.json").write_text(json.dumps(rows), encoding="utf-8")
        (task_root / "state" / "story-case-links.json").write_text(json.dumps(
            {"links": [{"case_id": c} for c in cases]}), encoding="utf-8")
        for case in cases:
            (task_root / "work" / "test-cases" / "workflows" / f"{case}.md").write_text("# case\n", encoding="utf-8")

        def brief_problems(data: dict) -> list:
            return human_text.problems(head + gate_brief.render(data) + tail)

        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("every pinned case with a file has its path", sorted(data["case_files"]), cases)
        text = gate_brief.render(data)
        check_in("the case is a link to its file",
                 "[TC-001](qa-factory/artifacts/TP1-15045/work/test-cases/workflows/TC-001.md)", text)
        check_in("an e2e row is named with what it verifies, not by its id alone",
                 "TS-1 (the import limit of the case group 1 as the ticket words…)", text)
        check_eq("a gate A brief with its case links journals no problem", brief_problems(data), [])
        # Before: the same brief with no case file to link names twelve ids nobody can look up.
        found = brief_problems(dict(data, case_files={}))
        check_eq("without the links: one finding, the id rule",
                 [p["rule"] for p in found], ["explained_ids"])
        check_eq("and it names all twelve", found[0]["found"].split(", "), cases)
        # One case with no file stays a bare id, and is the only one reported.
        (task_root / "work" / "test-cases" / "workflows" / "TC-007.md").unlink()
        gone = brief_problems(gate_brief.collect("TP1-15045", task_root))
        check_eq("a case whose file is missing is never given a guessed path",
                 [(p["rule"], p["found"]) for p in gone], [("explained_ids", "TC-007")])
        # No authoring copy, but the story's own pinned snapshot: the link points to it.
        snap = task_root / "state" / "case-versions" / "TC-007" / "cv_1.md"
        snap.parent.mkdir(parents=True)
        snap.write_text("# case\n", encoding="utf-8")
        links = json.loads((task_root / "state" / "story-case-links.json").read_text(encoding="utf-8"))
        for link in links["links"]:
            if link["case_id"] == "TC-007":
                link["path"] = "state/case-versions/TC-007/cv_1.md"
        (task_root / "state" / "story-case-links.json").write_text(json.dumps(links), encoding="utf-8")
        data = gate_brief.collect("TP1-15045", task_root)
        check_in("the pinned snapshot is linked when there is no authoring copy",
                 "[TC-007](qa-factory/artifacts/TP1-15045/state/case-versions/TC-007/cv_1.md)",
                 gate_brief.render(data))
        check_eq("and that brief is clean again", brief_problems(data), [])
        # plan_gloss: the row's own words, shortened at a word, parentheses removed; silence stays silent.
        gloss = gate_brief.plan_gloss([{"id": "TS-9", "what_we_verify": "a (short) thing"},
                                       {"id": "TS-8", "what_we_verify": "x " * 100}, {"id": "TS-7"}], limit=20)
        check_eq("a short row is kept, parentheses removed", gloss["TS-9"], "a short thing")
        check("a long one is cut at a word", gloss["TS-8"].endswith("x…") and len(gloss["TS-8"]) <= 21, gloss["TS-8"])
        check("a row with no words has no entry", "TS-7" not in gloss)
    finally:
        cleanup(base.parent)


def test_gate_brief_degrades() -> None:
    root = temp_dir("qa-gate-brief-bare-")      # NOT a project on purpose: the brief degrades with no project and no story (t-617 section 8.2)
    try:
        task_root = root / "TP1-9"
        task_root.mkdir(parents=True)
        text = gate_brief.render(gate_brief.collect("TP1-9", task_root))
        check("a story with nothing on disk still gets a brief", bool(text.strip()))
        check_in("which says what it could not read instead of guessing",
                 "Not readable by this brief", text)
        check_in("and still answers whether the next stage can start",
                 "## After your approval", text)
        empty = gate_brief.render_gate_b("TP1-9", task_root)
        check_in("gate B with no drafts says so rather than showing an empty list",
                 "Bugs found — none", empty)
        check_in("and still names the delivery summary - in words when it is not written, never as a JSON path (HF8-20)",
                 "the delivery summary is not written yet", empty)
        check_not_in("and no JSON file is named to the person", ".json", empty)
    finally:
        cleanup(root)


def test_t1676_code_reading_candidates_and_cuts_by_words() -> None:
    """t-1676: C4 (gate B marks a code-reading candidate and asks ONE question with three priced answers) and W4 (gate A lists every cut made in the
    person's name, under a heading that has a door, at most LEFT_OUT_CAP rows). Fixtures are English re-typings of LOCAL-1."""
    import human_text
    base = story("qa-gate-b-cr-")
    task_root = base / "artifacts" / "LOCAL-1"
    try:
        drafts = task_root / "work" / "bug-drafts"
        drafts.mkdir(parents=True)
        cases = (("R-24", "Q7", "the price shown when added is kept", "src/lib/services/cartService.ts", 103, "total uses the DB price"),
                 ("R-25", "Q8", "finish the add or ask to retry", "src/pages/BookDetailPage.tsx", 61, "no network-failure branch"),
                 ("R-26", "Q9", "an expired session asks to sign in", "src/lib/session.ts", 34, "owner is the guest cookie"))
        for n, (rid, qid, quote, path, line, note) in enumerate(cases, start=1):
            (drafts / f"cr-{n}.json").write_text(json.dumps({
                "title": f"Candidate {rid}", "impact": "money", "violates": f"requirement:{rid}", "evidence": "code-reading",
                "oracle": {"question": qid, "quote": quote}, "fact": {"id": f"fact {n}", "path": path, "line": line, "note": note},
                "check_state": "not_executed", "manual_steps": ["do it"], "confirmation": "unconfirmed"}), encoding="utf-8")
        text = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_eq("C4 three LOCAL-1 candidates render with the mark", text.count("by reading the code, not proven by a run"), 3)
        check_in("C4 each shows its oracle and its code place", 'your answer at gate A: "the price shown when added is kept"; the code: src/lib/services/cartService.ts:103 - total uses the DB price', text)
        check_not_in("C4 only code-reading drafts: no `Bugs found - none` (E-25)", "Bugs found", text.replace("Product bugs", ""))
        check_not_in("C4 ... and no reproduction words instead of the mark", "nobody outside the run", text)
        block = "\n".join(gate_brief.code_reading_block(gate_brief.bug_rows(task_root, {}))) + "\n---\nAnswer: say which, in your words\n"
        check_eq("C4 the block passes price_problems", human_text.price_problems(block, ["file", "not needed", "prove"]), [])
        check_eq("C4 ... and human_text.problems", human_text.problems(block, offered=["file", "not needed", "prove"]), [])
        check_in("C4 ... naming the three shown numbers", "`file` 1, 2, 3", block)
        check_eq("C4 no code-reading draft -> no block, byte for byte as before", gate_brief.code_reading_block([{"n": 1, "title": "t"}]), [])
        for path in drafts.glob("*.json"):
            path.unlink()
        (drafts / "plain.json").write_text(json.dumps({"title": "A plain draft", "impact": "degraded", "violates": "requirement:R-4"}), encoding="utf-8")
        plain = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_not_in("C4 a story with no code-reading draft shows no block and no mark", "by reading the code", plain)
        check_not_in("C4 ... and no price block", "What each answer costs and does", plain)
    finally:
        cleanup(base)
    row = lambda i: {"form": "quote", "decided": True, "quote": f"only the add-to-cart function {i}", "texts": ["Raising a quantity edits a line.", "Another."]}   # noqa: E731
    section = lambda rows, **kw: "\n".join(gate_brief._decided_lines({"excluded_by_words": rows, **kw}))   # noqa: E731
    got = section([row(1)])
    check_in("W4 a quote-form exclusion is listed with its quote and the first excluded sentence", 'your words "only the add-to-cart function 1" left out: Raising a quantity edits a line. (and 1 more sentences)', got)
    check_in("W4 the heading names the door (say which part to keep)", "## Left out by your words — say which part to keep if you meant otherwise", got)
    check_in("W4 ... and the sentence of the door", "say in your own words which part to keep", got)
    check_eq("W4 an undecided exclusion is never listed (the caller keeps only decided quotes): nothing gives no section", section([]), "")
    cap = gate_brief.LEFT_OUT_CAP
    at, beyond = section([row(i) for i in range(cap)]), section([row(i) for i in range(cap + 1)])
    check_eq("W4 AT the cap: every row shown, no `more` line", (sum(x.startswith("- your words") for x in at.splitlines()), "more -" in at), (cap, False))
    check_eq("W4 BEYOND the cap: the cap shown and `(+1 more - ...)`", (sum(x.startswith("- your words") for x in beyond.splitlines()), "(+1 more -" in beyond), (cap, True))
    check_in("W4 unread: the factory says it could not read, and asks nothing", "that is the factory's defect, nothing is asked of you", section([], excluded_by_words_unread=True))
    check_eq("W4 human_text.problems of the section is []", human_text.problems(got, kind="report"), [])


def _merged_fixture(task_root: Path, manifestations: int = 3, mechanism: dict | None = None, linked: bool = False) -> None:
    """Drafts of t-2187 (English re-typing of LOCAL-1): `qty` is one bug drafted from `manifestations` ways it shows; `cart` is another."""
    drafts = task_root / "work" / "bug-drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    ways = [{"action": f"type value {i}", "start_state": "field shows 1, selected" if i % 2 else "field erased first", "seen": f"1{i}",
             "requirement": f"R-{8 + i}", "case": f"TC-0{15 + i}", "evidence": f"work/evidence/manual/x/{i}.txt",
             "red_test_none": "manual check only"} for i in range(manifestations)]
    qty = {"title": "The quantity field turns invalid input into a different number", "impact": "degraded", "violates": "requirement:R-8",
           "case": "TC-015", "manifestations": ways, "expected": "invalid input is rejected", "actual": "the field shows 11"}
    if mechanism is not None:
        qty["mechanism"] = mechanism
    if linked:
        qty["possibly_same_cause"] = [{"draft": "cart.json", "why": "both fields turn input into a different number"}]
    (drafts / "qty.json").write_text(json.dumps(qty), encoding="utf-8")
    cart = {"title": "Typing 12 in the cart keeps one digit", "impact": "degraded", "violates": "requirement:R-11", "case": "TC-019"}
    if linked:
        cart["possibly_same_cause"] = [{"draft": "qty.json", "why": "both fields turn input into a different number"}]
    (drafts / "cart.json").write_text(json.dumps(cart), encoding="utf-8")


CONFIRMED = {"statement": "the field replaces a value it cannot read as a whole number with 1 after every key", "status": "confirmed",
             "basis": [{"id": "b1", "kind": "code_line", "path": "src/Page.tsx", "line": 4, "quote": "x"},
                       {"id": "b2", "kind": "run", "case": "settle-q", "capture": "c1", "quote": "1 11", "start_state": "field erased first"},
                       {"id": "b3", "kind": "run", "case": "settle-q", "capture": "c2", "quote": "1 1", "start_state": "typed over a selection"}],
             "claims": [{"says": "an invalid value becomes 1", "confirmed_by": ["b1", "b2"]},
                        {"says": "whether pasting -1 behaves like typing it", "confirmed_by": []}], "why": ""}


def test_t2187_n3b_a_merged_bug_is_one_row_with_its_ways_and_one_door_block() -> None:
    """t-2187 N3b (spec 5.7, 5.8, 8.1, 8.2): the cases of a manifestation count as spoken for; a bug drafted from several ways it shows
    prints its cause, what is not verified and its ways (at most MAX_MANIFESTATIONS_SHOWN, then how many more); the door block names
    `file`, `split`, `merge` (only for linked drafts) and `not a bug`, each priced; a one-manifestation bug renders as it did."""
    from unittest import mock
    import bug_records as BR
    import human_text
    base = story("qa-gate-b-merged-")
    task_root = base / "artifacts" / "LOCAL-1"
    try:
        # 5.7: a case named only by a manifestation is spoken for
        _merged_fixture(task_root, 3, mechanism=CONFIRMED)
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps({"unresolved": [
            {"case": "TC-017", "reason": "contradicts_requirement", "detail": "d"},
            {"case": "TC-099", "reason": "contradicts_requirement", "detail": "d"}]}), encoding="utf-8")
        check_eq("5.7 a case covered only by a manifestation is not `no draft speaks for it`; an unnamed one still is",
                 [r["case"] for r in gate_brief.undrafted_discrepancies(task_root)], ["TC-099"])
        items = gate_brief.packet_items(task_root, "B")
        check("5.7 the manifestation's case is an item of the packet", "TC-017" in items and "TC-019" in items)
        with mock.patch.object(BR, "_mechanism_scan", return_value=([], {"b1", "b2", "b3"})):
            text = gate_brief.render_gate_b("LOCAL-1", task_root)
            rows = gate_brief.bug_rows(task_root, {})
            block = gate_brief.merged_bug_block(rows)
        check_in("8.1 the head counts the ways, one cause when confirmed", "· one cause, 3 ways it shows", text)
        check_in("8.1 the cause line says how it was confirmed, in words", "Cause, confirmed by the line of the application code that does it and by trying it "
                 "from two starting states: the field replaces a value it cannot read as a whole number with 1 after every key.", text)
        check_in("8.1 a claim no basis confirms is printed as not verified", "Not verified: whether pasting -1 behaves like typing it.", text)
        check_in("8.1 the ways are lettered", "   c) type value 2;", text)
        check_not_in("8.1 ... and the cart bug (one way) has none", "   a) type value 0;\n   b) type value 1;\n   c) type value 2;\n   d)", text)
        check_in("8.2 the door block", "## One bug or several", text)
        check_in("8.2 ... names the bug and its count", "The factory found that 2 has one cause behind 3 different-looking problems", text)
        offered = ["file", "split", "not a bug"]
        body = "\n".join(block) + "\n---\nAnswer: say which, in your words\n"
        check_eq("8.2 every option names its three prices (price_problems empty)", human_text.price_problems(body, offered), [])
        check_eq("8.2 ... and human_text.problems finds nothing", human_text.problems(body, offered=offered), [])
        check_not_in("8.2 no `merge` without a linked draft", "`merge`", body)
        check_not_in("8.2 no file name and no field name in the body", "possibly_same_cause", body + text)
        check_not_in("8.2 ... nor a draft file", ".json", text)
        # 8.2 / F-6: the reverse door only for drafts linked as possibly the same cause
        _merged_fixture(task_root, 3, mechanism=CONFIRMED, linked=True)
        with mock.patch.object(BR, "_mechanism_scan", return_value=([], {"b1", "b2", "b3"})):
            linked_text = gate_brief.render_gate_b("LOCAL-1", task_root)
            linked_block = "\n".join(gate_brief.merged_bug_block(gate_brief.bug_rows(task_root, {}))) + "\n---\nAnswer: x\n"
        check_in("8.2 a linked draft offers `merge` with both numbers", "(d) `merge` 1 2 — they are one bug; draft them together.", linked_block)
        check_in("8.1 the link is said in numbers with its reason", "Possibly the same cause as 2 (not verified: both fields turn input into a different number).", linked_text)
        check_eq("8.2 the merge option is priced too", human_text.price_problems(linked_block, ["file", "split", "merge", "not a bug"]), [])
        check_not_in("8.2 `split` is offered for the merged bug only, `merge` names no unlinked draft", "`split` 1, 2", linked_block)
    finally:
        cleanup(base)


def test_t2187_n3b_the_unknown_is_said_as_unknown_and_the_cap_holds_at_six_and_seven() -> None:
    """t-2187 N3b edges: `unknown` is never a cause; a confirmed cause whose basis cannot be re-read is not printed as confirmed; the ways cap at
    MAX_MANIFESTATIONS_SHOWN (AT: no `more` line; BEYOND: the count); a one-manifestation bug is byte-equal to the plain one."""
    from unittest import mock
    import bug_records as BR
    cap = gate_brief.MAX_MANIFESTATIONS_SHOWN
    check_eq("14 the cap is six", cap, 6)
    base = story("qa-gate-b-merged-edges-")
    task_root = base / "artifacts" / "LOCAL-1"
    try:
        for ways, more in ((cap, False), (cap + 1, True)):
            _merged_fixture(task_root, ways, mechanism=CONFIRMED)
            with mock.patch.object(BR, "_mechanism_scan", return_value=([], {"b1", "b2", "b3"})):
                text = gate_brief.render_gate_b("LOCAL-1", task_root)
            shown = [x for x in text.splitlines() if x.startswith("   ") and x[3:5] in {f"{c})" for c in "abcdefghij"}]
            check_eq(f"cap {ways} ways: {cap} lines shown", len(shown), cap)
            check_eq(f"cap {ways} ways: the `more` line is there only beyond the cap", "(+1 more)" in text, more)
        unknown = {"statement": "ignored", "status": "unknown", "why": "only one starting state was run", "basis": [], "claims": []}
        _merged_fixture(task_root, 1, mechanism=unknown)
        one = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_in("an unknown cause says so with its reason", "   Cause not established: only one starting state was run.", one)
        check_not_in("... and never prints the statement as a cause", "ignored", one)
        check_not_in("... a single way gets no `ways it shows` and no door block", "ways it shows", one)
        check_not_in("... nor the merged block", "One bug or several", one)
        _merged_fixture(task_root, 2, mechanism=CONFIRMED)
        with mock.patch.object(BR, "_mechanism_scan", return_value=([("r", "the quote is not on that line")], set())):
            broken = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_in("a confirmed cause whose basis cannot be re-read is a cause not established", "Cause not established: the evidence behind it could not be re-read.", broken)
        check_not_in("... and is not named one cause", "one cause,", broken)
        # M2: ... and the block's intro does not say "has one cause" of it either: the row is drafted as one bug, the cause not confirmed
        check_in("M2 the intro of an unconfirmed merged row says the cause could not be confirmed",
                 "The factory drafted 2 as one bug from 2 different-looking problems, but could not confirm one cause behind them", broken)
        check_not_in("M2 ... and never `has one cause` for it", "has one cause", broken)
        with mock.patch.object(BR, "_mechanism_scan", side_effect=OSError("x")):
            check_in("a check that could not run is not a pass", "Cause not established", gate_brief.render_gate_b("LOCAL-1", task_root))
        with mock.patch.object(BR, "_mechanism_scan", return_value=([], {"b1", "b2", "b3"})):
            sure_text = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_in("M2 control: a confirmed and standing row keeps the confirmed intro", "The factory found that 2 has one cause behind 2 different-looking problems", sure_text)
        _merged_fixture(task_root, 2, mechanism=dict(CONFIRMED, status="unverified", why="one start state only"))
        unconfirmed = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_in("M2 an unverified merged row: the same words", "could not confirm one cause behind them", unconfirmed)
        check_not_in("M2 ... no `has one cause`", "has one cause", unconfirmed)
        # a single-manifestation bug renders byte-for-byte as the plain draft
        drafts = task_root / "work" / "bug-drafts"
        plain_draft = {"title": "T", "impact": "degraded", "violates": "requirement:R-8", "case": "TC-015", "expected": "e", "actual": "a"}
        (drafts / "cart.json").unlink()
        (drafts / "qty.json").write_text(json.dumps(plain_draft), encoding="utf-8")
        plain = gate_brief.render_gate_b("LOCAL-1", task_root)
        entry = {"action": "x", "start_state": "y", "seen": "z", "evidence": "w", "red_test_none": "manual"}
        (drafts / "qty.json").write_text(json.dumps(dict(plain_draft, manifestations=[entry])), encoding="utf-8")
        check_eq("golden: one manifestation renders byte-equal to the plain draft", gate_brief.render_gate_b("LOCAL-1", task_root), plain)
        check_not_in("golden: the plain packet carries none of the new lines", "ways it shows", plain)
    finally:
        cleanup(base)


def _linked_drafts(task_root: Path, links: dict, ways: dict | None = None, mechanism: dict | None = None) -> None:
    """Drafts a.json, b.json, ... (in file order, numbers 1, 2, ...): `links` maps a draft's name to the names it lists in `possibly_same_cause`;
    `ways` maps a name to a number of manifestations (2+ makes it a merged bug); `mechanism` goes to the draft named `a`."""
    drafts = task_root / "work" / "bug-drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    for old in drafts.glob("*.json"):
        old.unlink()
    for name in links:
        data = {"title": f"Bug {name}", "impact": "degraded", "violates": "requirement:R-8", "case": "TC-015", "expected": "e", "actual": "a"}
        if (ways or {}).get(name):
            data["manifestations"] = [{"action": f"do {i}", "start_state": f"state {i}", "seen": f"seen {i}", "evidence": "w",
                                       "red_test_none": "manual"} for i in range(ways[name])]
        if links[name]:
            data["possibly_same_cause"] = [{"draft": f"{other}.json", "why": "both turn input into a different number"} for other in links[name]]
        if name == "a" and mechanism is not None:
            data["mechanism"] = mechanism
        (drafts / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_t2187_n3b_linked_drafts_get_the_merge_block_without_a_multi_manifestation_row() -> None:
    """t-2187 N3b fix round (Lead decision 10.11.2026, spec 8.2, F-6): the block is rendered when a shown row has two or more ways it shows OR
    a shown row is linked as possibly the same cause to another shown row; `merge` is offered for linked groups only, `file`/`split`/`not a bug`
    for rows with two or more ways only; a linked pair alone gets its own intro and `merge` plus `file` (keep apart); every variant passes
    price_problems and problems."""
    import human_text
    base = story("qa-gate-b-linked-")
    task_root = base / "artifacts" / "LOCAL-1"
    try:
        def block_of(links, ways=None):
            _linked_drafts(task_root, links, ways)
            return "\n".join(gate_brief.merged_bug_block(gate_brief.bug_rows(task_root, {})))

        def clean(body, offered):
            text = body + "\n---\nAnswer: say which, in your words\n"
            check_eq("price_problems is empty", human_text.price_problems(text, offered), [])
            check_eq("human_text.problems is empty", human_text.problems(text, offered=offered), [])
            check_not_in("no field name in the body", "possibly_same_cause", text)
            check_not_in("... nor a draft file", ".json", text)
        # a linked pair, no row with several ways: the block with its own intro and exactly the two options
        pair = block_of({"a": ["b"], "b": ["a"]})
        check_in("pair: the block is there", "## One bug or several", pair)
        check_in("pair: its own intro, in plain words", "The factory suspects that bugs 1 and 2 share one cause, but it could not confirm it", pair)
        check_in("pair: merge is offered with both numbers", "(a) `merge` 1 2 — they are one bug; draft them together.", pair)
        check_in("pair: keep apart is the gate's own word `file`", "(b) `file` 1, 2 — file them as separate bugs, each naming the other as possibly the same cause.", pair)
        check_in("pair: the keep-apart story line", "if one fix does not cure both, nothing is lost", pair)
        check_eq("pair: exactly two options", len([x for x in pair.splitlines() if x.startswith("(")]), 2)
        check_not_in("pair: no `split` for a row without several ways", "`split`", pair)
        check_not_in("pair: ... nor `not a bug`", "`not a bug`", pair)
        clean(pair, ["merge", "file"])
        # a one-way link (a names b, b does not name a) is a link; both numbers named once
        one_way = block_of({"a": ["b"], "b": []})
        check_in("one-way link: treated as linked, merge 1 2", "`merge` 1 2 —", one_way)
        check_eq("one-way link: one merge option", one_way.count("`merge`"), 1)
        clean(one_way, ["merge", "file"])
        # m1: the link reads the same from both rows, so "each naming the other" is true of what the person sees
        _linked_drafts(task_root, {"a": ["b"], "b": []})
        seen = gate_brief.bug_rows(task_root, {})
        check_eq("m1 a one-way link is on both rows (a names b; b shows a)",
                 [[x["n"] for x in r.get("possibly_same_cause") or []] for r in seen], [[2], [1]])
        both_ways = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_in("m1 row 2 says it too", "Possibly the same cause as 1 (not verified:", both_ways)
        check_in("m1 row 1 says it", "Possibly the same cause as 2 (not verified:", both_ways)
        # three drafts linked in a chain are one group
        chain = block_of({"a": ["b"], "b": ["c"], "c": []})
        check_in("chain: one group merge 1 2 3", "(a) `merge` 1 2 3 —", chain)
        check_eq("chain: one merge option, not two overlapping", chain.count("`merge`"), 1)
        check_in("chain: the intro names the three", "bugs 1, 2 and 3 share one cause", chain)
        clean(chain, ["merge", "file"])
        # a link to a draft that is not in this packet offers no merge: there is nothing to merge with
        ghost = block_of({"a": ["zz"], "b": []})
        check_eq("a link to a draft not shown in this packet: no block at all", ghost, "")
        mixed_ghost = block_of({"a": ["zz"], "b": []}, ways={"a": 3})
        check_not_in("a link to a draft not shown in this packet: no merge beside a multi-way bug", "`merge`", mixed_ghost)
        check_in("... the multi-way block is still there", "(a) `file` 1 —", mixed_ghost)
        # a linked pair AND a multi-way row: one block, every applicable option, lettering continuous
        both = block_of({"a": ["b"], "b": ["a"], "c": []}, ways={"c": 3})
        check_eq("mixed: one block", both.count("## One bug or several"), 1)
        check_in("mixed: file for the multi-way bug only", "(a) `file` 3 —", both)
        check_in("mixed: split", "(b) `split` 3 —", both)
        check_in("mixed: not a bug", "(c) `not a bug` 3 —", both)
        check_in("mixed: merge for the linked pair, lettering continues", "(d) `merge` 1 2 —", both)
        check_in("mixed (m2): the linked pair also gets its keep-apart option, in the gate's own word `file`",
                 "(e) `file` 1, 2 — file them as separate bugs, each naming the other as possibly the same cause.", both)
        check_in("mixed (m2): its price is a difference from filing, not a second cost of the same word", "nothing beyond filing them", both)
        check_eq("mixed: five options", len([x for x in both.splitlines() if x.startswith("(")]), 5)
        clean(both, ["file", "split", "not a bug", "merge"])
        # the multi-way row is itself linked: file/split/not a bug for it AND merge for the group
        self_linked = block_of({"a": ["b"], "b": ["a"]}, ways={"a": 2})
        check_in("multi-way and linked: file for it", "`file` 1 —", self_linked)
        check_in("multi-way and linked: merge for the group", "`merge` 1 2 —", self_linked)
        clean(self_linked, ["file", "split", "not a bug", "merge"])
        # no links, no multi-way row: no block, and one manifestation is byte-equal to the plain draft (golden)
        _linked_drafts(task_root, {"a": [], "b": []})
        plain = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_not_in("golden: no block without links or several ways", "One bug or several", plain)
        _linked_drafts(task_root, {"a": [], "b": []}, ways={"a": 1})
        check_eq("golden: one manifestation and no links is byte-equal", gate_brief.render_gate_b("LOCAL-1", task_root), plain)
        # the whole packet of a linked pair: the block, and the link said in numbers
        _linked_drafts(task_root, {"a": ["b"], "b": ["a"]})
        text = gate_brief.render_gate_b("LOCAL-1", task_root)
        check_in("packet: the pair's block is in the packet", "## One bug or several", text)
        check_in("packet: the link is said in numbers", "Possibly the same cause as 2 (not verified:", text)
        check_not_in("packet: no file name", ".json", text)
    finally:
        cleanup(base)


def test_t2187_n3b_an_unverified_cause_is_printed_as_a_hypothesis() -> None:
    """t-2187 N3b fix round (Lead decision 10.11.2026): `unverified` with words is "Possible cause, not verified: <statement>" and then the
    reason when there is one - never "Cause," alone and never "confirmed"; with an empty statement it is printed as `unknown` is; `unknown`
    stays "Cause not established: <why>"."""
    base = story("qa-gate-b-hypothesis-")
    task_root = base / "artifacts" / "LOCAL-1"
    try:
        def text_of(mechanism):
            _linked_drafts(task_root, {"a": []}, mechanism=mechanism)
            return gate_brief.render_gate_b("LOCAL-1", task_root)
        said = text_of({"statement": "the field resets a value it cannot read", "status": "unverified",
                        "why": "only one starting state was run", "basis": [], "claims": []})
        check_in("hypothesis: statement and reason", "   Possible cause, not verified: the field resets a value it cannot read. only one starting state was run.", said)
        check_not_in("hypothesis: never `Cause,` alone", "Cause,", said)
        cause_line = next(x for x in said.splitlines() if "ossible cause" in x)
        check_not_in("hypothesis: its line never says `confirmed`", "confirmed", cause_line)
        check_not_in("hypothesis: never `one cause`", "one cause", said)
        bare = text_of({"statement": "the field resets a value", "status": "unverified", "why": "", "basis": [], "claims": []})
        check_in("hypothesis without a reason: the statement alone", "   Possible cause, not verified: the field resets a value.\n", bare)
        empty = text_of({"statement": "  ", "status": "unverified", "why": "no run yet", "basis": [], "claims": []})
        check_in("unverified with an empty statement is printed as unknown is", "   Cause not established: no run yet.", empty)
        check_not_in("... and not as a hypothesis", "Possible cause", empty)
        unknown = text_of({"statement": "ignored", "status": "unknown", "why": "no run yet", "basis": [], "claims": []})
        check_in("unknown stays `Cause not established`", "   Cause not established: no run yet.", unknown)
        check_not_in("... without the statement", "ignored", unknown)
    finally:
        cleanup(base)


def test_gate_b_bug_list_is_rendered_by_code() -> None:
    """The owner's decision of 21.09: the factory shows the bugs as a list in the chat and
    files the ones the person approved. Every row must be answerable without opening a file —
    number, title, impact turned into a priority, what is broken and how to see it, the path,
    and the duplicate the draft itself named."""
    base = story("qa-gate-b-bugs-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        (base / "config.json").write_text(json.dumps(
            {"external_writes": {"bugs": "jira", "channels": {
                "jira": {"method": "agent", "invoke": "jira-rw-assistant-cli"}}}}),
            encoding="utf-8")
        drafts = task_root / "work" / "bug-drafts"
        drafts.mkdir(parents=True)
        (drafts / "sixth-tag.json").write_text(json.dumps({
            "title": "A sixth tag is accepted on a workflow",
            "impact": "degraded", "violates": "requirement:R-4",
            "steps": ["POST /v1/workflows with six tags"],
            "expected": "422 and the workflow unchanged",
            "actual": "201, and the sixth tag is stored",
            "possible_duplicate": "TP2-123"}), encoding="utf-8")
        (drafts / "race.json").write_text(json.dumps({
            "title": "Check and write race on rename",
            "impact": "data-loss", "violates": "invariant:one name per project"}),
            encoding="utf-8")
        import bug_records
        written = bug_records.write_draft_texts(task_root)      # the one writer is the delivery summary's; gate B only reads (HF8-20)
        check_eq("every draft got its readable text", [e["problem"] for e in written], ["", ""])
        text = gate_brief.render_gate_b("TP1-15045", task_root)
        rows = gate_brief.bug_rows(task_root, {})
        check_eq("every draft becomes a numbered row", [r["n"] for r in rows], [1, 2])
        check_in("the list is numbered", "2. **A sixth tag", text)
        check_in("impact becomes a priority instead of being asserted", "`degraded` → P2", text)
        check_in("the worst impact gets the worst priority", "`data-loss` → P0", text)
        check_in("what is broken and how to see it is one line",
                 "201, and the sixth tag is stored", text)
        check_in("with the expected value beside it", "expected: 422", text)
        check_in("the readable text of the draft is on the row", "work/bug-text/sixth-tag.md", text)
        check_not_in("and the JSON draft is not", "sixth-tag.json", text)
        check_in("a duplicate the role found is shown, and left to the person",
                 "TP2-123", text)
        check_in("the answer shape is spelled out", "not a bug", text)
        check_in("and where the approved ones go", "jira-rw-assistant-cli", text)
        check_in("including whether anything proved they can get there",
                 "not checked", text)
        # A draft with no expected/actual pair says so rather than being summarised into one.
        (drafts / "bare.json").write_text(json.dumps(
            {"title": "Nothing recorded", "impact": "cosmetic"}), encoding="utf-8")
        check_in("a draft with nothing to quote says so",
                 "records no expected/actual pair", gate_brief.render_gate_b("TP1-15045", task_root))
    finally:
        cleanup(base.parent)


def test_the_size_the_code_computed_reaches_the_person() -> None:
    """`work/sizing.json` is written by another part of this build; the brief shows it when it
    is there and says nothing at all when it is not — an absent file is not a complaint."""
    base = story("qa-gate-brief-sizing-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        check_eq("no sizing file, no sizing line", gate_brief.sizing_line(task_root), "")
        (task_root / "work" / "sizing.json").write_text(json.dumps(
            {"size": "L", "budget": 18, "cap": 24, "overage": 0, "unverifiable": 2}),
            encoding="utf-8")
        line = gate_brief.sizing_line(task_root)
        check_in("the size class is shown", "size **L**", line)
        check_in("with what the requirements weigh", "the requirements weigh 18", line)
        check_in("and the cap of the size", "the L cap is 24", line)
        check_in("the requirements nothing can verify are counted", "2 requirement(s)", line)
        check_not_in("an overage of zero is not announced as an overage", "over the cap", line)
        text = gate_brief.render(gate_brief.collect("TP1-15045", task_root))
        check_in("and the gate A packet carries it", "size **L**", text)
        check("the size line never pushes the brief past its cap",
              len(text.splitlines()) <= gate_brief.MAX_LINES)
    finally:
        cleanup(base.parent)


MODEL = "claude-sonnet-5-5"   # catalogue: output $10 per 1M tokens, so 100000 output tokens = $1.00


def ledger_row(sid: str, rid: str, dollars: float, stream: str = "orchestrator") -> dict:
    """One request row of a cost file whose usage prices at `dollars` at the catalogue's list rate.
    It is bound to the story by a story ACTIVITY segment (`act-1`, see `story_activity`): the session
    these fixtures describe is an operator's own (orchestrator mode, no driver journal), and a
    `by_task` tag binds nothing since t-170 (FR-24). Its pinned valuation is 1.5x the list price, as
    the cmp1 copies carry, and nothing reads it: the file is re-priced at read."""
    from decimal import Decimal
    return {"request_key": f"anthropic:{sid}:{rid}:{stream}", "provider": "anthropic", "session_id": sid,
            "request_id": rid, "stream": stream, "model_id": MODEL, "timestamp": "2026-09-20T19:30:00+00:00",
            "activity_id": "act-1", "activity_segment_id": "act-1", "task": "TP1-15045",
            "usage": {"requests": 1, "input": 0, "output": int(Decimal(str(dollars)) * 100000),
                      "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0},
            "valuation": {"subtotal_usd": str(round(dollars * 1.5, 6)), "pricing_coverage": "complete",
                          "missing_rate_categories": [],
                          "rate_provenance": {"kind": "legacy_project_override"},
                          "tariff_confirmation": "unconfirmed"}}


def story_activity() -> dict:
    return {"act-1": {"type": "story", "task": "TP1-15045"}}


def test_retro_numbers() -> None:
    base = story("qa-retro-numbers-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        (base / "records").mkdir(exist_ok=True)
        (base / "records" / "journal.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"event": "rejected", "task": "TP1-15045", "reason_family": "grounding"},
            {"event": "gate_block", "task": "TP1-15045"},
            {"event": "gate_block", "task": "TP1-15045"},
            {"event": "compact", "task": "TP1-15045"},
        ]), encoding="utf-8")
        (base / "state" / "cost" / "b156530d.json").write_text(json.dumps({
            "session_id": "b156530d",
            # by_task is the FOLDED total (orchestrator + all three agent dispatches below —
            # cost_capture.py's real task_models aggregation): 13,938,892 + 4,000,000 +
            # 1,000,000 + 500,000 tokens, 6.1314 + 2.0 + 0.5 + 0.25 dollars.
            "by_task": {"TP1-15045": {"tokens": 19_438_892, "requests": 215,
                                          "cost": 8.8814, "active_s": 8171, "machine_s": 3652}},
            "orchestrator": {"tools": {"Bash": 150, "Grep": 42}},
            # requests[] carries the orchestrator's OWN (non-folded) slice — the only source
            # orchestrator_totals() reads for a true per-task orchestrator-only split — and, since
            # t-170, the ledger the story's price is made of: the file is re-priced at read, so each
            # row's usage is the one that prices at the dollars the old pinned figures named
            # (orchestrator 6.1314, the three roles 2.0 + 0.5 + 0.25 = 8.8814 in all).
            "by_activity": story_activity(),
            "requests": [ledger_row("b156530d", "r0", 6.1314),
                         ledger_row("b156530d", "r1", 2.0, "agent-adad2bbad054bc870.jsonl"),
                         ledger_row("b156530d", "r2", 0.5, "agent-afd55942eeff88cea.jsonl"),
                         ledger_row("b156530d", "r3", 0.25, "agent-x.jsonl")],
            "human_wait_s": 19071,
            "agents": [
                {"agent": "qa-factory:qa-scout", "purpose": "qa-scout S1 TP1-15045",
                 "task": "TP1-15045", "tokens": 4_000_000, "cost": 2.0,
                 "started": "2026-09-20T19:27:47+00:00", "by_model": {"m": {"requests": 64}},
                 "tools": {"Bash": 64}, "file": "agent-adad2bbad054bc870.jsonl"},
                {"agent": "qa-factory:qa-case-critic", "purpose": "qa-case-critic S4 TP1-15045",
                 "task": "TP1-15045", "tokens": 1_000_000, "cost": 0.5,
                 "started": "2026-09-20T21:20:12+00:00", "by_model": {"m": {"requests": 28}},
                 "tools": {"Read": 20}, "file": "agent-afd55942eeff88cea.jsonl"},
                {"agent": "qa-factory:qa-case-critic", "purpose": "qa-case-critic S4 TP1-15045",
                 "task": "TP1-15045", "tokens": 500_000, "cost": 0.25,
                 "started": "2026-09-20T21:30:12+00:00", "by_model": {"m": {"requests": 12}},
                 "tools": {"Read": 9}, "file": "agent-x.jsonl"},
            ],
        }), encoding="utf-8")
        data = retro_numbers.numbers("TP1-15045", base, task_root)
        check_eq("the story's cost is by_task plus the roles, not by_activity",
                 round(data["story"]["usd"], 4), 8.8814)
        check_eq("nothing is incomplete when every role carries usage",
                 data["incomplete"], False)
        check_eq("the orchestrator's share is computed, not assumed",
                 data["orchestrator_share_percent"], 69.0)
        check_eq("dispatches are attributed to stages", sorted(data["by_stage"]), ["S1", "S4"])
        check_eq("and to roles", sorted(data["by_role"]), ["qa-case-critic", "qa-scout"])
        check_eq("the second critic dispatch of S4 is a repair round",
                 data["rework"]["dispatches"], 1)
        check_eq("with its own cost", data["rework"]["cost"], 0.25)
        check_eq("the three most expensive dispatches are ranked",
                 [d["cost"] for d in data["top_dispatches"]], [2.0, 0.5, 0.25])
        check_eq("gate blocks are counted; the norm is zero",
                 data["journal"]["gate_blocks"], 2)
        check_eq("rejects are tallied by family",
                 data["journal"]["reject_families"], {"grounding": 1})
        check_eq("halts carry their wait", data["halts"]["waited_s"], 1728)
        check_eq("human wait comes from the cost file", data["human_wait_s"], 19071)
        check_eq("estimate against actual names the plan",
                 data["estimate_vs_actual"]["plan_rows"], 4)
        check_eq("and the requirements register",
                 data["estimate_vs_actual"]["requirements"], 15)

        text = retro_numbers.render(data)
        check_in("the rendered table names the roles", "qa-case-critic", text)
        check_in("and prints the orchestrator share", "69.0%", text)
        check_in("and the time to the first test", "Time to the first test", text)
    finally:
        cleanup(base.parent)


def test_retro_numbers_refuses_a_false_hundred_percent() -> None:
    """The TP1-15045 capture defect: six roles, every one recorded at tokens 0. The
    honest answer is "we cannot say", never "the orchestrator spent all of it"."""
    base = story("qa-retro-incomplete-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        (base / "state" / "cost" / "b156530d.json").write_text(json.dumps({
            "session_id": "b156530d",
            "by_task": {"TP1-15045": {"tokens": 13_938_892, "requests": 111, "cost": 6.1314}},
            # The session is the story's by a story activity segment with the orchestrator's one
            # request (t-170: a `by_task` tag binds nothing); the roles' usage is what is missing.
            "by_activity": story_activity(),
            "requests": [ledger_row("b156530d", "r0", 6.1314)],
            "orchestrator": {"tools": {}},
            "agents": [{"agent": "qa-factory:qa-scout", "purpose": "qa-scout S1 TP1-15045",
                        "task": "TP1-15045", "tokens": 0, "cost": None,
                        "tools": {"Bash": 3},      # it RAN with usage unread: a gap; with no tool calls it is idle (E-C5, a813ff32d)
                        "started": "2026-09-20T19:27:47+00:00", "by_model": {},
                        "file": "agent-adad2bbad054bc870.jsonl"}],
        }), encoding="utf-8")
        data = retro_numbers.numbers("TP1-15045", base, task_root)
        check("a role with no usage marks the whole figure incomplete", data["incomplete"])
        check_eq("and the orchestrator share is withheld",
                 data["orchestrator_share_percent"], None)
        check_in("the reason names the role", "qa-scout", data["incomplete_reason"])
        text = retro_numbers.render(data)
        check_in("the rendered table says INCOMPLETE out loud", "INCOMPLETE", text)
        check_in("and calls the number a floor", "floor, not a total", text)
        check_not_in("it never reports a 100% orchestrator share", "100.0%", text)

        # The same defect declared by the capture layer (cost_capture writes the list).
        payload = json.loads((base / "state" / "cost" / "b156530d.json").read_text(encoding="utf-8"))
        payload["agents"][0].update(tokens=4_000_000, cost=2.0)
        payload["incomplete_agents"] = ["qa-factory:qa-scout"]
        (base / "state" / "cost" / "b156530d.json").write_text(json.dumps(payload), encoding="utf-8")
        check("a declared incomplete_agents entry is honoured even with usage present",
              retro_numbers.numbers("TP1-15045", base, task_root)["incomplete"])
    finally:
        cleanup(base.parent)


def test_gate_b_names_the_direct_api_author() -> None:
    """a project with only API access to its tracker. Gate B must still say WHO will
    file the bugs — but `filing_line` is read-only by contract (a brief that opened a network
    connection would not be a brief), so the display name comes off the SAME cached receipt
    `tracker_write.py`'s probe already left, never a fresh call."""
    import tracker_write
    base = story("qa-gate-b-direct-api-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        (base / "config.json").write_text(json.dumps(
            {"external_writes": {"bugs": "jira", "channels": {"jira": {"method": "api"}}},
             "adapters": {"ticket": {"direct_api": {
                 "base_url": "https://tracker.example", "auth_type": "bearer",
                 "secret_ref": "QA_JIRA_TOKEN"}}}}),
            encoding="utf-8")
        drafts = task_root / "work" / "bug-drafts"
        drafts.mkdir(parents=True)
        (drafts / "one.json").write_text(json.dumps(
            {"title": "A bug", "impact": "degraded"}), encoding="utf-8")
        tracker_write.save_receipt(base.parent, {
            "channel": "jira", "status": tracker_write.CONFIRMED, "checked_at": "2026-09-22T00:00:00+00:00",
            "method": "direct_api", "project": "TP2",
            "author": {"username_ref": "QA_JIRA_TOKEN", "display_name": "Jane Reviewer"}})
        text = gate_brief.render_gate_b("TP1-15045", task_root)
        check_in("the direct-API way in is named", "the tracker's direct API", text)
        check_in("and the one sentence names the author by display name",
                 "Bugs and comments will be written to `jira` as **Jane Reviewer**.", text)
        check_not_in("never the credential's value", "QA_JIRA_TOKEN", text)
    finally:
        cleanup(base.parent)


def test_an_experiment_packet_says_filing_is_closed() -> None:
    """t-017 D3 (B-003, FR-36/FR-53): the gate B packet of a run whose pipeline says `no_trace`
    does not advertise a channel - not `jira`, not "tracker write: confirmed" - and says the
    filing is closed. The control is the same story and config without the flag."""
    import tracker_write
    base = story("qa-gate-b-experiment-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        config = {"external_writes": {"bugs": "jira", "channels": {"jira": {"method": "api"}}}}
        (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
        tracker_write.save_receipt(base.parent, {
            "channel": "jira", "status": tracker_write.CONFIRMED, "checked_at": "2026-09-22T00:00:00+00:00",
            "method": "direct_api", "project": "TP2"})
        control = gate_brief.filing_line(task_root, config)
        check_in("control: an ordinary story names the channel", "channel `jira`", control)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045", "no_trace": True}),
                                                 encoding="utf-8")
        line = gate_brief.filing_line(task_root, config)
        check_eq("an experiment: the line says the filing is closed, and where the bugs stay", line,
                 "**Filing** — closed for this run: it is an experiment that leaves no trace; "
                 "bugs stay as files in this repository.")
        packet = gate_brief.render_gate_b("TP1-15045", task_root)
        check_in("and it is in the packet the person reads", line, packet)
        check_not_in("no channel is named", "channel `jira`", packet)
        check_not_in("nothing is confirmed", "confirmed", line)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045", "no_trace": False}),
                                                 encoding="utf-8")
        check_in("`no_trace: false` closes nothing", "channel `jira`", gate_brief.filing_line(task_root, config))
        # F1 (critic t-047): the open-items list stays in an experiment, but is not "before the MR"
        # and does not offer to put itself into one; an ordinary story's list is unchanged.
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [{"id": "Q-1", "question": "Which reviewer?", "severity": "low",
                                 "owner_role": "qa-story"}]}), encoding="utf-8")
        # t-305 N8 (R6, K-N8.16): the packet offers the MR only on a verdict that opens it. A story with NO ledger reads
        # `no`, so the ordinary packet below is the `yes` one - its ledger says so.
        (task_root / "work").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "ledger.json").write_text(json.dumps({"rows": [], "delivery_ready": True, "delivery_verdict": "yes"}),
                                                       encoding="utf-8")
        ordinary = gate_brief.render_gate_b("TP1-15045", task_root)
        check_in("F1 control: an ordinary packet titles the list before the MR", "## Open before the MR (", ordinary)
        check_in("F1 control: and offers to open the MR anyway", 'say "open the MR anyway"', ordinary)
        check_not_in("K-N8.16 on `yes` the plain closing line carries no mention of what is left with the person",
                     "what is left with you", ordinary)
        for ledger, word in (({"delivery_ready": False, "delivery_verdict": "after_checks"}, "after_checks"),
                             ({"delivery_ready": False, "delivery_verdict": "no"}, "no"), ({"delivery_ready": False}, "no"),
                             ({"delivery_ready": "no"}, "unknown"), ({"delivery_verdict": "yes", "delivery_ready": False}, "unknown")):
            (task_root / "work" / "ledger.json").write_text(json.dumps(dict(ledger, rows=[])), encoding="utf-8")
            packet = gate_brief.render_gate_b("TP1-15045", task_root)
            offers = 'say "open the MR anyway"' in packet
            check_eq(f"K-N8.16 the word `{word}` {'offers' if word == 'after_checks' else 'does not offer'} the MR", offers,
                     word == "after_checks")
            if word == "after_checks":
                check_in("K-N8.16 on after_checks its description carries what is left with the person",
                         "with what is left with you.", packet)
            else:
                # HF8-23 (35f87491): the road is told by `risk_form()` (the approval word on the first line, then the vocabulary's
                # risk word and the reason on a line of its own), the one text both roads print; the bare sentence is its fallback
                form = gate_brief.risk_form()
                # t-440 (F10 of the t-430 verdict): the form is checked FIRST, and there is no fallback arm - an empty `form` made
                # the old expected text "." (in every packet) and the key could not fail. Killed by: `risk_form()` returning "".
                check("K-N8.16 the form is read from the two data files, not empty", bool(form), form)
                check_in(f"K-N8.16 on `{word}` the packet names the road to deliver over it, with its reason", form + ".", packet)
        (task_root / "work" / "ledger.json").write_text(json.dumps({"rows": [], "delivery_ready": True, "delivery_verdict": "yes"}),
                                                       encoding="utf-8")
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "TP1-15045", "no_trace": True}),
                                                 encoding="utf-8")
        packet = gate_brief.render_gate_b("TP1-15045", task_root)
        check_in("F1 an experiment: the list is still there, titled without the MR", "## Open items (", packet)
        check_in("F1 an experiment: with its question", "Which reviewer?", packet)
        check_in("F1 an experiment: and the sentence that blocks nothing", "None of this blocks you: answer what you want answered.", packet)
        import re
        check_eq("F1 an experiment: no MR and no merge request anywhere in the packet",
                 re.findall(r"\bMR\b|merge request", packet, re.IGNORECASE), [])
    finally:
        cleanup(base.parent)


def test_story_spend_is_shared_with_the_ceiling() -> None:
    base = story("qa-retro-spend-")
    try:
        # The session is the story's because the driver's journal names it (t-170, FR-24: a `by_task`
        # tag binds nothing): one role row whose running total is the $1.5 the tag carries.
        (base / "artifacts" / "TP1-15045" / "state" / "driver-runs.jsonl").write_text(json.dumps(
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
             "session_id": "s-1", "num_turns": 3, "total_cost_usd": 1.5,
             "ts": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps({
            # by_task is the FOLDED total (orchestrator's 100/$1.0 + the scout's 50/$0.5).
            "session_id": "s-1", "by_task": {"TP1-15045": {"tokens": 150, "cost": 1.5}},
            "agents": [{"agent": "qa-factory:qa-scout", "task": "TP1-15045",
                        "tokens": 50, "cost": 0.5, "purpose": "qa-scout S1"}],
        }), encoding="utf-8")
        spend = retro_numbers.story_spend("TP1-15045", base)
        check_eq("one function answers what the story has spent", spend["usd"], 1.5)
        check_eq("in tokens too", spend["tokens"], 150)
        check_eq("with no cost file at all the story reads incomplete, not free",
                 retro_numbers.story_spend("NOPE-1", base)["incomplete"], True)
    finally:
        cleanup(base.parent)


# ---- t-172 P6: the sources the person left out before the run, at gate A and in the retro -----------

import hashlib  # noqa: E402

import source_exclusions as SX  # noqa: E402
import source_inventory as SI  # noqa: E402

DASH = "—"
GITHOST = "https://git.example/tp1-group/"
REASON_1924 = "Draft MR of an earlier factory run, not a product change"
TASK = "TP1-15045"


class FakeJira:
    """The smallest client `collect_jira_source` needs: one ticket whose description carries `text`."""
    acceptance_criteria_fields: list = []
    api_version = "2"
    project_keys: list = []
    base_url = "https://jira.invalid"

    def __init__(self, text: str):
        self.text = text

    def get_json(self, path):
        return {"key": path.rsplit("/", 1)[-1]}

    def issue(self, key):
        return {"key": key, "id": "1", "fields": {
            "updated": "rev-1", "summary": "title " + key, "description": self.text, "attachment": [],
            "comment": {"total": 0, "startAt": 0, "comments": []}}}

    def all_comments(self, key, embedded=None):
        return []

    def get_bytes(self, url):
        return b"x"


def mr_url(n: int) -> str:
    return f"{GITHOST}proj{n}/-/merge_requests/{n}"


def left_out_story(prefix: str, lines: list, carried: list, revoke: tuple = (), no_decisions: bool = True) -> tuple:
    """(base, task_root) of a story whose person gave a list of sources before the run.

    `lines` are the list's lines (source, dash, reason); `carried` the text the task ticket's description
    holds (the links the sources come from); `revoke` = ((X-id, words), ...) are taken back afterwards.
    The record is written BEFORE the inventory (the order `--load` enforces), through the real
    parser, writer and collector - nothing here is a hand-built mark."""
    base = story(prefix)
    task_root = base / "artifacts" / TASK
    if no_decisions:
        # No waiver, no stage override: the gate A section has nothing but the person's word to show (C7).
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline.update(gate_waivers=[], stage_overrides=[])
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    data = ("\n".join(lines) + "\n").encode("utf-8")
    entries, problems = SX.parse_bytes(data, TASK)
    assert not problems, problems
    SX.write_record(task_root, entries, "list.txt", data)
    output = task_root / "work" / "source-inventory.json"
    record = SI.collect_jira_source(FakeJira(" ".join(carried)), TASK, output)
    SI.update_inventory(output, record)
    for key, words in revoke:
        result = SX.revoke(task_root, key, words)
        assert result["status"] == "revoked", result
    return base, task_root


def c29_task(n_default: int = 0, with_kind: bool = False) -> Path:
    """A task folder with ONE required source: `n_default` merge requests the collector's receipt says are unreachable (gap by default),
    and, with `with_kind`, one login-walled address that a recorded kind of gap (GC-1, the person's words) closes."""
    import json
    import tempfile
    task_root = Path(tempfile.mkdtemp(prefix="qa-gate-c29-"))
    items = [{"url": f"https://git.example.com/team/sdk/-/merge_requests/{n}", "status": "unavailable", "cause": "host_unreachable",
              "probe_ref": f"sources/SRC-1/mr-{n}.json", "probe_code": "host_unreachable"} for n in range(1, n_default + 1)]
    if with_kind:
        items.append({"url": "https://share.example.com/x/doc", "status": "unavailable", "cause": "auth_required"})
    source = {"source_id": "SRC-1", "canonical_ref": "https://jira.example.invalid/browse/APP-1", "relation": "referenced",
              "relevance": "relevant", "required": True, "status": "read", "inspection_status": "read",
              "human_review": {"words": "ok", "shown": {"relevance": "relevant"}},
              "materials": {"comments": {"status": "read"}, "attachments": {"status": "read", "items": []},
                            "external_media": {"status": "unavailable", "items": items}}}
    (task_root / "work").mkdir()
    (task_root / "work" / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": [source]}), encoding="utf-8")
    if with_kind:
        (task_root / "work" / "gap-classes.json").write_text(json.dumps({"schema_version": 1, "classes": [
            {"id": "GC-1", "cause": "auth_required", "words": "skip every login wall", "at": "2026-10-16T09:00:00+00:00"}]}), encoding="utf-8")
    return task_root


def test_c29_not_reachable_section() -> None:
    """T12 (C2-9): the section for what the factory itself established; the ceiling is five rows then `(+K more ...)`, the last line is the
    door; a gap closed by a recorded kind is a decided line with the kind's words and whose answer it was."""
    import shutil
    heading = "## Not reachable by the factory - recorded without asking you"

    def lines_of(n: int) -> list:
        task_root = c29_task(n)
        try:
            lines = gate_brief._unreachable_lines({"sources": gate_brief.sources_inventory(task_root)})
        finally:
            shutil.rmtree(task_root, ignore_errors=True)
        return lines

    five, six = lines_of(5), lines_of(6)
    check_eq("T12 five gaps by default: heading, five rows, the door - no `+K`", (five[1], len([l for l in five if l.startswith("- ") and "merge_requests" in l]),
             any("more" in l for l in five), five[-1].startswith("- To try again after you restore access")), (heading, 5, False, True))
    check_eq("T12 six: five rows and `(+1 more ...)`", (len([l for l in six if "merge_requests" in l]), any(l.startswith("- (+1 more") for l in six)), (5, True))
    check_in("T12 the row names the cause and the carrier", "host_unreachable", five[2])
    check_eq("T12 no gap by default: no section", lines_of(0), [])
    task_root = c29_task(0, with_kind=True)
    try:
        sources = gate_brief.sources_inventory(task_root)
        check_eq("T12 a gap closed by a recorded kind is an accepted gap with the kind's words and whose answer it was",
                 ("skip every login wall" in sources["accepted_gaps"][0], "GC-1 of 2026-10-16" in sources["accepted_gaps"][0]), (True, True))
        check_eq("T12 and it is not in the section for the factory's own verdicts", sources["defaulted"], [])
    finally:
        shutil.rmtree(task_root, ignore_errors=True)


def gate_text(task_root: Path) -> str:
    return gate_brief.render(gate_brief.collect(TASK, task_root))


def section_lines(text: str) -> list:
    """The lines of the "Already decided by you" section, without the heading."""
    lines = text.splitlines()
    if "## Already decided by you — repeated, not re-asked" not in lines:
        return []
    rest = lines[lines.index("## Already decided by you — repeated, not re-asked") + 1:]
    out = []
    for line in rest:
        if line.startswith("## "):
            break
        if line.strip():
            out.append(line)
    return out


def test_gate_a_left_out_lines() -> None:
    """P6 / C7: what the person left out before the run is repeated at gate A, even with no decision and no gap."""
    base, task_root = left_out_story(
        "qa-gate-leftout-", [f"proj1!1 {DASH} {REASON_1924}", f"PROJ-7 {DASH} not this story"],
        [mr_url(1), "see PROJ-7"])
    try:
        data = gate_brief.collect(TASK, task_root)
        rows = data["sources"]["left_out_by_word"]
        check_eq("sources() carries the applied exclusions: the merge request and the ticket mention",
                 [(r["as_written"], r["reason"]) for r in rows],
                 [("proj1!1", REASON_1924), ("PROJ-7", "not this story")])
        check_eq("they are all the person's own word", {r["origin"] for r in rows}, {"person_before_run"})
        check_eq("nothing is unmatched, nothing taken back",
                 (data["sources"]["unmatched_words"], data["sources"]["taken_back"]), ([], []))
        check_eq("the story has no decision and no accepted gap (so C7's condition is what opens the section)",
                 (data["gate_waivers"] + data["stage_overrides"], data["sources"]["accepted_gaps"]), ([], []))
        text = gate_brief.render(data)
        check_in("the section is rendered with only the left-out words in the story",
                 "## Already decided by you — repeated, not re-asked", text)
        check_eq("and it holds exactly the two lines, in the person's words (the reason in quotes)",
                 section_lines(text),
                 [f"- left out before the run by your word: proj1!1 {DASH} \"{REASON_1924}\"",
                  f"- left out before the run by your word: PROJ-7 {DASH} \"not this story\""])
        check_not_in("no internal id of the record reaches the person (FR-6)", "X1", text)
        block = gate_brief._attachment_lines(data)     # the attachments block is the question itself: render's cap grows by it (S6 1c)
        check_eq("the left-out link is named in the attachments block (F-5: the person's own decision, in words)",
                 [l for l in block if "(not opened: you left it out)" in l] != [], True)
        # GW1-32: the answer block stands whenever the packet has a form (an open item too), and render's cap grows by it like by a card
        answer_block = gate_brief.how_to_answer_lines(gate_brief.answer_forms(data, data.get("open_questions") or []),
                                                      str(data.get("case_id_example") or ""))
        check("the cover sheet without the attachments block still fits its cap",
              len(text.splitlines()) - (len(block) + 1) - len(answer_block) <= gate_brief.MAX_LINES)
    finally:
        cleanup(base.parent)


def test_gate_a_left_out_beside_other_decisions() -> None:
    """The word about sources stands BESIDE the waivers, overrides and gaps, never instead of them."""
    base, task_root = left_out_story(
        "qa-gate-leftout-beside-", [f"proj1!1 {DASH} {REASON_1924}"], [mr_url(1)], no_decisions=False)
    try:
        body = section_lines(gate_text(task_root))
        check_eq("the override keeps its line and the left-out word follows it",
                 [line.split(":")[0] if "left out" in line else line.split(" · your word")[0] for line in body],
                 ["- Context and grounding (S1) · video", "- left out before the run by your word"])
    finally:
        cleanup(base.parent)


def test_t373_already_decided_is_the_person_list() -> None:
    """t-373 (FR-10): the packet's "Already decided by you" section renders the person's passes through the ONE renderer,
    `waiver.person_lines` - the same lines as the driver's "Blocks passed by your word so far" - so a stand-gap pass shows
    its phrase here, never `S5 block [stand gap: RP-api]`."""
    import waiver
    base, task_root = left_out_story(
        "qa-gate-decided-one-renderer-", [f"proj1!1 {DASH} {REASON_1924}"], [mr_url(1)], no_decisions=False)
    try:
        pipeline_path = task_root / "pipeline.json"
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = list(pipeline.get("stage_overrides") or []) + [
            {"stage": "S5", "match": "stand gap: RP-api", "decision": "go on, I test admin by hand", "at": "2026-10-03T08:00:00+00:00"}]
        pipeline["gate_waivers"] = [{"gate": "B", "requirement": "REQ-12", "decision": "ship", "at": "2026-09-30T12:00:00+00:00"}]
        pipeline_path.write_text(json.dumps(pipeline), encoding="utf-8")
        body = [line for line in section_lines(gate_text(task_root)) if "left out" not in line]
        check_eq("t-373: the section's pass lines are exactly `waiver.person_lines` of the record",
                 body, ["- " + line for line in waiver.person_lines(pipeline)])
        for token in ("RP-api", "stand gap:", "block [", "REQ-12"):
            check_not_in(f"t-373: no `{token}` (a block key) in the section", token, "\n".join(body))
        check_in("t-373: the stand-gap pass is said by its phrase", waiver.STAND_GAP_BLOCK, "\n".join(body))
    finally:
        cleanup(base.parent)


def test_gate_a_cap_5_6() -> None:
    """Edge (iii): five applied exclusions print five lines; six print five and "and 1 more"."""
    for count, label in ((5, "at the cap"), (6, "beyond the cap")):
        base, task_root = left_out_story(
            f"qa-gate-leftout-cap{count}-", [f"proj{n}!{n} {DASH} reason {n}" for n in range(1, count + 1)],
            [mr_url(n) for n in range(1, count + 1)])
        try:
            body = section_lines(gate_text(task_root))
            left = [line for line in body if line.startswith("- left out before the run by your word")]
            check_eq(f"{label} ({count}): five lines, never more", len(left), 5)
            more = [line for line in body if line.startswith("- and ")]
            check_eq(f"{label} ({count}): the remainder is counted, and only beyond the cap",
                     more, [] if count == 5 else ["- and 1 more left out before the run"])
            check_eq(f"{label} ({count}): the first five are the first five of the record",
                     [line.split(":")[1].split(" ")[1] for line in left],
                     [f"proj{n}!{n}" for n in range(1, 6)])
            check_eq(f"{label} ({count}): the JSON of the brief keeps all of them",
                     len(gate_brief.collect(TASK, task_root)["sources"]["left_out_by_word"]), count)
        finally:
            cleanup(base.parent)


def test_gate_a_unmatched() -> None:
    """Edge (iv): a word that matched nothing is printed as information - never an error."""
    base, task_root = left_out_story(
        "qa-gate-unmatched-", [f"proj1!1 {DASH} {REASON_1924}", f"ghost/repo!77 {DASH} an old draft"], [mr_url(1)])
    try:
        data = gate_brief.collect(TASK, task_root)
        check_eq("the unmatched word is in its own key, whole",
                 [(r["as_written"], r["matched"]) for r in data["sources"]["unmatched_words"]],
                 [("ghost/repo!77", False)])
        check_eq("and is not among the applied ones",
                 [r["as_written"] for r in data["sources"]["left_out_by_word"]], ["proj1!1"])
        check_eq("no unread record: a stale word is not a defect", data["sources"]["left_out_unread"], "")
        body = section_lines(gate_brief.render(data))
        check_in("the line says what the list named and that nothing carried it",
                 "- your list named ghost/repo!77, and no source of this story carried it", body)
        check_eq("the applied line is untouched beside it", len(body), 2)
    finally:
        cleanup(base.parent)


def test_gate_a_revoked() -> None:
    """Edge (v): a revoked exclusion is history - `taken back: <word> - "<their words>"` - and not counted as applied."""
    words = "read it after all, I need the diff"
    base, task_root = left_out_story(
        "qa-gate-revoked-", [f"proj1!1 {DASH} {REASON_1924}", f"proj2!2 {DASH} second"], [mr_url(1), mr_url(2)],
        revoke=(("X1", words),))
    try:
        data = gate_brief.collect(TASK, task_root)
        check_eq("only the live one is applied", [r["as_written"] for r in data["sources"]["left_out_by_word"]],
                 ["proj2!2"])
        check_eq("the revoked one is in its own key, with their words",
                 [(r["as_written"], r["revoked_words"]) for r in data["sources"]["taken_back"]],
                 [("proj1!1", words)])
        check_eq("a revoked word is not reported as unmatched, though its mark moved to the history",
                 data["sources"]["unmatched_words"], [])
        body = section_lines(gate_brief.render(data))
        check_eq("the brief says what is left out and what was taken back, each once",
                 body, [f"- left out before the run by your word: proj2!2 {DASH} \"second\"",
                        f"- taken back: proj1!1 {DASH} \"{words}\""])
        check_not_in("the taken-back word is not among the left-out lines (not counted as applied)",
                     "by your word: proj1!1", "\n".join(body))
    finally:
        cleanup(base.parent)


def test_gate_a_factory_marker_origin() -> None:
    """Edge (vi): an exclusion whose origin is not the person's (B-232's marker) says so in its words.

    Pinned with a hand-edited record so B-232 plugs in with no change here."""
    base, task_root = left_out_story(
        "qa-gate-marker-", [f"proj1!1 {DASH} {REASON_1924}", f"ghost/repo!77 {DASH} an old draft"], [mr_url(1)])
    try:
        record_path = task_root / "work" / "source-exclusions.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        for entry in record["exclusions"]:
            entry["origin"] = "factory_marker"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        body = section_lines(gate_text(task_root))
        check_eq("a matched marker is left out 'by the factory's own marker', not by the person's word",
                 body[0], f"- left out by the factory's own marker: proj1!1 {DASH} \"{REASON_1924}\"")
        check_eq("an unmatched marker does not say 'your list'",
                 body[1], "- the factory's own marker named ghost/repo!77, and no source of this story carried it")
        check_not_in("no line of it says 'by your word'", "by your word", "\n".join(body))
        facts = gate_brief.collect(TASK, task_root)["sources"]["left_out_by_word"]
        check_eq("the origin travels in the row", [r["origin"] for r in facts], ["factory_marker"])
    finally:
        cleanup(base.parent)


def test_gate_a_reason_clip_and_encoding() -> None:
    """Edge (viii): the reason is clipped to 120 at gate A and whole in the retro; non-ASCII survives both."""
    accent, cjk = chr(0xE9), chr(0x4E2D)
    at, beyond = "a" * 120, "b" * 121
    wide = "caf" + accent + " " + cjk + cjk + " " + "w" * 140
    base, task_root = left_out_story(
        "qa-gate-clip-", [f"proj1!1 {DASH} {at}", f"proj2!2 {DASH} {beyond}", f"proj3!3 {DASH} {wide}"],
        [mr_url(1), mr_url(2), mr_url(3)])
    try:
        body = section_lines(gate_text(task_root))
        quoted = [line.split(f"{DASH} \"", 1)[1][:-1] for line in body]
        check_eq("a reason of exactly 120 characters is not touched", quoted[0], at)
        check("a reason of 121 is clipped, marked, and no longer than 120", quoted[1].endswith("...")
              and len(quoted[1]) <= 120, quoted[1])
        check("a long reason with non-ASCII characters is clipped with them intact",
              quoted[2].startswith("caf" + accent + " " + cjk + cjk + " w") and len(quoted[2]) <= 120, quoted[2])
        whole = retro_numbers.numbers(TASK, base, task_root)["sources_left_out"]
        check_eq("the retro's facts keep every reason WHOLE", [r["reason"] for r in whole], [at, beyond, wide])
        text = retro_numbers.retro_document(retro_numbers.numbers(TASK, base, task_root), {})
        for reason in (at, beyond, wide):
            check_in("the retro quotes the reason whole: " + reason[:8], f"{DASH} \"{reason}\"", text)
    finally:
        cleanup(base.parent)


def test_gate_a_left_out_lines_unit() -> None:
    """`left_out_lines` on rows of its own: the groups, the cap per group, the empty input."""
    def row(n, **kw):
        return dict({"id": f"X{n}", "as_written": f"w{n}", "reason": f"r{n}", "origin": "person_before_run",
                     "matched": True, "revoked": False, "revoked_words": ""}, **kw)
    check_eq("no rows, no lines", gate_brief.left_out_lines([]), [])
    check_eq("None is no rows", gate_brief.left_out_lines(None), [])
    rows = [row(n) for n in range(1, 8)] + [row(8, matched=False), row(9, matched=None),
                                            row(10, revoked=True, revoked_words="back")]
    lines = gate_brief.left_out_lines(rows, clip_to=120, cap=5)
    check_eq("seven applied: five and 'and 2 more'", [line for line in lines if line.startswith("and ")],
             ["and 2 more left out before the run"])
    check_in("an unmatched word has its own line", "your list named w8, and no source of this story carried it", lines)
    check_in("a word whose matching could not be checked says so and is not called unmatched",
             "your list named w9; whether a source of this story carried it could not be read", lines)
    check_in("a revoked one is taken back", f"taken back: w10 {DASH} \"back\"", lines)
    check_eq("without a cap, every one", len(gate_brief.left_out_lines(rows)), 10)
    check_eq("a revoked word with no words is still history", gate_brief.left_out_lines(
        [row(1, revoked=True)]), ["taken back: w1"])


def test_gate_a_unreadable_record_and_no_inventory() -> None:
    """A record that cannot be read is told as the factory's own defect; a missing inventory is never
    'nothing carried it' (FR-41)."""
    base, task_root = left_out_story("qa-gate-corrupt-", [f"proj1!1 {DASH} {REASON_1924}"], [mr_url(1)])
    try:
        (task_root / "work" / "source-exclusions.json").write_text("{not json", encoding="utf-8")
        data = gate_brief.collect(TASK, task_root)
        check("the unreadable record is named in its own key", data["sources"]["left_out_unread"])
        check_eq("and lists nothing as left out", data["sources"]["left_out_by_word"], [])
        body = section_lines(gate_brief.render(data))
        check("the brief says it could not read the record, and that it is not the person's to repair",
              len(body) == 1 and "could not be read" in body[0] and "not something you have to repair" in body[0],
              str(body))
        check_not_in("without a path or a command (FR-6)", "source_exclusions", "\n".join(body))
        facts = retro_numbers.numbers(TASK, base, task_root)
        check_eq("the retro's facts carry no rows and the reason", (facts["sources_left_out"],
                                                                     bool(facts["sources_left_out_unread"])), ([], True))
        check_in("the retro says it could not read it", "could not be read, so this retro cannot say",
                 retro_numbers.retro_document(facts, {}))
    finally:
        cleanup(base.parent)
    base, task_root = left_out_story("qa-gate-noinv-", [f"proj1!1 {DASH} {REASON_1924}"], [mr_url(1)])
    try:
        (task_root / "work" / "source-inventory.json").unlink()
        data = gate_brief.collect(TASK, task_root)
        check_eq("with no inventory nothing is claimed matched or unmatched",
                 ([r["matched"] for r in data["sources"]["unchecked_words"]], data["sources"]["unmatched_words"],
                  data["sources"]["left_out_by_word"]), ([None], [], []))
        check_in("the line says it could not be checked",
                 "- your list named proj1!1; whether a source of this story carried it could not be read",
                 section_lines(gate_brief.render(data)))
    finally:
        cleanup(base.parent)


def test_retro_lists_whole_reason() -> None:
    """Edge (ix) and the retro: the facts carry `sources_left_out` with its shape; render() and the retro
    document list ALL of them, the reason whole, with the revoked and the unmatched."""
    reasons = [f"reason {n} " + "long " * 40 for n in range(1, 8)]
    lines = [f"proj{n}!{n} {DASH} {reasons[n - 1]}".rstrip() for n in range(1, 8)]
    lines += [f"ghost/repo!77 {DASH} an old draft"]
    base, task_root = left_out_story("qa-retro-leftout-", lines, [mr_url(n) for n in range(1, 8)],
                                     revoke=(("X3", "I do want 3"),))
    try:
        data = retro_numbers.numbers(TASK, base, task_root)
        rows = data["sources_left_out"]
        check_eq("the facts carry a row per exclusion, in the record's order",
                 [r["as_written"] for r in rows], [f"proj{n}!{n}" for n in range(1, 8)] + ["ghost/repo!77"])
        check_eq("with the shape the spec names (and the id and the revoked words the lines need)",
                 sorted(rows[0]), sorted(["id", "as_written", "reason", "origin", "matched", "revoked",
                                          "revoked_words"]))
        check_eq("matched and revoked are booleans of the record",
                 [(r["matched"], r["revoked"]) for r in rows],
                 [(True, False), (True, False), (True, True)] + [(True, False)] * 4 + [(False, False)])
        check_eq("the reason is whole in the facts", rows[0]["reason"], reasons[0].strip())
        check_eq("the facts are plain JSON", json.loads(json.dumps(data["sources_left_out"])), rows)
        check_eq("and the unread key is empty", data["sources_left_out_unread"], "")
        text = retro_numbers.render(data)
        check_in("render() has the block", "**Sources the person left out before the run:**", text)
        listed = [line for line in text.splitlines() if line.startswith("- left out before the run by your word")]
        check_eq("render() lists all six live ones: no cap, no 'and N more'", len(listed), 6)
        check("and 'and N more' appears nowhere", "more left out" not in text)
        check_in("the last reason is whole, not clipped", f"{DASH} \"{reasons[6].strip()}\"", text)
        check_in("the unmatched word is listed", "- your list named ghost/repo!77, and no source of this story "
                                                 "carried it", text)
        check_in("the revoked one is history", f"- taken back: proj3!3 {DASH} \"I do want 3\"", text)
        check_not_in("the revoked one is not among the left-out ones", "by your word: proj3!3", text)
        doc = retro_numbers.retro_document(data, {})
        decisions = doc.split("## Decisions this story recorded", 1)[1].split("## The human's answer", 1)[0]
        check_eq("retro.md lists them under 'Decisions this story recorded', all eight, once each",
                 len([line for line in decisions.splitlines() if line.startswith("- ")]), 8)
        check_eq("and not a second time inside the numbers block", doc.count("by your word: proj1!1"), 1)
        check_not_in("no 'No gate words' sentence is lost or confused: it still says there are none",
                     "by your word: proj3!3", decisions)
        check_in("the pipeline's own decisions stay", "No gate words are recorded", decisions)
    finally:
        cleanup(base.parent)


def test_gate_b_rejected_by_the_code_critic() -> None:
    """C1-5c (F7, F11): gate B lists the tests the code critic rejected at their repair limit with the lines of the REPORT's own
    renderer (`report_facts.review_gap_lines`, imported - one text, FR-10); nothing to list adds no section; an unreadable record
    is said; the S7 runs left failing have their own section with the triage wording."""
    import report_facts
    root = temp_dir("qa-gate-b-gaps-")
    try:
        task_root = root / "TP1-9"
        (task_root / "work").mkdir(parents=True)
        remark = {"id": "F-1", "problem": "it never reads the flag", "expected": "the flag reads cancelled", "fix": "assert the flag",
                  "cause": "test_defect"}
        row = {"ref": "ti_1", "kind": "test", "state": "review_rejected", "detail": "tests/a.py", "function": "test_a", "case": "TC-001",
               "remarks": [remark], "repair_limit": {"stage": "S5", "counted": 2, "cap": 2, "reason": "cap"}}
        run = {"ref": "ti_2", "kind": "test", "state": "failed:TEST_BUG", "detail": "tests/b.py", "function": "test_b", "case": "TC-002",
               "repair_limit": {"stage": "S7", "counted": 2, "cap": 2, "reason": "cap"}, "triage_words": "the run failed: the locator is stale"}
        window = {"stage": "S5", "cases": ["TC-001"], "tests": [], "reason": "cap", "counted": 2, "cap": 2, "token": "debt", "at": "",
                  "refs": ["ti_1"], "fixed": False, "fixed_by": "", "missing": [], "remarks": []}

        def packet(ledger):
            (task_root / "work" / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            return gate_brief.render_gate_b("TP1-9", task_root)
        none = packet({"rows": []})
        check_not_in("nothing rejected: no section", "Rejected by the code critic", none)
        text = packet({"rows": [row, run], "repair_windows": [window, dict(window, stage="S7", cases=["TC-002"], tests=["ti_2"])]})
        gaps = report_facts.review_gaps(json.loads((task_root / "work" / "ledger.json").read_text(encoding="utf-8")))
        check_in("the rejected section, counted", "## Rejected by the code critic (1)", text)
        for line in report_facts.review_gap_lines(gaps):
            check_in("every line of the report's renderer stands in the packet: " + line[:40], line, text)
        check_in("the critic's problem, expectation and fix", '"it never reads the flag" — expected: "the flag reads cancelled" — to fix: "assert the flag"', text)
        check_in("the S7 runs have their own section and the triage wording", "## Runs left failing (1)", text)
        check_in("... with the run's row", "- `test_b` (TC-002) — the run failed: the locator is stale", text)
        for needle in ("test_defect", "waiver", "F-1"):
            check_not_in("no cause token, finding id or command name: " + needle, needle, text)
        check_in("an unreadable record is said", "Unknown — the record of the repair-limit answers cannot be read.",
                 packet({"rows": [], "repair_windows_problem": "the record of the repair-limit answers cannot be read"}))
        # F5: two copies of the ledger that differ do not crash the packet; it says the ledger cannot be read, and the delivery word
        # (read through the same guarded helper) is `no`
        (task_root / "ledger.json").write_text(json.dumps({"rows": [], "marker": "the other copy"}), encoding="utf-8")
        diverging = gate_brief.render_gate_b("TP1-9", task_root)
        check_in("F5: diverging ledger copies: the packet still renders and says the ledger cannot be read",
                 "Unknown — the ledger cannot be read.", diverging)
        check_eq("F5: ... and the delivery word is `no`", gate_brief.delivery_word(task_root), "no")
    finally:
        cleanup(root)


def test_no_record_changes_nothing() -> None:
    """Edges (i) and (ii): with no record, and with an empty list of exclusions, the gate A brief and the
    retro are byte-identical to each other and carry no word about sources left out."""
    def renders(record_text):
        base = story("qa-left-out-none-")
        task_root = base / "artifacts" / TASK
        if record_text is not None:
            (task_root / "work" / "source-exclusions.json").write_text(record_text, encoding="utf-8")
        data = retro_numbers.numbers(TASK, base, task_root)
        try:
            return {"gate": gate_brief.render(gate_brief.collect(TASK, task_root)),
                    "retro": retro_numbers.render(data),
                    "doc": retro_numbers.retro_document(data, json.loads(
                        (task_root / "pipeline.json").read_text(encoding="utf-8"))),
                    "facts": data["sources_left_out"], "brief": gate_brief.collect(TASK, task_root)["sources"]}
        finally:
            cleanup(base.parent)
    none = renders(None)
    empty = renders(json.dumps({"schema_version": 1, "exclusions": []}))
    for name in ("gate", "retro", "doc"):
        same = hashlib.sha256(none[name].encode("utf-8")).hexdigest() == hashlib.sha256(empty[name].encode("utf-8")).hexdigest()
        check(f"{name}: no record and an empty list render the same bytes", same)
        check_not_in(f"{name}: no word about a list", "left out", none[name])
        check_not_in(f"{name}: and none about a word taken back", "taken back", none[name])
    check_eq("the facts carry an empty list in both worlds", (none["facts"], empty["facts"]), ([], []))
    check_eq("the gate's sources carry empty keys in both", [
        (v["left_out_by_word"], v["unmatched_words"], v["taken_back"], v["left_out_unread"])
        for v in (none["brief"], empty["brief"])], [([], [], [], "")] * 2)
    check_eq("the section of the fixture is what it always was: the one override",
             section_lines(none["gate"]),
             ['- Context and grounding (S1) · video · your word: "go on without the video and the external links" · not recorded'])


def named_story(prefix: str, *, waivers=(), overrides=(), remarks=(), ids=("Q1", "Q2", "Q3", "Q4", "Q5", "Q10")) -> Path:
    """The fixture story with a register of `ids` and the person's recorded words as given."""
    base = story(prefix)
    task_root = base / "artifacts" / TASK
    (task_root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [
        {"id": qid, "question": f"What must happen for {qid}?", "severity": "minor", "owner_role": "po_ba",
         "readings": [{"reading": "one", "from": "description"}, {"reading": "two", "from": "description"}]}
        for qid in ids]}), encoding="utf-8")
    pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    pipeline.update(gate_waivers=list(waivers), stage_overrides=list(overrides), remarks=list(remarks))
    (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return base


def test_an_id_in_a_waiver_an_override_or_a_remark_is_named_never_answered() -> None:
    """t-155's fork (R12, FR-41): the three records that carry a person's words outside the gates give
    `named`, the same rule as the gate's own words. Before, such an id made the question vanish from the
    list - an answer nobody had recorded. Error direction: toward asking."""
    import question_register as QR
    bs = chr(92)
    base = named_story(
        "qa-named-records-",
        waivers=[{"gate": "A", "requirement": "Q1", "decision": "go on, the risk is mine", "at": "t"}],
        overrides=[{"stage": "S2", "match": "question threshold", "decision": "Q2 can wait, ask it later", "at": "t"}],
        remarks=[{"stage": "S2", "text": "About Q3: I do not know", "at": "t"},
                 {"stage": "S2", "text": "the ticket is http://x/browse/Q4 and see Q5.", "at": "t"},
                 {"stage": "S2", "text": "Q10 is fine", "at": "t"}])
    task_root = base / "artifacts" / TASK
    try:
        listed = {q["id"]: q for q in gate_brief.unanswered_questions(task_root)}
        check_eq("every question is still listed: none vanished as 'answered'", sorted(listed),
                 sorted(["Q1", "Q2", "Q3", "Q4", "Q5", "Q10"]))
        check_eq("a waiver's words name Q1: named, where = waiver",
                 (listed["Q1"]["status"], listed["Q1"]["where"]), ("named", "waiver"))
        check_eq("a stage override's decision names Q2: named, where = stage override",
                 (listed["Q2"]["status"], listed["Q2"]["where"]), ("named", "stage override"))
        check_eq("a kept remark names Q3: named, where = remark",
                 (listed["Q3"]["status"], listed["Q3"]["where"]), ("named", "remark"))
        check_eq("an id inside a URL is no token (today's rule): Q4 stays open", listed["Q4"].get("status"), "open")
        check_eq("an id followed by a full stop is no token (today's rule): Q5 stays open", listed["Q5"].get("status"), "open")
        check_eq("an exact token: Q10 in a remark names Q10 and not Q1 (Q1 is named by its own waiver)",
                 (listed["Q10"]["status"], listed["Q10"]["where"]), ("named", "remark"))
        check("and no question is ever `answered` by a mention", all(q.get("status") != "answered" for q in listed.values()))
        check_eq("the note says exactly what it was: named, no answer recorded",
                 listed["Q1"]["status_note"], "named in your waiver words; the factory recorded no answer")
        check_eq("an open question carries no note", listed["Q4"].get("status_note", ""), "")
        check_eq("FR-10: the gate A packet lists the same questions as the list",
                 [q.get("id") for q in gate_brief.collect(TASK, task_root)["open_questions"]], list(listed))
        check_in("the MR list carries the named note for a question named in a waiver",
                 "named in your waiver words; the factory recorded no answer", "\n".join(gate_brief.open_before_mr(task_root)))
        # a recorded answer still wins over a mention: the register says answered, so it is not listed
        shown = {q["id"]: q["row_hash"] for q in QR.load(task_root)["questions"]}
        QR.record(task_root, "Q1", "answered", "Q1: a", "gate A", "person", shown["Q1"], reading="a")
        check("an answered question that a waiver also names is not listed",
              "Q1" not in [q["id"] for q in gate_brief.unanswered_questions(task_root)])
        # the register's own `named` (gate words) and `with_designer` are kept, not overwritten by a record
        QR.record(task_root, "Q2", "with_designer", "Q2: sent to the designer", "conductor", "conductor", shown["Q2"])
        kept = {q["id"]: q for q in gate_brief.unanswered_questions(task_root)}
        check_eq("a with_designer question that a record also names keeps its status",
                 (kept["Q2"]["status"], kept["Q2"]["status_note"]), ("with_designer", "with the designer; no answer is recorded yet"))
    finally:
        cleanup(base.parent)
    # an exact token: the id of a longer question is no mention of a shorter one
    only_long = named_story("qa-named-exact-", remarks=[{"stage": "S2", "text": "Q10: a", "at": "t"}], ids=("Q1", "Q10"))
    try:
        got = {q["id"]: q.get("status") for q in gate_brief.unanswered_questions(only_long / "artifacts" / TASK)}
        check_eq("Q10 in a record does not name Q1", got, {"Q1": "open", "Q10": "named"})
    finally:
        cleanup(only_long.parent)
    # no register at all (a story older than the register): the row is listed, named by the waiver, never dropped
    old = named_story("qa-named-legacy-", waivers=[{"gate": "A", "requirement": "Q1", "decision": "ok", "at": "t"}], ids=("Q1",))
    try:
        (old / "artifacts" / TASK / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [
            {"question": "a bare question, no id", "severity": "minor", "owner_role": "po_ba"},
            {"ref": "Q1", "question": "an old-style ref", "severity": "minor", "owner_role": "po_ba"}]}), encoding="utf-8")
        got = gate_brief.unanswered_questions(old / "artifacts" / TASK)
        check_eq("legacy rows: both are listed", [q.get("ref") or q.get("question") for q in got],
                 ["a bare question, no id", "Q1"])
        check_eq("the row with a ref the waiver names is `named`, the bare one has no status",
                 [q.get("status") for q in got], [None, "named"])
    finally:
        cleanup(old.parent)
    # the boundary class the same matcher shares with question_register: a backslash before an id is a boundary
    check_eq("_mentions: a backslash before the id is a boundary (markdown escape)",
             (gate_brief._mentions(bs + "Q1", "Q1"), gate_brief._mentions(bs * 2 + "Q1", "Q1")), (True, True))
    check_eq("_mentions: negative control - `aQ1` and `Q10` are not Q1",
             (gate_brief._mentions("aQ1", "Q1"), gate_brief._mentions("Q10", "Q1")), (False, False))


def test_the_card_and_the_applier_read_one_patch_resolver() -> None:
    """t-227b C5: `gate_brief._patch_for` (the card) and `planning_contract.resolve_patch` (the S3 check and
    the applier) were two readers of ONE field, one merging `*` with the letter and one replacing. A card
    that shows a row the applier does not produce is a lie to the person (FR-10): both callers are pinned on
    the same spec, `{"*": {disposition}, "a": {reason}}`."""
    import planning_contract
    spec = {"*": {"disposition": "automate"}, "a": {"reason": "kept by hand"}, "not_needed": {"disposition": "skip"}}
    both = {"disposition": "automate", "reason": "kept by hand"}
    check_eq("the card merges `*` with the letter", gate_brief._patch_for(spec, "a"), both)
    check_eq("the resolver gives the same merged patch", planning_contract.resolve_patch(spec, "a"), both)
    check_eq("a letter with no key of its own gets `*`, in both",
             (gate_brief._patch_for(spec, "b"), planning_contract.resolve_patch(spec, "b")),
             ({"disposition": "automate"}, {"disposition": "automate"}))
    check_eq("`not needed` is its own key in both (the card spells it with a space, the plan with an underscore)",
             (gate_brief._patch_for(spec, gate_brief.NOT_NEEDED), planning_contract.resolve_patch(spec, "not_needed")),
             ({"disposition": "skip"}, {"disposition": "skip"}))
    bare = {"*": {"disposition": "automate"}}
    check_eq("`*` never covers `not needed`: the card shows nothing, the resolver says None",
             (gate_brief._patch_for(bare, gate_brief.NOT_NEEDED), planning_contract.resolve_patch(bare, "not_needed")),
             ({}, None))
    check_eq("an entry with nothing for the answer is an empty card effect",
             gate_brief._patch_for({"a": {"level": "api"}}, "b"), {})


def test_t256_o3_a_before_now_card_shows_both_behaviours_and_a_legacy_card_nothing_extra() -> None:
    """O3 (P20): a behaviour-claim question asks the person to choose between what the code did BEFORE the change
    and what it does NOW; the card printed neither, so the choice was blind."""
    import contract as C
    claim = {"id": "Q7", "question": "Which status code must PUT return for a body that breaks two checks at once?",
             "severity": "major", "owner_role": "po_ba",
             "source_says": [{"quote": "returns the same error codes as before", "where": "register R-19"}],
             "readings": C.claim_readings("400", "403"),
             "before": {"value": "400", "where": "the base revision, workflow.py:989"},
             "now": {"value": "403", "where": "the diff, workflow.py:158"}}
    lines = gate_brief.question_card(claim, 1)
    check_in("O3: the card shows what the behaviour was before the change, and where that was read",
             "  - before the change: 400 — the base revision, workflow.py:989", lines)
    check_in("O3: ...and what it is now, and where", "  - now: 403 — the diff, workflow.py:158", lines)
    check("O3: both come after what the source says and before the readings",
          lines.index("  - before the change: 400 — the base revision, workflow.py:989") < lines.index("  - now: 403 — the diff, workflow.py:158")
          < next(i for i, ln in enumerate(lines) if ln.startswith("  - a) ")) and
          next(i for i, ln in enumerate(lines) if "the source says" in ln) < lines.index("  - before the change: 400 — the base revision, workflow.py:989"))
    unknown = gate_brief.question_card(dict(claim, before={"value": "unknown", "where": "the base revision is not in the hunk"}), 1)
    check_in("O3: a before nobody could read is shown as `unknown` (FR-41), never left out",
             "  - before the change: unknown — the base revision is not in the hunk", unknown)
    legacy = {k: v for k, v in claim.items() if k not in ("before", "now")}
    plain = gate_brief.question_card(legacy, 1)
    check_eq("O3: a question written before the field prints nothing extra (and no `None`)",
             [ln for ln in plain if ln.startswith(("  - before the change:", "  - now:")) or "None" in ln], [])
    only_where = gate_brief.question_card(dict(claim, before={"value": "400"}), 1)
    check_in("O3: a side with no `where` prints its value alone", "  - before the change: 400", only_where)
    check_eq("O3: a side with no value prints nothing", [ln for ln in gate_brief.question_card(dict(claim, now={"where": "x"}), 1)
                                                         if ln.startswith("  - now")], [])


def test_t256_o6_the_packet_says_how_to_accept_a_case_as_blocked() -> None:
    """O6: the stand card offers `accept as blocked`; the packet shows the card's first 200 characters and the words
    to write live in the finding's fix, which it does not show - so one line of the packet says them."""
    import gate_preflight
    stand_card = {"id": "case_preconditions-1", "check": "case_preconditions", "class": gate_preflight.PERSON_DECIDES,
                  "message": "TP1-15045_TC_014: 2 of 4 partitions need a second user", "fix": ""}
    other = {"id": "vcs-1", "check": "vcs", "class": gate_preflight.PERSON_DECIDES, "message": "the tree is dirty", "fix": ""}

    def packet(findings) -> str:
        return gate_brief.render({"task": "TP1-15045", "case_id_example": "TP1-15045_TC_014",
                                  "rehearsal": {"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {}, "findings": findings}})
    word = ("- To accept a case as blocked on this stand, write `<full case id>: accept as blocked` on a line of its own, "
            "for example `TP1-15045_TC_014: accept as blocked`; S5 then reports exactly those as not executed.")
    check_in("O6: a packet with a stand card carries the one line, with a real case id as the example", word, packet([stand_card]))
    check_not_in("O6: a packet with no stand card does not", "accept as blocked", packet([other]))
    check_eq("O6: the line is the helper's, and drops the example when there is none",
             gate_brief.blocked_answer_line(), "- To accept a case as blocked on this stand, write `<full case id>: accept as blocked` "
             "on a line of its own; S5 then reports exactly those as not executed.")


def golden_packet_data(fits: bool) -> dict:
    """t-683 D8: one packet with EVERY section of `render` present. `fits=False` is the whole of it (the
    cap truncates it); `fits=True` trims the repeatable lines so that nothing is cut and the last section
    (the long documents) is printed."""
    left = [
        {"id": "a", "as_written": "proj1!1", "reason": "r " * 70, "origin": "person_before_run",
         "matched": True, "revoked": False, "revoked_words": ""},
        {"id": "b", "as_written": "proj2!2", "reason": "second", "origin": "factory_marker",
         "matched": True, "revoked": False, "revoked_words": ""}]
    data = {
        "task": "TP1-15045",
        "pyramid": {"total": 9, "by_level": {"api": 4, "e2e-ui": 3, "manual": 2},
                    "by_disposition": {"automate": 7, "manual-human": 2},
                    "by_level_disposition": {"api/automate": 4, "e2e-ui/automate": 3, "manual/manual-human": 2}},
        "pinned_cases": [f"TP1-15045_TC_{n:03d}" for n in range(1, 18)],
        "case_files": {"TP1-15045_TC_001": "work/test cases/TC_001.md"},
        "roll_call": {"total": 9, "unreviewed": [f"TS-{n}" for n in range(1, 11)]},
        "critic_verdict": "approve_with_concerns",
        "sizing": "**Size** - L, because it has 9 rows.",
        "case_id_example": "TP1-15045_TC_014",
        "rehearsal": {"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
                      "findings": [
                          {"id": "case_preconditions-1", "check": "case_preconditions", "class": "person_decides",
                           "message": "TP1-15045_TC_014: 2 of 4 partitions need a second user", "fix": ""},
                          {"id": "vcs-1", "check": "vcs", "class": "factory_defect", "message": "the tree is dirty", "fix": "w"}]},
        "open_questions": [
            {"id": "Q1", "severity": "major", "owner_role": "po_ba", "question": "Where must a removed node appear?",
             "shown_hash": "ab" * 32, "status_note": "asked twice",
             "source_says": [{"quote": "no layout meta", "where": "AC3"}],
             "before": {"value": "400", "where": "api.py:12"}, "now": {"value": "403"},
             "readings": [{"reading": "at the root", "from": "AC3", "if_chosen": "one case moves"},
                          {"reading": "nowhere", "from": "spec"}]},
            {"id": "Q2", "severity": "minor", "owner_role": "dev", "question": "Scope?", "readings_unnameable": True}],
        "question_status_unread": "the  file\nwas broken",
        "question_effects": {"Q1": {"a": [], "b": [], "not needed": []}},
        "question_effect_problems": ["effects  of\nQ9"],
        "stand_gap_cards": ["## Stand gaps (1)", "- card line one", "- card line two"],
        "adapted_lines": ["## What the factory adapted", "- adapted one"],
        "gate_waivers": [{"gate": "A", "requirement": "REQ-1", "decision": "ship it", "at": "2026-10-03T08:00:00+00:00"}],
        "stage_overrides": [{"stage": "S5", "match": "stand gap: RP-api", "decision": "go on", "at": "2026-10-03T08:00:00+00:00"}],
        "sources": {"accepted_gaps": [f"gap {n}" for n in range(1, 7)],
                    "left_out_by_word": left, "unmatched_words": [], "unchecked_words": [], "taken_back": [],
                    "left_out_unread": True, "unreviewed": [f"proj{n}!{n}" for n in range(1, 12)]},
        "unearned_automation": [f"TS-{n}" for n in range(1, 17)],
        "plan_gloss": {"TS-1": "login works"},
        "warnings": [f"warning  number {n} " + "x" * 200 for n in range(1, 7)],
        "judge": {"provider": "none-yet", "mode": "shadow", "decided": 2, "questions": 3, "cost_usd": 0.0123,
                  "errors": 1, "passes": [{"refusal": "r1", "judgment": "j1", "strength": 0.9, "stage": "S5"}]},
        "missing_inputs": ["work/b.json", "work/a.json", "work/a.json"],
        "documents": {"test plan": "work/test-plan.json", "cases": "work/test-cases"},
        "critic_path": "work/test-cases/workflows/critic-findings.md"}
    if fits:
        data["sources"] = dict(data["sources"], accepted_gaps=["gap 1"], left_out_by_word=left[:1])
        data["warnings"] = data["warnings"][:1]
        data["stage_overrides"] = []
        data["judge"] = dict(data["judge"], errors=0, passes=[])
        data["unearned_automation"] = data["unearned_automation"][:4]
        data["open_questions"] = data["open_questions"][:1]
    return data


def test_t683_d8_render_is_byte_for_byte_what_it_was() -> None:
    """t-683 D8 (I-pure): the golden `render(data)` is split against. Three packets: every section and it fits;
    every section and the cap cuts it; nothing at all. Captured on the tree BEFORE the split, so the split is a
    move and not a rewrite - and no person text changed with it (FR-6)."""
    cases = [f"TP1-15045_TC_{n:03d}" for n in range(2, 16)]
    expected = "\n".join([
        "# Gate A — TP1-15045",
        "",
        # GW1-11: the packet opens with the two documents the person approves (not four); the line is built from GATE_A_DOCUMENTS
        "**Approve: `understanding.md`, `test-plan.md`.** This brief is a summary of them, not a document to approve.",
        "",
        "**Plan** — 9 rows. Levels: api 4, e2e-ui 3, manual 2. Dispositions: automate 7, manual-human 2.",
        "Pyramid: api/automate 4, e2e-ui/automate 3, manual/manual-human 2.",
        "**Cases** — 17 pinned: [TP1-15045_TC_001](work/test%20cases/TC_001.md), " + ", ".join(cases) + "....",
        "**Critic** — verdict `approve_with_concerns`, roll-call 9 rows, 10 not reviewed semantically: "
        "TS-1, TS-2, TS-3, TS-4, TS-5, TS-6, TS-7, TS-8....",
        "**Size** - L, because it has 9 rows.",
        "",
        "## After your approval",
        "- [your call] TP1-15045_TC_014: 2 of 4 partitions need a second user",
        "- [factory owns this] the tree is dirty",
        # RH1-6 (A-AC7): the fixture's `case_preconditions` item has no line door, so the packet names it in one line of its own
        "- needs your word before your approval counts (1 open): [case_preconditions-1] (each is under "
        "\"Rehearsal of gate A\" below) — or answer `approve as is` to approve over all of them, each recorded with your words",
        "",
        "## Open questions (1)",
        "- Question status could not be read (the file was broken), so every question below is shown as it stands.",
        "- **Q1** [major, owner po_ba] Where must a removed node appear?",
        "  - asked twice.",
        "  - the source says: \"no layout meta\" — AC3",
        "  - before the change: 400 — api.py:12",
        "  - now: 403",
        "  - a) at the root (from AC3)",
        "    if chosen: one case moves",
        "    what changes if you choose a:",
        "    - nothing in the plan or the cases changes.",
        "  - b) nowhere (from spec)",
        "    what changes if you choose b:",
        "    - nothing in the plan or the cases changes.",
        "  - or your own wording — the readings are what the sources say, not a closed list of answers.",
        "  - Answer: `Q1: a`, `Q1: b` or `Q1: not needed`",       # GW1-32: the last line of the card, with the card's own id
        "  <!-- card Q1 " + "ab" * 32 + " -->",
        "- Not read, so not shown above: effects of Q9.",
        "",
        "## How to answer",
        "Write each answer on its own line, in one of these forms:",
        "- `<question id>: <letter>` - the reading you choose, for example `Q1: a`",
        "- `<question id>: not needed`",
        "- `<full case id>: manual` - keep that case checked by hand",
        "- `<full case id>: automate` - have that case checked by an automated test",
        # GW1-32: one list - the open item's own form (the as-is word) and the blocked line now stand here, not under "After your approval"
        "- `approve as is` - alone on the first line: approves over every open item, each recorded with your words",
        "- To accept a case as blocked on this stand, write `<full case id>: accept as blocked` on a line of its own, "
        "for example `TP1-15045_TC_014: accept as blocked`; S5 then reports exactly those as not executed.",
        "A full case id is the whole id, as written in this packet, for example `TP1-15045_TC_014`.",
        "Anything else, in your own words, goes to the assistant running this story, who turns it into one of these or asks you back; "
        "only the forms above are read by code.",
        "",
        "## Stand gaps (1)",
        "- card line one",
        "- card line two",
        "",
        "## What the factory adapted",
        "- adapted one",
        "",
        "## Already decided by you — repeated, not re-asked",
        "- gate A · a check the factory ran · your word: \"ship it\" · 2026-10-03",
        "- accepted source gap: gap 1",
        "- left out before the run by your word: proj1!1 — \"" + "r " * 58 + "r...\"",
        "- the record of the sources you left out before the run could not be read, so this brief cannot say what it "
        "names; that is a defect of the factory's own record, not something you have to repair",
        "",
        "## Sources found after the S1 review — new to you",
        "- proj1!1, proj2!2, proj3!3, proj4!4, proj5!5, proj6!6, proj7!7, proj8!8, proj9!9, proj10!10...",
        "",
        "## e2e rows without a highest-risk field (4), for your information",
        "- TS-1 (login works), TS-2, TS-3, TS-4: `automate` at e2e-ui, as written or after an answer to a question, while `impact`, `likelihood` and "
        "`verification_depth` do not say highest risk. The strategist judged them so; this is no question to you, and "
        "a critic of the plan reads the level. Say so in your answer if you want them changed.",
        "",
        "## Warnings the factory is carrying",
        "- warning number 1 " + "x" * 163,
        "",
        "## Judge",
        "- `none-yet` in mode `shadow`: 2 of 3 decided, $0.0123. Answers were journalled and nobody acted on them.",
        "- No block of the factory's own was passed by the judge.",
        "",
        "## Not readable by this brief — say so rather than guess",
        "- work/a.json, work/b.json",
        "",
        "## The long documents (paths, not summaries)",
        "- cases: work/test-cases",
        "- test plan: work/test-plan.json",
        "- critic findings: work/test-cases/workflows/critic-findings.md",
        ""])
    check_eq("D8: the packet with every section and no cut, byte for byte", gate_brief.render(golden_packet_data(True)), expected)
    cut = gate_brief.render(golden_packet_data(False))
    check_eq("D8: the same packet, whole, is cut at the cap - its length", len(cut.splitlines()), 83)   # GW1-11: 77 + the approval line and its blank line; GW1-32: + the card's Answer lines and the open-item form (the cap grows by them)
    check_eq("D8: ... and says so on its last line", cut.splitlines()[-1],
             "_(brief truncated at 83 lines; the documents above carry the rest)_")
    check_eq("D8: ... and the whole text is the one captured before the split (sha256)",
             hashlib.sha256(cut.encode("utf-8")).hexdigest(), "3830de604286558041da236080335ac3e48945c16cc1c664aeae1397a7235dcf")   # GM2-2 O7 rewrite: recomputed through gate_brief.render, was 22f58b7a...; t-550 F9: "as written or after an answer"; was 31355e59... GW1-29: the e2e section text for information (was 1f21fa11...); GW1-11: + the approval line (was 05adcfc5...); RH1-6: + the A-AC7 line (t-1455: names every open item, count stated); GW1-32: one answer list (was a8421a13...)
    # GW1-32: with no question at all, the open item still has its form, and the cap cuts the tail, never the answer block
    no_question = golden_packet_data(False)
    no_question["open_questions"] = []
    cut_bare = gate_brief.render(no_question).splitlines()
    check_in("GW1-32: no question, a cut packet: the answer block stands", "## How to answer", cut_bare)
    check_in("GW1-32: ...with the open item's form", "- `approve as is` - alone on the first line: approves over every open item, each recorded with your words", cut_bare)
    check_eq("GW1-32: ...and the cut is real (the block is above what was cut)",
             (cut_bare[-1].startswith("_(brief truncated at"), cut_bare.index("## How to answer") < len(cut_bare) - 1), (True, True))
    check_eq("D8: an empty packet reads as it did", gate_brief.render({}),
             "# Gate A — ?\n\n**Approve: `understanding.md`, `test-plan.md`.** This brief is a summary of them, "
             "not a document to approve.\n\n**Plan** — 0 rows. Levels: none. Dispositions: none.\n**Cases** — 0 pinned (none).\n"
             "**Critic** — verdict `not recorded`, roll-call 0 rows, every row reviewed.\n\n## After your approval\n"
             "- the next stage can start: yes.\n")


def test_t279_k_hash_the_card_carries_the_row_hash_and_the_applier_stores_that_one() -> None:
    """t-271 F5 / t-279 K-HASH. The gate A card is rendered from a register row with fingerprint h and says so in a
    hidden comment; the applier records the person's answer against THAT h, not against the row as it stands when
    the answer arrives. The row edited between the card and the answer: a re-rendered card carries a new h', and
    the answer given to the OLD card reads `changed_since_answer` - the claim stays unconfirmed."""
    import contract as C
    import planning_contract as PC
    import question_register as QR
    base = named_story("qa-khash-", ids=("Q1", "Q2"))
    task_root = base / "artifacts" / TASK
    readiness = task_root / "work" / "requirements-readiness.json"
    try:
        # HF4-7 (N7-2): a before/now question says which reading is the behaviour now (`claim`); one that does not
        # confirms nothing, so the fixture's two readings are marked before any hash is taken
        marked = json.loads(readiness.read_text(encoding="utf-8"))
        for q in marked["open_questions"]:
            q["readings"][0]["claim"], q["readings"][1]["claim"] = C.CLAIM_KEYS
        readiness.write_text(json.dumps(marked), encoding="utf-8")

        def card_text() -> str:
            return gate_brief.render(gate_brief.collect(TASK, task_root))

        def row_hash(qid: str) -> str:
            return {q["id"]: q for q in QR.load(task_root)["questions"]}[qid]["row_hash"]
        h1, h2 = row_hash("Q1"), row_hash("Q2")
        first = card_text()
        check_eq("K-HASH: the card of each question carries the fingerprint of the row it was rendered from",
                 gate_brief.shown_hashes(first), {"Q1": h1, "Q2": h2})
        check_in("K-HASH: as a hidden comment line", f"<!-- card Q1 {h1} -->", first)
        check_eq("K-HASH: the card JSON (the question item) carries it as a field too",
                 {q["id"]: q["shown_hash"] for q in gate_brief.collect(TASK, task_root)["open_questions"]}, {"Q1": h1, "Q2": h2})
        check_eq("K-HASH control: a card with no fingerprint (a row the register cannot place) prints no marker and shown_hashes reads none",
                 (gate_brief.card_marker("Q1", ""), gate_brief.card_marker("Q1", "abc"), gate_brief.card_marker("", h1),
                  gate_brief.shown_hashes("no marker here\n  <!-- card Q1 notahash -->")), ("", "", "", {}))
        # the row changes after the card was shown (the readiness file is edited: another wording of Q1)
        doc = json.loads(readiness.read_text(encoding="utf-8"))
        doc["open_questions"][0]["question"] = "What must happen for Q1 - reworded by the requirements tester?"
        readiness.write_text(json.dumps(doc), encoding="utf-8")
        check_eq("K-HASH: the row now has another fingerprint (the apply-time hash differs from the card's)", row_hash("Q1") != h1, True)
        second = card_text()
        check_eq("K-HASH: the re-rendered card carries the NEW fingerprint, the other card keeps its own",
                 gate_brief.shown_hashes(second), {"Q1": row_hash("Q1"), "Q2": h2})
        # the person answers the OLD card
        PC.apply_gate_answers(task_root, "Q1: a\nQ2: a", shown=gate_brief.shown_hashes(first))
        view = {q["id"]: q for q in QR.load(task_root)["questions"]}
        check_eq("K-HASH: the answer to the old card is stored with the card's hash h, not the apply-time one",
                 (view["Q1"]["record_row_hash"], view["Q1"]["row_hash"] != h1), (h1, True))
        check_eq("K-HASH: so the answered row reads `changed_since_answer` and the claim is NOT confirmed",
                 (view["Q1"]["status"], view["Q1"]["changed_since_answer"], C.claim_confirmed(view["Q1"])), ("answered", True, False))
        check_eq("K-HASH: the row that did not change reads unchanged and confirmed",
                 (view["Q2"]["changed_since_answer"], C.claim_confirmed(view["Q2"])), (False, True))
    finally:
        cleanup(base.parent)
    # control, both worlds: a caller that holds no shown packet (the driver today) records the row as it stands
    base = named_story("qa-khash-old-", ids=("Q1",))
    task_root = base / "artifacts" / TASK
    try:
        PC.apply_gate_answers(task_root, "Q1: a")
        view = {q["id"]: q for q in QR.load(task_root)["questions"]}
        check_eq("K-HASH control: with no `shown` the apply-time hash is stored, as before (nothing detected, nothing crashed)",
                 (view["Q1"]["status"], view["Q1"]["changed_since_answer"], view["Q1"]["record_row_hash"] == view["Q1"]["row_hash"]),
                 ("answered", False, True))
    finally:
        cleanup(base.parent)


def test_t279_k_fence_a_decision_in_a_code_block_is_said_not_read() -> None:
    """t-269 F6 on the applier: a token inside a fenced block (or after a fence nobody closed) applies nothing and
    is printed once, by the same line the register's `fence_notices` writes - for a question token and for
    `accept as blocked` alike, never twice."""
    import planning_contract as PC
    import question_register as QR
    base = named_story("qa-kfence-", ids=("Q1", "Q2"))
    task_root = base / "artifacts" / TASK
    try:
        words = "Q1: a\n```\nQ2: b\n```\n"
        lines = PC.apply_gate_answers(task_root, words)
        check_in("K-FENCE: the fenced decision is said, with the `where` prefix and the line", "gate A: a decision inside a code block is not read: Q2: b", lines)
        check_eq("K-FENCE: ONE line for it", len([ln for ln in lines if "inside a code block" in ln]), 1)
        view = {q["id"]: q for q in QR.load(task_root)["questions"]}
        check_eq("K-FENCE: the question outside the fence is answered, the one inside is not",
                 (view["Q1"]["status"], view["Q2"]["status"]), ("answered", "open"))
        lines = PC.apply_gate_answers(task_root, "```\nQ2: a\nTC_001: accept as blocked\n")
        check_eq("K-FENCE: a fence nobody closed swallows what follows - said once per line, the case token included",
                 [ln for ln in lines if "inside a code block" in ln],
                 ["gate A: a decision inside a code block is not read: Q2: a",
                  "gate A: a decision inside a code block is not read: TC_001: accept as blocked"])
        lines = PC.apply_gate_answers(task_root, "Q2: a\nsome words, no fence")
        check_eq("K-FENCE control: words with no fence print no such line", [ln for ln in lines if "code block" in ln], [])
    finally:
        cleanup(base.parent)


def test_t363_b1_the_driver_gate_text_lists_waivers_in_words() -> None:
    """t-363 B1: `Driver.gate_text` puts the blocks the person passed by their word into the packet as one line each, in
    words - the section used to be `waiver.py`'s machine lines, with the script name, a flag and a timestamp in them (the
    gate packet obeys human-questions.md: no script name, no flag)."""
    import human_text
    import story_run_common as SRC
    task = "QA-9"
    root, task_root, env = SRC.seed(task)
    try:
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "executor unavailable: pytest",
                                        "decision": "go on, I will run them myself", "at": "2026-10-03T05:41:12+00:00",
                                        "by": "human"}]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        driver = SRC.driver_for(root, env, task)
        text = driver.gate_text("A")
        heading = "## Blocks passed by your word so far\n"
        check_in("B1 gate_text: the section is in the gate A packet (control: the heading is found)", heading, text)
        section = text.split(heading, 1)[1].split("\n## ", 1)[0].split("\nApproval is its own word", 1)[0].strip()
        check_eq("B1 gate_text: the section is one line in words", section,
                 'Automation (S5) · a test runner that could not be started on this stand · your word: "go on, I will run them myself" · 2026-10-03')
        for token in ("waiver.py", "--", "exit ", "T05:"):
            check_not_in(f"B1 gate_text: no `{token}` in the waivers section", token, section)
        check_eq("B1 gate_text: the section obeys the text rules", human_text.problems(section, kind="report"), [])
        pipeline["stage_overrides"] = []
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        check_not_in("B1 gate_text: with no waivers there is no section", "Blocks passed by your word", driver.gate_text("A"))
        (task_root / "pipeline.json").unlink()
        broken = driver.gate_text("A")
        check_not_in("B1 gate_text: a pipeline.json nobody can read is not printed as a section (the sentence is for whoever ran the command)",
                     "no readable pipeline.json", broken)
    finally:
        cleanup(root)


def test_t370_b_a_gate_brief_that_failed_shows_a_person_no_script_and_no_exit_code() -> None:
    """`Driver.gate_text` used to print `gate_brief.py exit 2:` and the brief's raw output when the brief failed. The person
    reads that the brief could not be built (and the brief's own first line when it names no script); the code and the
    output go to the driver log."""
    import contextlib
    import io
    import human_text
    import story_run_common as SRC
    root, task_root, env = SRC.seed("QA-9")
    try:
        driver = SRC.driver_for(root, env, "QA-9")
        real = driver.py

        def failing(output: str):
            return lambda script, *a, **k: (2, output) if script == "gate_brief.py" else real(script, *a, **k)
        for label, output, shown in (
                ("a plain first line", "the case files could not be read\nmore detail below", "The gate brief could not be built (the case files could not be read)."),
                ("a first line that names a script and a code", "gate_brief.py: exit 2 - boom\nTraceback (most recent call last)", "The gate brief could not be built."),
                ("no output at all", "", "The gate brief could not be built.")):
            driver.py = failing(output)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                text = driver.gate_text("A")
            driver.py = real
            check_in(f"t-370 b ({label}): the person reads the sentence", shown, text)
            check_not_in(f"t-370 b ({label}): no script name in the packet's brief part", "gate_brief.py", text)
            check_eq(f"t-370 b ({label}): no `exit <n>` in the packet", [p["rule"] for p in human_text.problems(text, kind="report") if p["rule"] == "exit_code"], [])
            check_in(f"t-370 b ({label}): the code goes to the driver log", "(exit 2)", printed.getvalue())
        driver.py = lambda script, *a, **k: (0, "THE BRIEF OF GATE A") if script == "gate_brief.py" else real(script, *a, **k)
        ok_text = driver.gate_text("A")
        driver.py = real
        check_in("control: a brief that built is shown whole", "THE BRIEF OF GATE A", ok_text)
        check_not_in("control: ...with no such sentence", "could not be built", ok_text)
    finally:
        cleanup(root)


def test_t364_one_list_of_stand_gaps_per_gate_is_what_the_card_shows_and_the_answer_reads() -> None:
    """`gate_brief.stand_gap_gaps(task_root, gate, rehearsed)` - the list gate A's rehearsal and gate B's manifest give - is
    the ONE list a packet's card is built from and the person's line is read against (t-364: the driver reads gate A with it)."""
    import stand_gaps
    base = story("qa-gate-brief-t364-")
    try:
        task_root = base / "artifacts" / "TP1-15045"
        remedy = {"kind": "flag", "where": "app/config.yaml:3", "change": "turn the flag on"}
        pc = {"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are enabled", "partitions": [], "remedy": remedy,
              "check": {"http": {"path": "/v1/config", "status": 200, "json_path": "features.a", "equals": True}}}
        (task_root / "work" / "test-cases" / "workflows" / "TC-007.md").write_text(
            f"---\nid: TC-007\ntitle: a node keeps its state\nrequirements: R-3\npreconditions: {json.dumps([pc])}\n---\n\n## When\n1. call it\n",
            encoding="utf-8")
        links = json.loads((task_root / "state" / "story-case-links.json").read_text(encoding="utf-8"))
        links["links"] = [{"case_id": "TC-007", "version": "cv_x", "path": "work/test-cases/workflows/TC-007.md"}]
        (task_root / "state" / "story-case-links.json").write_text(json.dumps(links), encoding="utf-8")
        rehearsal = {"stand_gaps": stand_gaps.declared_preconditions(task_root)}
        gaps_a =gate_brief.stand_gap_gaps(task_root, "A", rehearsal)
        check_eq("gate A: the rehearsal's rows, at stage S5, named by the gap id and the case", [(g["id"], g["case_id"], g["stage"]) for g in gaps_a],
                 [("PC-1", "TC-007", "S5")])
        (task_root / "work" / "automation-manifest.json").write_text(json.dumps({"unresolved": [
            {"case": "workflows/TC-007", "reason": "blocked_by_env", "detail": "off", "remedy": remedy}]}), encoding="utf-8")
        gaps_b = gate_brief.stand_gap_gaps(task_root, "B")
        check_eq("gate B: the manifest's rows, at stage S9, named by the case key", [(g["id"], g["case_id"], g["stage"]) for g in gaps_b],
                 [("workflows/TC-007", "TC-007", "S9")])
        check_eq("gate B: exactly what the t-342 reader used (`gate_b_gaps`)", [g["id"] for g in gaps_b], [g["id"] for g in gate_brief.gate_b_gaps(task_root)])
        for gate, gaps in (("A", gaps_a), ("B", gaps_b)):
            found = gate_brief.read_stand_gap_answers("TC-007: accept", gaps)
            check_eq(f"gate {gate}: the same line reads against the same list as the card shows",
                     [(e["gap"]["id"], e["option"]) for e in found["read"]], [(gaps[0]["id"], "accept")])
            cards = "\n".join(gate_brief.stand_gap_cards(task_root, gate, rehearsal if gate == "A" else None)[0])
            check_in(f"gate {gate}: and the card of that list is headed by the id the line starts with", "Stand gap: [TC-007](", cards)
        check_eq("an unreadable rehearsal gives an empty packet block, never a crash",
                 gate_brief.stand_gap_cards(task_root / "nowhere", "A", {"stand_gaps": "not rows"}), ([], []))
    finally:
        cleanup(base.parent)


# --- B-220 part 2, item 2: the gate A reporter card's answers ------------------------------------------------------------------
# `command <the person's own line>` / `myself` / `run` / `accept`, and `change` only where the card has a cure that is ONE change of
# its command. The reader is `read_stand_gap_answers`; the two legs of a `command` answer are `probe_reporter_command` and
# `apply_reporter_command` (the same sealed-proposal path as the onboarding: probe, S5's contract, one "Do it?", applied on a yes).

CARD_WHERE = "qa-factory/config.json:profiles[web].commands.one_test"
NO_CURE = ["theirs", "handed", "accept"]
WITH_CURE = ["apply", "theirs", "handed", "accept"]
LIVE = ["command", "theirs", "handed", "accept"]


def reporter_gap(offers: list, gap_id: str = "RP-web", case: str = "TC-001", profile: str = "web") -> dict:
    return {"id": gap_id, "gate": "A", "stage": "S5", "case": case, "case_id": case, "requirement": "the report is read", "partitions": [],
            "the_test": "reads the report", "missing": "reporter: web writes no junit-xml report the factory can read",
            "remedy": {"kind": "reporter", "where": CARD_WHERE, "change": "name the flag that writes a JUnit report", "restart": "",
                       "profile": profile, "offers": offers}, "reason": "precondition", "owner": "", "source": "case preconditions",
            "state": "unmet", "task": "TP2-2553"}


def precondition_gap(gap_id: str = "PC-1", case: str = "TC-002") -> dict:
    return {"id": gap_id, "gate": "A", "stage": "S5", "case": case, "case_id": case, "requirement": "the flag is on", "partitions": [],
            "the_test": "needs a flag", "missing": "feature flag: on", "remedy": {"kind": "flag", "where": "app/config.yaml:3", "change": "turn it on"},
            "reason": "precondition", "owner": "", "source": "case preconditions", "state": "unmet", "task": "TP2-2553"}


def read_of(words: str, gaps: list) -> tuple:
    found = gate_brief.read_stand_gap_answers(words, gaps)
    return ([(e["gap"]["id"], e["option"]) for e in found["read"]], [(e["gap"]["id"], e["arg"]) for e in found["commands"]],
            [u["line"] for u in found["unread"]], found)


def test_b220_p2_the_reporter_card_takes_its_own_words_and_change_only_with_a_cure() -> None:
    gap = reporter_gap(NO_CURE)
    read, commands, unread, found = read_of("TC-001: myself", [gap])
    check_eq("`myself` on a reporter card is the `theirs` answer, as everywhere", (read, commands, unread), ([("RP-web", "theirs")], [], []))
    check_eq("`run` is still one of its words (not in the spec's list, so not changed)", read_of("TC-001: run", [gap])[0], [("RP-web", "handed")])
    check_eq("`accept` is read", read_of("TC-001: accept", [gap])[0], [("RP-web", "accept")])
    read, commands, unread, found = read_of("TC-001: change", [gap])
    check_eq("F12: `change` on a reporter card with NO cure is NOT read (it used to be recorded as a waiver that closed the card)",
             (read, commands), ([], []))
    check_in("F12: it is unread, the refusal says what is wrong", "no change the factory can make", found["unread"][0]["why"])
    check_in("F12 (FR-1): and names the words that DO apply", "the words that apply here are: `myself`, `run`, `accept`", found["unread"][0]["why"])
    check_not_in("F12: `change` is not among them", "`change`,", found["unread"][0]["why"].split("apply here are:")[1])
    for synonym in ("fix it", "apply", "you change it"):
        check_eq(f"F12: the synonym `{synonym}` is refused the same way", read_of(f"TC-001: {synonym}", [gap])[0], [])
    check_eq("positive control: with a cure that is one change of the command, `change` IS read",
             read_of("TC-001: change", [reporter_gap(WITH_CURE)])[0], [("RP-web", "apply")])
    # the card that carries no `offers` keeps the rule it had: `change` only with an exact change on the card
    check_eq("control: a precondition card with an exact change still reads `change`", read_of("TC-002: change", [precondition_gap()])[0],
             [("PC-1", "apply")])
    nothing = dict(precondition_gap(), remedy={})
    check_in("control: and with none it is unread, in the old words", "offers no exact change", read_of("TC-002: change", [nothing])[3]["unread"][0]["why"])


def test_b220_p2_the_command_line_is_read_whole_and_never_as_a_waiver() -> None:
    gap = reporter_gap(LIVE)
    line = "TC-001: command python -m pytest --junitxml={report_path} -k \"a  b\" <test-id>"
    read, commands, unread, found = read_of(line, [gap])
    check_eq("the line is a COMMAND row, and `read` (the rows a driver records as waivers) stays empty",
             (read, unread, [c[0] for c in commands]), ([], [], ["RP-web"]))
    check_eq("the value is the rest of the line: case kept, inner spacing kept", commands[0][1],
             "python -m pytest --junitxml={report_path} -k \"a  b\" <test-id>")
    row = found["commands"][0]
    check_eq("the row carries the card, the word, the person's line and what it replaces", (row["gap"]["id"], row["option"], row["word"], row["replaced"]),
             ("RP-web", "command", "command", []))
    check_eq("one pair of backquotes round the whole value is peeled", read_of("TC-001: command `poetry run pytest -x`", [gap])[1], [("RP-web", "poetry run pytest -x")])
    check_eq("case is kept: `Poetry` stays", read_of("TC-001: COMMAND Poetry run pytest", [gap])[1], [("RP-web", "Poetry run pytest")])
    check_eq("a bullet in front is forgiven, as for every word", read_of("- TC-001: command pytest -x", [gap])[1], [("RP-web", "pytest -x")])
    check_eq("a card that does NOT offer `command` (the form is not live, or it is another card): unread, with the words that apply",
             (read_of("TC-001: command pytest", [reporter_gap(NO_CURE)])[0:2], "is not an answer this card takes" in read_of("TC-001: command pytest", [reporter_gap(NO_CURE)])[3]["unread"][0]["why"]),
             (([], []), True))
    other = read_of("TC-002: command pytest", [precondition_gap()])
    check_eq("`command` on a precondition card is unread too (never a waiver)", (other[0], other[1], len(other[2])), ([], [], 1))


def test_b220_p2_every_edge_of_the_command_line_is_unread_in_words_and_writes_nothing() -> None:
    gap = reporter_gap(LIVE)
    rows = [("an empty value", "TC-001: command", "needs the command after it"),
            ("an empty value with spaces", "TC-001: command   ", "needs the command after it"),
            ("a question", "TC-001: command what do you mean?", "a question is never an answer"),
            ("a question inside the value", "TC-001: command pytest -k a?", "a question is never an answer"),
            ("a trailing backslash", "TC-001: command pytest \\", "goes on in the next line"),
            ("a trailing caret", "TC-001: command pytest ^", "goes on in the next line"),
            ("an open backquote", "TC-001: command pytest `", "goes on in the next line"),
            ("an unbalanced quote", "TC-001: command pytest -k \"a", "cannot be split into words"),
            ("a value that is an answer of its own", "TC-001: command accept", "two answers"),
            ("a value that is another answer's synonym", "TC-001: command myself", "two answers"),
            ("two words in one answer", "TC-001: myself accept", "not one of the answers")]
    for label, text, why in rows:
        read, commands, unread, found = read_of(text, [gap])
        check_eq(f"{label}: nothing is read", (read, commands), ([], []))
        check_eq(f"{label}: and it is unread, never dropped", len(unread), 1)
        check_in(f"{label}: the reason is in words", why, found["unread"][0]["why"])
    check_eq("a word nobody offers is unread", read_of("TC-001: sudo", [gap])[2], ["TC-001: sudo"])
    check_eq("a word for a card that is not in this gate is unread (`command`)", read_of("TC-009: command pytest", [gap])[2], ["TC-009: command pytest"])
    check_in("and says the id is no stand gap of this gate", "not a stand gap of this gate", read_of("TC-009: command pytest", [gap])[3]["unread"][0]["why"])
    check_eq("a word for a card that is not in this gate is unread (`myself`)", read_of("TC-009: myself", [gap])[2], ["TC-009: myself"])
    check_eq("a line that is not the form at all stays in the person's words: neither read nor unread",
             read_of("TC-001:\nTC-001 command pytest\nplease run it for me", [gap])[0:3], ([], [], []))
    # the limit this form introduces: 1000 characters, AT and BEYOND
    at, beyond = "p" + "a" * 999, "p" + "a" * 1000
    check_eq("AT the limit: 1000 characters are read", read_of(f"TC-001: command {at}", [gap])[1], [("RP-web", at)])
    check_eq("BEYOND it: 1001 are not", (read_of(f"TC-001: command {beyond}", [gap])[1], len(read_of(f"TC-001: command {beyond}", [gap])[2])), ([], 1))
    check_in("BEYOND it, the reason says the limit", "longer than 1000", read_of(f"TC-001: command {beyond}", [gap])[3]["unread"][0]["why"])
    # a command in a code fence is not an answer: it stays in the person's words
    fenced = "```\nTC-001: command pytest -x\n```"
    check_eq("a `command` line inside a code fence is not read, and not called unreadable", read_of(fenced, [gap])[0:3], ([], [], []))
    check_eq("control: the same line outside a fence is read", read_of("TC-001: command pytest -x", [gap])[1], [("RP-web", "pytest -x")])
    check_eq("a word line in a fence is read as it always was", read_of("```\nTC-001: accept\n```", [gap])[0], [("RP-web", "accept")])
    # the person's LAST line for a card decides
    last = gate_brief.read_stand_gap_answers("TC-001: myself\nTC-001: command pytest -x", [gap])
    check_eq("a later `command` replaces an earlier word: one command row, the earlier line kept in `replaced`",
             ([e["arg"] for e in last["commands"]], last["commands"][0]["replaced"], last["read"]), (["pytest -x"], ["TC-001: myself"], []))
    broken = gate_brief.read_stand_gap_answers("TC-001: command pytest -x\nTC-001: command", [gap])
    check_eq("a readable line followed by an unreadable one: the person's last word is unread, both go to the conductor",
             (broken["commands"], len(broken["unread"])), ([], 2))
    # a damaged or missing list of answers reads less, never more
    original = gate_brief.probe_answers
    gate_brief.probe_answers = lambda: {"live": True, "command": None, "reporter_accept": "", "problem": "damaged"}
    try:
        damaged = gate_brief.read_stand_gap_answers("TC-001: command pytest -x", [gap])
        check_eq("a list with no usable `command` row: the line is unread, nothing crashes", (damaged["commands"], len(damaged["unread"])), ([], 1))
    finally:
        gate_brief.probe_answers = original


def test_t409_h4_an_unknown_word_names_the_words_that_apply_to_that_card() -> None:
    reporter = reporter_gap(NO_CURE)
    for label, text in (("an unknown word", "TC-001: sudo"), ("two words in one answer", "TC-001: myself accept"),
                        ("a word in another script", "TC-001: ναι")):
        why = read_of(text, [reporter])[3]["unread"][0]["why"]
        check_in(f"H4: {label} on a reporter card: the refusal says the word is not one of the card's answers", "not one of the answers the card offers", why)
        check_in(f"H4: {label}: and names the words THAT card takes", "the words that apply here are: `myself`, `run`, `accept`", why)
        check_not_in(f"H4: {label}: and not `change`, which the card does not take", "`change`", why)
    plain = read_of("PC-1: sudo", [dict(precondition_gap(), case="PC-1", case_id="PC-1")])[3]["unread"][0]["why"]
    check_in("H4: a card with NO `offers` names the four standing words", "the words that apply here are: `change`, `myself`, `run`, `accept`", plain)
    live = read_of("TC-001: sudo", [reporter_gap(LIVE)])[3]["unread"][0]["why"]
    check_in("H4: a card that offers `command` names it first", "the words that apply here are: `command`, `myself`, `run`, `accept`", live)
    check_eq("H4 (the old reason still opens the sentence, the relay reads it)", read_of("TC-001: sudo", [reporter])[3]["unread"][0]["why"].startswith(
        "the word is not one of the answers the card offers"), True)


def test_t409_h3_the_conductor_relay_and_the_phase_say_the_words_per_card() -> None:
    """The relay (`story_run.take_stand_gap_answers`) builds its per-gap lines with `gate_brief.relay_card_line`, and the s4 phase text
    says the same thing: the options are PER CARD, from the same `offered_options` the card and the reader use."""
    reporter, other = reporter_gap(NO_CURE), precondition_gap()
    line = gate_brief.relay_card_line(reporter, "TC-001", "S5")
    check_in("H3: a reporter card's line names the block and the stage as before", "- TC-001: block `stand gap: RP-web`, stage S5; ", line)
    check_in("H3: and says it takes ONLY its options, with their words", "takes ONLY `theirs`, `handed`, `accept` (the words: `myself`, `run`, `accept`)", line)
    check_in("H3: and that another word is not recorded and the person is told the words that apply", "any other word is NOT recorded - tell the person the words that apply to this card", line)
    check_eq("H3: `change` (option `apply`) is not on a reporter card's line", ("`apply`" in line, "`change`" in line), (False, False))
    packet = "\n".join([gate_brief.relay_card_line(reporter, "TC-001", "S5"), gate_brief.relay_card_line(other, "TC-002", "S5")])
    check_in("H3: a packet with both kinds: the card that shows an exact change takes every option (so `change`)", "- TC-002: block `stand gap: PC-1`, stage S5; takes every option above", packet)
    check_eq("H3: and the reporter card's line, in the SAME packet, does not (the note about `change` is per card)",
             ["takes ONLY" in row for row in packet.splitlines()], [True, False])
    check_eq("H3: a gap with no `offers` field keeps all four options", (gate_brief.offered_options(other), gate_brief.relay_card_line(dict(other, remedy={}), "X", "S9").endswith("takes every option above")),
             (list(gate_brief.C.STAND_GAP_OPTIONS), True))
    check_eq("H3: a live card lists `command` and `change` in its line", gate_brief.relay_card_line(reporter_gap(["command", "apply", "theirs", "handed", "accept"]), "TC-001", "S5")
             .split("(the words:")[0].split("takes ONLY ")[1], "`command`, `apply`, `theirs`, `handed`, `accept` ")
    phase = (SCRIPTS.parent / "skills" / "qa-story" / "phases" / "s4.md").read_text(encoding="utf-8")
    check_in("H3: the s4 phase says the words are per card and names the reporter card's three", "takes `myself`, `run` and `accept` only (never `change`", phase)
    check_in("H3: and that a word the card does not list is not recorded, the person told the words that apply", "a word the card does not list is not recorded - tell the person the words that apply to", phase)
    # the three checks of the driver's relay note (`Driver.take_stand_gap_answers`) were a source pin of one member: deleted by TD-11 phase 0 (F3)


def test_t667_d17_the_relay_note_reads_one_context_and_the_stage_default_reaches_the_lines() -> None:
    """t-667 D17: `Driver._relay_note(out, found, ctx)` - the answer's fixed facts travel as ONE `RelayCtx(forms, gaps, rehearsal, gate,
    default_stage)`. INVARIANT: the stage a gap or a rehearsal door has none of is the context's `default_stage`; the form id of a
    gap is the context's `forms` entry; the gate letter is the context's; nothing recorded and nothing unread is no note at all."""
    import contextlib
    import io
    import story_run
    bare = dict(precondition_gap(), stage="")
    rehearsal = {"findings": [{"id": "gate_decision-1", "waives": [{"block": "gate decision: x", "option": "any"}]}]}
    ctx = story_run.RelayCtx({"PC-1": "TC-9"}, [bare], rehearsal, "A", "S9")
    found = {"unread": [{"line": "TC-9: a word nobody knows", "why": "a word outside the closed list"}]}
    out = {"recorded": ["TC-8"], "unread": ["TC-9: a word nobody knows"], "note": ""}
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        note = story_run.Driver._relay_note(None, out, found, ctx)
    check_in("D17: a gap with no stage of its own is recorded under the default stage, with the context's form id",
             "- TC-9: block `stand gap: PC-1`, stage S9; takes every option above", note)
    check_in("D17: a rehearsal door with no stage is recorded under the default stage",
             "- gate_decision-1: block `gate decision: x`, stage S9, word option `any`", note)
    check_in("D17: what was recorded is named", "already recorded: TC-8 - do not record those again", note)
    check_in("D17: the line printed names the context's gate", "gate A: 1 line(s) of the answer look like a stand-gap answer", printed.getvalue())
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        nothing = story_run.Driver._relay_note(None, {"recorded": [], "unread": []}, {"unread": []}, ctx)
    check_eq("D17: nothing recorded and nothing unread: no note, nothing printed", (nothing, quiet.getvalue()), ("", ""))


def test_b220_p2_the_list_of_probe_answers_is_data_and_a_damaged_row_is_named() -> None:
    import hooklib
    shipped = gate_brief.probe_answers()
    check_eq("the shipped file: `command` is the word, the form is NOT live yet (no handler executes it)",
             (shipped["command"]["word"], shipped["live"], shipped["problem"]), ("command", False, ""))
    check_in("the card's line about `accept` on this kind of card is data", "the report lists them as not run", shipped["reporter_accept"])
    check_eq("the continuation marks are data", shipped["command"]["continuation_marks"], ["\\", "^", "`"])
    original = hooklib.load_ref_json
    try:
        hooklib.load_ref_json = lambda name: {"probe_answers": {"live": True, "command": {"word": "command", "value": "([unclosed"}}}
        bad = gate_brief.probe_answers()
        check_eq("a `value` that is not a regular expression drops the row and the reader names why", (bad["command"], "not a regular expression" in bad["problem"]), (None, True))
        hooklib.load_ref_json = lambda name: {"probe_answers": {"live": True, "command": {"value": "x"}}}
        check_in("a row with no word is dropped and named", "names no word", gate_brief.probe_answers()["problem"])
        hooklib.load_ref_json = lambda name: {}
        check_in("a file with no `probe_answers`: no row, said", "no `probe_answers`", gate_brief.probe_answers()["problem"])
        hooklib.load_ref_json = lambda name: (_ for _ in ()).throw(OSError("gone"))
        gone = gate_brief.probe_answers()
        check_eq("a file that cannot be read: no row, not live, said", (gone["command"], gone["live"], "could not be read" in gone["problem"]), (None, False, True))
        hooklib.load_ref_json = lambda name: {"probe_answers": {"live": "yes", "command": {"word": "command"}}}
        check_eq("`live` is true only when it is the JSON true", gate_brief.probe_answers()["live"], False)
    finally:
        hooklib.load_ref_json = original


def test_b220_p2_the_card_lists_only_the_words_an_open_card_takes() -> None:
    def card(gaps: list) -> str:
        return "\n".join(gate_brief.stand_gap_card_lines(None, gaps))
    text = card([reporter_gap(NO_CURE)])
    check_eq("a reporter card with no cure and no live form: `myself`, `run`, `accept` - and no `change`, no `command`",
             [w for w in ("change", "command", "myself", "run", "accept") if f"- `{w}` —" in text], ["myself", "run", "accept"])
    check_in("and says what `accept` means on this kind of card (the delivery consequence, from the data file)", "the report lists them as not run", text)
    check_in("the answer's own consequence line is the general one beside it", "it stays blocked and is reported as not run", text)
    with_cure = card([reporter_gap(WITH_CURE)])
    check_eq("with a cure that is one change of the command: `change` is listed", "- `change` —" in with_cure, True)
    live = card([reporter_gap(LIVE)])
    words = [w for w in ("command", "myself", "run", "accept") if f"- `{w}` —" in live]
    check_eq("a live form lists `command`, first among the words that are the person's own", words, ["command", "myself", "run", "accept"])
    check("and `command` comes BEFORE `myself` in the text", live.index("- `command` —") < live.index("- `myself` —"))
    check_in("with its note", "offered only for a card about a test command that writes no report", live)
    mixed = card([reporter_gap(NO_CURE), precondition_gap()])
    check_eq("a packet with a precondition card too lists all four (the other card takes `change`), and the reader holds the rule for the reporter card",
             [w for w in ("change", "myself", "run", "accept") if f"- `{w}` —" in mixed], ["change", "myself", "run", "accept"])
    plain = card([precondition_gap()])
    check_not_in("a packet with no reporter card never says anything about `command` or the reporter's `accept`", "writes no report", plain)
    check_eq("and lists the four words as it did", [w for w in ("change", "myself", "run", "accept") if f"- `{w}` —" in plain], ["change", "myself", "run", "accept"])
    import human_text
    check_eq("the whole card, with every new line, obeys the text rules", [p["rule"] for p in human_text.shape_problems(live)], [])


# the two legs: a project whose recorded command writes nothing, and the person's own command that does
FIXED_RUNNER = ("import sys\nfrom pathlib import Path\n"
                "Path(sys.argv[1]).write_text('<?xml version=\"1.0\"?><testsuite name=\"s\" tests=\"1\" failures=\"0\" errors=\"0\" "
                "skipped=\"0\"><testcase classname=\"c\" name=\"t\"/></testsuite>', encoding=\"utf-8\")\n")
BROKEN_RUNNER = "import sys\nprint('Executed 1 of 1 SUCCESS', file=sys.stderr)\n"
PERSON_LINE = "python fixed_runner.py {report_path} <test-id>"


def answer_project() -> tuple:
    root = temp_project("qa-gate-answer-")
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["profiles"] = [{"profile_id": "web", "capabilities": ["api"], "roots": {"test": "tests"}, "reporter": {"kind": "junit-xml"},
                        "commands": {"one_test": {"argv": ["python", "broken_runner.py", "{report_path}", "<test-id>"], "cwd": "."}}}]
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (root / "tests" / "test_one.py").write_text("def test_one():\n    pass\n", encoding="utf-8")
    (root / "broken_runner.py").write_text(BROKEN_RUNNER, encoding="utf-8")
    (root / "fixed_runner.py").write_text(FIXED_RUNNER, encoding="utf-8")
    use_project(root)
    return root, temp_dir("qa-gate-answer-proposals-")


def tree(root: Path) -> dict:
    import hashlib
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and ".pytest_cache" not in p.parts}


def quiet(func, *args, **kwargs):
    import contextlib
    import io
    with contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


def approvals(root: Path) -> list:
    import config_contract
    path = config_contract.approvals_path(root)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def test_b220_p2_a_command_answer_is_probed_sealed_asked_and_applied_only_on_a_yes() -> None:
    import config_contract
    import human_text
    root, proposals = answer_project()
    try:
        gap = reporter_gap(LIVE)
        before = tree(root)
        asked = quiet(gate_brief.probe_reporter_command, root, gap, PERSON_LINE, proposals)
        check_eq("leg 1: the person's own command proved, S5's contract took it: a proposal is ASKED", (asked["state"], asked["profile"]), ("ask", "web"))
        check_in("the sentence is the sealed one and carries the command", "python fixed_runner.py {report_path} <test-id>", asked["text"])
        check_in("and ends in the question the person answers", "Do it?", asked["text"])
        check_eq("the sentence passes the text rules", [p["rule"] for p in human_text.shape_problems(asked["text"])], [])
        check_eq("nothing was written to the project before the yes (no proof row, no approval, no config change)", tree(root), before)
        sealed = json.loads(Path(asked["proposal"]["path"]).read_text(encoding="utf-8"))
        check_eq("the proposal is the maker's `command` kind, one change", (config_contract.command_kind(sealed), len(sealed["changes"])), ("command", 1))
        check_eq("old and new, for the journal", (asked["old"], asked["new"]),
                 (["python", "broken_runner.py", "{report_path}", "<test-id>"], ["python", "fixed_runner.py", "{report_path}", "<test-id>"]))
        done = gate_brief.apply_reporter_command(root, sealed, "TP2-2553", gap, PERSON_LINE)
        check_eq("leg 2: on the person's recorded yes it is applied", (done["state"], done["old"], done["new"]), ("applied", asked["old"], asked["new"]))
        check_eq("the config holds the command, nothing else moved", json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))["profiles"][0]["commands"]["one_test"]["argv"], asked["new"])
        log = approvals(root)
        check_eq("one approval, of the kind `command`, under the gate A ref, with the person's line WHOLE as the evidence (FR-8)",
                 [(r["kind"], r["evidence_ref"], r["approval_ref"].startswith("gate-a:TP2-2553:RP-web:" + sealed["proposal_hash"][:12] + ":"))
                  for r in log], [("command", PERSON_LINE, True)])
        check("and a backup of the config it replaced", done["backup"] is not None and Path(done["backup"]).is_file(), str(done["backup"]))
        second = gate_brief.apply_reporter_command(root, sealed, "TP2-2553", gap, PERSON_LINE)
        check_eq("a second yes is 'already done', never the stale refusal (E18)", (second["state"], len(approvals(root))), ("already_done", 1))
        again = quiet(gate_brief.probe_reporter_command, root, gap, PERSON_LINE, proposals)
        check_eq("the same line again is 'already done' too: no proposal", (again["state"], again["proposal"]), ("already_done", None))
        check_in("and says so to the person", "already the command", again["text"])
    finally:
        cleanup(root)
        cleanup(proposals)


def test_b220_p2_a_headless_approval_of_a_person_command_is_refused_like_a_cure() -> None:
    import config_contract
    root, proposals = answer_project()
    try:
        gap = reporter_gap(LIVE)
        asked = quiet(gate_brief.probe_reporter_command, root, gap, PERSON_LINE, proposals)
        sealed = json.loads(Path(asked["proposal"]["path"]).read_text(encoding="utf-8"))
        before = tree(root)
        for label, ref in (("an approval ref", "headless:driver"), ("an upper-case ref", "HEADLESS:driver")):
            refused = gate_brief.apply_reporter_command(root, sealed, "T-1", gap, PERSON_LINE, approval_ref=ref)
            check_eq(f"F9: {label} that starts with `headless:` is refused", refused["state"], "refused")
            check_in(f"F9: {label}: the person is told only their own word approves it", "Only your own word approves", refused["text"])
            check_in(f"F9: {label}: the reason for code names the rule", "only a person's word approves that", refused["says"])
            check_eq(f"F9: {label}: nothing was written", tree(root), before)
        evidence = gate_brief.apply_reporter_command(root, sealed, "T-1", gap, "headless: yes please")
        check_eq("F9: the evidence that starts with `headless:` is refused as well", (evidence["state"], tree(root)), ("refused", before))
        check_eq("no approval was recorded by any of them", approvals(root), [])
        check_eq("and the kind is the one that carries the ban", config_contract.command_kind(sealed), "command")
        ok = gate_brief.apply_reporter_command(root, sealed, "T-1", gap, PERSON_LINE)
        check_eq("positive control: the person's own ref goes through", (ok["state"], len(approvals(root))), ("applied", 1))
    finally:
        cleanup(root)
        cleanup(proposals)


def test_b220_p2_a_command_the_factory_cannot_run_is_refused_in_words_and_never_recorded() -> None:
    root, proposals = answer_project()
    try:
        gap = reporter_gap(LIVE)
        before = tree(root)
        rows = [("an absolute POSIX path", "/usr/bin/python3 fixed_runner.py {report_path}", "exists only on this machine"),
                ("an absolute Windows path", "C:/Python312/python.exe fixed_runner.py {report_path}", "exists only on this machine"),
                ("a home path", "~/bin/run-tests {report_path}", "exists only on this machine"),
                ("a shell chain", "python a.py && python b.py", "needs a shell"),
                ("an unbalanced quote", "python fixed_runner.py \"{report_path}", "cannot be split")]
        for label, text, words in rows:
            got = quiet(gate_brief.probe_reporter_command, root, gap, text, proposals)
            check_eq(f"A20: {label}: refused", (got["state"], got["proposal"]), ("refused", None))
            check_in(f"A20: {label}: in words", words, got["text"])
            check_eq(f"A20: {label}: no script name and no flag in what the person reads", __import__("human_text").shape_problems(got["text"]), [])
        check_eq("A20: nothing was written, no sealed file left, no approval", (tree(root), list(proposals.iterdir()), approvals(root)), (before, [], []))
        failing = quiet(gate_brief.probe_reporter_command, root, gap, "python broken_runner.py again {report_path} <test-id>", proposals)
        check_eq("a command that proves nothing is explained, not proposed", (failing["state"], failing["proposal"], tree(root)), ("explain", None, before))
        check_in("in words: what came out", "did not prove", failing["text"])
        inside = quiet(gate_brief.probe_reporter_command, root, gap, PERSON_LINE, root / "sealed-here")
        check_eq("a folder for sealed files inside the project is refused in words, not raised", (inside["state"], tree(root)), ("refused", before))
        no_form = quiet(gate_brief.probe_reporter_command, root, reporter_gap(NO_CURE), PERSON_LINE, proposals)
        check_eq("a card that does not take `command` has no leg 1", (no_form["state"], tree(root)), ("refused", before))
        check_in("and says why", "takes no command line", no_form["says"])
        stale_gap = quiet(gate_brief.probe_reporter_command, root, reporter_gap(LIVE, profile="nobody"), PERSON_LINE, proposals)
        check_in("a profile that is not in the configuration is named", "`nobody` is not in the configuration", stale_gap["says"])
    finally:
        cleanup(root)
        cleanup(proposals)


def test_b220_p2_a_yes_after_the_config_moved_is_refused_with_a_door_and_shows_no_script() -> None:
    root, proposals = answer_project()
    try:
        gap = reporter_gap(LIVE)
        asked = quiet(gate_brief.probe_reporter_command, root, gap, PERSON_LINE, proposals)
        sealed = json.loads(Path(asked["proposal"]["path"]).read_text(encoding="utf-8"))
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["profiles"][0]["capabilities"] = ["api", "ui"]
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        before = tree(root)
        stale = gate_brief.apply_reporter_command(root, sealed, "T-1", gap, PERSON_LINE)
        check_eq("E12: bytes moved between the question and the yes: refused, nothing written", (stale["state"], tree(root)), ("refused", before))
        check_in("the person is told what to do (give the command again)", "Give the command again", stale["text"])
        check_not_in("and sees no script name", ".py", stale["text"])
        check_in("the reason for code carries the door", "proposal is stale", stale["says"])
        edited = dict(sealed, proposal_hash="0" * 64)
        invalid = gate_brief.apply_reporter_command(root, edited, "T-1", gap, PERSON_LINE)
        check_eq("a proposal edited after sealing is refused too", (invalid["state"], tree(root)), ("refused", before))
    finally:
        cleanup(root)
        cleanup(proposals)


# --- B-414 (D-0029, D-0032): the card says one case or a whole level; `accept always`; the covered block; `ask again` --------

LEVEL_REMEDY = {"kind": "reporter", "where": "qa-factory/config.json:profiles[web].commands.one_test",
                "where_words": "qa-factory/config.json, the command that runs one web test", "change": "name the flag",
                "profile": "web", "offers": ["theirs", "handed", "accept"]}
CASE_REMEDY = {"kind": "flag", "where": "app/config.yaml:3", "change": "enabled: true"}
KEY_LEVEL = {"scope": "level", "contour": "web", "argv_digest": "a" * 64, "reason_class": "zero_tests"}
KEY_CASE = {"scope": "case", "environment": "QA", "definition_sha": "b" * 64, "precondition_kind": "feature_flag", "check_digest": "c" * 64}


def level_gap(cases=("TC-001", "TC-002"), key=None, lasting="", reason="zero_tests", **over) -> dict:
    return dict({"id": "RP-web", "gate": "A", "scope": "level", "contour": "web", "cases": list(cases), "case": "", "case_id": "",
                 "the_test": "every web test of this story", "missing": "web writes no report (with the command recorded now)",
                 "remedy": LEVEL_REMEDY, "partitions": [], "requirement": "", "reason_class": reason, "exit_code": 0,
                 "property_key": key, "lasting": lasting, "state": "unmet"}, **over)


def case_gap(case="TC-007", gid="PC-1", key=None, **over) -> dict:
    return dict({"id": gid, "gate": "A", "scope": "case", "case": case, "case_id": case, "the_test": "a node keeps its state",
                 "missing": "feature flag: on (on QA)", "remedy": CASE_REMEDY, "partitions": [], "requirement": "R-3", "stand": "QA",
                 "property_key": key, "lasting": "" if key else "no_key", "state": "unmet"}, **over)


def test_b414_the_card_says_one_case_or_a_whole_level_and_what_accept_always_records() -> None:
    card = "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(key=KEY_LEVEL)]))
    check_in("R3: a level card is headed by its tests and says it is a whole level, with the cases it costs",
             "Stand gap: the web tests — a whole level: every web test of this story (2 cases: TC-001, TC-002)", card)
    check_in("R3: its `the test:` line", "  the test: every web test of this story", card)
    check_in("R3: the fix line says the place in words, not a config key path", "the fix:  qa-factory/config.json, the command that runs one web test -> name the flag", card)
    check_not_in("R3: and never the path `profiles[`", "profiles[", card)
    check_not_in("R3: no `headed by something other than a case id` line for a level", "Where a card is headed by something other than a case id", card)
    check_in("R3: the example is the level's name", "for example `web: accept`", card)
    check_in("R3: `accept always` is listed, right after `accept`", "- `accept always` — ", card)
    check_in("R3: the lasting question for a level, verbatim",
             "Is this how this command always is, or temporary? A word alone answers for this story; `accept always` records it in the "
             "project's environment record for this exact command, on every machine that uses this project, and no story asks it again "
             "until the command changes or you take it back.", card)
    for banned in ("profile", "RP-", "waiver.py"):
        check_not_in(f"R3: no {banned!r} in the card", banned, card)
    case_card = "\n".join(gate_brief.stand_gap_card_lines(None, [case_gap(key=KEY_CASE)]))
    check_in("R3: a case card is today's heading plus `one case`", "Stand gap: TC-007 — needs R-3 — one case", case_card)
    check_in("R3: the lasting question for a case names the stand",
             "Is this temporary, or how QA always is? A word alone answers for this story; `accept always` records it in the project's "
             "environment record for QA as it is configured now, and no story asks it again until the stand's address changes or you take it back.", case_card)
    both = "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(key=KEY_LEVEL), case_gap(key=KEY_CASE)]))
    check_eq("R3: both kinds of card: each question once", (both.count("how this command always is"), both.count("how QA always is")), (1, 1))
    plain = "\n".join(gate_brief.stand_gap_card_lines(None, [case_gap()]))
    check_not_in("R3: a card with no key offers no `accept always`", "accept always", plain)
    check_not_in("R3 / E5: and asks no lasting question", "always is", plain)
    check_in("R3: the plain `accept` is listed as before", "- `accept` — ", plain)
    # M13: a level whose cause is a file or the machine: the word is absent and the card says why in one line
    fault = "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(lasting="fault", reason="no_file")]))
    check_not_in("M13: a `no_file` level offers no `accept always`", "accept always", fault)
    check_in("M13: and the card says why in one line, with the door", "the report was not written: a fault of this machine, not a property of the environment", fault)
    check_in("M13: ... fix it, or write `accept`", "write `accept` to go on without it for this story", fault)
    check_not_in("M13: no lasting question either", "always is", fault)


def test_b414_a_level_card_names_six_cases_and_counts_the_rest() -> None:
    six = "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(cases=[f"TC-00{n}" for n in range(1, 7)])]))
    check_in("E11: six cases are named whole", "(6 cases: TC-001, TC-002, TC-003, TC-004, TC-005, TC-006)", six)
    seven = "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(cases=[f"TC-00{n}" for n in range(1, 8)])]))
    check_in("E11: at seven the heading names six and `and 1 more`", "(7 cases: TC-001, TC-002, TC-003, TC-004, TC-005, TC-006 and 1 more)", seven)
    one = "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(cases=["TC-001"])]))
    check_in("one case is `1 case`", "(1 case: TC-001)", one)


def test_b414_the_covered_block_is_the_only_text_when_every_gap_is_covered() -> None:
    prop = {"id": "EP-1", "subject": KEY_LEVEL, "words": "web: accept always", "at": "2026-10-05T10:00:00+00:00", "about": "the web tests"}
    covered = [dict(level_gap(), property=prop)]
    lines = gate_brief.stand_gap_card_lines(None, [], {}, covered=covered)
    check_eq("the block, one line per gap, and the line that has one asked again",
             lines, ["## Decided once for this environment (1)", "",
                     '- web: on this environment the web tests cannot be checked — you wrote on 2026-10-05: "web: accept always"', "",
                     "To have one asked again, write `<name>: ask again` on a line of its own."])
    check_eq("no gap and nothing covered: no text", gate_brief.stand_gap_card_lines(None, [], {}), [])
    mixed = gate_brief.stand_gap_card_lines(None, [case_gap(key=KEY_CASE)], {}, covered=covered)
    check_eq("an open card and a covered gap: the card block first, the covered block after it",
             (mixed[0], [i for i, x in enumerate(mixed) if x.startswith("## ")]), ("## Stand gaps (1)", [0, mixed.index("## Decided once for this environment (1)")]))


def test_b414_the_answer_reader_reads_lasting_words_levels_and_ask_again() -> None:
    level, case = level_gap(key=KEY_LEVEL), case_gap(key=KEY_CASE)
    got = gate_brief.read_stand_gap_answers("web: accept always\nTC-007: accept", [level, case])
    check_eq("a lasting word is read as `accept` with `lasting`; the plain one is not lasting",
             [(e["gap"]["id"], e["option"], e["lasting"]) for e in got["read"]], [("RP-web", "accept", True), ("PC-1", "accept", False)])
    check_eq("nothing is unread, nothing in `revokes`", (got["unread"], got["revokes"]), ([], []))
    check_eq("the level is written by its contour (`web: accept` binds), a case id of its cases binds to no level",
             ([e["gap"]["id"] for e in gate_brief.read_stand_gap_answers("web: accept", [level])["read"]],
              gate_brief.read_stand_gap_answers("TC-001: accept", [level])["unread"][0]["why"]),
             (["RP-web"], "that id is not a stand gap of this gate"))
    # E5: a card with no key reads `accept always` as unread, naming why and the words that apply
    plain = gate_brief.read_stand_gap_answers("TC-007: accept always", [case_gap()])
    check_eq("E5: `accept always` on a gap with no key is unread, never read", (plain["read"], len(plain["unread"])), ([], 1))
    check_in("E5: with the words that apply", "the words that apply here are: `change`", plain["unread"][0]["why"])
    # M13: a file/machine fault: unread, with the fault line and the door `accept`
    fault = gate_brief.read_stand_gap_answers("web: accept always", [level_gap(lasting="fault", reason="no_file")])
    check_eq("M13: `accept always` on a fault gap is unread", (fault["read"], len(fault["unread"])), ([], 1))
    check_in("M13: the refusal says what it is and the door", "not a property of the environment", fault["unread"][0]["why"])
    check_in("M13: ... `accept` for this story", "write `accept`", fault["unread"][0]["why"])
    check_eq("M13: the plain `accept` on that same gap is read", [e["option"] for e in gate_brief.read_stand_gap_answers("web: accept", [level_gap(lasting="fault", reason="no_file")])["read"]], ["accept"])
    # a qualified precondition id is an id like any other
    qa = [case_gap(case="TC-007", gid="PC-1@TC-007"), case_gap(case="TC-008", gid="PC-1@TC-008")]
    read = gate_brief.read_stand_gap_answers("PC-1@TC-007: accept", qa)
    check_eq("F18: `PC-1@TC-007: accept` binds to that gap alone", [e["gap"]["id"] for e in read["read"]], ["PC-1@TC-007"])
    check_eq("F18: and the form reader reads the id whole", gate_brief._FORM_LINE_RE.match("PC-1@TC-007: accept").group("id"), "PC-1@TC-007")
    check_eq("F18: a case with two gaps of one case id: the case id names both, so it is unread (as before)",
             len(gate_brief.read_stand_gap_answers("TC-007: accept", [case_gap(gid="PC-1"), case_gap(gid="PC-2")])["unread"]), 1)
    # `ask again`: only against a covered gap, only into `revokes`
    prop = {"id": "EP-1", "subject": KEY_LEVEL, "words": "w", "at": "2026-10-05T10:00:00+00:00"}
    covered = [dict(level_gap(), property=prop)]
    asked = gate_brief.read_stand_gap_answers("web: ask again", [], covered=covered)
    check_eq("M4: `ask again` is read even when EVERY gap is covered (no open gap), into `revokes` alone",
             (asked["read"], [(e["gap"]["id"], e["option"]) for e in asked["revokes"]], asked["unread"]), ([], [("RP-web", "revoke")], []))
    check_eq("`ask again` for an open gap is unread (E18: it is not recorded for the environment)",
             (gate_brief.read_stand_gap_answers("web: ask again", [level], covered=[])["revokes"],
              gate_brief.read_stand_gap_answers("web: ask again", [level])["unread"][0]["why"]),
             ([], "this gap is not recorded for the environment, so there is nothing to ask again"))
    check_in("`ask again` for an id that is no gap at all is unread", "not a stand gap of this gate", gate_brief.read_stand_gap_answers("zzz: ask again", [level], covered=covered)["unread"][0]["why"])
    other = gate_brief.read_stand_gap_answers("web: accept", [], covered=covered)
    check_in("any other word for a covered gap is unread and says how to have it asked again", "ask again", other["unread"][0]["why"])
    check_eq("a lasting word for a covered gap is unread too", (gate_brief.read_stand_gap_answers("web: accept always", [], covered=covered)["read"]), [])
    last = gate_brief.read_stand_gap_answers("web: ask again\nweb: ask it again", [], covered=covered)
    check_eq("two `ask again` lines for one covered gap are one revoke (the last line)", [e["line"] for e in last["revokes"]], ["web: ask it again"])
    check_eq("the early return holds only when BOTH lists are empty", gate_brief.read_stand_gap_answers("web: accept", [], covered=[]),
             {"read": [], "unread": [], "commands": [], "revokes": []})
    # the words of the two lists never collide, and the standing readers never see the lasting row
    check_eq("`stand_gap_words()` keeps one standing word per option; the lasting row only on request",
             ([r["word"] for r in gate_brief.stand_gap_words() if r["option"] == "accept"], [r["word"] for r in gate_brief.stand_gap_words(lasting=True) if r["option"] == "accept"]),
             (["accept"], ["accept", "accept always"]))
    check_eq("`ask again` is not an answer word of the stand-gap list", gate_brief.stand_gap_word_index().get("ask again"), None)
    check_in("the conductor relay says a keyed card also takes `accept always`", "also takes `accept always`", gate_brief.relay_card_line(level, "web", "S5"))
    check_not_in("and a card with no key does not", "accept always", gate_brief.relay_card_line(case_gap(), "TC-007", "S5"))


# --- B-416 (D-0031): what the helper understood (N7) and what the factory adapted by itself (N8) -------------------------------

def test_b416_n7_the_card_shows_what_the_helper_understood_at_400_and_not_at_401() -> None:
    def card(text, **over):
        return "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(key=KEY_LEVEL, understood=text, **over)]))
    at, beyond = "u" * 400, "u" * 401
    check_in("N7: 400 characters are shown whole, on a line of their own, before the fix line", f"  the factory's helper read it: {at}\n  the fix:", card(at))
    shown = card(beyond)
    check_in("N7: 401 are cut to 400", f"  the factory's helper read it: {at}\n", shown)
    check_not_in("N7: ... and the 401st is not shown", "u" * 401, shown)
    check_not_in("N7: no helper line when the helper understood nothing", "the factory's helper read it", card(""))
    check_not_in("N7: no helper line when the gap carries no `understood` at all", "the factory's helper read it",
                 "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(key=KEY_LEVEL)])))
    named = card("the run set TOKEN=hunter2 and wrote a binary report")
    check_not_in("N7: names only: a value assigned to a name is not printed", "hunter2", named)
    check_in("N7: ... the name is", "TOKEN=<value not printed>", named)
    # Fix 3 (a), TEMPORAL: a record written before `understood` refused such text may hold a script name, a flag, a path or a secret
    for label, old in (("a script name", "ran run_tests.py and found nothing"), ("a flag", "add --profile web to the command"),
                       ("a path", "the report is at C:\\proj\\out\\report.bin"), ("a command line", "ran report_adapt.py kind --profile web; it said no")):
        shown = card(old)
        check_in(f"Fix 3 (a): an old record with {label} renders the fallback line", "the factory's helper read it: the factory's helper left a note it cannot print here (names only)", shown)
        for needle in ("run_tests.py", "--profile", "C:\\proj", "report_adapt.py"):
            check_not_in(f"Fix 3 (a): {label}: `{needle}` is never printed", needle, shown)
    check_in("Fix 3 (a): TOKEN=abc123 in an old record prints only the name", "TOKEN=<value not printed>", card("the run set TOKEN=abc123 first"))
    check_not_in("Fix 3 (a): ... and never the value", "abc123", card("the run set TOKEN=abc123 first"))
    check_in("Fix 3 (a) control: a plain note is printed", "the factory's helper read it: the runner wrote a binary report", card("the runner wrote a binary report"))
    check_in("N7: at gate B the same renderer prints it (the gap row is the same)", "the factory's helper read it: hello",
             "\n".join(gate_brief.stand_gap_card_lines(None, [level_gap(key=KEY_LEVEL, understood="hello", gate="B")])))


def adapted_story(count: int, extra_rows=()) -> tuple:
    """A story whose project holds `count` proven `reporter_kind` rows (profiles p0..), and whatever `extra_rows` say."""
    import onboarding_probe
    import report_adapt
    base = story("qa-gate-adapted-")
    project = base.parent
    proofs = {}
    for index in range(count):
        digest = onboarding_probe.argv_digest(["run", str(index)])
        row, problem = report_adapt.append(project, {"kind": "reporter_kind", "by": "driver", "profile_id": f"p{index}", "argv_digest": digest,
                                                     "story": "TP1-15045", "reader": "trx" if index % 2 == 0 else "junit-xml"})
        assert row, problem
        proofs[f"k{index}"] = {"at": "2999-01-01T00:00:00+00:00", "profile_id": f"p{index}", "argv_digest": digest}
    for extra in extra_rows:
        row, problem = report_adapt.append(project, extra)
        assert row, problem
    (project / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    (project / "qa-factory" / "state" / "reporter-rehearsals.json").write_text(json.dumps({"schema_version": 1, "rehearsals": proofs}), encoding="utf-8")
    return base, base / "artifacts" / "TP1-15045"


def test_b416_n8_the_adapted_block_lists_only_proven_adaptations_five_lines_then_the_count() -> None:
    for count, lines in ((5, 5), (6, 6)):
        base, task_root = adapted_story(count)
        try:
            got = gate_brief.adapted_lines(task_root)
            check_eq(f"N8: {count} proven adaptations: the heading, then {5 if count == 5 else '5 lines and `and 1 more`'}",
                     (got[0], len(got) - 2), ("## What the factory adapted by itself", lines))
            check_in("N8: a line says the tests, the report in words and the day", "- the p0 tests: their report is read as a .NET (trx) report since 20", got[2])
            check_in("N8: the other reader in words", "- the p1 tests: their report is read as a JUnit XML report since 20", got[3])
            check_eq(f"N8: {count}: the count line is {'absent' if count == 5 else 'present'}", got[-1] == "- and 1 more", count == 6)
            data = gate_brief.collect("TP1-15045", task_root)
            text = gate_brief.render(data)
            check_in("N8: the packet carries the block", "## What the factory adapted by itself", text)
            check_not_in("N8: the block never costs the packet its document links (the cap grows by the block, as for the cards)", "brief truncated", text)
        finally:
            cleanup(base.parent)
    # nothing the proof did not confirm
    import onboarding_probe
    import report_adapt
    digest = onboarding_probe.argv_digest(["run", "unproven"])
    base, task_root = adapted_story(1, extra_rows=[
        {"kind": "reporter_kind", "by": "driver", "profile_id": "noproof", "argv_digest": digest, "story": "TP1-15045", "reader": "trx"},
        {"kind": "not_adapted", "by": "conductor", "profile_id": "p0", "argv_digest": onboarding_probe.argv_digest(["run", "0"]),
         "story": "TP1-15045", "understood": "a cure in words"},
        {"kind": "reporter_kind", "by": "driver", "profile_id": "p0", "argv_digest": onboarding_probe.argv_digest(["run", "0"]),
         "story": "OTHER-1", "reader": "trx"}])
    try:
        got = gate_brief.adapted_lines(task_root)
        check_eq("N8: a row no later proof confirms, a `not_adapted` row and another story's row are NOT listed", [x for x in got if x.startswith("- the")],
                 [x for x in got if x.startswith("- the p0 tests")])
        check_eq("N8: exactly the one proven row of this story", len([x for x in got if x.startswith("- the")]), 1)
        check_not_in("N8: the unproven profile is not named", "noproof", "\n".join(got))
        (base.parent / "qa-factory" / "state" / "reporter-rehearsals.json").write_text("{broken", encoding="utf-8")
        check_eq("N8: an unreadable proof file lists nothing (an unknown is never a fact)", gate_brief.adapted_lines(task_root), [])
        (base.parent / "qa-factory" / "state" / "reporter-rehearsals.json").unlink()
        check_eq("N8: no proof file: nothing", gate_brief.adapted_lines(task_root), [])
        report_adapt.record_path(base.parent).write_text("{broken", encoding="utf-8")
        check_eq("N8: an unreadable record: nothing, no crash", gate_brief.adapted_lines(task_root), [])
    finally:
        cleanup(base.parent)
    base = story("qa-gate-adapted-none-")
    try:
        check_eq("N8: a story with no adaptation has no block", gate_brief.adapted_lines(base / "artifacts" / "TP1-15045"), [])
        check_not_in("N8: and the packet has no such heading", "What the factory adapted", gate_brief.render(gate_brief.collect("TP1-15045", base / "artifacts" / "TP1-15045")))
    finally:
        cleanup(base.parent)


def test_t674_c_rows_gate_brief_read_json_keeps_its_direction() -> None:
    """t-666 R2 (row 1.3): `gate_brief.read_json(path, default=None)` is the shared reader with ONE direction of its own: every
    exception a bad path or file can raise is the default (`errors=Exception`). C-rows over one file per way to fail, a list,
    a null, a None path and a str path. The `bom` and `str path` rows are the F-2 flip (t-611 precedent): the old reader read
    `utf-8` through `path.read_text`, so a BOM file was a parse error and a str path an AttributeError, both the default; the
    shared reader reads `utf-8-sig` through `Path(path)`, so both are data now."""
    root = temp_dir("qa-gate-brief-readjson-")
    try:
        write = {"good": b'{"a": 1}', "empty": b"", "invalid": b"{not json", "bom": b"\xef\xbb\xbf" + b'{"a": 1}',
                 "latin1": b'{"a": "\xe9"}', "deep": b"[" * 300000, "list": b"[1, 2]", "null": b"null"}
        files = {name: root / f"{name}.json" for name in (*write, "dir", "missing")}
        for name, raw in write.items():
            files[name].write_bytes(raw)
        files["dir"].mkdir()
        read = gate_brief.read_json
        check_eq("C good: the value", read(files["good"]), {"a": 1})
        check_eq("C list: returned as parsed", read(files["list"], {}), [1, 2])
        check_eq("C null: None whatever the default", read(files["null"], {}), None)
        for name in ("missing", "empty", "invalid", "latin1", "dir", "deep"):
            check_eq(f"C {name}: None by default", read(files[name]), None)
            check_eq(f"C {name}: the caller's default, positionally", read(files[name], {}), {})
            check_eq(f"C {name}: the caller's default, by keyword", read(files[name], default=[]), [])
        check_eq("C None path: the default (errors=Exception, a TypeError is swallowed)", read(None, {}), {})
        check_eq("C F-2 bom: the data (utf-8-sig; before the move a parse error, so the default)", read(files["bom"], {}), {"a": 1})
        check_eq("C F-2 str path: the data (Path(path); before the move an AttributeError, so the default)",
                 read(str(files["good"]), {}), {"a": 1})
        check_eq("C F-2 str path that names nothing: still the default", read(str(files["missing"]), {}), {})
        check_eq("C F-2 bom in a file that is not JSON after it: still the default", read(files["invalid"], {}), {})
    finally:
        cleanup(root)


def test_c14b_approval_words_are_the_raw_words_of_the_data_file_and_an_unreadable_file_has_none() -> None:
    """C1-4b (H13, FR-13, FR-59): `gate_brief.approval_words(gate)` is THE reader of `references/gate-approval-words.json`: the RAW words
    in the file's order (it normalizes nothing - the driver reads both sides with its one normalizer), only the words whose `gates` name
    the gate; `()` for the file or the key that cannot be read, a row that is not an object, a word that is blank. The driver side (an
    unreadable list approves nothing and files ONE defect) is proved in test_story_run_gate_repair (A4)."""
    root = temp_dir("qa-approval-words-")
    saved = gate_brief.APPROVAL_WORDS_FILE
    try:
        check_eq("the shipped file: `approve` for both gates, and gate A's closed `approve as is` after it (RH1-6)",
                 (gate_brief.approval_words("A"), gate_brief.approval_words("B")), (("approve", "approve as is"), ("approve",)))
        check_eq("and no other gate has a word", (gate_brief.approval_words("C"), gate_brief.approval_words("")), ((), ()))

        def reads(body, gate="A", name="words.json"):
            path = root / name
            if body is not None:
                path.write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
            gate_brief.APPROVAL_WORDS_FILE = str(path)          # an absolute name: `ref()` joins it under references/ and keeps it whole
            return gate_brief.approval_words(gate)
        rows = {"gate_approval_words": {" Approve. ": {"gates": ["A", "B"]}, "ok": {"gates": ["B"]}, "  ": {"gates": ["A"]},
                                        "flat": "not a row", "none": {"gates": None}, "late": {"gates": ["A"]}}}
        check_eq("RAW words, in the file's order, for gate A (the spelling is the file's: no case, no stop, no space is changed)",
                 reads(rows, "A"), (" Approve. ", "late"))
        check_eq("a word listed for gate B only is not a word of gate A", reads(rows, "B"), (" Approve. ", "ok"))
        for label, body in (("a missing file", None), ("an empty file", b""), ("broken JSON", b"{not json"), ("a list", []), ("null", b"null"),
                            ("the key absent", {"gates": {}}), ("the key a list", {"gate_approval_words": ["approve"]}),
                            ("the key null", {"gate_approval_words": None}), ("a BOM and no JSON after it", b"\xef\xbb\xbfnope")):
            check_eq(f"FR-59: {label}: no word, so nothing approves", reads(body, "A", name=label.replace(" ", "_") + ".json"), ())
    finally:
        gate_brief.APPROVAL_WORDS_FILE = saved
        cleanup(root)


def test_hf27_p3_question_note_says_where_in_words_and_still_open_reads_the_one_definition() -> None:
    """K5 (still_open delegates to QR.settled), K10 (the suffix through QR.where_words, T4, the `before` mark) and K11."""
    import inspect
    import human_text
    import question_register as QR

    def asked(**extra):
        return dict({"id": "Q1", "status": "answered", "reading": "a", "where": "gate A", "changed_since_answer": False,
                     "row_hash": "0" * 64}, **extra)
    again = "its text changed after your answer, so it is asked again"
    check_eq("K10: gate A stays 'at gate A' byte for byte (the pin of test_gate_question_form)",
             gate_brief.question_note(asked(changed_since_answer=True)), again + " (answered at gate A)")
    check_eq("K10: the S2 stop is said in words, not as its code",
             gate_brief.question_note(asked(changed_since_answer=True, where="S2 stop")),
             again + " (answered when the requirements were checked)")
    check_not_in("K10: no raw code reaches the person", "S2 stop", gate_brief.question_note(asked(changed_since_answer=True, where="S2 stop")))
    check_eq("K10: an unknown place is 'earlier'", gate_brief.question_note(asked(changed_since_answer=True, where="zzz")),
             again + " (answered earlier)")
    check_eq("K10: a not_needed question carries no suffix", gate_brief.question_note(
             asked(status="not_needed", reading="", changed_since_answer=True)), again)
    before = "you chose the behaviour before the change, but nobody knows what it was: say what it was"
    check_eq("K10: the 'before' mark is the note's now (its old text)", gate_brief.question_note(
             asked(reading="b", before={"value": "unknown"})), before)
    kept = asked(status="deferred_to_report", reading="", where="S2 stop")
    t4 = "kept open until the report, on your word when the requirements were checked; it is not asked again here"
    check_eq("T4: a held deferred question is kept open on the person's word", gate_brief.question_note(kept), t4)
    check_eq("T4: gate A reads 'at gate A'", gate_brief.question_note(dict(kept, where="gate A")),
             "kept open until the report, on your word at gate A; it is not asked again here")
    check_eq("H43: a deferred question whose row changed is asked again, not kept", gate_brief.question_note(
             dict(kept, changed_since_answer=True)), again)
    for text in (t4, "- **Q3** [blocker, owner po_ba] Which behaviour?" + chr(10) + "  - " + t4 + "."):
        check_eq("K11: T4 obeys the text rules", human_text.problems(text, kind="report"), [])
    # K5: the list of what a person still decides
    questions = [asked(id="Q5", status="deferred_to_report", reading="", where="gate A"),
                 asked(id="Q6", status="deferred_to_report", reading="", changed_since_answer=True),
                 asked(id="Q7", changed_since_answer=True), asked(id="Q8"), asked(id="Q9", reading="b", before={"value": ""}),
                 asked(id="Q10", status="not_needed", reading="")]
    task = temp_dir("qa-hf27-p3-open-")
    try:
        listed = {i["id"]: i for i in gate_brief.still_open([{"id": q["id"], "question": f"{q['id']}?"} for q in questions],
                                                            {"questions": questions}, {}, task)}
        check_eq("K5: settled questions leave the list, the others stay", sorted(listed), ["Q5", "Q6", "Q7", "Q9"])
        check_eq("K5: a held deferred one carries T4", listed["Q5"]["status_note"],
                 "kept open until the report, on your word at gate A; it is not asked again here")
        check_in("K5: a changed deferred one is asked again", "asked again", listed["Q6"]["status_note"])
        check_eq("K5: an answered one that changed stays, as today", listed["Q7"]["status_note"], again + " (answered at gate A)")
        check_eq("K5: and so does one whose `before` value is missing", listed["Q9"]["status_note"], before)
    finally:
        cleanup(task)
    source = inspect.getsource(gate_brief.still_open) + inspect.getsource(gate_brief.question_note)
    check("K5 AR-13: neither function names the settled statuses", '("answered", "not_needed")' not in source
          and "SETTLED_STATUSES" not in source and "QR.settled(" in source)
    check_eq("K5: the delegate and the list agree for every question", [QR.settled(q) for q in questions],
             [q["id"] not in listed for q in questions])

def finding(number, message, klass="person_decides", fix="say so in your own words", waives=None, check="s5_x"):
    row = {"id": f"{check}-{number}", "check": check, "class": klass, "message": message, "fix": fix}
    if waives is not None:
        row["waives"] = waives
    return row


def rh16_items(findings, **extra):
    return gate_brief.open_rehearsal_items(None, "A", dict({"gate": "A", "next_stage": "S5", "findings": findings}, **extra))


def test_rh16_open_rehearsal_items_one_reader_and_its_doors() -> None:
    """RH1-6 A1 (A-K1..K5, K23): `open_rehearsal_items` is the one reader of "answered"; a doorless item gets a block the rehearsal's own
    drop accepts (round trip), or `none`; `as_is_words` is the data row's flag."""
    from gate_preflight import Rehearsal
    read = rh16_items([])
    check_eq("A-K1 zero items", (read["status"], read["items"]), ("read", []))
    door = [{"block": "stand gap: TC-1", "stage": "S5", "option": "any"}]
    item = rh16_items([finding(1, "a gap in TC-1", waives=door, fix="answer the card")])["items"][0]
    check_eq("A-K2 a `line` item carries its waives, block, stage and says",
             (item["door"]["kind"], item["door"]["block"], item["door"]["stage"], item["door"]["says"], item["door"]["waives"]),
             ("line", "stand gap: TC-1", "S5", "answer the card", door))
    message = "a" * 30 + '"quoted" and a tail that goes on beyond sixty characters'
    found = rh16_items([finding(1, message)])["items"][0]
    check_eq("A-K3 a `words` block stops before the quote", (found["door"]["kind"], found["door"]["block"]), ("words", "a" * 30))
    # the ROUND TRIP: the offered block, recorded as a person's word, is dropped by the rehearsal's own `add`
    base = story("qa-rh16-roundtrip-")
    try:
        root = base / "qa-factory" / "artifacts" / "TP1-15045"
        before = Rehearsal(root, "A")
        before.add("s5_x", "person_decides", message)
        check_eq("A-K3 the item is listed by a fresh rehearsal", len(before.findings), 1)
        after = Rehearsal(root, "A")
        after.pipeline = {"stage_overrides": [{"stage": "S5", "match": found["door"]["block"], "decision": "x"}]}
        after.add("s5_x", "person_decides", message)
        check_eq("A-K3 ROUND TRIP: a fresh rehearsal drops it once the offered block is recorded", after.findings, [])
        wrong = Rehearsal(root, "A")
        wrong.pipeline = {"stage_overrides": [{"stage": "S5", "match": found["door"]["block"].replace("a", "'", 1), "decision": "x"}]}
        wrong.add("s5_x", "person_decides", message)
        check_eq("A-K3 control: a block that is not in the message drops nothing", len(wrong.findings), 1)
    finally:
        cleanup(base)
    check_eq("A-K3b a message that starts with a quote: no block, kind `none`",
             rh16_items([finding(1, '"quoted" first')])["items"][0]["door"]["kind"], "none")
    at = rh16_items([finding(1, "b" * 60)])["items"][0]["door"]
    beyond = rh16_items([finding(1, "b" * 61)])["items"][0]["door"]
    check_eq("A-K3c AT the 60-character limit the block is offered whole", (at["kind"], len(at["block"])), ("words", 60))
    check_eq("A-K3c BEYOND it (one word longer than 60) no block is offered: kind `none`, nothing cut (GW1-1: a block that is not a whole word is no door)",
             (beyond["kind"], len(beyond["block"])), ("none", 0))
    # Q1: `Rehearsal.add` has already replaced `<check-id>` by the finding's own id in the STORED message, so the stop is that id (the
    # rehearsal drops by the RAW text, where a block crossing the id would never match); the placeholder itself is no longer in the text
    placeholder = rh16_items([finding(1, "head of the text " + "s5_x-1" + " tail")])["items"][0]["door"]["block"]
    check_eq("A-K4 (10) the finding's own id ends the block", placeholder, "head of the text")
    check_eq("A-K4 (10) control: another finding's id does not", rh16_items([finding(1, "head of s5_x-2 text")])["items"][0]["door"]["block"],
             "head of s5_x-2 text")
    from gate_preflight import Rehearsal, DOOR_ID
    raw = f"head of the text {DOOR_ID} tail that goes on"
    base = story("qa-rh16-q1-")
    try:
        root = base / "qa-factory" / "artifacts" / "TP1-15045"
        first = Rehearsal(root, "A")
        first.add("s5_x", "person_decides", raw)
        stored = first.findings[0]
        offered = gate_brief.open_rehearsal_items(None, "A", {"gate": "A", "next_stage": "S5", "findings": [stored]})["items"][0]["door"]["block"]
        again = Rehearsal(root, "A")
        again.pipeline = {"stage_overrides": [{"stage": "S5", "match": offered, "decision": "x"}]}
        again.add("s5_x", "person_decides", raw)
        check_eq("A-K4 (10) ROUND TRIP over a replaced id: the offered block drops the raw message", (offered, again.findings), ("head of the text", []))
    finally:
        cleanup(base)
    check_eq("A-K4 (5) `waives: []` is a `words` item", rh16_items([finding(1, "m one", waives=[])])["items"][0]["door"]["kind"], "words")
    check_eq("A-K4 (6) a `waives` entry without a block is not usable",
             rh16_items([finding(1, "m two", waives=[{"stage": "S5", "option": "accept"}])])["items"][0]["door"]["kind"], "words")
    check_eq("A-K4 A-E18 a `handed` door alone is a `words` item",
             rh16_items([finding(1, "m three", waives=[{"block": "x", "stage": "S5", "option": "handed"}])])["items"][0]["door"]["kind"], "words")
    check_eq("A-K4 (7) only `person_decides` is an item", rh16_items([finding(1, "m", klass="factory_fixable"),
                                                                      finding(2, "n", klass="PERSON_DECIDES")])["items"], [])
    for label, bad in (("a non-dict finding", ["junk"]), ("a finding without an id", [{"class": "person_decides"}]),
                       ("a finding without a class", [{"id": "x-1"}])):
        check_eq(f"A-K4 (4) {label} is counted: the list is unknown", rh16_items(bad)["status"], "unknown")
    check_eq("A-K5 a rehearsal that could not run is unknown, with its reason",
             (rh16_items([], unavailable="OSError: boom")["status"], rh16_items([], unavailable="OSError: boom")["why"]), ("unknown", "OSError: boom"))
    check_eq("A-K23 `approve as is` is gate A's closed word, after `approve`",
             (gate_brief.as_is_words("A"), gate_brief.as_is_words("B"), gate_brief.approval_words("A")[0]),
             (("approve as is",), (), "approve"))


def test_rh16_b1_the_one_reader_drops_a_doorless_item_the_person_passed_as_is() -> None:
    """B1 (critic t-1447), against the REAL reader: an item whose message starts with a quote has door `none`; once `approve as is` has
    been recorded for it at S4 (its own block, `none_item_block`) `open_rehearsal_items` no longer lists it. On the old code the
    reader had no such branch and the item stayed listed for ever (an endless refusal)."""
    base = story("qa-rh16-b1-reader-")
    try:
        task_root = base / "artifacts" / "TP1-15045"
        rehearsed = {"gate": "A", "next_stage": "S5", "findings": [finding(1, '"quoted" start of a doorless item'),
                                                                   finding(2, "plain words item")]}
        first = gate_brief.open_rehearsal_items(task_root, "A", rehearsed)
        check_eq("B1 before the word: both are listed, the quoted one is `none`",
                 [(i["id"], i["door"]["kind"]) for i in first["items"]], [("s5_x-1", "none"), ("s5_x-2", "words")])
        block = gate_brief.none_item_block("A", first["items"][0])
        (task_root / "pipeline.json").write_text(json.dumps({"stage_overrides": [
            {"stage": "S4", "match": block, "decision": "accept - the person wrote: ok", "at": "t", "by": "human"}]}), encoding="utf-8")
        after = gate_brief.open_rehearsal_items(task_root, "A", rehearsed)
        check_eq("B1 after the as-is word at its block: the doorless item is not listed, the words item is",
                 [i["id"] for i in after["items"]], ["s5_x-2"])
        (task_root / "pipeline.json").write_text(json.dumps({"stage_overrides": [
            {"stage": "S4", "match": block, "decision": "x", "revoked_at": "t2"}]}), encoding="utf-8")
        check_eq("B1 a revoked word passes nothing", [i["id"] for i in gate_brief.open_rehearsal_items(task_root, "A", rehearsed)["items"]],
                 ["s5_x-1", "s5_x-2"])
        (task_root / "pipeline.json").write_text("[1]", encoding="utf-8")
        check_eq("B1 an unreadable pipeline.json drops nothing", len(gate_brief.open_rehearsal_items(task_root, "A", rehearsed)["items"]), 2)
        check_eq("B1 no task root drops nothing (the packet's own call)", len(gate_brief.open_rehearsal_items(None, "A", rehearsed)["items"]), 2)
        check_eq("M4 one reader of the word to name", (gate_brief.as_is_word_of("A"), gate_brief.as_is_word_of("B")), ("approve as is", ""))
    finally:
        cleanup(base)


def test_rh16_the_packet_line_and_open_before_mr() -> None:
    """RH1-6 A1 (A-K11, A-K24): one packet line names every item without a line door (the sixth, behind brief_lines' five), and
    `open_before_mr` still lists `not decided` for each open item and its own unknown sentence."""
    door = [{"block": "stand gap: TC-1", "stage": "S5", "option": "any"}]
    items = [finding(n, f"item number {n} text", waives=door) for n in range(1, 6)] + [finding(6, "the doorless sixth item")]
    lines = gate_brief._after_approval({"rehearsal": {"gate": "A", "next_stage": "S5", "findings": items, "by_class": {"person_decides": 6}}})
    named = [line for line in lines if line.startswith("- needs your word")]
    check_eq("A-K11 ONE packet line", len(named), 1)
    check_in("A-K11 it names the doorless sixth item", "[s5_x-6]", named[0])
    # RH1-6 Q3 (Lead's decision, t-1455): the `line` items are named too, so none hides under brief_lines' "+N more"; the count is stated
    for n in range(1, 7):
        check_in(f"A-AC7/Q3: item {n} is named in the one line", f"[s5_x-{n}]", named[0])
    check_in("A-AC7/Q3: the count is stated", "(6 open)", named[0])
    check_not_in("A-AC7/Q3: ids only - no message text", "item number 1 text", named[0])
    check_in("A-K11 and the closed word", "`approve as is`", named[0])
    check_eq("A-K11 control: nothing open, no line",
             [l for l in gate_brief._after_approval({"rehearsal": {"gate": "A", "next_stage": "S5", "findings": []}})
              if l.startswith("- needs your word")], [])
    import gate_preflight
    real = gate_preflight.run
    base = story("qa-rh16-mr-")
    try:
        root = base / "qa-factory" / "artifacts" / "TP1-15045"
        gate_preflight.run = lambda task_root, gate="A": {"gate": gate, "next_stage": "S9", "findings": [finding(1, "an open one"), finding(2, "fixable", klass="factory_fixable")]}
        check_in("A-K24 an open item is listed as before", "- not decided: an open one", gate_brief.open_before_mr(root, "B"))
        check_not_in("A-K24 a factory item is not", "- not decided: fixable", gate_brief.open_before_mr(root, "B"))

        def boom(task_root, gate="A"):
            raise OSError("down")
        gate_preflight.run = boom
        check_in("A-K24 an unreadable rehearsal keeps its own sentence",
                 "- the gate rehearsal could not be read (OSError: down), so what it would have asked is unknown — that is the factory's own gap, not yours",
                 gate_brief.open_before_mr(root, "B"))
        gate_preflight.run = lambda task_root, gate="A": {"gate": gate, "next_stage": "S9", "findings": [{"class": "person_decides"}]}
        check_in("Q4 a finding without an id says what was unreadable, not that the rehearsal could not run",
                 "could not be read (1 finding(s) of the rehearsal have no id or no class)", "\n".join(gate_brief.open_before_mr(root, "B")))
    finally:
        gate_preflight.run = real
        cleanup(base)


G25_TABLE = """schema_version: 1
implementation_source: diff
refactoring_share:
  road: notify
  percent: 42.5
  total: 80
  policy:
    notify_above_percent: 30
    stop_above_percent: 50
requirement_coverage:
  implemented: 1
  partial: 0
  n: 3
  percent: 33.3
  road: highlight
  outside:
    - r: R-2
      state: not_implemented
    - r: R-3
      state: unknown
"""


def test_g2_5_grounding_lines_at_gate_a() -> None:
    """G2-5: the gate A packet says the refactoring share (notify / stop) and the requirements the change leaves out, in a person's words,
    asks nothing, and does not cut them at the cap. Mutations named, NOT run, each killed by this file: the lines placed below the questions
    (the head check); `cap` not grown by them (the AT / BEYOND checks); a saved `unknown` hidden (the defect-line checks)."""
    import human_text
    lines_of = gate_brief._grounding_lines
    table = {"state": "table", "statements": {"R-2": "A guest cannot check out"},
             "share": {"road": "notify", "percent": "42.5", "policy": {"notify_above_percent": 30, "stop_above_percent": 50}},
             "coverage": {"road": "highlight", "implemented": 1, "partial": 0, "n": 3,
                          "outside": [{"r": "R-2", "state": "not_implemented"}, {"r": "R-3", "state": "unknown"}]}}
    got = lines_of({"grounding": table, "open_questions": []})
    text = "\n".join(got)
    check_eq("G2-5 a block starts with a blank line and holds the share and the coverage", (got[0], len(got)), ("", 3))
    check_in("G2-5 the notify line names the share and the mark", "42.5% of the changed production lines are refactoring or not classified, above the 30% mark", text)
    check_in("G2-5 the coverage names the requirements left out, with the register's words", "R-2 (A guest cannot check out); R-3", text)
    check_in("G2-5 and the count of what is implemented", "implements 1 of 3 requirements", text)
    check_eq("G2-5 the words obey the shape rules of a text a person reads (AR-16)", human_text.problems(text, kind="report"), [])
    for machine in ("K-", "B-", "road", "refactoring_share", "requirement_coverage", "not_implemented", "?"):
        check_not_in(f"G2-5 no machine word `{machine}` in the lines", machine, text)
    stop = lines_of({"grounding": dict(table, share=dict(table["share"], road="stop", percent="61.0"), coverage={"road": "none"})})
    check_in("G2-5 stop: the 50% mark and that the plan came after the person's word", "above the 50% mark: the plan was written after you chose to go on", "\n".join(stop))
    check_eq("G2-5 a share at or under the notify mark and a covered change say nothing (road none, 100 %)",
             lines_of({"grounding": dict(table, share={"road": "none", "percent": "10.0"}, coverage={"road": "none", "implemented": 3, "n": 3})}), [])
    check_eq("G2-5 no table (a story with no diff) says nothing", (lines_of({"grounding": {"state": "none"}}), lines_of({})), ([], []))
    bad = lines_of({"grounding": dict(table, share={"road": "unknown", "reason": "a hunk has an empty mark"}, coverage={"road": "unknown", "reason": "no register"})})
    check_eq("G2-5 a share and a coverage the table saved as unknown are two defect lines of the factory",
             (len(bad), sum("gap of the factory" in l for l in bad)), (3, 2))
    check_in("G2-5 ... with the reason", "a hunk has an empty mark", "\n".join(bad))
    broken = lines_of({"grounding": {"state": "unreadable", "why": "syntax"}})
    check_eq("G2-5 a table that cannot be read is ONE line, not silence", (len(broken), "gap of the factory" in broken[-1]), (2, True))
    check_in("G2-5 nothing is left for the change to implement", "no requirement of the story is left",
             "\n".join(lines_of({"grounding": dict(table, share=None, coverage={"road": "stop", "reading": "nothing_asked"})})))
    asked = lines_of({"grounding": table, "open_questions": [{"question": "Does R-2 hold for a guest?", "source_says": ""}]})
    check_in("G2-5 a requirement a question below is about says so (one packet does not argue with itself, FR-10)", "R-2 (A guest cannot check out) — asked as a question below", "\n".join(asked))
    check_not_in("G2-5 ... and R-3 (R-30 is not R-3) is not marked", "R-3 — asked", "\n".join(asked))
    many = {"road": "highlight", "implemented": 0, "partial": 0, "n": 8, "outside": [{"r": f"R-{n}", "state": "not_implemented"} for n in range(1, 9)]}
    check_in("G2-5 more than six names: six and the count of the rest", "; and 2 more", "\n".join(lines_of({"grounding": dict(table, coverage=many)})))

    base = story("qa-gate-brief-g25-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        check_eq("G2-5 collect: no table is `none`", gate_brief.collect("TP1-15045", task_root)["grounding"], {"state": "none"})
        (task_root / "work" / "grounding.yaml").write_bytes(G25_TABLE.encode("utf-8"))
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("G2-5 collect reads the saved keys, nothing is measured again (a table with no hunk still says 42.5)",
                 (data["grounding"]["state"], data["grounding"]["share"]["percent"], data["grounding"]["coverage"]["road"]), ("table", "42.5", "highlight"))
        (task_root / "work" / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n"
            "| R-1 | A guest can pay | description |\n| R-2 | A guest cannot check out | description |\n| R-3 | A guest sees a receipt | description |\n", encoding="utf-8")
        said = gate_brief.collect("TP1-15045", task_root)["grounding"]["statements"]
        check_eq("G2-5 collect over a REAL register carries the requirement's words, never a digest (F-1)", said.get("R-2"), "A guest cannot check out")
        check_in("G2-5 ... and the packet line shows them", "R-2 (A guest cannot check out)", "\n".join(gate_brief._grounding_lines({"grounding": data["grounding"] | {"statements": said}})))
        plain = gate_brief.render(dict(data, grounding={"state": "none"}))
        text = gate_brief.render(data)
        head = text.splitlines()
        check("G2-5 the lines stand in the head, before the questions and the rehearsal",
              head.index("## After your approval") > next(i for i, l in enumerate(head) if l.startswith("**Coverage**")) > next(i for i, l in enumerate(head) if l.startswith("**Refactoring**")) > next(i for i, l in enumerate(head) if l.startswith("**Critic**")))
        check_eq("G2-5 the packet grows by exactly the block", len(head) - len(plain.splitlines()), len(lines_of(data)))
        # at and beyond the cap: the block is never cut, the tail is cut by the same one line (MAX_LINES is the cover sheet's budget)
        real, none = gate_brief.MAX_LINES, dict(data, grounding={"state": "none"})
        try:
            edge = len(plain.splitlines())               # the other terms of the cap are fixed: walk down to the first budget that cuts the plain packet
            while edge > 1:
                gate_brief.MAX_LINES = edge
                if "brief truncated" in gate_brief.render(none):
                    break
                edge -= 1
            gate_brief.MAX_LINES = edge + 1             # the plain packet fits exactly: AT the limit
            at_plain, at_text = gate_brief.render(none), gate_brief.render(data)
            check_eq("G2-5 AT the cap: neither is cut", ("brief truncated" in at_plain, "brief truncated" in at_text), (False, False))
            gate_brief.MAX_LINES = edge                 # one line BEYOND
            over_plain, over_text = gate_brief.render(none), gate_brief.render(data)
        finally:
            gate_brief.MAX_LINES = real
        check_eq("G2-5 BEYOND the cap: both cut by one line, the grounding lines all kept",
                 ("brief truncated" in over_plain, "brief truncated" in over_text, over_text.count("**Coverage**"), over_text.count("**Refactoring**")), (True, True, 1, 1))
        check_eq("G2-5 ... and the cut is the same one line", len(over_text.splitlines()) - len(over_plain.splitlines()), len(lines_of(data)))
        (task_root / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\n\timplementation_source: diff\n")
        check_eq("G2-5 collect: a table that exists and cannot be read is `unreadable`, not `none`", gate_brief.collect("TP1-15045", task_root)["grounding"]["state"], "unreadable")
        (task_root / "work" / "grounding.yaml").write_bytes(b"schema_version: 1\nimplementation_source: ungrounded\nnull_outcome:\n  source: ungrounded\n  words: nothing to label\n")
        check_eq("G2-5 collect: a story with no diff says nothing", gate_brief.collect("TP1-15045", task_root)["grounding"], {"state": "none"})
    finally:
        cleanup(base.parent if base.name == "qa-factory" else base)


def pc9c_story(prefix: str, items: int, differs: list, used: set, parity=("R-1",), claim_words=None, with_snapshot: bool = True,
               gaps=()) -> Path:
    """A story with a reference (side `ui`, stand `old`): a snapshot of `items` behaviours (`item-01`...), a register whose rows R-1..R-n
    carry `parity`, one behaviour claim per `differs` word (the claim of R-k cites `reference:item-k`), and one case per `used` item."""
    import grounding_table as GT
    import reference_snapshot as RS
    base = story(prefix)
    task_root = base / "artifacts" / "TP1-15045"
    pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["sides"] = {"ui": {"reality": "real", "reference": "old", "source": "launch"}}
    (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    if with_snapshot:
        GT.write_yaml(RS.snapshot_path(task_root), {
            "reference_env": "old", "walked_at": "2026-11-11T00:00:00Z", "gaps": list(gaps),
            "items": [{"id": f"item-{n:02d}", "area": f"page {n}", "user_path": f"open page {n} and read the total", "observed": f"total {n}",
                       "evidence": [], "old_test": f"old.spec.ts:{n}", "locators_portable": "yes"} for n in range(1, items + 1)]})
    count = max(len(differs), len(parity), 1)
    rows = "".join(f"| R-{n} | requirement {n} words | description | | | | | {'yes' if f'R-{n}' in parity else 'no'} |\n" for n in range(1, count + 1))
    claims = "".join(f"| R-{n} | the old total is {n} | reference:item-{n:02d} | the new total is {n + 1} | code | {word} | | S2 |\n"
                     for n, word in enumerate(differs, start=1))
    (task_root / "work" / "requirements-register.md").write_text(
        "# Requirements register\n\n## Register\n\n| ID | Requirement (one verifiable statement) | source | derived_from | quote | ac_ref | observable | parity |\n"
        "|---|---|---|---|---|---|---|---|\n" + rows + "\n## Behaviour claims\n\n| R | before | before_ref | now | now_ref | differs | question | origin |\n"
        "|---|---|---|---|---|---|---|---|\n" + claims, encoding="utf-8")
    for n in sorted(used):
        (task_root / "work" / "test-cases" / f"TC-{n:03d}.md").write_text(
            f"---\nid: TC-{n:03d}\ntask: TP1-15045\ntitle: reads total {n}\nbasis: requirement:R-1\n"
            f'then_oracles: [{{"then": 1, "source": "precedent", "ref": "reference:item-{n:02d}"}}]\n---\n## Then\n1. the total is {n}\n', encoding="utf-8")
    return base


def test_pc9c_gate_a_for_a_story_with_a_reference() -> None:
    """t-2181 PC-9c (owner D3, F-7; W1): a story with a reference gets ONE block at gate A: the claims that differ or are not known to,
    the parity requirements with nothing seen, the unused items, the gaps of the walk and a count line; the rest is the count. Mutations
    named, NOT run, each killed here: the differing claims not filtered by `differs` (the 2-of-20 key); an unused item taken for a used one
    (the unused key); an empty heading for a story that matches (the one-line key); a missing snapshot read as a pass (the unreadable key);
    the cap off by one (the AT and BEYOND keys); a story with no reference gaining a line (the byte-identity key)."""
    shown = gate_brief.REFERENCE_SHOWN
    # edge 1: a story with NO reference reads as it did, byte for byte
    base = story("qa-gate-brief-pc9c-none-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("PC-9c no reference: the facts say none", data["reference"], {"state": "none"})
        check_eq("PC-9c no reference: no line", gate_brief._reference_lines(data), [])
        check_eq("PC-9c no reference: gate A text is byte-identical to the text without the key",
                 gate_brief.render(data), gate_brief.render({k: v for k, v in data.items() if k != "reference"}))
    finally:
        cleanup(base.parent)
    # (b) 20 items, 2 differences, the other 18 used by cases: exactly the 2 and the count line
    base = pc9c_story("qa-gate-brief-pc9c-20-", 20, ["yes", "unknown"], set(range(3, 21)), parity=("R-1", "R-2"))
    task_root = base / "artifacts" / "TP1-15045"
    try:
        data = gate_brief.collect("TP1-15045", task_root)
        text = gate_brief.render(data)
        block = text.split("## The old version as the reference (old)")[1].split("\n## ")[0].splitlines()
        shown_rows = [l for l in block if l.startswith("- R-")]
        check_eq("PC-9c 20 items, 2 differences: exactly the 2 differences are listed", len(shown_rows), 2)
        check_in("PC-9c ... the first by its requirement and both texts", "- R-1 (requirement 1 words): the old version the old total is 1; the story now the new total is 2", shown_rows[0])
        check_in("PC-9c ... the unknown one says it is not known", "(not known whether this is a difference)", shown_rows[1])
        check_in("PC-9c ... the count line: 18 of 20 carried over", "18 of the 20 behaviours the factory saw in the old version are carried over as they are. All of them are listed in the document below.", block)
        check_in("PC-9c ... and the long documents list the file of every behaviour seen (F1)", "- reference behaviours: work/reference-behaviours.md", text)
        check_not_in("PC-9c ... no unused list, no gap list", "used by no test case", "\n".join(block))
        check_in("PC-9c ... the approval confirms the parity requirements (F-7)", "these requirements ask to match the old version: R-1, R-2.", block)
        check_in("PC-9c ... the sample sentence (W1)", "is not evidence for it", block)
        check_eq("PC-9c ... the block stands in the head, before the rehearsal",
                 text.splitlines().index("## After your approval") > text.splitlines().index("## The old version as the reference (old)") > 0, True)
        for raw in ("item-0", "reference:", "before_ref", ".yaml", "reference-snapshot", "parity"):
            check_not_in(f"PC-9c ... no raw key `{raw}` in the block", raw, "\n".join(block))
        # edge 6 (W1): gate_brief reads NO run ledger, so a run recorded on the reference stand cannot reach the block. This is a pin of
        # absence, made able to fail: the reference readers' source names no ledger, and a ledger written beside them is not shown (N2)
        import inspect
        source = "".join(inspect.getsource(fn) for fn in (gate_brief.reference_facts, gate_brief._reference_uses, gate_brief._reference_lines,
                                                           gate_brief.reference_behaviours_text))
        check_not_in("PC-9c W1: the reference readers read no run ledger (a pin of absence: reading one fails this)", "ledger", source.lower())
        (task_root / "work" / "run-ledger.json").write_text(json.dumps({"runs": [{"id": "RUN-ON-REFERENCE-77", "stand": "old", "result": "passed"}]}), encoding="utf-8")
        check_not_in("PC-9c a run recorded on the reference stand is not shown as evidence", "RUN-ON-REFERENCE-77", gate_brief.render(gate_brief.collect("TP1-15045", task_root)))
        check_not_in("PC-9c ... the block is inside the budget of the cover sheet: the packet is not cut", "brief truncated", text)
    finally:
        cleanup(base.parent)
    # edge 3: zero differences and zero gaps: ONE line with the count, no heading
    base = pc9c_story("qa-gate-brief-pc9c-same-", 20, ["no"], set(range(1, 21)))
    task_root = base / "artifacts" / "TP1-15045"
    try:
        lines = gate_brief._reference_lines(gate_brief.collect("TP1-15045", task_root))
        check_eq("PC-9c zero differences and zero gaps: a blank line and ONE line", len(lines), 2)
        check_in("PC-9c ... it says the story matches on all 20 behaviours", "this story matches the old version (old) on all 20 behaviours", lines[1])
        check_not_in("PC-9c ... and there is no empty heading", "## The old version", gate_brief.render(gate_brief.collect("TP1-15045", task_root)))
    finally:
        cleanup(base.parent)
    # (c) the claim of R-2 differs, R-3 asks to match and nothing was seen, items 4 and 5 are used by no case, the walk has a gap line
    base = pc9c_story("qa-gate-brief-pc9c-all-", 5, ["no", "yes"], {1, 2, 3}, parity=("R-1", "R-2", "R-3"), gaps=["the checkout page needs a sign-in the factory did not have"])
    task_root = base / "artifacts" / "TP1-15045"
    try:
        facts = gate_brief.collect("TP1-15045", task_root)["reference"]
        check_eq("PC-9c the differing claim is the one with `yes`", [d["r"] for d in facts["differing"]], ["R-2"])
        check_eq("PC-9c the parity requirement with nothing seen is R-3 (R-1 rests on a case, R-2 on a claim)", [g["r"] for g in facts["parity_gaps"]], ["R-3"])
        check_eq("PC-9c the unused items are listed by their words (item 2 is shown by its claim, 1 and 3 by cases)",
                 facts["unused"], ["page 4 — open page 4 and read the total", "page 5 — open page 5 and read the total"])
        text = "\n".join(gate_brief._reference_lines({"reference": facts}))
        check_in("PC-9c the unused list is counted", "Seen in the old version and used by no test case (2):", text)
        check_in("PC-9c the gap of the walk is shown", "the checkout page needs a sign-in the factory did not have", text)
        check_in("PC-9c the count line: 2 of 5 carried over (5 less the claim's item and the 2 unused)", "2 of the 5 behaviours", text)
        check_in("PC-9c ... the requirement with nothing seen is named", "- R-3 (requirement 3 words)", text)
    finally:
        cleanup(base.parent)
    # edge 2: a snapshot that is absent, or cannot be read: a plain sentence, the full brief as today, never a pass (AR-28)
    for label, damage in (("absent", None), ("unreadable", b"items: [\n\t- {{{")):
        base = pc9c_story(f"qa-gate-brief-pc9c-{label}-", 3, [], set(), with_snapshot=damage is not None)
        task_root = base / "artifacts" / "TP1-15045"
        try:
            if damage is not None:
                (task_root / "work" / "reference-snapshot.yaml").write_bytes(damage)
            data = gate_brief.collect("TP1-15045", task_root)
            check_eq(f"PC-9c snapshot {label}: unreadable, with the stand", (data["reference"]["state"], data["reference"]["env"]), ("unreadable", "old"))
            said = gate_brief._reference_lines(data)
            check_eq(f"PC-9c snapshot {label}: ONE line after a blank line, in plain words", (len(said), "could not be read" in said[1]), (2, True))
            full = gate_brief.render(data)
            check_in(f"PC-9c snapshot {label}: the brief is shown whole as today", "## After your approval", full)
            check_not_in(f"PC-9c snapshot {label}: never an empty section or a match line", "matches the old version", full)
        finally:
            cleanup(base.parent)
    # edge 4 and 5: the cap AT and BEYOND, for the differences and for the unused items
    for count in (shown, shown + 1, shown + 5):
        base = pc9c_story(f"qa-gate-brief-pc9c-cap{count}-", count + 2, ["yes"] * count, set())
        task_root = base / "artifacts" / "TP1-15045"
        try:
            text = "\n".join(gate_brief._reference_lines(gate_brief.collect("TP1-15045", task_root)))
            listed = [l for l in text.splitlines() if l.startswith("- R-")]
            check_eq(f"PC-9c {count} differences: at most {shown} are listed", len(listed), min(count, shown))
            check_eq(f"PC-9c {count} differences: the rest is counted, not cut in silence",
                     [l for l in text.splitlines() if l.startswith("- and ") and "more" in l][:1],
                     [f"- and {count - shown} more"] if count > shown else [])
            check_in(f"PC-9c {count} differences: the heading says all {count}", f"({count}):", text)
            names = [l for l in text.splitlines() if l.startswith("- page ")]
            check_eq(f"PC-9c {count} differences, 2 unused items: both unused items are listed by name", len(names), 2)
        finally:
            cleanup(base.parent)
    base = pc9c_story("qa-gate-brief-pc9c-unused-", shown + 3, ["no"], set())
    task_root = base / "artifacts" / "TP1-15045"
    try:
        lines = gate_brief._reference_lines(gate_brief.collect("TP1-15045", task_root))
        check_eq(f"PC-9c {shown + 3} unused items: {shown} by name and the count of the rest",
                 (len([l for l in lines if l.startswith("- page ")]), "- and 3 more" in lines), (shown, True))
    finally:
        cleanup(base.parent)
    # a register that cannot be read: differences and gaps are NOT known, and the block says so (never none)
    base = pc9c_story("qa-gate-brief-pc9c-noreg-", 4, ["yes"], {1, 2, 3, 4})
    task_root = base / "artifacts" / "TP1-15045"
    try:
        (task_root / "work" / "requirements-register.md").write_text("no table here\n", encoding="utf-8")
        text = "\n".join(gate_brief._reference_lines(gate_brief.collect("TP1-15045", task_root)))
        check_in("PC-9c an unread register is said, not read as no difference", "could not be read, so where the story differs", text)
        check_not_in("PC-9c ... and no match line is made of it", "matches the old version", text)
    finally:
        cleanup(base.parent)
    # F2: ONE list renderer, so the cap AT and BEYOND holds for all four lists, the parity requirements and the gaps of the walk too
    for count in (shown, shown + 1, shown + 5):
        base = pc9c_story(f"qa-gate-brief-pc9c-lists{count}-", 1, [], {1}, parity=tuple(f"R-{n}" for n in range(1, count + 1)),
                          gaps=[f"gap line {n}" for n in range(1, count + 1)])
        task_root = base / "artifacts" / "TP1-15045"
        try:
            text = gate_brief._reference_lines(gate_brief.collect("TP1-15045", task_root))
            rest = [f"- and {count - shown} more"] if count > shown else []
            parity_lines = [l for l in text if l.startswith("- R-")]
            check_eq(f"PC-9c F2 {count} parity requirements with nothing seen: at most {shown} listed", len(parity_lines), min(count - 1, shown))
            gap_lines = [l for l in text if l.startswith("- gap line")]
            check_eq(f"PC-9c F2 {count} gaps of the walk: at most {shown} listed", len(gap_lines), min(count, shown))
            check_in(f"PC-9c F2 {count} gaps: the heading counts all of them", f"What the factory could not see of the old version ({count}):", "\n".join(text))
            check_eq(f"PC-9c F2 {count} gaps: the rest of the gaps is counted", [l for l in text[text.index(gap_lines[0]):] if l.startswith("- and ")][:1], rest)
            parity_rest = [f"- and {count - 1 - shown} more"] if count - 1 > shown else []
            after = text[text.index(parity_lines[0]):text.index(f"What the factory could not see of the old version ({count}):")]
            check_eq(f"PC-9c F2 {count} parity requirements: the rest is counted", [l for l in after if l.startswith("- and ")][:1], parity_rest)
        finally:
            cleanup(base.parent)
    # F4 (F-7): a story that matches on everything, with no parity requirement, says its approval confirms none, like the full block
    base = pc9c_story("qa-gate-brief-pc9c-same-noparity-", 3, ["no"], {1, 2, 3}, parity=())
    task_root = base / "artifacts" / "TP1-15045"
    try:
        lines = gate_brief._reference_lines(gate_brief.collect("TP1-15045", task_root))
        check_eq("PC-9c F4 matches, no parity requirement: still ONE line after a blank line", (len(lines), lines[0]), (2, ""))
        check_in("PC-9c F4 ... and it says the approval confirms none", "so your approval confirms none.", lines[1])
        check_in("PC-9c F4 ... and the sample sentence stands before it", "is not evidence for it", lines[1])
    finally:
        cleanup(base.parent)


def test_pc9c_every_behaviour_is_written_to_the_reference_behaviours_document() -> None:
    """F1 (critic t-2549, D3 'the attached document'): `write_gate_message` writes `work/reference-behaviours.md` from the same facts as
    the block: every snapshot item in words, marked carried over / differs / used by no test case, the walk's gaps whole (no cap). Edges:
    a story with no reference or an unreadable snapshot gets no file; the count line and the long documents point to it only when it is
    written (the driver mode writes no message, so names no document)."""
    base = pc9c_story("qa-gate-brief-pc9c-doc-", 20, ["yes", "no"], set(range(3, 19)), parity=("R-1",), gaps=[f"gap line {n}" for n in range(1, 13)])
    task_root = base / "artifacts" / "TP1-15045"
    try:
        data = gate_brief.collect("TP1-15045", task_root)
        text = gate_brief.render(data)
        path = gate_brief.write_gate_message(task_root, text, "s-1")
        doc = (task_root / "work" / gate_brief.REFERENCE_BEHAVIOURS).read_text(encoding="utf-8")
        check_eq("PC-9c F1 the message is written beside the document", path.name, "gate-a-message.md")
        check_eq("PC-9c F1 every one of the 20 behaviours is in the document, by its words", len([l for l in doc.splitlines() if l.startswith("- page ")]), 20)
        check_in("PC-9c F1 ... the claim's item differs, with its requirement", "- page 1 — open page 1 and read the total (R-1): total 1", doc)
        check_in("PC-9c F1 ... the sections count the standings: 1 differs, 16 carried (item 2 is cited by a claim that says no: used by no case)", "## Differs from the story (1)", doc)
        facts = data["reference"]
        counts = {k: sum(1 for b in facts["behaviours"] if b["standing"] == k) for k in ("differs", "carried", "unused")}
        check_eq("PC-9c F1 the document and the count line read the same lists", (counts["carried"], facts["carried"], len(facts["unused"]), counts["unused"]),
                 (facts["carried"], facts["carried"], counts["unused"], counts["unused"]))
        check_in("PC-9c F1 ... the carried section carries the count line's number", f"## Carried over as they are ({facts['carried']})", doc)
        check_in("PC-9c F1 ... the walk's 12 gaps are listed whole (the brief caps at 8)", "- gap line 12", doc)
        check_in("PC-9c F1 the count line points to the document and the long documents list it", "All of them are listed in the document below.", text)
        check_in("PC-9c F1 ... the sample sentence stands in the document", "is not evidence for it", doc)
    finally:
        cleanup(base.parent)
    base = story("qa-gate-brief-pc9c-doc-none-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        gate_brief.write_gate_message(task_root, gate_brief.render(gate_brief.collect("TP1-15045", task_root)), "s-1")
        check_eq("PC-9c F1 no reference: no document", (task_root / "work" / gate_brief.REFERENCE_BEHAVIOURS).exists(), False)
    finally:
        cleanup(base.parent)
    base = pc9c_story("qa-gate-brief-pc9c-doc-unread-", 3, [], set())
    task_root = base / "artifacts" / "TP1-15045"
    try:
        (task_root / "work" / "reference-snapshot.yaml").write_bytes(b"items: [\n\t- {{{")
        data = gate_brief.collect("TP1-15045", task_root)
        gate_brief.write_gate_message(task_root, gate_brief.render(data), "s-1")
        check_eq("PC-9c F1 an unreadable snapshot: no document, and none named", ((task_root / "work" / gate_brief.REFERENCE_BEHAVIOURS).exists(),
                                                                                  "reference behaviours" in data["documents"]), (False, False))
    finally:
        cleanup(base.parent)
    base = pc9c_story("qa-gate-brief-pc9c-doc-driver-", 3, ["no"], {1, 2, 3})
    task_root = base / "artifacts" / "TP1-15045"
    saved = os.environ.get(gate_brief.RUN_MODE_ENV)
    try:
        os.environ[gate_brief.RUN_MODE_ENV] = "driver"
        data = gate_brief.collect("TP1-15045", task_root)
        check_eq("PC-9c F1 the driver mode names no document (it writes no message file)", ("reference behaviours" in data["documents"], "document" in data["reference"]), (False, False))
        check_not_in("PC-9c F1 ... and the count line points nowhere", "document below", gate_brief.render(data))
    finally:
        if saved is None:
            os.environ.pop(gate_brief.RUN_MODE_ENV, None)
        else:
            os.environ[gate_brief.RUN_MODE_ENV] = saved
        cleanup(base.parent)


def test_pc9c_f3_the_project_root_walk_has_one_copy() -> None:
    """F3 (critic t-2549): `portable`, `project_config` and the filing line go through `_project_root_of`, like the reference facts."""
    base = story("qa-gate-brief-pc9c-root-")
    task_root = base / "artifacts" / "TP1-15045"
    try:
        root = gate_brief._project_root_of(task_root)
        check_eq("PC-9c F3 the project root is the folder above `qa-factory/config.json`", root, base.parent.resolve())
        check_eq("PC-9c F3 `portable` is relative to it", gate_brief.portable(task_root / "work" / "x.md", task_root), (task_root / "work" / "x.md").resolve().relative_to(root).as_posix())
        check_eq("PC-9c F3 `project_config` reads the config found by the same walk", gate_brief.project_config(task_root), json.loads((base / "config.json").read_text(encoding="utf-8")))
        import inspect
        check_eq("PC-9c F3 the marker walk is written once in gate_brief", inspect.getsource(gate_brief).count('/ "config.json").is_file()'), 1)
    finally:
        cleanup(base.parent)


if __name__ == "__main__":
    test_pc9c_gate_a_for_a_story_with_a_reference()
    test_pc9c_every_behaviour_is_written_to_the_reference_behaviours_document()
    test_pc9c_f3_the_project_root_walk_has_one_copy()
    test_g2_5_grounding_lines_at_gate_a()
    test_rh16_open_rehearsal_items_one_reader_and_its_doors()
    test_rh16_b1_the_one_reader_drops_a_doorless_item_the_person_passed_as_is()
    test_rh16_the_packet_line_and_open_before_mr()
    test_c14b_approval_words_are_the_raw_words_of_the_data_file_and_an_unreadable_file_has_none()
    test_t674_c_rows_gate_brief_read_json_keeps_its_direction()
    test_b416_n7_the_card_shows_what_the_helper_understood_at_400_and_not_at_401()
    test_b416_n8_the_adapted_block_lists_only_proven_adaptations_five_lines_then_the_count()
    test_b414_the_card_says_one_case_or_a_whole_level_and_what_accept_always_records()
    test_b414_a_level_card_names_six_cases_and_counts_the_rest()
    test_b414_the_covered_block_is_the_only_text_when_every_gap_is_covered()
    test_b414_the_answer_reader_reads_lasting_words_levels_and_ask_again()
    test_t409_h4_an_unknown_word_names_the_words_that_apply_to_that_card()
    test_t409_h3_the_conductor_relay_and_the_phase_say_the_words_per_card()
    test_t667_d17_the_relay_note_reads_one_context_and_the_stage_default_reaches_the_lines()
    test_b220_p2_the_reporter_card_takes_its_own_words_and_change_only_with_a_cure()
    test_b220_p2_the_command_line_is_read_whole_and_never_as_a_waiver()
    test_b220_p2_every_edge_of_the_command_line_is_unread_in_words_and_writes_nothing()
    test_b220_p2_the_list_of_probe_answers_is_data_and_a_damaged_row_is_named()
    test_b220_p2_the_card_lists_only_the_words_an_open_card_takes()
    test_b220_p2_a_command_answer_is_probed_sealed_asked_and_applied_only_on_a_yes()
    test_b220_p2_a_headless_approval_of_a_person_command_is_refused_like_a_cure()
    test_b220_p2_a_command_the_factory_cannot_run_is_refused_in_words_and_never_recorded()
    test_b220_p2_a_yes_after_the_config_moved_is_refused_with_a_door_and_shows_no_script()
    test_t370_b_a_gate_brief_that_failed_shows_a_person_no_script_and_no_exit_code()
    test_t364_one_list_of_stand_gaps_per_gate_is_what_the_card_shows_and_the_answer_reads()
    test_t373_already_decided_is_the_person_list()
    test_t363_b1_the_driver_gate_text_lists_waivers_in_words()
    test_t279_k_hash_the_card_carries_the_row_hash_and_the_applier_stores_that_one()
    test_t279_k_fence_a_decision_in_a_code_block_is_said_not_read()
    test_t256_o3_a_before_now_card_shows_both_behaviours_and_a_legacy_card_nothing_extra()
    test_t256_o6_the_packet_says_how_to_accept_a_case_as_blocked()
    test_t683_d8_render_is_byte_for_byte_what_it_was()
    test_the_card_and_the_applier_read_one_patch_resolver()
    test_an_id_in_a_waiver_an_override_or_a_remark_is_named_never_answered()
    test_hf27_p3_question_note_says_where_in_words_and_still_open_reads_the_one_definition()
    test_hf8_12_a_capability_the_story_proved_after_s0_leaves_the_brief()
    test_oh1_11_an_unknown_probe_is_not_shown_at_gate_a()
    test_oh1_11_s0_says_unknown_is_not_shown_at_gate_a()
    test_gate_a_brief()
    test_gate_a_brief_obeys_the_human_text_rules()
    test_an_answer_is_read_against_the_packet()
    test_gate_brief_degrades()
    test_t2187_n3b_a_merged_bug_is_one_row_with_its_ways_and_one_door_block()
    test_t2187_n3b_the_unknown_is_said_as_unknown_and_the_cap_holds_at_six_and_seven()
    test_t2187_n3b_linked_drafts_get_the_merge_block_without_a_multi_manifestation_row()
    test_t2187_n3b_an_unverified_cause_is_printed_as_a_hypothesis()
    test_gate_b_bug_list_is_rendered_by_code()
    test_t1676_code_reading_candidates_and_cuts_by_words()
    test_gate_b_names_the_direct_api_author()
    test_an_experiment_packet_says_filing_is_closed()
    test_the_size_the_code_computed_reaches_the_person()
    test_retro_numbers()
    test_retro_numbers_refuses_a_false_hundred_percent()
    test_story_spend_is_shared_with_the_ceiling()
    test_gate_a_left_out_lines()
    test_gate_a_left_out_beside_other_decisions()
    test_gate_a_cap_5_6()
    test_gate_a_unmatched()
    test_gate_a_revoked()
    test_gate_a_factory_marker_origin()
    test_gate_a_reason_clip_and_encoding()
    test_gate_a_left_out_lines_unit()
    test_gate_a_unreadable_record_and_no_inventory()
    test_retro_lists_whole_reason()
    test_no_record_changes_nothing()
    test_gate_b_rejected_by_the_code_critic()
    test_c29_not_reachable_section()
    finish("gate brief and retro numbers")
