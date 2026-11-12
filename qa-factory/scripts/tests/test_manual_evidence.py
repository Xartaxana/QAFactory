"""Manual evidence validation, safe export, and immutable block semantics."""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "scripts"))
import manual_evidence as M

# Outside the package: a local-directory marketplace copies whatever lies in it.
ROOT = Path(tempfile.mkdtemp(prefix="qa-manual-evidence-"))

# t-275 (A): the two revisions a REAL story carries, in their real shapes. The controller's `source_revision` is the
# sha256 of the ticket snapshot (64 hex); a runtime probe's `expected_source_revision` is the profile checkout's git
# HEAD (40 hex). The fixtures used to give both the same word (`"source"`), which is the only way they could ever be
# equal - and so hid that `validate_manual_current` compared the two and refused every real record.
SNAPSHOT_SHA = hashlib.sha256(b"cmp2 ticket snapshot").hexdigest()
CHECKOUT_HEAD = hashlib.sha1(b"cmp2 profile checkout HEAD").hexdigest()
assert (len(SNAPSHOT_SHA), len(CHECKOUT_HEAD)) == (64, 40)


def seed_provenance(task, profile="manual", revision=CHECKOUT_HEAD, stamp="20261001T100000Z"):
    """The `evidence/runtime-provenance-<profile>-<stamp>.json` `runtime_probe.py` writes for a run of the story: it
    names the profile and the checkout's HEAD, which is what a manual proof binds to (coverage_contract.
    recorded_checkout_revisions)."""
    path = Path(task) / "evidence" / f"runtime-provenance-{profile}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profile_id": profile, "timestamp": "2026-10-01T10:00:00+00:00", "environment_id": "localhost",
                                "expected_source_revision": revision, "observed_runtime_identity": "verified_content:abc",
                                "result": "matched"}), encoding="utf-8")
    return path


def evidence(path, phase, proves):
    return {"path": path.relative_to(ROOT).as_posix(),
            "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "kind": "image", "phase": phase, "captured_at": "2026-09-17T10:00:00Z",
            "proves": proves, "mask_acknowledged": True}


def record(before, after):
    runtime = {"profile_id": "manual", "timestamp": "2026-09-17T10:00:00Z",
               "environment_id": "device-1", "expected_source_revision": CHECKOUT_HEAD,
               "observed_runtime_identity": "build-1", "evidence_refs": ["device/build"],
               "provenance": {"technical_verification": True, "source_linkage": "exact",
                              "deployed_source_revision": CHECKOUT_HEAD}, "result": "matched"}
    return {"schema_version": 2, "case": "TC-1", "case_version": "cv_1",
            "obligation_ids": ["O-1"], "obligation_hashes": {"O-1": "ob-hash"},
            "attempt_id": "a1", "dispatch_id": "d1", "source_revision": SNAPSHOT_SHA,
            "runtime_identity": "build-1", "steps_actual": ["open", "save"],
            "expected": "saved", "actual": "saved",
            "completion_condition": "save response and state observed",
            "attempt_started_at": "2026-09-17T10:00:00Z",
            "attempt_ended_at": "2026-09-17T10:01:00Z", "result": "pass",
            "runtime_before": dict(runtime), "runtime_after": dict(runtime),
            "evidence_policy": "ui", "limitations": [],
            "evidence_refs": [evidence(before, "before", ["initial state"]),
                              evidence(after, "after", ["completion", "saved state"])]}


def legacy_checks():
    shutil.rmtree(ROOT, ignore_errors=True)
    before = ROOT / "work/evidence/before.png"
    after = ROOT / "work/evidence/after.png"
    before.parent.mkdir(parents=True)
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    row = record(before, after)
    assert M.validate_record(row, ROOT) == []
    exported = M.export_records(ROOT, [row])
    assert not exported["errors"] and len(exported["rows"]) == 1
    assert all((ROOT / x["path"]).is_file() for x in exported["rows"][0]["evidence_refs"])

    corrupt = record(before, after)
    corrupt["evidence_refs"][1]["content_hash"] = "0" * 64
    rejected = M.export_records(ROOT, [corrupt])
    assert rejected["errors"] and rejected["rows"] == []
    missing_kind = record(before, after)
    missing_kind["evidence_refs"][0].pop("kind")
    assert "invalid evidence kind" in M.validate_record(missing_kind, ROOT)
    weak_no_write = record(before, after)
    weak_no_write["evidence_policy"] = "no_write"
    weak_no_write["evidence_refs"] = [weak_no_write["evidence_refs"][1]]
    assert any(e.startswith("no_write requires before and after state evidence and completion proof")
           for e in M.validate_record(weak_no_write, ROOT))
    static = record(before, after)
    static["evidence_policy"] = "static"
    static["before_not_applicable_reason"] = "immutable config"
    static["evidence_refs"] = [static["evidence_refs"][1]]
    assert M.validate_record(static, ROOT) == []
    api = record(before, after)
    api["evidence_policy"] = "api"
    api["evidence_refs"][0]["kind"] = "request_response"
    api["evidence_refs"][1]["kind"] = "state"
    assert M.validate_record(api, ROOT) == []
    traversal = record(before, after)
    traversal["evidence_refs"][0]["path"] = "../secret"
    assert M.validate_record(traversal, ROOT)
    active = ROOT / "work/evidence/view.html"
    active.write_text("<script>alert(1)</script>")
    active_row = record(before, after)
    active_row["evidence_refs"][1] = evidence(active, "after", ["completion"])
    active_export = M.export_records(ROOT, [active_row])
    assert active_export["rows"][0]["evidence_refs"][1]["path"].endswith(".bin")

    # Preparing a new attempt preserves old bytes as an explicit gap; it never upgrades them.
    legacy = ROOT / "work/manual-blocks/legacy.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps({"manual_checks": [{"case": "TC-old"}]}))
    gaps = M._legacy_evidence_gaps(ROOT)
    assert gaps and gaps[0]["path"] == "work/manual-blocks/legacy.json"

    original = M._validate_current
    M._validate_current = lambda task, value: M.validate_record(value, task)
    try:
        forged = dict(row, current_obligation_ids=["O-1"])
        try:
            M.write_block(ROOT, [forged])
            raise AssertionError("writer accepted reducer-owned current_obligation_ids")
        except ValueError as exc:
            assert "current_obligation_ids is reducer-owned" in str(exc)
        block = M.write_block(ROOT, [row])
        again = M.write_block(ROOT, [row])
        assert block == again
        payload = json.loads(block.read_text())
        assert payload["dispatch_id"] == "d1" and payload["head"] == SNAPSHOT_SHA
        assert payload["attempt_started_at"] and payload["attempt_ended_at"]
    finally:
        M._validate_current = original
    shutil.rmtree(ROOT, ignore_errors=True)
    print("PASS test_manual_evidence (the v2 record rules, export and block)")


# =========================================================================================================
# t-250 B2: prepare (C2, C3, C5), build (C7, C10), the docs (K5), the refused request (K6)
# =========================================================================================================
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

MC = S.MC
PKG = Path(__file__).resolve().parents[2]

# K5. The keys are quoted VERBATIM from spec t-250 §5 and fixed here, before the run; a key picked after the
# fact would be the performer checking itself. One negative control below proves the checker can fail.
# The role-text keys of this block live in design/role-rules.json (TD-5.3.3); what stays is the state-exits table of design/.
# §5: "each with its door" - the command or word the row's way out names.
STATE_EXIT_DOORS = {"an S6 manual case with no record": ["manual_evidence.py build", "manual_capture.py"],
                    "a refused `prepare`": ["semantic_reopen", "the person's answer"],
                    "an inconclusive record": ["manual_capture.py", "build"]}


def missing_keys(text, keys):
    return [key for key in keys if key not in text]


def doc_keys():
    walk = (PKG / "design" / "state-exits.md").read_text(encoding="utf-8").splitlines()
    for label, doors in STATE_EXIT_DOORS.items():
        row = next((line for line in walk if line.startswith("| " + label)), "")
        check(f"K5 state-exits.md: the row `{label}` exists", bool(row))
        check_eq(f"K5 state-exits.md: and `{label}` names its door", missing_keys(row, doors), [])


def prepare_cases():
    t = S.make_task(manual=("ui", "api", "impl"))
    try:
        ids = {"ui": ["OB-7"], "api": ["OB-12"], "impl": ["OB-15"]}
        with t.patched():
            request = M.prepare_to_file(t.task, S.CASES["ui"], ids["ui"])
        check_eq("prepare TC_007: the request is the approved policy", (request["evidence_policy"], request["covers"],
                 request["gate_a_decision_ref"], request["expected"]),
                 ("ui", ["R-7"], "gateA-1", ["Zoom, fit-view and pan change the viewport."]))
        on_disk = json.loads(M.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8"))
        check_eq("prepare: request.json holds exactly the request", on_disk, request)
        check("prepare: it sits under work/evidence/manual/<case>/", M.request_path(t.task, S.CASES["ui"]).relative_to(t.task).as_posix()
              == f"work/evidence/manual/{S.CASES['ui']}/request.json")
        with t.patched():
            api = M.prepare_request(t.task, S.CASES["api"], ids["api"])
        check_eq("prepare TC_012 (the api case of the owner's two): policy api", api["evidence_policy"], "api")

        # --- C5: a re-recorded gate A leaves two approved records; the CURRENT one is chosen, never a refusal
        t.state(gate_ids=("gateA-1", "gateA-1-2"))
        with t.patched():
            request = M.prepare_request(t.task, S.CASES["ui"], ids["ui"])
        check_eq("C5: two approved gate A records -> the current (last) one is bound", request["gate_a_decision_ref"], "gateA-1-2")
        t.state()
        S.FakeController.STATE["decisions"] = {
            "gateA-old": {"id": "gateA-old", "gate": "A", "status": "approved", "source_revision": "src-0"},
            "gateA-1": {"id": "gateA-1", "gate": "A", "status": "approved", "source_revision": S.SOURCE},
            "gateA-x": {"id": "gateA-x", "gate": "A", "status": "stale", "source_revision": S.SOURCE}}
        with t.patched():
            request = M.prepare_request(t.task, S.CASES["ui"], ids["ui"])
        check_eq("C5: a record of an older source revision, or a stale one, is never the current one", request["gate_a_decision_ref"], "gateA-1")
        S.FakeController.STATE["decisions"] = {"gateA-old": {"id": "gateA-old", "gate": "A", "status": "approved",
                                                              "source_revision": "src-0"}}
        with t.patched():
            try:
                M.prepare_to_file(t.task, S.CASES["ui"], ids["ui"])
                check("C5 control: no current gate A is refused", False)
            except ValueError as exc:
                check_in("C5 control: no current gate A is refused, with the door", "no gate A decision is current", str(exc))
        t.state()

        # --- C2 (P20): an expectation nobody confirmed is refused at prepare
        refusal = M.Refused("", "")        # a mutant that lets TC_015 through fails the checks below, it does not crash them
        with t.patched():
            try:
                M.prepare_to_file(t.task, S.CASES["impl"], ids["impl"])
                check("C2: TC_015 (R-19, implementation-only, no question) is refused", False)
            except M.Refused as exc:
                refusal = exc
        check_in("C2: TC_015 is refused as an unconfirmed expectation", "expectation unconfirmed", refusal.reason)
        check_in("C2: ... naming the requirement and that no question was raised",
                 "R-19 exists only in the new code and no question about it is linked in the register", refusal.reason)
        check_in("C2: ... with a door that is the person's answer", "the person's answer", refusal.door)
        # K6: the refused request.json shape
        shape = json.loads(M.request_path(t.task, S.CASES["impl"]).read_text(encoding="utf-8"))
        check_eq("K6: request.json of a refused case is exactly {refused: {reason, door}}",
                 (sorted(shape), sorted(shape["refused"])), (["refused"], ["door", "reason"]))
        check("K6: reason and door are non-empty words", all(isinstance(shape["refused"][k], str) and len(shape["refused"][k]) > 20
                                                             for k in ("reason", "door")))
        check_eq("K6: and they are the refusal's own", (shape["refused"]["reason"], shape["refused"]["door"]),
                 (refusal.reason, refusal.door))
        check_not_in("K6: the person-facing reason carries no field or script name", "obligation_", shape["refused"]["reason"])
        check_not_in("K6: nor a plugin script", ".py", shape["refused"]["reason"])
        # a later good prepare rewrites the file with the request (the refusal is not a tombstone)
        with t.patched():
            M.prepare_to_file(t.task, S.CASES["ui"], ids["ui"])
        check("K6: a refused request.json is replaced by the request when prepare is run again and passes",
              "refused" not in json.loads(M.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8")))
    finally:
        S.cleanup(t)
    # --- C2 with a claim row whose question is open: the refusal names the question
    t = S.make_task(manual=("impl",), claims=True)
    try:
        reg = t.task / "work" / "requirements-register.md"
        reg.write_text(reg.read_text(encoding="utf-8") + "| R-19 | unknown | unknown | 400 | diff:+w.py:532 | unknown | Q7 |\n", encoding="utf-8")
        with t.patched():
            try:
                M.prepare_request(t.task, S.CASES["impl"], ["OB-15"])
                check("C2: a claim whose question is open still refuses", False)
            except M.Refused as exc:
                check_in("C2: the reason says `expectation unconfirmed — Q7`", "expectation unconfirmed — Q7", exc.reason)
                check_in("C2: and the door names the question", "Q7", exc.door)
            # control: the person answered Q7 -> the requirement is confirmed, prepare goes on
            original = M._question_rows
            M._question_rows = lambda task: {"Q7": {"id": "Q7", "status": "answered", "reading": "a", "changed_since_answer": False}}
            try:
                request = M.prepare_request(t.task, S.CASES["impl"], ["OB-15"])
                check_eq("C2 control: with Q7 answered the same case is prepared", request["obligation_ids"], ["OB-15"])
            finally:
                M._question_rows = original
    finally:
        S.cleanup(t)
    # --- C2 on a Then: `unknown` is open until answered by a reading with a text; anything else stays refused
    t = S.make_task()
    try:
        pinned = next((t.task / "state" / "case-versions" / S.CASES["ui"]).glob("*.md"))
        base = pinned.read_text(encoding="utf-8")

        def with_oracles(oracles, thens):
            text = base.replace("plan_row: TS-7\n", f"then_oracles: {oracles}\nquestion_thens: {thens}\nplan_row: TS-7\n", 1)
            pinned.write_text(text, encoding="utf-8")

        open_ = '[{"then": 1, "source": "unknown", "ref": "Q7"}, {"then": 2, "source": "ac", "ref": "R-7"}, {"then": 3, "source": "ac", "ref": "R-7"}]'
        thens = '[{"then": 1, "question": "Q7", "readings": {"a": "scale grows", "b": "scale shrinks"}}]'
        with_oracles(open_, thens)

        def attempt(rows=None):
            original = M._question_rows
            if rows is not None:
                M._question_rows = lambda task: rows
            try:
                with t.patched():
                    return M.prepare_request(t.task, S.CASES["ui"], ["OB-7"])
            finally:
                M._question_rows = original
        try:
            attempt()
            check("C2: a Then whose question is open is refused", False)
        except M.Refused as exc:
            check_in("C2: a Then whose question is open: `expectation unconfirmed — Q7`", "expectation unconfirmed — Q7", exc.reason)
            check_in("C2: and it says which expected result", "expected result 1", exc.reason)
        answered = {"Q7": {"id": "Q7", "status": "answered", "reading": "a", "changed_since_answer": False}}
        check_eq("C2 control: the same Then, answered with a reading that has a text, is prepared",
                 attempt(answered)["obligation_ids"], ["OB-7"])
        for label, row in (("changed since it was answered", dict(answered["Q7"], changed_since_answer=True)),
                           ("answered in the person's own words (no reading)", dict(answered["Q7"], reading="")),
                           ("a reading nobody wrote a text for", dict(answered["Q7"], reading="c")),
                           ("not needed", {"id": "Q7", "status": "not_needed", "reading": ""})):
            try:
                attempt({"Q7": row})
                check(f"C2: a Then answered {label} stays refused", False)
            except M.Refused:
                check(f"C2: a Then answered {label} stays refused (the error direction is toward unconfirmed)", True)
        with_oracles('[{"then": 1, "source": "code", "ref": "x"}]', "[]")
        try:
            attempt()
            check("C2: an invented oracle word is refused", False)
        except M.Refused as exc:
            check_in("C2: an invented oracle word is refused as having no confirmed source", "has no confirmed source", exc.reason)
        with_oracles("not json", "[]")
        try:
            attempt()
            check("C2: an unreadable then_oracles line is refused", False)
        except M.Refused as exc:
            check_in("C2: an unreadable then_oracles line is refused, said in words", "cannot be read", exc.reason)
        pinned.write_text(base, encoding="utf-8")
        check_eq("C2 control: the case as pinned (no then_oracles line, AC-backed R-7) is prepared", attempt()["covers"], ["R-7"])
    finally:
        S.cleanup(t)
    # --- the plain refusals carry words and a door too (every refusal of prepare has both halves)
    t = S.make_task(manual=())
    try:
        with t.patched():
            refusals = {}
            for label, case, ids, needle in (
                    ("a decision that is still `new`", S.CASES["ui"], ["OB-7"], "as `new`"),
                    ("unknown obligations", S.CASES["ui"], ["OB-404"], "not in the approved plan"),
                    ("a case that is not pinned", "TP1-15045_TC_099", ["OB-7"], "not among the cases pinned")):
                try:
                    M.prepare_to_file(t.task, case, ids)
                    check(f"prepare: {label} is refused", False)
                except M.Refused as exc:
                    refusals[label] = exc
                    check_in(f"prepare: {label}: the reason", needle, exc.reason)
                    check(f"prepare: {label}: and a door", len(exc.door) > 20, exc.door)
        new = refusals["a decision that is still `new`"]
        # t-271 D6 (FR-6): the sentence a person reads says "reopen gate A for this case"; the operation word is a
        # machine field of its own (`door_code`), the t-271 section of test_oracle_provenance.py holds the mutation.
        check_in("prepare: the `new` decision's door says to reopen gate A for this case (a plan approved before B1 keeps `new`)",
                 "reopen gate A for this case", new.door)
        check_eq("prepare: ... and the operation travels in its own field", new.door_code, "semantic_reopen")
        check_not_in("prepare: ... and never in the sentence", "semantic_reopen", new.door + new.reason)
        check_not_in("prepare: ... and the person-facing reason names no script or field", "manual-agent request", new.reason)
    finally:
        S.cleanup(t)


def refusal_texts_are_for_a_person():
    """t-271 D6 (t-263): `reason` and `door` of a refused `prepare` are what the report quotes to a person (FR-6): no code word
    of ours (`semantic_reopen` - the operation travels in its own field, `door_code`), no path under work/
    (`grammar.REPORT_FORBIDDEN`); the case and the KIND of record are named instead."""
    import grammar as G
    from unittest import mock

    def forbidden(text):
        return [key for key in G.REPORT_FORBIDDEN if key in text] + (["semantic_reopen"] if "semantic_reopen" in text else [])
    t = S.make_task(manual=())
    try:
        with t.patched():
            refusals = {}
            for label, case, ids in (("a decision still `new`", S.CASES["ui"], ["OB-7"]),
                                     ("a case that is not pinned", "TP1-15045_TC_099", ["OB-7"]),
                                     ("unknown obligations", S.CASES["ui"], ["OB-404"])):
                try:
                    M.prepare_to_file(t.task, case, ids)
                except M.Refused as exc:
                    refusals[label] = exc
            check_eq("D6: three refusals were provoked", sorted(refusals), ["a case that is not pinned", "a decision still `new`", "unknown obligations"])
            for label, exc in refusals.items():
                check_eq(f"D6: {label}: the sentence a person reads passes REPORT_FORBIDDEN and names no code word", forbidden(exc.reason + " " + exc.door), [])
            check_in("D6: the not-pinned refusal names the case", "TP1-15045_TC_099", refusals["a case that is not pinned"].reason)
            check_in("D6: the reopen door is said in words", "reopen gate A for this case", refusals["a decision still `new`"].door)
            written = json.loads(M.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8"))["refused"]
            check_eq("D6: request.json (what the report reads) holds reason and door, both clean", forbidden(written["reason"] + " " + written["door"]), [])
            check_eq("D6: ... and nothing else (the file keeps its documented shape; the operation word is on the exception only)",
                     sorted(written), ["door", "reason"])
            plan = t.task / "work" / "test-plan.json"
            said = M.refusal_words(FileNotFoundError(2, "No such file or directory", str(plan)), S.CASES["ui"])
            check_eq("D6: a missing record (an OSError carrying its path) is said by case and kind of record",
                     (forbidden(" ".join(said)), S.CASES["ui"] in said[0], "the plan could not be read (FileNotFoundError)" in said[0]), ([], True, True))
            for label, error in (("a controller block that quotes a path (Windows)", ValueError(f"cannot read {str(plan).replace('/', chr(92))}: Gate A plan changed")),
                                 ("a controller block that quotes two paths", ValueError(f"{plan} and {t.task / 'work' / 'requirements-readiness.json'} disagree"))):
                with mock.patch.object(S.FakeController, "_validate_gate_a_content_current", create=True, side_effect=error):
                    try:
                        M.prepare_to_file(t.task, S.CASES["ui"], ["OB-7"])
                        check(f"D6: {label}: refused", False, "no refusal")
                    except ValueError:
                        pass
                shown = json.loads(M.request_path(t.task, S.CASES["ui"]).read_text(encoding="utf-8"))["refused"]
                check_eq(f"D6: {label}: no work/ path and no code word in what the person reads", forbidden(shown["reason"] + " " + shown["door"]), [])
                check_in(f"D6: {label}: the case is named", S.CASES["ui"], shown["reason"])
            check_in("D6: ... and the KIND of record, not its path", "the plan", shown["reason"] + " " + json.dumps(shown))
            print("K-D6 | prepare refusals: no `semantic_reopen`, no work/ path in reason/door ('reopen gate A for this case'; the case and "
                  "'the plan' named); the operation word is `Refused.door_code` only, request.json stays {refused: {reason, door}}")
    finally:
        S.cleanup(t)


def prepare_cli():
    t = S.make_task(manual=("ui", "impl"))
    try:
        for case, ids, code_expected in ((S.CASES["ui"], ["OB-7"], 0), (S.CASES["impl"], ["OB-15"], 2)):
            payload = t.task / "prepare-input.json"
            payload.write_text(json.dumps({"case": case, "obligation_ids": ids}), encoding="utf-8")
            with t.patched():
                code, out, err = S.run(["prepare", "--task-root", str(t.task), "--input", str(payload)], main=M.main,
                                       command="manual_evidence.py prepare")
            check_eq(f"prepare CLI {case}: exit {code_expected}", code, code_expected)
            written = json.loads(M.request_path(t.task, case).read_text(encoding="utf-8"))
            if code_expected == 0:
                check_eq("prepare CLI: stdout is the request, ASCII JSON", json.loads(out), written)
            else:
                check_in("prepare CLI: the refusal reaches the role with its door", "the person's answer", err)
                check_eq("prepare CLI: and request.json holds the refused shape", sorted(written), ["refused"])
        code, out, err = S.run(["validate", "--task-root", str(t.task)], main=M.main, command="manual_evidence.py validate")
        check_eq("a command with no --input is a refusal naming the missing flag", (code, "--input is missing" in err), (2, True))
    finally:
        S.cleanup(t)


def build_cases():
    # C7: `build` copies the runner's `proves`; it never stamps `completion` itself.
    t = S.make_task()
    try:
        # the story's S5 run recorded the checkout the scaffold's probe names (t-275 A: a proof binds to that)
        seed_provenance(t.task, "e2e-ui", S.probe()["expected_source_revision"])
        steps = f"goto {TMC.UI}\ncapture pre_action initial\ncapture post_action final\n"
        TMC.ui_run(t, steps=steps)
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "pass", "--actual", "x", "--masked")
        check_eq("C7: a post_action capture the runner did not call `completion` makes a pass refused", code, 2)
        check_in("C7: by the pass rule", "pass requires post_action evidence proving completion", err)
        check("C7: build wrote no block", not (t.task / "work" / "manual-blocks").exists())
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "fail", "--actual", "the pane did not move", "--masked")
        check_eq("C7: the same files are a valid FAIL (a fail needs the phases, not the completion line)", code, 0)
        record = json.loads((t.attempt_dir(S.CASES["ui"]) / "record.json").read_text(encoding="utf-8"))
        check_eq("C7: the proves are exactly the runner's words", [r["proves"] for r in record["evidence_refs"] if r["phase"] == "post_action"], [["final"]])
        check_eq("C7: and build left --result alone", record["result"], "fail")
        # C10: that attempt is written now
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "inconclusive", "--actual", "x", "--masked", "--limitation", "l")
        check_eq("C10: building again on the written attempt is refused", code, 2)
        check_in("C10: naming the attempt and the door", "attempt a1 of TP1-15045_TC_007 is already written", err)
        check_in("C10: the door is the next attempt", "--attempt a2", err)
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "pass", "--actual", "x", "--masked", "--attempt", "a1")
        check_eq("C10: naming the written attempt explicitly is refused too", code, 2)
        # a new capture is a new attempt; build takes the latest
        TMC.ui_run(t)
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "pass", "--actual", "scale grew", "--masked")
        check_eq("C10: capture again (a2) and build: the new attempt is built", (code, json.loads(out)["attempt"]), (0, "a2"))
        blocks = sorted((t.task / "work" / "manual-blocks").glob("*.json"))
        check_eq("C10: two attempts, two immutable blocks (the first is history)", len(blocks), 2)
    finally:
        S.cleanup(t)


def observations_build_cases():
    """RN1-10 (c) on the road a runner takes (`build`): the record always declares `observations` (`[]` when none), a made-up
    quote is refused with the field's name, a quote that stands in the attempt's own capture is taken, and an attempt that still
    holds a live browser profile is not built. The rules themselves are pinned in test_manual_observations.py."""
    t = S.make_task()
    try:
        seed_provenance(t.task, "e2e-ui", S.probe()["expected_source_revision"])
        TMC.ui_run(t, steps=f"goto {TMC.UI}\ncapture pre_action initial\nread {TMC.VIEWPORT} style=transform\n"
                            "capture post_action completion\n")
        case, folder = S.CASES["ui"], t.attempt_dir(S.CASES["ui"])
        live = folder / "sessions" / "user" / "profile"
        live.mkdir(parents=True)
        code, out, err = TMC.build(t, case, "--result", "pass", "--actual", "x", "--masked")
        check_eq("RN1-10: build over a live browser profile is refused", code, 2)
        check_in("RN1-10: ... and the door is `session close`", "close the sessions first", err)
        check("RN1-10: ... nothing was written", not (folder / "record.json").exists())
        shutil.rmtree(folder / "sessions")
        captures = TMC.jsonl(folder / "captures.jsonl")
        text = next((c for c in captures if Path(c["path"]).suffix in M.QUOTE_SUFFIXES), None)
        check("RN1-10: the run captured a text file to quote (fixture sanity)", text is not None, str(captures))
        words = " ".join((t.task / text["path"]).read_text(encoding="utf-8").split())[:12] if text else ""
        with t.patched():
            M.prepare_to_file(t.task, case, TMC.OBLIGATIONS[case])
            thens = TMC.then_flags(t.task, case, ["--result", "pass"])
            quotes = [({"--then-seen": "seen", "--then-quote": "text"}[flag], value) for flag, value in zip(thens[::2], thens[1::2])]
            try:
                M.build_record(t.task, case, "pass", "x", True, quotes=quotes, observations=[
                    {"step": 1, "expected": "e", "seen": "s", "evidence": text["path"], "quote": "words nobody ever captured"}])
                refused = ""
            except ValueError as exc:
                refused = str(exc)
            check_in("RN1-10: a made-up observation quote is refused, naming the field", "the quote of observations[0] is not in", refused)
            check("RN1-10: ... and no record was written", not (folder / "record.json").exists())
            done = M.build_record(t.task, case, "pass", "x", True, quotes=quotes, observations=[
                {"step": 1, "expected": "e", "seen": "s", "evidence": text["path"], "quote": words}])
        record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
        check_eq("RN1-10: a quote of the attempt's own capture is taken, as written", record["observations"][0]["quote"], words)
        check("RN1-10: ... and the block was written", bool(done.get("written")), str(done))
        TMC.ui_run(t, steps=f"goto {TMC.UI}\ncapture pre_action initial\ncapture post_action completion\n")
        code, out, err = TMC.build(t, case, "--result", "pass", "--actual", "x", "--masked")
        record = json.loads((t.attempt_dir(case, "a2") / "record.json").read_text(encoding="utf-8"))
        check_eq("RN1-10: a build with no observation declares the empty outcome", (code, record.get("observations")), (0, []))
    finally:
        S.cleanup(t)


def checkout_revision_binding():
    """t-275 (A): the runtime proof of a manual record binds to the PROFILE CHECKOUT's revision (40 hex, recorded by the
    story's runs under evidence/runtime-provenance-*.json), never to the controller's `source_revision` (64 hex, the
    ticket snapshot): the two can never be equal, and comparing them refused every real record. The record below has
    the real shapes; the old fixture word `source` on both sides is the negative control."""
    t = S.make_task()
    saved = S.SOURCE
    S.SOURCE = SNAPSHOT_SHA          # the controller's side, in its real shape (state() and the gate decisions read it)
    try:
        shutil.rmtree(t.task / "evidence", ignore_errors=True)   # the story has recorded NO run yet (a scaffold may seed some)
        t.state()
        heads = lambda spec: dict(S.probe("api" if spec["argv"] == ["probe-api"] else "e2e-ui"),
                                  expected_source_revision=CHECKOUT_HEAD,
                                  provenance={"technical_verification": True, "source_linkage": "exact",
                                              "deployed_source_revision": CHECKOUT_HEAD})
        steps_file = t.task / "steps.txt"
        steps_file.write_text(TMC.UI_STEPS, encoding="utf-8")
        TMC.patch_backends(S.FakeBrowser(), probes=heads)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", S.CASES["ui"], "--steps-file", str(steps_file)])
        check_eq("A: the capture ran", code, 0)
        pre = [p for p in (t.task / "evidence").glob("runtime-provenance-*.json")] if (t.task / "evidence").exists() else []
        check_eq("A: CONTROL: the story has recorded no checkout revision yet, so nothing can be bound to", len(pre), 0)
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "pass", "--actual", "x", "--masked")
        check_eq("A: a proof with no recorded checkout revision for its profile is refused", code, 2)
        check_in("A: ... naming what to do (the door)", "run runtime_probe.py for that profile", err)
        seed_provenance(t.task, "e2e-ui", CHECKOUT_HEAD)
        code, out, err = TMC.build(t, S.CASES["ui"], "--result", "pass", "--actual", "x", "--masked")
        check_eq("A: with the story's own checkout revision on record (40 hex) and the snapshot sha256 (64 hex) in the "
                 "controller, the record is accepted", code, 0)
        record = json.loads((t.attempt_dir(S.CASES["ui"]) / "record.json").read_text(encoding="utf-8"))
        shapes = (len(record["source_revision"]), len(record["runtime_before"]["expected_source_revision"]))
        check_eq("A: ... and those are the two real shapes", shapes, (64, 40))
        from coverage_contract import validate_manual_current

        def at(revision=None, profile=None, recorded=None, applicable=True):
            """The record with its probes naming `revision` on both sides, validated against a story whose runs
            recorded `recorded` (a list of (profile, revision)) - everything else as built."""
            changed = json.loads(json.dumps(record))
            for key in ("runtime_before", "runtime_after"):
                if revision is not None:
                    changed[key]["expected_source_revision"] = revision
                    changed[key]["provenance"]["deployed_source_revision"] = revision
                if profile is not None:
                    changed[key]["profile_id"] = profile
            for old in (t.task / "evidence").glob("runtime-provenance-*.json"):
                old.unlink()
            for number, (name, rev) in enumerate(recorded if recorded is not None else [("e2e-ui", CHECKOUT_HEAD)]):
                seed_provenance(t.task, name, rev, stamp=f"2026100110000{number}Z")
            with t.patched():
                return validate_manual_current(t.task, changed)
        binds = "binds a checkout revision no run of this story recorded"
        check_eq("A: validate_manual_current accepts the real shapes", at(), [])
        check_in("A: NEGATIVE CONTROL: the old fixture word `source` on both sides is refused", binds, at(revision="source"))
        check_in("A: NEGATIVE CONTROL: the controller's own sha256 as the probe's revision (what the old rule demanded) is refused",
                 binds, at(revision=SNAPSHOT_SHA))
        check_in("A: NEGATIVE CONTROL: a checkout revision the story never recorded is refused", binds,
                 at(revision=hashlib.sha1(b"another checkout").hexdigest()))
        check_in("A: NEGATIVE CONTROL: no record at all for the profile is refused", binds, at(recorded=[]))
        check_in("A: NEGATIVE CONTROL: a record of ANOTHER profile does not bind this one", binds, at(recorded=[("api", CHECKOUT_HEAD)]))
        check_eq("A: both of the story's checkouts recorded (api and e2e-ui): the one the probe names binds",
                 at(recorded=[("api", hashlib.sha1(b"api checkout").hexdigest()), ("e2e-ui", CHECKOUT_HEAD)]), [])
        check_eq("A: `unknown` is the probe's word for a revision it could not read, never a revision",
                 sorted({e for e in at(revision="unknown", recorded=[("e2e-ui", "unknown")]) if "binds a checkout" in e}),
                 [next(e for e in at(revision="unknown") if "binds a checkout" in e)])
        check_eq("A: the rest of the proof is kept: before and after must still name the same checkout",
                 [e for e in at() if "changed during execution" in e], [])
        changed_mid = json.loads(json.dumps(record))
        changed_mid["runtime_after"]["expected_source_revision"] = hashlib.sha1(b"x").hexdigest()
        with t.patched():
            check_in("A: ... and a checkout that moved during the attempt is refused", "manual runtime changed during execution",
                     validate_manual_current(t.task, changed_mid))
        # t-279 K-NA on the controller-side gate: a probe that compared nothing because the story changes no file of
        # this checkout (`reason_code: no_changed_file`) binds nothing and is enough on any stand kind; every other
        # not_applicable still needs a verified local_source record.
        bypass = "live manual interaction cannot bypass runtime identity"

        def na_errors(**extra):
            changed = json.loads(json.dumps(record))
            for key in ("runtime_before", "runtime_after"):
                changed[key] = dict(changed[key], result="not_applicable", observed_runtime_identity="",
                                    evidence_refs=[], provenance={}, **extra)
            with t.patched():
                return validate_manual_current(t.task, changed)
        check_in("K-NA control: not_applicable with NO reason_code on a record that is not local_source is refused as before",
                 bypass, na_errors())
        check_in("K-NA control: with another reason_code too", bypass, na_errors(reason_code="stand_down"))
        check_eq("K-NA: `reason_code: no_changed_file` passes that gate on the same record",
                 [e for e in na_errors(reason_code="no_changed_file") if bypass in e], [])
        print("K-A | probe revision 40 hex (checkout HEAD) vs controller source_revision 64 hex: accepted when the story recorded "
              "the checkout; `source`, the snapshot sha256, another checkout, no record, another profile: each refused")
    finally:
        S.SOURCE = saved
        S.cleanup(t)


# =========================================================================================================
# t-277 (critic t-275 F8, F9 and the api `build` test)
# =========================================================================================================
import grammar as G  # noqa: E402

# F8 (FR-38). The key is the code's own refusal, word for word (manual_evidence.validate, the api/cli rule), fixed here
# before the run: the doc must tell the runner what the code will refuse it with.
API_STATE_WORDS = "api/cli requires request/output and post_action state evidence"


def api_build_cases():
    """The api leg of `build` (critic t-275: no test had the post_action `state`). A POST in `post_action` that proves
    the completion, WITH a `--state-url` read -> a pass record `validate` accepts; WITHOUT it -> refused with the words
    manual-evidence.md quotes; a state read only before the action does not stand in for the one after it."""
    get, post = f"{TMC.LOCAL}/v1/workflows/w1", f"{TMC.LOCAL}/v1/workflows/w1/validate"
    routes = {("POST", f"{TMC.LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
              ("GET", get): S.ok_json({"id": "w1"}), ("POST", post): S.ok_json({"valid": True})}
    said = "validate answered 200 and the workflow is unchanged"
    # --- with the post_action state: a valid pass
    t = S.make_task(manual=("api",))
    try:
        TMC.seed_runtime_records(t)
        http = S.FakeHttp(routes)
        code, out, err = TMC.http_run(t, http, "--method", "POST", "--url", post, "--state-url", get, "--proves", "completion")
        check_eq("api build: the POST and its state read are captured (exit 0)", code, 0)
        code, out, err = TMC.build(t, S.CASES["api"], "--result", "pass", "--actual", said, "--masked")
        check_eq("api build: `--result pass` with a post_action state writes the block", (code, json.loads(out)["written"]), (0, True))
        record = json.loads((t.attempt_dir(S.CASES["api"]) / "record.json").read_text(encoding="utf-8"))
        check_eq("api build: the record validates", M.validate_record(record, t.task), [])
        check_eq("api build: it holds a request_response and a state, both post_action",
                 sorted((r["kind"], r["phase"]) for r in record["evidence_refs"]),
                 [("request_response", "post_action"), ("state", "post_action")])
        check_eq("api build: the policy is api, the runner's result is untouched", (record["evidence_policy"], record["result"]), ("api", "pass"))
        print("api build K-line | POST post_action + --state-url + completion -> pass validates (kinds "
              + ", ".join(sorted(r["kind"] + "/" + r["phase"] for r in record["evidence_refs"])) + ")")
    finally:
        S.cleanup(t)
    # --- without it: refused with the F8 words, and the door
    t = S.make_task(manual=("api",))
    try:
        TMC.seed_runtime_records(t)
        http = S.FakeHttp(routes)
        TMC.http_run(t, http, "--method", "POST", "--url", post, "--proves", "completion")
        code, out, err = TMC.build(t, S.CASES["api"], "--result", "pass", "--actual", said, "--masked")
        check_eq("api build NEGATIVE: a pass with no state capture at all is refused", code, 2)
        check_in("api build NEGATIVE: with the code's own words (the ones manual-evidence.md quotes)", API_STATE_WORDS, err)
        check_in("api build NEGATIVE: and the door", "capture the post_action again", err)
        check("api build NEGATIVE: no block was written", not (t.task / "work" / "manual-blocks").exists())
        # the control for the rule's `post_action`: a state read BEFORE the action is not the state after it
        TMC.http_run(t, http, "--method", "GET", "--url", get, "--state-url", get, "--phase", "pre_action", "--attempt", "a1")
        code, out, err = TMC.build(t, S.CASES["api"], "--result", "pass", "--actual", said, "--masked")
        check_eq("api build NEGATIVE: a state read in pre_action does not stand in for post_action", (code, API_STATE_WORDS in err), (2, True))
        # inconclusive stays recordable on the same files (FR-23) and is never changed
        code, out, err = TMC.build(t, S.CASES["api"], "--result", "inconclusive", "--actual", said, "--masked",
                                   "--limitation", "the state read after the call was not taken")
        check_eq("api build: the same attempt as inconclusive with a limitation is accepted", code, 0)
    finally:
        S.cleanup(t)


def doc_keys_t277():
    """F8: manual-evidence.md states the api/cli post_action `state` requirement in the words the code refuses with."""
    check_in("F8 references/manual-evidence.md: the code's refusal words are quoted", API_STATE_WORDS,
             (PKG / "references" / "manual-evidence.md").read_text(encoding="utf-8"))
    # the key IS the code's refusal: derive it from validate() on an api record that has the request but no state
    shutil.rmtree(ROOT, ignore_errors=True)
    before, after = ROOT / "work/evidence/before.png", ROOT / "work/evidence/after.png"
    before.parent.mkdir(parents=True)
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    try:
        api = record(before, after)
        api["evidence_policy"] = "api"
        api["evidence_refs"][0]["kind"] = "request_response"      # the call, and no state anywhere
        refusal = [e for e in M.validate_record(api, ROOT) if e.startswith("api/cli")]
        check_eq("F8: the doc's key is exactly what validate() refuses with", refusal, [API_STATE_WORDS])
        api["evidence_refs"][1]["kind"] = "state"
        check_eq("F8 CONTROL: with the post_action state the same record validates", M.validate_record(api, ROOT), [])
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)


def phase_words_one_source():
    """F9: the phase words live in references/manual-capture-steps.json (`phases`, `phase_aliases`); grammar, the
    validator and the capture script all read that file; a missing or malformed table is a refusal naming it."""
    data = json.loads((PKG / "references" / "manual-capture-steps.json").read_text(encoding="utf-8"))
    check_eq("F9: grammar.MANUAL_PHASE_WORDS is the file's phases[], in its order", G.MANUAL_PHASE_WORDS, tuple(data["phases"]))
    check_eq("F9: grammar.MANUAL_PHASE_ALIASES is the file's phase_aliases", G.MANUAL_PHASE_ALIASES, data["phase_aliases"])
    check_eq("F9: the alias map is before -> pre_action, after -> post_action",
             data["phase_aliases"], {"before": "pre_action", "after": "post_action"})
    check_eq("F9: manual_evidence.PHASES is those words, the old words and the validator's own `baseline`",
             M.PHASES, set(data["phases"]) | set(data["phase_aliases"]) | {"baseline"})
    check_eq("F9: manual_evidence.PHASE_ALIAS is the inverse (new word -> the old one validate() reads by)",
             M.PHASE_ALIAS, {"pre_action": "before", "post_action": "after"})
    check_eq("F9: manual_capture reads the same file", MC.spec()["phases"], data["phases"])
    # the loader is data-driven: another file gives another table, nothing is built in
    root = Path(tempfile.mkdtemp(prefix="qa-phase-words-"))
    try:
        path = root / "manual-capture-steps.json"
        path.write_text(json.dumps({"phases": ["pre_action", "post_action", "supporting", "midway"],
                                    "phase_aliases": {"before": "pre_action", "mid": "midway"}}), encoding="utf-8")
        check_eq("F9: a file with a fourth phase and another alias gives exactly that table", G.load_manual_phases(path),
                 (("pre_action", "post_action", "supporting", "midway"), {"before": "pre_action", "mid": "midway"}))
        check_eq("F9: the shipped file through the same loader is the module's table", G.load_manual_phases(), (G.MANUAL_PHASE_WORDS, G.MANUAL_PHASE_ALIASES))
        good = {"phases": ["pre_action", "post_action"], "phase_aliases": {"before": "pre_action"}}
        bad = (("no file at all", None, "cannot be read"),
               ("not JSON", "{ torn", "cannot be read"),
               ("JSON but not an object", [1, 2], "`phases` is missing"),
               ("no phases", {"phase_aliases": {}}, "`phases` is missing"),
               ("an empty phases list", dict(good, phases=[]), "`phases` is missing"),
               ("a phase that is not a word", dict(good, phases=["pre_action", 7]), "`phases` is missing"),
               ("a blank phase", dict(good, phases=["pre_action", " "]), "`phases` is missing"),
               ("a repeated phase", dict(good, phases=["pre_action", "pre_action"]), "repeats a word"),
               ("no aliases object", {"phases": ["pre_action"]}, "`phase_aliases` is missing"),
               ("aliases that are a list", dict(good, phase_aliases=["before"]), "`phase_aliases` is missing"),
               ("an alias pointing at no phase", dict(good, phase_aliases={"before": "elsewhere"}), "points at none of"),
               ("an alias whose target is a list", dict(good, phase_aliases={"before": ["pre_action"]}), "points at none of"),
               ("an old word that is a phase itself", dict(good, phase_aliases={"pre_action": "post_action"}), "is a phase itself"))
        for label, content, needle in bad:
            target = root / "bad-steps.json"
            target.unlink(missing_ok=True)
            if content is not None:
                target.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            try:
                G.load_manual_phases(target)
                check(f"F9 refusal: {label} is refused", False)
            except ValueError as exc:
                check(f"F9 refusal: {label}: refused, naming the file, the fault and what is expected",
                      "bad-steps.json" in str(exc) and needle in str(exc) and "Expected `phases`" in str(exc), str(exc))
        # the validator reads the words from the table: a phase the table does not hold is refused, saying which are
        shutil.rmtree(ROOT, ignore_errors=True)
        before, after = ROOT / "work/evidence/before.png", ROOT / "work/evidence/after.png"
        before.parent.mkdir(parents=True)
        before.write_bytes(b"before")
        after.write_bytes(b"after")
        row = record(before, after)
        row["evidence_refs"][0]["phase"] = "midway"
        check_in("F9: a phase outside the table is refused, naming the table's words",
                 "invalid evidence phase: use pre_action | post_action | supporting", "\n".join(M.validate_record(row, ROOT)))
        row["evidence_refs"][0]["phase"] = "pre_action"
        row["evidence_refs"][1]["phase"] = "post_action"
        check_eq("F9 CONTROL: the new words validate, and the old ones (legacy_checks) still do", M.validate_record(row, ROOT), [])
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(ROOT, ignore_errors=True)


IMAGE = "image:sha256:" + "b" * 64

# t-300 N2 K-N2.15 doc keys, quoted VERBATIM from the DoD before the paragraphs were written (the t-279 keys they replace -
# the image identity, `build-sha.txt`, "Automation needs `matched`" - described what the capture no longer takes): a doc that
# names the build the person confirmed, the word's name in the lifecycle, and the file the person's decision lives in.
def doc_keys_n2():
    """K-N2.15: s5.md names the file the person's decision lives in (a path the code writes, FR-37). The role-text keys of the
    block live in design/role-rules.json (TD-5.3.3)."""
    text = (PKG / "skills" / "qa-story" / "phases" / "s5.md").read_text(encoding="utf-8")
    check_in("K-N2.15 s5.md names the stand identity file", "qa-factory/records/stand-identity.json", text)


def pc_probe(row, task=None, **fields):
    """A person's word for this story as `runtime_probe.confirm_record` writes it (kind, story, revision, the image it binds
    to), over the fixture's own runtime part."""
    probe = dict(row["runtime_before"], result="person_confirmed", observed_runtime_identity=IMAGE, evidence_refs=["probe/pc"],
                 provenance={"technical_verification": False, "identity_kind": "person_confirmed"},
                 person_confirmation={"words": "yes, it is deployed", "at": "2026-10-02T11:00:00+00:00",
                                      "task": task or ROOT.name, "kind": "deployed", "revision": CHECKOUT_HEAD})
    probe.update(fields)
    return probe


def n2_k9_the_persons_word_in_validate_and_the_baseline_that_refuses_it():
    """K-N2.9 (t-300 N2, S10-S12): `manual_evidence.validate` reads both probes through the ONE predicate: a person's word for
    THIS story is valid (the same identity before and after), mixed `matched`/word is valid with the word's sentence
    (the weaker word governs), `unknown` is refused with or without an image, a word for another story is refused; the
    baseline refuses the word; `person_sentences` is the one function that writes code's sentences."""
    shutil.rmtree(ROOT, ignore_errors=True)
    try:
        before, after = ROOT / "work/evidence/before.png", ROOT / "work/evidence/after.png"
        before.parent.mkdir(parents=True)
        before.write_bytes(b"before")
        after.write_bytes(b"after")
        row = record(before, after)

        def swap(**fields):
            probe = dict(row["runtime_before"], **fields)
            return dict(row, runtime_before=probe, runtime_after=dict(probe))

        def errors(value):
            return "\n".join(M.validate_record(value, ROOT))
        word = pc_probe(row)
        check_eq("K-N2.9: a person's word for this story, before == after: valid",
                 M.validate_record(dict(row, runtime_before=word, runtime_after=dict(word)), ROOT), [])
        elsewhere = pc_probe(row, task="OTHER-9")
        check_in("K-N2.9 X5: a word given for ANOTHER story is refused, naming both",
                 "the person's word was given for story OTHER-9, and this is story " + ROOT.name,
                 errors(dict(row, runtime_before=elsewhere, runtime_after=dict(elsewhere))))
        again = dict(word, observed_runtime_identity="image:sha256:" + "c" * 64)
        check_in("K-N2.9: PC/PC with DIFFERING identities is refused (a redeploy between the probes)", "runtime provenance changed during the attempt",
                 errors(dict(row, runtime_before=word, runtime_after=again)))
        mixed_before = dict(row["runtime_before"], observed_runtime_identity=IMAGE)
        check_eq("K-N2.9 X14: matched before, the word after, ONE identity: valid (the weaker word governs)",
                 M.validate_record(dict(row, runtime_before=mixed_before, runtime_after=word), ROOT), [])
        check_eq("K-N2.9 X14: and the other way round", M.validate_record(dict(row, runtime_before=word, runtime_after=mixed_before), ROOT), [])
        incomplete = pc_probe(row, person_confirmation={"words": "yes", "at": "2026-10-02T11:00:00+00:00", "task": ROOT.name, "kind": "deployed"})
        check_in("K-N2.9 X6: a word with no revision is refused", "person_confirmation.revision is required",
                 errors(dict(row, runtime_before=incomplete, runtime_after=dict(incomplete))))
        # `unknown` is taken by no token - with or without the image the container runs (Q18-B)
        weaker = dict(result="unknown", observed_runtime_identity=IMAGE, evidence_refs=[],
                      provenance={"technical_verification": False})
        check_in("K-N2.9 Q18-B: `unknown` + the image, before == after: refused (t-279 K-IMG took it; nothing is taken on an unknown now)",
                 "runtime provenance must be matched", errors(swap(**weaker)))
        for label, fields in (("a bare identity", dict(weaker, observed_runtime_identity="build-1")),
                              ("a short digest", dict(weaker, observed_runtime_identity="image:sha256:abc")),
                              ("a digest without `image:`", dict(weaker, observed_runtime_identity="sha256:" + "b" * 64)),
                              ("the image on a `mismatched`", dict(weaker, result="mismatched")),
                              ("no identity at all", dict(weaker, observed_runtime_identity=""))):
            check_in(f"K-N2.9 control ({label}): refused", "runtime provenance must be matched", errors(swap(**fields)))
        check_eq("K-N2.9 control: `matched` still validates (the old rule)", M.validate_record(row, ROOT), [])
        # S11: the baseline is a measured OLD build
        evidence_file = ROOT / "work" / "evidence" / "before.txt"
        evidence_file.write_text("old state", encoding="utf-8")
        old = {"profile_id": "p", "timestamp": "2026-01-01T00:00:00Z", "environment_id": "e", "expected_source_revision": "old",
               "observed_runtime_identity": IMAGE, "evidence_refs": ["build-id"], "result": "matched",
               "provenance": {"technical_verification": True, "source_linkage": "exact", "deployed_source_revision": "old"}}
        baseline = {"evidence_phase": "baseline", "case": "TC-1", "case_version": "v1", "dispatch_id": "d1", "source_revision": "old",
                    "steps_actual": ["open old build"], "runtime_before": old, "runtime_after": dict(old),
                    "baseline_contract": {"case_id": "TC-1", "case_version": "v1", "baseline_revision": "old", "verification_revision": "new",
                                          "fixture_identity": "seed-1", "gate_a_decision_ref": "gate-A", "reason": "prove changed behaviour",
                                          "execution_scope": "current_task", "capture_steps": ["open old build"],
                                          "comparison_assertions": ["compare rendered graph"], "capture_artifact_refs": ["evidence/before-state.json"]},
                    "capture_status": "captured", "attempt_id": "a1", "attempt_ended_at": "2026-01-01T00:00:00Z",
                    "evidence_refs": [{"path": "work/evidence/before.txt", "phase": "baseline",
                                       "content_hash": hashlib.sha256(evidence_file.read_bytes()).hexdigest()}]}
        check_eq("K-N2.9 control: a baseline on a `matched` old build is valid (the control)", M.validate_record(baseline, ROOT), [])
        oldword = dict(old, result="person_confirmed", evidence_refs=["probe/pc"],
                       provenance={"technical_verification": False, "identity_kind": "person_confirmed"},
                       person_confirmation={"words": "yes", "at": "2026-01-01T00:00:00Z", "task": ROOT.name, "kind": "deployed", "revision": "old"})
        check_in("K-N2.9 S11: a baseline taken on a person's word is refused: a baseline is a measured old build",
                 "a baseline is a measured old build, and a person's word does not stand in for it",
                 errors(dict(baseline, runtime_before=oldword, runtime_after=dict(oldword))))
        # F6 (t-395): the S11 sentence is read from the refusals block - a changed block value changes the sentence
        import profile_contract as P
        block = ROOT / "methods-block.json"
        block.write_text(json.dumps({"refusals": {"baseline_person": "BLOCK[baseline_person]"}}), encoding="utf-8")
        held, P.REFUSAL_DATA = P.REFUSAL_DATA, block
        try:
            changed = errors(dict(baseline, runtime_before=oldword, runtime_after=dict(oldword)))
        finally:
            P.REFUSAL_DATA = held
            block.unlink()
        check_in("K-N2.9 F6: the S11 sentence is read from the refusals block", "BLOCK[baseline_person]", changed)
        # S12: the sentences code writes into limitations[]
        sentences = M.person_sentences(word)
        check_eq("K-N2.9 S12: a `deployed` word gets one sentence: who, when, not read by the factory",
                 sentences, ["the build was confirmed by the person (yes, it is deployed, 2026-10-02), not read by the factory"])
        tested = pc_probe(row, tested_build="d" * 40, person_confirmation={
            "words": "test what is there", "at": "2026-10-02T11:00:00+00:00", "task": ROOT.name, "kind": "test_deployed",
            "revision": "d" * 40, "story_revision": CHECKOUT_HEAD})
        check_eq("K-N2.9 S12: a `test_deployed` word adds the second sentence: the build under test is not this story's",
                 M.person_sentences(tested)[1:], ["the build under test is " + "d" * 12 + ", not this story's " + CHECKOUT_HEAD[:12]])
        content_word = pc_probe(row, accepted_files=["Makefile", "a.py", "b.py", "c.py"], person_confirmation={
            "words": "test as is", "at": "2026-10-02T11:00:00+00:00", "task": ROOT.name, "kind": "content_accepted",
            "revision": CHECKOUT_HEAD, "content": "a" * 64})
        check_eq("FB8 (R16, fb8_person_sentences_content_kind): a `content_accepted` word gets EXACTLY ONE sentence, its own "
                 "(files capped at three), and not the base one nor the test-deployed one",
                 M.person_sentences(content_word),
                 ["the person said to test the stand as it is although Makefile, a.py, b.py and 1 more differ from this story's "
                  "(test as is, 2026-10-02); the factory compared the other files"])
        check_eq("K-N2.9 S12 control: a `matched` record has none, and neither has a non-record",
                 (M.person_sentences(row["runtime_before"]), M.person_sentences(None), M.person_sentences("x")), ([], [], []))
        # K-NA: a probe that compared nothing; the stand kind is not the record's own claim to make
        na = dict(result="not_applicable", observed_runtime_identity="", evidence_refs=[], provenance={})
        check_in("K-NA control: not_applicable with no reason_code on a docker stand (no local_source) is refused as before",
                 "runtime not_applicable requires local_source with runtime_required false", errors(swap(**na)))
        check_in("K-NA control: another reason_code too", "runtime not_applicable requires local_source",
                 errors(swap(**dict(na, reason_code="stand_down"))))
        check_eq("K-NA: `reason_code: no_changed_file` is valid on the same record", M.validate_record(swap(**dict(na, reason_code="no_changed_file")), ROOT), [])
        local = dict(swap(**na), runtime_required=False, target_kind="local_source")
        check_eq("K-NA: a verified local_source not_applicable is valid with no code, as before", M.validate_record(local, ROOT), [])
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)


def n2_validators_list_all():
    """t-1355 N2: write_block names every refused record by `records[i]` and folds nothing; validate prints its closed lists."""
    import friction
    from detector_verdict import one_of, split_items
    tmp = Path(tempfile.mkdtemp(prefix="qa-manual-n2-"))
    original = M._validate_current
    try:
        try:
            M.write_block(tmp, ["a", "b"])
            text = ""
        except ValueError as exc:
            text = str(exc)
        check_eq("N2-M: two non-object records give two numbered problems", split_items(text),
                 ["records[0]: manual block records must be objects", "records[1]: manual block records must be objects"])
        check_eq("N2: every multi-problem refusal is validator friction",
                 friction.classify("manual_evidence.py: " + text), "validator")

        def current(task, record):
            if record.get("boom"):
                raise ValueError("cannot read the story")
            return ["bad head", "bad dispatch"] if record.get("bad") else []
        M._validate_current = current
        try:
            M.write_block(tmp, [{"bad": 1}, {"ok": 1}, {"boom": 1}, {"current_obligation_ids": []}, 5])
            text = ""
        except ValueError as exc:
            text = str(exc)
        check_eq("N2-M: a record's own issue carries records[i]; a ValueError of the check too; order kept, nothing sorted",
                 split_items(text),
                 ["records[0]: bad head", "records[0]: bad dispatch", "records[2]: cannot read the story",
                  "records[3]: current_obligation_ids is reducer-owned and forbidden in writer input",
                  "records[4]: manual block records must be objects"])
        for empty in ([], None, "x"):
            try:
                M.write_block(tmp, empty)
                got = "accepted"
            except ValueError as exc:
                got = str(exc)
            check_eq(f"E-N2-10 write_block {empty!r} is refused, unchanged", got, "manual block requires current records")
    finally:
        M._validate_current = original
        shutil.rmtree(tmp, ignore_errors=True)
    check_eq("N2-M: RESULTS is the carrier of the three results", M.RESULTS, ("pass", "fail", "inconclusive"))
    errors = M.validate({"result": "maybe", "evidence_policy": "video"}, ROOT)
    check_in("N2-M: invalid result prints its list", "invalid result (one of pass, fail, inconclusive)", errors)
    check_in("N2-M: invalid evidence_policy prints its list (sorted)",
             "invalid evidence_policy (one of " + one_of(M.POLICIES) + ")", errors)
    check_in("N2-M: the policies are api, cli, no_write, static, ui", "(one of api, cli, no_write, static, ui)", str(errors))
    good = M.validate({"result": "pass", "evidence_policy": "ui"}, ROOT)
    check("a valid result and policy raise neither", not any(e.startswith("invalid result") or e.startswith("invalid evidence_policy") for e in good))


def _dict_policy_task(*, manual=("ui", "api", "impl"), rows=("TS-7",), mutate=None):
    """A task whose plan, like arm B's TS-14/15/16, holds a RECORD as `evidence_policy` on the obligations of `rows`."""
    arm_b = json.loads((Path(__file__).resolve().parent / "fixtures" / "manual-evidence" / "arm-b-dict-policies.json")
                       .read_text(encoding="utf-8"))
    t = S.make_task(manual=manual)
    for index, row_id in enumerate(rows):
        row = t.row(row_id)
        policy = arm_b[sorted(arm_b)[index % len(arm_b)]]
        row["evidence_policy"] = policy
        for ob in row["coverage_obligations"]:
            ob["evidence_policy"] = policy
    if mutate:
        mutate(t)
    t.write_plan()
    return t


def f5_only_the_cases_own_shape_errors_unprepare_it():
    """M1 (t-1945): the plan check is whole-plan, but a malformed evidence rule unprepares only the case whose OWN obligations carry
    it. Mixed plan: TS-7 (ui) holds a record, TS-12 (api) a valid word -> the api case is prepared normally, the ui case is walkable;
    every row malformed (arm B) -> every case walkable."""
    api, ui = S.CASES["api"], S.CASES["ui"]
    t = _dict_policy_task(manual=("ui", "api"), rows=("TS-7",))
    try:
        with t.patched():
            request = M.prepare_request(t.task, api, ["OB-12"])
            check_eq("M1: a valid word in another row leaves this case prepared (a request, not a refusal)",
                     (request["case"], request["evidence_policy"]), (api, "api"))
            try:
                M.prepare_request(t.task, ui, ["OB-7"])
                check("M1: the case holding the record is refused", False)
            except M.Refused as exc:
                check_eq("M1: ...and it is the walkable one", exc.walkable, True)
    finally:
        S.cleanup(t)
    t = _dict_policy_task(manual=("ui", "api"), rows=("TS-7", "TS-12"))
    try:
        with t.patched():
            for case, ids in ((ui, ["OB-7"]), (api, ["OB-12"])):
                try:
                    M.prepare_request(t.task, case, ids)
                    check(f"M1: all rows malformed: {case} is refused", False)
                except M.Refused as exc:
                    check_eq(f"M1: all rows malformed: {case} is walkable", exc.walkable, True)
    finally:
        S.cleanup(t)


def f5_unprepared_cases():
    """F5 (B-15, t-1936 N5): a malformed evidence rule is the FACTORY's failure; only the factory's own failures are walked
    unprepared, every story-owned refusal stays a refusal. Test names are the spec's (F5.4), as labels."""
    import coverage_contract as CC
    from unittest import mock
    ui, impl = S.CASES["ui"], S.CASES["impl"]
    # --- test_dict_policy_walkable_after_story_checks (the arm B shape) ---------------------------------------------------
    t = _dict_policy_task()
    try:
        with t.patched():
            try:
                M.prepare_to_file(t.task, ui, ["OB-7"])
                check("test_dict_policy_walkable_after_story_checks: a dict policy is not prepared", False)
            except M.Refused as exc:
                walkable = exc
        check("test_dict_policy_walkable_after_story_checks: walkable", walkable.walkable is True)
        check_in("test_dict_policy_walkable_after_story_checks: the reason is in words", "an evidence rule that is not one word",
                 walkable.reason)
        check_in("test_dict_policy_walkable_after_story_checks: the five words are in the detail",
                 "api|cli|no_write|static|ui", walkable.detail)
        check_in("test_dict_policy_walkable_after_story_checks: the row's obligation id is in the detail", "OB-7", walkable.detail)
        doc = json.loads(M.request_path(t.task, ui).read_text(encoding="utf-8"))
        check_eq("test_preparation_failure_writes_unprepared_request: the file holds `unprepared`, never `refused`",
                 ("unprepared" in doc, "refused" in doc), (True, False))
        check_eq("test_preparation_failure_writes_unprepared_request: reason, door, ids, revision, gate A ref",
                 (doc["unprepared"]["reason"], doc["unprepared"]["obligation_ids"], doc["unprepared"]["source_revision"],
                  doc["unprepared"]["gate_a_decision_ref"], bool(doc["unprepared"]["door"])),
                 (walkable.reason, ["OB-7"], S.SOURCE, "gateA-1", True))
        check_eq("test_preparation_failure_writes_unprepared_request: case, version, covers",
                 (doc["case"], bool(doc["case_version"]), doc["covers"]), (ui, True, ["R-7"]))
        check("test_preparation_failure_writes_unprepared_request: no evidence_policy and no required fields (nothing to bind)",
              "evidence_policy" not in doc and "required_actual_fields" not in doc)
        with t.patched():
            got = M.prepare_for_block(t.task, ui)
        check_eq("prepare_for_block: a walkable case is (ids, no refusal, the reason)", got, (["OB-7"], "", walkable.reason))
        check_eq("request_actors reads an unprepared request as it reads a refused one: no accounts, no crash",
                 M.request_actors(t.task, ui), ([], ""))
        check_eq("unprepared_request: the one reader of the marker", M.unprepared_request(t.task, ui)["reason"], walkable.reason)
        check_eq("unprepared_request: a case with no request file has none", M.unprepared_request(t.task, "NOPE_TC_001"), None)
    finally:
        S.cleanup(t)

    # --- the story-owned refusals stay refusals, with a dict policy beside them (E5.6) ---------------------------------
    def refused_not_walkable(label, case, ids, needle, task):
        with task.patched():
            try:
                M.prepare_to_file(task.task, case, ids)
                check(f"{label}: refused", False)
            except M.Refused as exc:
                check_eq(f"{label}: not walkable", exc.walkable, False)
                check_in(f"{label}: the story's own reason", needle, exc.reason)
        shape = json.loads(M.request_path(task.task, case).read_text(encoding="utf-8"))
        check_eq(f"{label}: request.json is `refused`, not `unprepared`", ("refused" in shape, "unprepared" in shape), (True, False))
        with task.patched():
            got = M.prepare_for_block(task.task, case)
        check_eq(f"{label}: prepare_for_block names the refusal and walks nothing", (got[0], bool(got[1]), got[2]), ([], True, ""))

    t = _dict_policy_task(rows=("TS-15",))
    try:
        refused_not_walkable("test_dict_policy_with_expectation_gap_not_walkable (TS-15)", impl, ["OB-15"],
                             "expectation unconfirmed", t)
    finally:
        S.cleanup(t)
    t = S.make_task(manual=("impl",))
    try:
        refused_not_walkable("test_expectation_gap_not_walkable", impl, ["OB-15"], "expectation unconfirmed", t)
    finally:
        S.cleanup(t)
    t = _dict_policy_task()
    try:
        with t.patched(), mock.patch.object(S.FakeController, "_validate_gate_a_content_current", create=True,
                                            side_effect=ValueError("Gate A plan changed")):
            try:
                M.prepare_to_file(t.task, ui, ["OB-7"])
                check("test_gate_a_drift_not_walkable: refused", False)
            except ValueError as exc:
                check_eq("test_gate_a_drift_not_walkable: not walkable", getattr(exc, "walkable", False), False)
            check_eq("test_gate_a_drift_not_walkable: prepare_for_block refuses", bool(M.prepare_for_block(t.task, ui)[1]), True)
        refused_not_walkable("test_unpinned_case_not_walkable", "TP1-15045_TC_099", ["OB-7"], "not among the cases pinned", t)
    finally:
        S.cleanup(t)

    def other_error(task):
        task.row("TS-12")["coverage_obligations"][0]["oracle_status"] = "maybe"       # a plan error that is not a policy shape
    t = _dict_policy_task(mutate=other_error)
    try:
        refused_not_walkable("test_other_validate_plan_error_not_walkable", ui, ["OB-7"],
                             "the approved plan does not pass its own checks", t)
    finally:
        S.cleanup(t)
    for label, field, value, needle in (("decision still `new`", "decision", "new", "as `new`"),
                                       ("only a recommendation", "execution_scope", "recommended_regression", "only a recommendation"),
                                       ("oracle unresolved", "oracle_status", "unresolved", "does not pass its own checks")):
        def scope(task, field=field, value=value):
            task.row("TS-7")["coverage_obligations"][0][field] = value
            if field == "oracle_status":
                task.row("TS-7")["coverage_obligations"][0].pop("oracle_source_ref", None)
        t = _dict_policy_task(mutate=scope)
        try:
            refused_not_walkable(f"test_scope_refusals_not_walkable ({label})", ui, ["OB-7"], needle, t)
        finally:
            S.cleanup(t)

    # --- a crash of OUR preparation after the scope checks: walkable, the traceback kept (F5(c) item 4) --------------------
    t = S.make_task(manual=("ui",))
    try:
        with t.patched(), mock.patch.object(M, "_actor_preconditions", side_effect=RuntimeError("boom in the actors")):
            try:
                M.prepare_to_file(t.task, ui, ["OB-7"])
                check("test_tail_exception_walkable_keeps_trace: refused", False)
            except M.Refused as exc:
                tail = exc
            got = M.prepare_for_block(t.task, ui)
        check("test_tail_exception_walkable_keeps_trace: walkable", tail.walkable is True)
        check_in("test_tail_exception_walkable_keeps_trace: the type and the words", "RuntimeError: boom in the actors", tail.reason)
        marker = M.unprepared_request(t.task, ui)
        check("test_tail_exception_walkable_keeps_trace: the traceback is in the request file, at most 20 lines",
              "RuntimeError" in marker.get("trace", "") and len(marker["trace"].splitlines()) <= M.TRACE_LINES)
        check_eq("test_tail_exception_walkable_keeps_trace: and the block gets the case", (got[0], got[1]), (["OB-7"], ""))
        # mixed policies, and an empty completion condition, are the factory's too (item 3)
        for label, selected in (("mixed policies", [{"evidence_policy": "ui", "completion_condition": "c"},
                                                    {"evidence_policy": "api", "completion_condition": "c"}]),
                                ("an empty completion condition", [{"evidence_policy": "ui", "completion_condition": ""}])):
            try:
                M._request_tail(t.task, ui, {}, {}, ["OB-7"], selected, {}, {}, {}, "door")
                check(f"item 3: {label} is refused", False)
            except M.Refused as exc:
                check_eq(f"item 3 (E5.2): {label} is walkable", exc.walkable, True)
    finally:
        S.cleanup(t)

    # --- the record: write_block, validate_manual_current, the reader ------------------------------------------------------
    t = _dict_policy_task()
    try:
        with t.patched():
            M.prepare_for_block(t.task, ui)
            reason = M.unprepared_request(t.task, ui)["reason"]

            def walk(**over):
                record = {"schema_version": 2, "case": ui, "obligation_ids": ["OB-7"], "unprepared": {"reason": reason},
                          "observations": [], "finding": "work/evidence/manual/x/finding.md", "dispatch_id": "S6-qa-runner-1",
                          "attempt_started_at": "2026-10-01T10:00:00+00:00", "attempt_ended_at": "2026-10-01T10:05:00+00:00",
                          "source_revision": S.SOURCE}
                record.update(over)
                return record
            issues = CC.validate_manual_current(t.task, walk())
            check_eq("test_unprepared_never_empty_issues: an honest unprepared record yields exactly [UNPREPARED]", issues, [CC.UNPREPARED])
            check_eq("test_unprepared_only_helper: True exactly for [UNPREPARED]",
                     (CC.unprepared_only(issues), CC.unprepared_only([]), CC.unprepared_only([CC.UNPREPARED, "x"]),
                      CC.unprepared_only(None)), (True, False, False, False))
            path = M.write_block(t.task, [walk()], declared=True)
            written = json.loads(path.read_text(encoding="utf-8"))["manual_checks"][0]
            check_eq("test_write_block_accepts_unprepared_record: written whole, with no result",
                     ("unprepared" in written, "result" in written), (True, False))
            for label, bad, needle in (
                    ("test_unprepared_record_with_result_refused", walk(result="pass"), "an unprepared walk records no result"),
                    ("test_unprepared_record_with_result_refused (then_quotes)", walk(then_quotes=[]), "records no result"),
                    ("test_unprepared_marker_without_request_refused (other reason)", walk(unprepared={"reason": "I say so"}),
                     "unprepared marker without an unprepared request"),
                    ("an unprepared walk of other obligations", walk(obligation_ids=["OB-12"]), "names the obligations of its request")):
                try:
                    M.write_block(t.task, [bad], declared=True)
                    check(f"{label}: refused", False)
                except ValueError as exc:
                    check_in(f"{label}: refused with the words", needle, str(exc))
        report = {"current_manual_checks": [dict(walk(), evidence_validated=False, current_obligation_ids=["OB-7"]),
                                            {"case": "x", "result": "pass", "evidence_validated": True}]}
        rows = M.unprepared_rows(report)
        check_eq("test_unprepared_rows_reader: one row, the case, ids, reason, observations, finding",
                 rows, [{"case": ui, "obligation_ids": ["OB-7"], "reason": reason, "observations": [],
                         "finding": "work/evidence/manual/x/finding.md"}])
        check_eq("test_unprepared_rows_reader: a report with none, or no list, has none",
                 (M.unprepared_rows({}), M.unprepared_rows({"current_manual_checks": [{"result": "pass"}]}), M.unprepared_rows(None)),
                 ([], [], []))
    finally:
        S.cleanup(t)
    t = S.make_task(manual=("ui",))
    try:
        with t.patched():
            M.prepare_to_file(t.task, ui, ["OB-7"])         # a PREPARED case: its request holds no `unprepared`
            record = {"schema_version": 2, "case": ui, "obligation_ids": ["OB-7"], "unprepared": {"reason": "to escape the quote rule"},
                      "observations": [], "dispatch_id": "d", "attempt_started_at": "2026-10-01T10:00:00+00:00",
                      "attempt_ended_at": "2026-10-01T10:05:00+00:00", "source_revision": S.SOURCE}
            check_eq("test_unprepared_marker_without_request_refused: a prepared case's runner cannot write the marker",
                     CC.validate_manual_current(t.task, record)[:2], [CC.UNPREPARED, "unprepared marker without an unprepared request"])
            try:
                M.write_block(t.task, [record], declared=True)
                check("test_unprepared_marker_without_request_refused: write_block refuses", False)
            except ValueError as exc:
                check_in("test_unprepared_marker_without_request_refused: write_block refuses", "without an unprepared request", str(exc))
    finally:
        S.cleanup(t)


def pc5a_c11_about_is_checked_against_the_stories_sides():
    """t-2181 PC-5a C11: a walked case's `about` names sides of THIS story (read through `contract.story_sides`); a name that
    is no side is refused with a door, a story with no record of its sides reads the default side, no `about` is not checked."""
    shutil.rmtree(ROOT, ignore_errors=True)
    try:
        before, after = ROOT / "work/evidence/before.png", ROOT / "work/evidence/after.png"
        before.parent.mkdir(parents=True)
        before.write_bytes(b"before")
        after.write_bytes(b"after")
        row = record(before, after)
        (ROOT / "pipeline.json").write_text(json.dumps({"sides": {"ui": {"reality": "real"}, "backend": {"reality": "substituted"}}}),
                                            encoding="utf-8")
        text = lambda value: "\n".join(M.validate_record(dict(row, about=value), ROOT))
        check_eq("PC-5a C11: a record with no `about` is as valid as before", M.validate_record(row, ROOT), [])
        check_eq("PC-5a C11: `about` naming the story's sides is valid", M.validate_record(dict(row, about=["ui", "backend"]), ROOT), [])
        check_in("PC-5a C11: a name that is not a side is refused, naming it and the sides", "'cart', not a side of this story (its sides: backend, ui)",
                 text(["ui", "cart"]))
        check_in("PC-5a C11: the refusal names a door", "Door: name only those sides in `about`", text(["cart"]))
        check_in("PC-5a C11: a string is refused as a shape", "about must be an array of side names", text("ui"))
        (ROOT / "pipeline.json").unlink()
        check_in("PC-5a C11: a story with no record of its sides has the default side `product` only", "its sides: product", text(["ui"]))
        check_eq("PC-5a C11: ... and `product` is valid there", M.validate_record(dict(row, about=["product"]), ROOT), [])
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)


def main():
    pc5a_c11_about_is_checked_against_the_stories_sides()
    f5_unprepared_cases()
    f5_only_the_cases_own_shape_errors_unprepare_it()
    n2_validators_list_all()
    legacy_checks()
    n2_k9_the_persons_word_in_validate_and_the_baseline_that_refuses_it()
    doc_keys_n2()
    doc_keys()
    prepare_cases()
    refusal_texts_are_for_a_person()
    prepare_cli()
    build_cases()
    observations_build_cases()
    checkout_revision_binding()
    doc_keys_t277()
    phase_words_one_source()
    api_build_cases()
    finish("test_manual_evidence")


if __name__ == "__main__":
    main()
