"""V14/V15: partial valuation and explicit nested activity attribution."""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / f".usage-activity-test-{os.getpid()}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import activity_capture as A
import cost_capture as C
import telemetry_capture as T


ACME = {"id": "acme", "command_re": r"(?:^|[;&|\n])\s*acme-cli\s+ask(?:\s|$)",
        "consumer_re": r"--bot[= ](\S+)", "call_id_prefix": "acme", "invocation_method": "acme-cli ask",
        "provider": "acme", "service": "bots", "unknown_consumer_label": "Acme bot (identity unavailable)"}
ASSIST = {"id": "assist", "command_re": r"(?:^|[;&|\n])\s*&?\s*assist-cli\s+chat(?:\s|$)",
          "consumer_re": r"--assistant(?:-id|-name)?(?:=|\s+)[\"']?([A-Za-z0-9_.-]{1,128})", "call_id_prefix": "assist",
          "invocation_method": "assist-cli chat", "provider": "assist", "service": "assistants",
          "unknown_consumer_label": "Assist assistant (identity unavailable)"}
GOLDEN = {"external_call_id": "assist:f967e8f11c607ec0ee9376ba", "consumer_agent": "jira-assistant",
          "invocation_method": "assist-cli chat", "provider": "assist", "service": "assistants",
          "usage_status": "pending", "reason": "Remote usage receipt was not present in the host transcript",
          "observed_at": "2026-01-01T00:03:00+00:00", "task": "T"}


def write_transcript(path, *commands, first_id="tool-0"):
    """One Bash tool_use per command, ids first_id, tool-1, tool-2, ..."""
    path.write_text("\n".join(json.dumps({"type": "assistant", "requestId": f"r{i}", "uuid": f"u{i}",
        "timestamp": "2026-01-01T00:03:00Z", "message": {"model": "model-exact", "usage": {"input_tokens": 1},
        "content": [{"type": "tool_use", "id": first_id if i == 0 else f"tool-{i}", "name": "Bash",
                     "input": {"command": cmd}}]}}) for i, cmd in enumerate(commands)) + "\n", encoding="utf-8")


def calls_of(path, forms=None, problems=None):
    _, tools, markers, *_ = C.scan_file(path, True, forms)
    return C.inferred_external_calls(tools, markers, "T", forms, problems)


def external_forms_checks():
    """K-D1..K-D4 (B-407 D): the external-agent call forms are data, and the package ships none: a project names its own."""
    transcript = ROOT / "forms.jsonl"
    # the package list is empty: no row, no problem, no form printed
    package = json.loads((Path(__file__).resolve().parents[2] / "references/external-agent-calls.json").read_text("utf-8"))
    assert package["forms"] == []
    rows, problem = C.external_forms()
    assert rows == [] and problem == ""
    # K-D1 GOLDEN: the project's row counts a call under its own prefix (tool-123 / --assistant jira-assistant)
    mine, problem = C.external_forms([ASSIST])
    assert [r["id"] for r in mine] == ["assist"] and problem == ""
    write_transcript(transcript, "assist-cli chat --assistant jira-assistant", first_id="tool-123")
    assert calls_of(transcript, mine) == [GOLDEN]
    write_transcript(transcript, "assist-cli chat")
    assert [x["consumer_agent"] for x in calls_of(transcript, mine)] == ["Assist assistant (identity unavailable)"]
    # an agent whose form is in no row is a shell command like any other: no call, `complete` as the
    # sources say, and the form is NOT in the printed list (the only way it can be seen, FR-41)
    assert calls_of(transcript) == []
    bare = C.external_reconciliation([], "", C.external_forms()[0])
    assert bare["complete"] is True and bare["recognized_forms"] == []
    # K-D2: a second form is a pending call under its own prefix; both ids are named
    rows, problem = C.external_forms([ASSIST, ACME])
    assert [r["id"] for r in rows] == ["assist", "acme"] and problem == ""
    write_transcript(transcript, "acme-cli ask --bot helper")
    problems = []
    calls = calls_of(transcript, rows, problems)
    assert len(calls) == 1 and calls[0]["external_call_id"].startswith("acme:") and problems == []
    assert calls[0]["consumer_agent"] == "helper" and calls[0]["usage_status"] == "pending"
    assert calls[0]["invocation_method"] == "acme-cli ask" and calls[0]["provider"] == "acme"
    reconciliation = C.external_reconciliation(calls, problem, rows)
    assert reconciliation["complete"] is False and reconciliation["recognized_forms"] == ["assist", "acme"]
    # E-D2: two agents in one command are two calls, one form twice is one call, a span an earlier row
    # matched is not matched again
    write_transcript(transcript, "assist-cli chat --assistant x; acme-cli ask --bot y")
    two = calls_of(transcript, rows)
    assert sorted(x["external_call_id"].split(":")[0] for x in two) == ["acme", "assist"]
    assert len({x["external_call_id"] for x in two}) == 2
    write_transcript(transcript, "acme-cli ask --bot a\nacme-cli ask --bot b")
    assert [x["consumer_agent"] for x in calls_of(transcript, rows)] == ["a"]
    overlap = {**ACME, "id": "second", "call_id_prefix": "second", "command_re": r"assist-cli\s+chat"}
    write_transcript(transcript, "assist-cli chat --assistant x")
    assert [x["external_call_id"].split(":")[0] for x in calls_of(transcript, C.external_forms([ASSIST, overlap])[0])] == ["assist"]
    # item 10: the consumer value must be [A-Za-z0-9_.-]{1,128}; a `:` would shift the key's split
    for odd in ("a:b", "x" * 129, "a/b"):
        write_transcript(transcript, "acme-cli ask --bot " + odd)
        shifted = calls_of(transcript, rows)
        assert [x["consumer_agent"] for x in shifted] == ["Acme bot (identity unavailable)"], odd
        assert shifted[0]["observed_at"] == "2026-01-01T00:03:00+00:00"
    write_transcript(transcript, "acme-cli ask --bot " + "x" * 128)
    assert calls_of(transcript, rows)[0]["consumer_agent"] == "x" * 128
    # K-D3: a key with no `~` names no form (a checkpoint older than the rows): still a call, and named (FR-41)
    legacy = {"__external__:abc123:jira-assistant:2026-01-01T00:03:00+00:00": 1}
    unmarked = []
    old = C.inferred_external_calls(dict(legacy), [], "T", rows, unmarked)
    assert [(x["external_call_id"], x["consumer_agent"]) for x in old] == [("unmarked:abc123", "jira-assistant")]
    assert len(unmarked) == 1 and "unmarked" in unmarked[0]
    # a key whose form no row names is still a call, and is named (never lost silently)
    ghost, named = {"__external__:ghost~abc:who:unknown": 1}, []
    lost = C.inferred_external_calls(ghost, [], "T", rows, named)
    assert [x["external_call_id"] for x in lost] == ["ghost:abc"] and lost[0]["observed_at"] is None
    assert len(named) == 1 and "ghost" in named[0] and not ghost
    # E-D4 / item 10: a project row can only ADD forms; a bad one is skipped, named, and `complete` False
    for bad, word in (({**ACME, "id": "a:b"}, "id"), ({**ACME, "id": "a~b"}, "id"), ({**ACME, "id": "a b"}, "id"),
                      ({**ACME, "id": "acme\n"}, "id"), ({**ACME, "call_id_prefix": "A"}, "call_id_prefix"),
                      ({**ACME, "consumer_re": r"--bot[= ]\S+"}, "group"), ({**ACME, "command_re": "("}, "compile"),
                      ({**ACME, "command_re": "x*"}, "empty"), ({**ACME, "provider": ""}, "provider"),
                      ({**ACME, "id": "assist"}, "reuses"), ({**ACME, "call_id_prefix": "assist"}, "reuses"),
                      ("acme", "object")):
        kept, why = C.external_forms([ASSIST, bad])
        assert [r["id"] for r in kept] == ["assist"] and word in why, (bad, why)
        assert C.external_reconciliation([], why, kept)["complete"] is False
    kept, why = C.external_forms([ACME, ACME])
    assert [r["id"] for r in kept] == ["acme"] and "reuses id" in why
    kept, why = C.external_forms({"id": "acme"})
    assert kept == [] and "not a list" in why
    # K-D4: unreadable or invalid package data -> no package row is used, `complete` False, the problem named;
    # the project's own row still counts
    real_load = C.load_ref_json
    try:
        for broken in ({}, [], {"forms": "x"}, {"forms": [{"id": "x"}]}, {"forms": [ASSIST, {"id": "bad"}]}):
            C.load_ref_json = lambda name, broken=broken: broken
            none, why = C.external_forms()
            assert none == [] and "no package form is used" in why, (broken, why)
            kept, why = C.external_forms([ASSIST])
            assert [r["id"] for r in kept] == ["assist"] and "no package form is used" in why, (broken, why)
            write_transcript(transcript, "assist-cli chat --assistant jira-assistant")
            recorded = calls_of(transcript, kept)
            assert len(recorded) == 1 and recorded[0]["external_call_id"].startswith("assist:")
            assert recorded[0]["consumer_agent"] == "jira-assistant" and recorded[0]["provider"] == "assist"
            broke = C.external_reconciliation([], why, kept)
            assert broke["complete"] is False and broke["forms_problem"] == why and broke["recognized_forms"] == ["assist"]
        # data that holds a row (a package may carry one) still adds only through the validated path
        C.load_ref_json = lambda name: {"forms": [ASSIST, ACME]}
        assert [r["id"] for r in C.external_forms()[0]] == ["assist", "acme"]
    finally:
        C.load_ref_json = real_load
    # end to end through the real hook: the cost file names the forms beside the price, the project's
    # rows are read from config, and a config list that is not a list names itself
    both = ("assist-cli chat --assistant jira-assistant", "acme-cli ask --bot helper")
    for tag, cost_cfg, commands, want_forms, want_problem, want_calls in (
            ("ok", {"external_agent_forms": [ASSIST, ACME]}, both, ["assist", "acme"], False, ["acme", "assist"]),
            ("bad", {"external_agent_forms": "acme"}, both, [], True, []),
            ("none", {"external_agent_forms": "acme"}, ("git status",), [], True, [])):   # no call, still a problem
        project = ROOT / ("forms-project-" + tag)
        (project / "qa-factory").mkdir(parents=True)
        (project / "qa-factory/config.json").write_text(json.dumps({"cost": cost_cfg}), encoding="utf-8")
        session = project / "session.jsonl"
        write_transcript(session, *commands)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
        event = {"hook_event_name": "Stop", "session_id": "forms-" + tag, "transcript_path": str(session), "cwd": str(project)}
        for _ in (1, 2):   # the second run is the idempotent recapture: no call twice, none lost
            run = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "cost_capture.py")],
                                 input=json.dumps(event), text=True, capture_output=True, cwd=project, env=env)
            assert run.returncode == 0, run.stderr
            document = json.loads((project / "qa-factory/state/cost" / f"forms-{tag}.json").read_text("utf-8"))
            reconciliation = document["external_reconciliation"]
            assert reconciliation["recognized_forms"] == want_forms, reconciliation
            assert bool(reconciliation.get("forms_problem")) is want_problem and reconciliation["complete"] is False
            assert document["reconciliation"]["match"] is None
            assert document["telemetry_coverage"]["external_usage"] == ("incomplete" if want_problem else "partial")
            assert sorted(x["external_call_id"].split(":")[0] for x in document["external_calls"]) == want_calls


def external_keys(tools):
    return sorted(k for k in tools if k.startswith("__external__:"))


def checkpoint_forms_checks():
    """F1 (critic t-547): a scan checkpoint remembers WHICH forms scanned the file. A file scanned with other
    rows is rescanned whole, or `recognized_forms` would claim a form for calls never looked for (FR-41)."""
    transcript = ROOT / "ckpt.jsonl"
    write_transcript(transcript, "acme-cli ask --bot helper", "assist-cli chat --assistant x")
    base, both = C.external_forms([ASSIST])[0], C.external_forms([ASSIST, ACME])[0]
    first = C.scan_file_incremental(transcript, forms=base)
    assert len(external_keys(first[1])) == 1 and external_keys(first[1])[0].startswith("__external__:assist~")
    assert first[-1]["forms"] == C.forms_fingerprint(base)
    C.inferred_external_calls(first[1], first[2], "T", base)          # as _capture does: the keys are consumed
    rows = [{"request_id": rid, "model_id": model, "timestamp": ts.isoformat() if ts else None,
             "usage": {"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                       "cache_read": u.get("cache_read_input_tokens", 0),
                       "cache_write_5m": (u.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0),
                       "cache_write_1h": (u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0)}}
            for rid, (model, u, ts) in first[0].items()]       # the cost file's requests[] (the H1 guard re-reads a checkpoint with usage but no rows)
    steady = C.scan_file_incremental(transcript, first[-1], rows, forms=base)
    assert external_keys(steady[1]) == []                              # same rows, same file: not scanned again
    grown = C.scan_file_incremental(transcript, steady[-1], rows, forms=both)   # a row was added after the scan
    assert [k.split(":")[1].split("~")[0] for k in external_keys(grown[1])].count("acme") == 1, external_keys(grown[1])
    assert grown[-1]["forms"] == C.forms_fingerprint(both)
    assert sorted(x["external_call_id"].split(":")[0] for x in C.inferred_external_calls(grown[1], grown[2], "T", both)) == ["acme", "assist"]
    again = C.scan_file_incremental(transcript, grown[-1], rows, forms=both)
    assert external_keys(again[1]) == []                               # steady again under the new rows
    # (i) a checkpoint made before the fingerprint existed: one rebuild, then steady
    old = dict(again[-1]); old.pop("forms")
    rebuilt = C.scan_file_incremental(transcript, old, [], forms=both)
    assert len(external_keys(rebuilt[1])) == 2 and rebuilt[-1]["forms"] == C.forms_fingerprint(both)
    C.inferred_external_calls(rebuilt[1], rebuilt[2], "T", both)
    assert external_keys(C.scan_file_incremental(transcript, rebuilt[-1], rows, forms=both)[1]) == []
    # (ii) a damaged table (no package row) fingerprints the project's rows alone; a readable table with another row differs
    real_load = C.load_ref_json
    try:
        C.load_ref_json = lambda name: {}
        damaged = C.external_forms([ASSIST])[0]
        C.load_ref_json = lambda name: {"forms": [ACME]}
        readable = C.external_forms([ASSIST])[0]
    finally:
        C.load_ref_json = real_load
    assert C.forms_fingerprint(damaged) != C.forms_fingerprint(readable) and [r["id"] for r in readable] == ["acme", "assist"]
    # (iii) the fingerprint does not depend on dict ordering or on the file's whitespace
    shuffled = [{k: r[k] for k in reversed(list(r))} for r in both]
    assert C.forms_fingerprint(shuffled) == C.forms_fingerprint(both)
    assert C.forms_fingerprint(C.external_forms([ASSIST, json.loads(json.dumps(ACME, indent=4))])[0]) == C.forms_fingerprint(both)
    # end to end through the real hook, a story session (checkpoints are used): the project adds a row AFTER a
    # capture; the same unchanged transcript is then scanned with it, and acme is named only because it was
    project = ROOT / "forms-project-grow"
    (project / "qa-factory/state/activities").mkdir(parents=True)
    config = project / "qa-factory/config.json"
    config.write_text(json.dumps({"cost": {"external_agent_forms": [ASSIST]}}), encoding="utf-8")
    session = project / "session.jsonl"
    write_transcript(session, "acme-cli ask --bot helper")
    A.update(project / "qa-factory/state/activities/grow.json", "grow", "start", "story", task="T-1",
             event_id="e1", timestamp="2025-12-31T00:00:00Z")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
    event = {"hook_event_name": "Stop", "session_id": "grow", "transcript_path": str(session), "cwd": str(project)}

    def capture():
        run = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "cost_capture.py")],
                             input=json.dumps(event), text=True, capture_output=True, cwd=project, env=env)
        assert run.returncode == 0, run.stderr
        return json.loads((project / "qa-factory/state/cost/grow.json").read_text("utf-8"))
    before = capture()
    assert before["external_calls"] == [] and before["external_reconciliation"]["recognized_forms"] == ["assist"]
    assert before["scan_checkpoints"][str(session.resolve())]["forms"]            # the checkpoint was used and fingerprinted
    config.write_text(json.dumps({"cost": {"external_agent_forms": [ASSIST, ACME]}}), encoding="utf-8")
    after = capture()
    assert [x["external_call_id"].split(":")[0] for x in after["external_calls"]] == ["acme"]
    assert after["external_reconciliation"]["recognized_forms"] == ["assist", "acme"]
    assert after["external_reconciliation"]["complete"] is False and after["reconciliation"]["match"] is None


def forms_problem_travels_checks():
    """F5 (critic t-547): with no rows passed, the problem with the package data is not dropped."""
    transcript = ROOT / "travel.jsonl"
    write_transcript(transcript, "assist-cli chat --assistant jira-assistant")
    real_load = C.load_ref_json
    try:
        C.load_ref_json = lambda name: {}
        reconciliation = C.external_reconciliation([])
        assert reconciliation["complete"] is False and "no package form is used" in reconciliation["forms_problem"]
        assert reconciliation["recognized_forms"] == []
        joined = C.external_reconciliation([], "earlier problem")["forms_problem"]
        assert joined.startswith("earlier problem; ") and "no package form is used" in joined   # a caller's problem and the data's both travel
        for scan in (lambda p: C.scan_file(transcript, True, None, p),
                     lambda p: C.scan_file_incremental(transcript, None, None, True, None, p)):
            named = []
            tools = scan(named)[1]
            assert len(named) == 1 and "no package form is used" in named[0] and external_keys(tools) == []
        named = []
        assert len(C.inferred_external_calls({}, [], "T", None, named)) == 0 and len(named) == 1
    finally:
        C.load_ref_json = real_load
    assert "forms_problem" not in C.external_reconciliation([])        # readable data: no problem invented

def main():
    for model, expected in (("claude-opus-5", 5), ("claude-sonnet-5", 2),
                            ("claude-haiku-4-5", 1)):
        rates, provenance = C.resolve_rate(model, {})
        assert rates["input"] == expected and provenance["kind"] == "bundled_exact"
    assert C.resolve_rate("claude-opus-5-unknown", {})[0] is None
    # 5-5 generation: input/output/cache_read quoted by the provider table; an unlisted
    # suffix must stay unpriced (exact match only, FR-41).
    for model, expected in (("claude-sonnet-5-5", (2, 10, 0.1)), ("claude-opus-5-5", (4, 20, 0.2))):
        rates, provenance = C.resolve_rate(model, {})
        assert (rates["input"], rates["output"], rates["cache_read"]) == expected
        assert provenance["kind"] == "bundled_exact"
    assert C.resolve_rate("claude-sonnet-5-5-x", {})[0] is None
    complete = C.value_usage({"input": 1_000_000, "output": 500_000, "cache_read": 0,
        "cache_write_5m": 0, "cache_write_1h": 0}, "model-exact",
        {"rate_overrides": [{"model_id": "model-exact", "aliases": [], "revision": "r1",
         "rates": {"input": 2, "output": 8}}]}, {"catalogue_revision": "c", "entries": []})
    assert complete["subtotal_usd"] == "6" and complete["pricing_coverage"] == "complete"
    partial = C.value_usage({"input": 1_000_000, "output": 500_000, "cache_read": 0,
        "cache_write_5m": 0, "cache_write_1h": 0}, "model-exact",
        {"rate_overrides": [{"model_id": "model-exact", "revision": "r1",
         "rates": {"input": 2}}]}, {"catalogue_revision": "c", "entries": []})
    assert partial["subtotal_usd"] == "2" and partial["pricing_coverage"] == "partial"
    assert partial["missing_rate_categories"] == ["output"]
    assert C.cost_of({"requests": 1, "input": 1_000_000, "output": 1,
        "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0},
        "m", {"m": {"input": 2}}) is None
    empty = C.value_usage({"input": 0, "output": 0, "cache_read": 0,
        "cache_write_5m": 0, "cache_write_1h": 0}, "unknown", {},
        {"catalogue_revision": "c", "entries": []})
    assert empty["subtotal_usd"] == "0" and empty["missing_rate_categories"] == []
    retained = C.request_record("p", "s", "r", "main", "model-exact",
        {"input_tokens": 1_000_000}, None, "a", "seg", "T", {"rate_overrides": [{"model_id":
        "model-exact", "rates": {"input": 99}}]}, {"catalogue_revision": "new", "entries": []},
        {"model_id": "model-exact", "usage": {"requests": 1, "input": 1_000_000,
         "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0},
         "valuation": {"subtotal_usd": "2", "pricing_coverage": "complete"}})
    assert retained["valuation"]["subtotal_usd"] == "2"
    combined = {"requests": 1, "input": 1_000_000, "output": 0, "cache_read": 0,
                "cache_write_5m": 0, "cache_write_1h": 0}
    C.apply_pinned_valuations(combined, [retained])
    assert combined["cost"] == 2 and combined["valuation"]["subtotal_usd"] == "2"
    assert C.resolve_rate("model-exact-suffix", {"rate_overrides": [{"model_id": "model-exact",
        "rates": {"input": 1}}]}, {"catalogue_revision": "c", "entries": []})[0] is None
    rates_doc = json.loads((Path(__file__).resolve().parents[2] / "references/model-rates.json").read_text())
    bundled, bundled_provenance = C.resolve_rate("claude-sonnet-4-20250514", {}, rates_doc)
    assert bundled["input"] == 3 and bundled_provenance["kind"] == "bundled_exact"
    assert C.resolve_rate("claude-sonnet-4-20250514", {}, rates_doc,
                          "anthropic", datetime.fromisoformat("2025-01-01T00:00:00+00:00"))[0] is None
    assert C.resolve_rate("claude-sonnet-4-20250514", {}, rates_doc, "other",
                          datetime.fromisoformat("2026-01-01T00:00:00+00:00"))[0] is None
    assert C.resolve_rate("claude-sonnet-future", {}, rates_doc)[0] is None
    legacy, legacy_provenance = C.resolve_rate("vendor-model-v1",
        {"model_prices": {"model": {"input": 1, "cache_write": 2}}}, rates_doc)
    assert legacy["cache_write_5m"] == 2 and legacy_provenance["kind"] == "legacy_project_override"
    assert C.task_at([(datetime.fromisoformat("2026-01-01T00:02:00+00:00"), "T")],
                     datetime.fromisoformat("2026-01-01T00:01:00+00:00")) == "(no task)"
    calls = C.merge_external_calls([], [{"external_call_id":"x","consumer_agent":"jira-assistant",
        "invocation_method":"assist-cli chat","task":"T","usage_status":"pending"}])
    calls = C.merge_external_calls(calls, [{"external_call_id":"x","consumer_agent":"jira-assistant",
        "invocation_method":"assist-cli chat","task":"T","usage_status":"available",
        "remote_receipt_ref":"receipt:1","cost_usd":"1.25"}])
    assert len(calls) == 1 and C.external_reconciliation(calls)["known_external_subtotal_usd"] == "1.25"
    migration = C.pricing_migration(["vendor-model-v1"], {"model_prices":{"model":{"input":1}}}, rates_doc)
    assert migration["rows"][0]["confirmation"] == "required" and not migration["rows"][0]["applied"]
    telemetry = [T.envelope(event_id="a:start",phase="start",span_kind="hook",source="plugin"),
        T.envelope(event_id="a:end",phase="end",span_kind="hook",source="plugin",duration_ms=10),
        T.envelope(event_id="b:start",phase="start",span_kind="command",source="plugin")]
    reduced = T.reduce(telemetry + [telemetry[1]])
    assert reduced["event_count"] == 3 and reduced["incomplete_spans"] == 1 and reduced["wall_time_ms"] is None
    timing = T.stage_timings([{"kind":"dispatch_started","stage":"S1","timestamp":"2026-01-01T00:00:00Z"},
        {"kind":"stage_done","stage":"S1","timestamp":"2026-01-01T00:00:01Z"},
        {"kind":"output_accepted","stage":"S1","timestamp":"2026-01-01T00:02:00Z"}])
    assert timing["S1"]["wall_seconds"] == 120
    telemetry_path=ROOT / "telemetry.jsonl"; aggregate_path=ROOT / "telemetry-summary.json"
    telemetry_path.parent.mkdir(parents=True,exist_ok=True)
    telemetry_path.write_text("\n".join(json.dumps(x) for x in telemetry[:2])+"\n",encoding="utf-8")
    maintained=T.maintain(telemetry_path,aggregate_path,max_bytes=1)
    assert maintained["rotated"] and aggregate_path.exists()
    aged=ROOT/"aged.jsonl"; aged.write_text("\n".join(json.dumps(x) for x in telemetry[:2])+"\n")
    os.utime(aged,(1,1)); retired=T.maintain(aged,ROOT/"aged.aggregate.json")
    assert not aged.exists() and retired["removed"] and list(ROOT.glob("aged.jsonl.*.aggregate.json"))
    incremental=ROOT / "incremental.jsonl"
    row=lambda rid: json.dumps({"type":"assistant","requestId":rid,"timestamp":"2026-01-01T00:00:00Z",
        "message":{"model":"model-exact","usage":{"input_tokens":1},"content":[]}})
    first, second=row("one"),row("two")
    incremental.write_text(first+"\n"+second[:20],encoding="utf-8")
    result=C.scan_file_incremental(incremental); checkpoint=result[-1]
    assert set(result[0])=={"one"} and checkpoint["partial"]
    prior_rows=[{"request_id":rid,"model_id":v[0],"usage":{"input":v[1].get("input_tokens",0),
        "output":v[1].get("output_tokens",0),"cache_read":0,"cache_write_5m":0,"cache_write_1h":0},
        "timestamp":v[2].isoformat() if v[2] else None} for rid,v in result[0].items()]
    with incremental.open("a",encoding="utf-8") as stream: stream.write(second[20:]+"\n")
    result=C.scan_file_incremental(incremental,checkpoint,prior_rows); checkpoint=result[-1]
    assert set(result[0])=={"one","two"}
    incremental.write_text(row("replacement")+"\n",encoding="utf-8")
    result=C.scan_file_incremental(incremental,checkpoint,prior_rows)
    assert set(result[0])=={"replacement"}
    class ExitSpan(T.Span):
        def finish(self,outcome="ok",reason_code=None): self.finished=(outcome,reason_code)
    span=ExitSpan(ROOT/"unused",span_kind="hook",source="test")
    span.__exit__(SystemExit,SystemExit(0),None)
    assert span.finished==("ok",None)
    assistant=ROOT/"assistant.jsonl"
    assistant.write_text(json.dumps({"type":"assistant","requestId":"local-wrapper","uuid":"tool-event",
        "timestamp":"2026-01-01T00:03:00Z","message":{"model":"model-exact","usage":{"input_tokens":1},
        "content":[{"type":"tool_use","id":"tool-123","name":"PowerShell",
        "input":{"command":"assist-cli chat --assistant jira-assistant"}}]}})+"\n",encoding="utf-8")
    assist_forms=C.external_forms([ASSIST])[0]
    _,assistant_tools,assistant_markers,*_=C.scan_file(assistant,True,assist_forms)
    inferred=C.inferred_external_calls(assistant_tools,assistant_markers,"T",assist_forms)
    assert len(inferred)==1 and inferred[0]["consumer_agent"]=="jira-assistant"
    assert inferred[0]["usage_status"]=="pending" and not any(k.startswith("__external__:") for k in assistant_tools)
    assistant.write_text("\n".join(json.dumps({"type":"assistant","requestId":"r"+str(i),"uuid":"u"+str(i),
        "timestamp":"2026-01-01T00:03:00Z","message":{"model":"model-exact","usage":{"input_tokens":1},
        "content":[{"type":"tool_use","id":"tool-"+str(i),"name":"Bash","input":{"command":cmd}}]}})
        for i,cmd in enumerate(("assist-cli chat --assistant-name jira-assistant",
                                "assist-cli chat --assistant-id 28c25a88-5270-49bd-ae66-8ec96fdb73d7")))+"\n",encoding="utf-8")
    _,distinct_tools,distinct_markers,*_=C.scan_file(assistant,True,assist_forms)
    consumers={x["consumer_agent"] for x in C.inferred_external_calls(distinct_tools,distinct_markers,"T",assist_forms)}
    assert consumers=={"jira-assistant","28c25a88-5270-49bd-ae66-8ec96fdb73d7"}
    external_forms_checks()
    checkpoint_forms_checks()
    forms_problem_travels_checks()
    wrapper_root=ROOT/"wrapper-project"; (wrapper_root/"qa-factory/state").mkdir(parents=True)
    (wrapper_root/"qa-factory/config.json").write_text("{}",encoding="utf-8")
    (wrapper_root/"qa-factory/state/telemetry").write_text("blocks telemetry directory",encoding="utf-8")
    counter=wrapper_root/"count.txt"; target=wrapper_root/"target.py"
    target.write_text("from pathlib import Path\np=Path('count.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\nprint('wrapped-output')\nraise SystemExit(7)\n",encoding="utf-8")
    env=dict(os.environ); env["CLAUDE_PROJECT_DIR"]=str(wrapper_root)
    wrapped=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/"telemetry_hook.py"),str(target)],
        input=json.dumps({"hook_event_name":"PostToolUse","session_id":"s"}),text=True,capture_output=True,cwd=wrapper_root,env=env)
    assert wrapped.returncode==7 and wrapped.stdout.strip()=="wrapped-output" and counter.read_text()=="1"

    shutil.rmtree(ROOT, ignore_errors=True)
    path = ROOT / "activity.json"
    A.update(path, "s", "start", "onboarding", event_id="e1", timestamp="2026-01-01T00:00:00Z")
    A.update(path, "s", "end", "onboarding", event_id="e2", timestamp="2026-01-01T00:01:00Z")
    A.update(path, "s", "start", "story", task="T-1", event_id="e3", timestamp="2026-01-01T00:02:00Z")
    A.update(path, "s", "start", "doctor", event_id="e4", timestamp="2026-01-01T00:03:00Z")
    A.update(path, "s", "end", "doctor", event_id="e5", timestamp="2026-01-01T00:04:00Z")
    A.update(path, "s", "end", "story", task="T-1", event_id="e6", timestamp="2026-01-01T00:05:00Z")
    doc = json.loads(path.read_text())
    story = next(x for x in doc["activities"] if x["type"] == "story")
    doctor = next(x for x in doc["activities"] if x["type"] == "doctor")
    assert len(story["segments"]) == 2 and doctor["status"] == "closed"
    assert story["segments"][0]["segment_id"] != story["segments"][1]["segment_id"]
    assert C.activity_at(doc["activities"], datetime.fromisoformat("2026-01-01T00:03:30+00:00")) == doctor["activity_id"]
    assert C.activity_at(doc["activities"], datetime.fromisoformat("2026-01-01T00:04:30+00:00")) == story["activity_id"]
    assert C.activity_binding(doc["activities"], datetime.fromisoformat("2026-01-01T00:02:30+00:00"))[1] != \
           C.activity_binding(doc["activities"], datetime.fromisoformat("2026-01-01T00:04:30+00:00"))[1]
    wait, interactions = C.human_wait([
        (datetime.fromisoformat("2026-01-01T00:02:30+00:00"), "assistant"),
        (datetime.fromisoformat("2026-01-01T00:03:30+00:00"), "human"),
        (datetime.fromisoformat("2026-01-01T00:04:10+00:00"), "assistant"),
        (datetime.fromisoformat("2026-01-01T00:04:30+00:00"), "human")], doc["activities"], 1800)
    assert wait == 20 and interactions == 1
    before = len(doc["activities"])
    A.update(path, "s", "start", "story", task="T-1", event_id="e3", timestamp="2026-01-01T00:02:00Z")
    assert len(json.loads(path.read_text())["activities"]) == before
    hooks = json.loads((Path(__file__).resolve().parents[2] / "hooks/hooks.json").read_text())
    stop = hooks["hooks"]["Stop"][0]["hooks"]
    assert any("activity_capture.py" in x["command"] for x in stop)
    cli_path = ROOT / "cli.json"
    old_argv, old_read, old_path = sys.argv, A.read_event, A.activity_path
    try:
        A.read_event = lambda: {}
        A.activity_path = lambda event, session: cli_path
        def cli(action, kind, event_id, task=""):
            sys.argv = ["activity_capture.py", "--action", action, "--type", kind,
                        "--session", "cli-session", "--event-id", event_id,
                        "--task", task]
            assert A.main() == 0
        cli("start", "story", "cli-story-start", "T")
        cli("start", "story", "cli-story-start", "T")
        cli("start", "doctor", "cli-doctor-start")
        cli("start", "doctor", "cli-doctor-start")
        cli("end", "doctor", "cli-doctor-end")
        cli("end", "doctor", "cli-doctor-end")
        cli("end", "story", "cli-story-end", "T")
        cli("end", "story", "cli-story-end", "T")
        cli_doc = json.loads(cli_path.read_text())
        assert cli_doc["session_id"] == "cli-session" and cli_doc["active_stack"] == []
        assert len(next(x for x in cli_doc["activities"] if x["type"] == "story")["segments"]) == 2
        try:
            cli("start", "story", "cli-story-start", "OTHER")
            raise AssertionError("conflicting activity event retry was accepted")
        except ValueError as exc:
            assert "different payload" in str(exc)
    finally:
        sys.argv, A.read_event, A.activity_path = old_argv, old_read, old_path
    shutil.rmtree(ROOT, ignore_errors=True)
    print("PASS test_usage_activity")


if __name__ == "__main__": main()
