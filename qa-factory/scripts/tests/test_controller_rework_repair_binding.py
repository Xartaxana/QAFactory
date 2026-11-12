#!/usr/bin/env python3
"""repair binding: a part of test_controller_rework.py, split by tools/test_split.py (TD-11c). The shared helpers are in controller_rework_common."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, s5_apply, temp_project
sys.path.insert(0, str(SCRIPTS))
from controller import Controller, repair_ledger
from event_store import StateConflict  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402
import test_controller_rework_scope as SCOPED  # noqa: E402  (plan_row/gate_a_task fixtures)
import test_dispatch_liveness as LIFE  # noqa: E402  (transcript/fake_hooklib fixtures)
from controller_rework_common import CANONICAL, DESIGNER, designer_story, pin, refusal  # noqa: E402


CONTRACT = ("case_version_links", "repair_cause", "repair_cause_source", "rework_of", "reason",
            "purpose", "plan_rows", "limits")


def sent(controller, dispatch_id):
    """The payload the journal holds for a dispatch: what the request was, stamps included."""
    return next(event["payload"] for event in controller.store.read()
                if event["type"] == "dispatch" and event["payload"]["id"] == dispatch_id)


def never_started_action(root):
    """What `next` answers when nothing proves an agent ever started: the liveness repair closes
    the dispatch and hands over the relaunch packet."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text(
        json.dumps({"dispatch": {"never_started_after_s": 0.01}}), encoding="utf-8")
    LIFE.fake_hooklib([LIFE.transcript(root, "critic", "S4-qa-case-critic-1",
                                       role="qa-case-critic", ticket=root.name, age=30)])
    time.sleep(0.05)
    return Controller(root).next_action()


def a_repair_request_carries_the_current_pinned_versions():
    root = temp_project("qa-rework-canonical-case-version-")
    try:
        controller = designer_story(root)
        request = controller.build_rework_request(
            "S4", "qa-case-designer", ["TC-082"],
            "repair against the current canonical CaseVersion", cause="mechanical")
        check_eq("the request resolves the CURRENT canonical version, not the stale receipt's",
                 request.get("case_version_links"), [{"case_id": "TC-082", "version": CANONICAL}])
        check_not_in("a case outside the repair is not copied in", "TC-099",
                     [link["case_id"] for link in request.get("case_version_links") or []])
        for link in request.get("case_version_links") or []:
            link["version"] = "changed-copy"
        again = controller.build_rework_request("S4", "qa-case-designer", ["TC-082"], "again")
        check_eq("the links are copies: editing the request does not touch the pin file",
                 again.get("case_version_links"), [{"case_id": "TC-082", "version": CANONICAL}])
        check_eq("and the request stays valid for the dispatch operation",
                 refusal(lambda: controller.validate("dispatch", again, controller.state())), "")
    finally:
        cleanup(root)


def the_binding_of_a_repair_follows_the_pins_it_can_find():
    root = temp_project("qa-rework-binding-edges-")
    try:
        scope = ("TC-001", "TC-002", "TC-003")
        controller = designer_story(root, scope, links=(
            {"case_id": "TC-001", "area": "speakers", "version": "cv_speakers"},
            {"case_id": "TC-001", "area": "hosts", "version": "cv_hosts"},
            {"case_id": "TC-002", "version": "cv_two"},
            {"case_id": "TC-003"}))
        ask = lambda *cases: controller.build_rework_request(  # noqa: E731
            "S4", "qa-case-designer", list(cases), "repair", cause="tooling")
        links = lambda *cases: ask(*cases).get("case_version_links")  # noqa: E731
        check_eq("a bare id pinned in two areas brings both pins",
                 [link["version"] for link in links("TC-001") or []], ["cv_speakers", "cv_hosts"])
        check_eq("a scope case with no pin is left out, nothing is invented",
                 [link["case_id"] for link in links("TC-002", "TC-003") or []], ["TC-002"])
        check_eq("and a pin with no version is not a pin", links("TC-003"), [])
        check_eq("the area travels with the link it belongs to",
                 [link.get("area") for link in links("TC-001") or []], ["speakers", "hosts"])
        request = ask("TC-001", "TC-002")
        check_eq("the request is valid for the dispatch operation",
                 refusal(lambda: controller.validate("dispatch", request, controller.state())), "")

        (root / "state" / "story-case-links.json").unlink()
        check_eq("a story with no pin file carries an empty list, not an error",
                 links("TC-001"), [])

        caseless = controller.build_rework_request("S1", "qa-worker", [], "the sources moved",
                                                   cause="environment")
        check_eq("a caseless stage names no pins", caseless.get("case_version_links"), [])
        check_eq("and its request is valid too",
                 refusal(lambda: controller.validate("dispatch", caseless, controller.state())), "")
    finally:
        cleanup(root)


def continuation_matches_the_request(label, controller, packet, state, original, parent_status):
    for key in CONTRACT:
        check_eq(f"{label}: {key} is the request's", packet.get(key), original.get(key))
    check_eq(f"{label}: the whole packet passes the dispatch validator",
             refusal(lambda: controller.validate("dispatch", packet, state)), "")
    check_eq(f"{label}: the parent is the dispatch that stopped", parent_status[0],
             parent_status[1])


def a_paused_repair_resumes_with_its_original_request():
    root = temp_project("qa-rework-paused-")
    try:
        controller = designer_story(root)
        request = controller.build_rework_request(
            "S4", "qa-case-designer", ["TC-082"],
            "repair against the current canonical CaseVersion", cause="mechanical")
        request["limits"] = {"requests": 33}
        controller.apply("dispatch", dict(request))
        original = sent(controller, request["id"])
        pin(root, {"case_id": "TC-082", "version": "cv_moved_since"})
        bound = controller.state()["dispatches"][request["id"]].get("request_binding")
        check("the binding is written at dispatch time, from the request",
              bound and bound.get("reason") == request["reason"], str(bound))
        # A checkpoint that tries to carry a binding of its own (adversarial): written once, so
        # nothing the dispatch goes through afterwards can replace it.
        controller.apply("checkpoint", {"id": request["id"], "status": "paused",
                                        "reason": "waiting on the stand",
                                        "checkpoint": {"remaining": ["TC-082"]},
                                        "request_binding": {"reason": "forged"},
                                        "idempotency_key": "cp-1"})
        state = controller.state()
        record = state["dispatches"][request["id"]]
        check_eq("a checkpoint never rewrites the binding", record.get("request_binding"), bound)
        check("the record's reason is no longer the request's (a checkpoint rewrote it)",
              record["reason"] == "waiting on the stand" and original["reason"] != record["reason"],
              record["reason"])
        for source, packet in (("recover", controller.retry_packets(state)[0]["packet"]),
                               ("next", controller.next_action()["packet"]),
                               ("builder", Controller._retry_packet(state, record))):
            check_eq(f"{source}: the reason is the request's, not the checkpoint's",
                     packet.get("reason"), request["reason"])
            check_eq(f"{source}: the binding is the ORIGINAL one, never re-resolved from the pins",
                     packet.get("case_version_links"), [{"case_id": "TC-082", "version": CANONICAL}])
            continuation_matches_the_request(f"paused {source}", controller, packet, state,
                                             original, (record["status"], "paused"))
        packet = Controller._retry_packet(state, record)
        for link in packet.get("case_version_links") or []:
            link["version"] = "changed-copy"
        (packet.get("limits") or {})["requests"] = 1
        packet["known_paths"]["added"] = "x"
        binding = record.get("request_binding") or {}
        check_eq("the packet is a copy: the record's binding is untouched",
                 [link["version"] for link in binding.get("case_version_links") or []], [CANONICAL])
        check_eq("nor its limits", binding.get("limits"), {"requests": 33})
        check_eq("nor its paths", "added" in record["known_paths"], False)
        fresh = Controller._retry_packet(state, record)
        for link in binding.get("case_version_links") or []:
            link["version"] = "changed-record"
        check_eq("and a later change of the record does not reach a packet already built",
                 [link["version"] for link in fresh.get("case_version_links") or []], [CANONICAL])

        resumed = Controller._retry_packet(controller.state(), controller.state()["dispatches"][request["id"]])
        controller.apply("dispatch", dict(resumed))
        new = controller.state()["dispatches"][resumed["id"]]
        check_eq("the retry dispatches as it stands", new["status"], "running")
        check_eq("and its own binding is the original one again, so a second continuation keeps it",
                 (new.get("request_binding") or {}).get("case_version_links"),
                 [{"case_id": "TC-082", "version": CANONICAL}])
        check_eq("with the original reason", (new.get("request_binding") or {}).get("reason"),
                 request["reason"])
    finally:
        cleanup(root)


def a_never_started_repair_relaunches_with_its_original_request():
    root = temp_project("qa-rework-never-started-")
    try:
        controller = designer_story(root)
        request = controller.build_rework_request(
            "S4", "qa-case-designer", ["TC-082", "TC-099"],
            "repair against the current canonical CaseVersion", cause="mechanical")
        # The stand-signal stamp: a cause the CONTROLLER chose, with its source, which a
        # continuation must carry as it carried the person's.
        controller._window_stand_signal = lambda state, req: {"summary": "evidence/runs/s4/run-1.json"}
        stamped = dict(request)
        stamped.pop("repair_cause")
        controller.apply("dispatch", stamped)
        original = sent(controller, request["id"])
        check_eq("the controller stamped the cause and its source on the request",
                 (original.get("repair_cause"), original.get("repair_cause_source")),
                 ("environment", "stand_signal:evidence/runs/s4/run-1.json"))
        ledger_before = repair_ledger(controller.state()["dispatches"],
                                      controller.state()["dispatches"][request["id"]])
        pin(root, {"case_id": "TC-082", "version": "cv_moved_since"})
        try:
            action = never_started_action(root)
            check_eq("nothing proves an agent started, so `next` closes it and relaunches",
                     action["action"], "relaunch")
            state = Controller(root).state()
            record = state["dispatches"][request["id"]]
            check("the record's reason is the liveness repair's, not the request's",
                  record["status"] == "never_started" and record["reason"] != original["reason"]
                  and "no subagent transcript" in record["reason"], record["reason"])
            check_eq("and the liveness repair left the binding as it was",
                     record.get("request_binding", {}).get("reason"), original["reason"])
            for source, packet in (("next", action["dispatch_request"]),
                                   ("builder", Controller._relaunch_packet(state, record))):
                check_eq(f"{source}: the reason is the request's", packet.get("reason"),
                         original["reason"])
                check_eq(f"{source}: the cause and its source are the controller's stamp",
                         (packet.get("repair_cause"), packet.get("repair_cause_source")),
                         ("environment", "stand_signal:evidence/runs/s4/run-1.json"))
                check_eq(f"{source}: the binding is the original, not the moved pin",
                         packet.get("case_version_links"),
                         [{"case_id": "TC-082", "version": CANONICAL},
                          {"case_id": "TC-099", "version": "cv_other"}])
                check_eq(f"{source}: it names the dispatch it relaunches",
                         (packet.get("relaunch_of"), packet.get("rework_of")), (request["id"], DESIGNER))
                continuation_matches_the_request(f"relaunch {source}", controller, packet, state,
                                                 original, (record["status"], "never_started"))
            packet = Controller._relaunch_packet(state, record)
            for link in packet.get("case_version_links") or []:
                link["version"] = "changed-copy"
            packet["known_paths"]["added"] = "x"
            packet["budget"]["added"] = 1
            binding = record.get("request_binding") or {}
            check_eq("the packet is a copy of the binding",
                     [link["version"] for link in binding.get("case_version_links") or []],
                     [CANONICAL, "cv_other"])
            check_eq("of the paths", "added" in record["known_paths"], False)
            check_eq("and of the budget", "added" in record["budget"], False)

            check_eq("the relaunch dispatches as it stands",
                     refusal(lambda: controller.apply("dispatch", dict(action["dispatch_request"]))), "")
            check_eq("the same packet replayed is the same event, not a refusal (FR-45)",
                     refusal(lambda: controller.apply("dispatch", dict(action["dispatch_request"]))), "")
            after = Controller(root).state()
            new = after["dispatches"][action["dispatch_request"]["id"]]
            check_eq("the new record names the closed one", new.get("relaunch_of"), request["id"])
            check("with the original binding", binding and new.get("request_binding") == binding,
                  str(new.get("request_binding")))
            ledger_after = repair_ledger(after["dispatches"], new)
            check_eq("relaunching a round that never started spends no extra round",
                     (ledger_after["counted"], ledger_after["by_cause"]),
                     (ledger_before["counted"], ledger_before["by_cause"]))
            # t-2183 F1: the same id under a FRESH idempotency key is no replay - it is refused by name, nothing dispatched
            fresh = dict(action["dispatch_request"], idempotency_key=str(action["dispatch_request"].get("idempotency_key")) + "-fresh")
            fresh.pop("expected_revision", None)
            dispatched_before = [e for e in controller.store.read() if e["type"] == "dispatch"]
            check_in("a recorded id under a fresh key is refused: resume, do not replace",
                     "resume existing dispatch", refusal(lambda: controller.apply("dispatch", dict(fresh))))
            check_eq("and no dispatch event was committed for it",
                     ([e for e in controller.store.read() if e["type"] == "dispatch"] == dispatched_before,
                      any(e["idempotency_key"] == fresh["idempotency_key"] for e in controller.store.read())),
                     (True, False))
        finally:
            LIFE.without_hooklib()
    finally:
        cleanup(root)


def a_relaunch_of_a_test_defect_round_is_not_a_second_round():
    root = temp_project("qa-rework-relaunch-counted-")
    try:
        controller = designer_story(root)
        request = controller.build_rework_request("S4", "qa-case-designer", ["TC-082", "TC-099"],
                                                  "the critic's two replacements")
        controller.apply("dispatch", dict(request))
        running = controller.state()["dispatches"][request["id"]]
        before = repair_ledger(controller.state()["dispatches"], running)
        check_eq("the round counts while it runs", before["counted"], 1)
        try:
            action = never_started_action(root)
            s5_apply(controller, dict(action["dispatch_request"]))
        finally:
            LIFE.without_hooklib()
        after = controller.state()
        new = after["dispatches"][action["dispatch_request"]["id"]]
        check_eq("its relaunch counts as the same one round",
                 repair_ledger(after["dispatches"], new)["counted"], before["counted"])
    finally:
        cleanup(root)


def a_record_without_a_binding_falls_back_to_the_four_fields():
    root = temp_project("qa-rework-no-binding-")
    try:
        controller = designer_story(root)
        state = controller.state()
        record = {"id": "S4-qa-case-designer-9", "stage": "S4", "role": "qa-case-designer",
                  "scope": ["TC-082"], "input_hash": "design-input", "known_paths": {"root": "r"},
                  "budget": {"requests": 5}, "status": "paused", "purpose": "repair_verify",
                  "limits": {"requests": 9}, "execution_kind": "automation",
                  "manual_case_ids": ["TC-082"], "reason": "written before the binding existed",
                  "repair_cause": "mechanical", "checkpoint": {"remaining": ["TC-082"]}}
        for name, build in (("retry", Controller._retry_packet), ("relaunch", Controller._relaunch_packet)):
            packet = build(state, record)
            check_eq(f"{name}: today's four fields come from the record",
                     (packet["purpose"], packet["limits"], packet["execution_kind"],
                      packet["manual_case_ids"]),
                     ("repair_verify", {"requests": 9}, "automation", ["TC-082"]))
            check_eq(f"{name}: nothing else is invented from a record that cannot say it",
                     [key for key in ("case_version_links", "repair_cause", "reason", "rework_of")
                      if key in packet], [])
        bare = dict(record, request_binding={})
        check_eq("a binding that is empty is a request that carried none of them",
                 "purpose" in Controller._retry_packet(state, bare), False)
    finally:
        cleanup(root)


def a_continuation_packet_takes_its_paths_from_the_stamp_and_its_plan_rows_by_presence():
    """0.8.1 `_stamped_paths` (portable tokens, this package's fingerprint) is the one source of a
    continuation's `known_paths`, binding or not; `plan_rows` is carried by PRESENCE: the binding's
    list wins, else the record's, and `[]` stays `[]` while an absent key stays absent."""
    root = temp_project("qa-rework-packet-sources-")
    try:
        controller = designer_story(root)
        state = controller.state()
        base = {"id": "S4-qa-case-designer-8", "stage": "S4", "role": "qa-case-designer",
                "scope": ["TC-082"], "input_hash": "design-input", "budget": {"requests": 5},
                "status": "paused", "checkpoint": {"remaining": ["TC-082"]}}
        stale = {"root": "r", "package_fingerprint": "stamp-of-another-package", "package_version": "0.0.0"}
        for name, build in (("retry", Controller._retry_packet), ("relaunch", Controller._relaunch_packet)):
            for label, extra in (("no binding", {}), ("a binding", {"request_binding": {"reason": "why"}})):
                record = dict(base, known_paths=dict(stale), **extra)
                packet = build(state, record)
                check_eq(f"{name}, {label}: known_paths is what `_stamped_paths` makes of the record's",
                         packet["known_paths"], Controller._stamped_paths(record["known_paths"]))
                check(f"{name}, {label}: the old package's stamp is not copied",
                      packet["known_paths"].get("package_fingerprint") != "stamp-of-another-package",
                      str(packet["known_paths"]))
                check_eq(f"{name}, {label}: the record's own paths are not aliased",
                         record["known_paths"], stale)
                check_eq(f"{name}, {label}: the budget is a copy", packet["budget"] is record["budget"], False)
            rows = [{"row_id": "TS-1"}]
            for label, record, expected in (
                    ("no binding, absent", dict(base), None),
                    ("no binding, empty", dict(base, plan_rows=[]), []),
                    ("no binding, rows", dict(base, plan_rows=rows), rows),
                    ("a binding without the key falls to the record", dict(
                        base, request_binding={"reason": "why"}, plan_rows=rows), rows),
                    ("a binding with the key wins", dict(
                        base, request_binding={"plan_rows": []}, plan_rows=rows), []),
                    ("a binding with the key and rows", dict(
                        base, request_binding={"plan_rows": rows}), rows),
                    ("a binding without the key, none on the record", dict(
                        base, request_binding={"reason": "why"}), None)):
                packet = build(state, record)
                if expected is None:
                    check_eq(f"{name}, {label}: plan_rows stays absent", "plan_rows" in packet, False)
                else:
                    check_eq(f"{name}, {label}: plan_rows", packet.get("plan_rows"), expected)
                    check_eq(f"{name}, {label}: plan_rows is a copy",
                             any(packet["plan_rows"] is value for value in (rows, record.get("plan_rows"),
                                 (record.get("request_binding") or {}).get("plan_rows"))), False)
    finally:
        cleanup(root)


def a_made_up_relaunch_is_refused_and_a_new_dispatch_is_judged_as_before():
    root = temp_project("qa-rework-relaunch-refused-")
    try:
        controller = designer_story(root)
        request = controller.build_rework_request("S4", "qa-case-designer", ["TC-082"],
                                                  "repair", cause="mechanical")
        controller.apply("dispatch", dict(request))
        try:
            action = never_started_action(root)
        finally:
            LIFE.without_hooklib()
        good = action["dispatch_request"]
        state = controller.state()
        check_eq("the packet `next` printed is accepted", refusal(
            lambda: controller.validate("dispatch", good, state)), "")

        made_up = dict(good, relaunch_of="S4-qa-case-designer-99")
        message = refusal(lambda: controller.apply("dispatch", dict(made_up)))
        check_in("a relaunch of a dispatch that does not exist is refused, naming it",
                 "S4-qa-case-designer-99", message)
        check_in("and the door: the packet next prints", "dispatch_request", message)
        message = refusal(lambda: controller.apply("dispatch", dict(good, relaunch_of=DESIGNER)))
        check_in("a relaunch of an accepted dispatch is refused, naming its state",
                 "accepted", message)
        check_in("and the way on", "--operation rework", message)
        check_eq("neither left a receipt", sorted(controller.state()["dispatches"]),
                 sorted(state["dispatches"]))

        no_reason = dict(good, repair_cause="environment")
        no_reason.pop("reason", None)
        no_reason.pop("repair_cause_source", None)
        check_in("a relaunch is no door past the reason a non-test cause needs",
                 "needs `reason`", refusal(lambda: controller.validate("dispatch", no_reason, state)))
        check_in("nor past the purposes that exist", "must be one of",
                 refusal(lambda: controller.validate("dispatch", dict(good, purpose="regression"), state)))

        # The stand-signal stamp is the continuation's own business only when the packet names
        # a dispatch that exists; a made-up name is a new dispatch and is classified as one.
        controller._window_stand_signal = lambda s, req: {"summary": "evidence/runs/s4/run-2.json"}
        for name, packet, expected in (
                ("a relaunch", dict(good), None),
                ("a made-up relaunch", dict(made_up), "environment"),
                ("a fresh dispatch", {k: v for k, v in good.items() if k != "relaunch_of"}, "environment")):
            packet = dict(packet)  # the cause is not named: the stamp is what decides
            packet.pop("repair_cause", None)
            packet.pop("repair_cause_source", None)
            controller._stamp_dispatch(packet, state)
            check_eq(f"{name} is stamped as the stand says only when it is a new dispatch",
                     packet.get("repair_cause"), expected)
    finally:
        cleanup(root)


def a_continuation_is_tied_to_the_dispatch_it_names():
    """`parent_retry` always had to repeat its parent's stage, role, scope and input hash; a
    `relaunch_of` was only checked for existing and for being in a relaunchable state, so a
    packet could name a never-started dispatch and ask for different work. And a `parent_retry`
    that named nothing was a bare KeyError."""
    root = temp_project("qa-rework-continuation-tied-")
    try:
        controller = designer_story(root)
        request = controller.build_rework_request("S4", "qa-case-designer", ["TC-082", "TC-099"],
                                                  "repair", cause="mechanical")
        controller.apply("dispatch", dict(request))
        try:
            action = never_started_action(root)
        finally:
            LIFE.without_hooklib()
        good = action["dispatch_request"]
        state = controller.state()
        check_eq("the packet `next` printed is accepted as it stands", refusal(
            lambda: controller.validate("dispatch", good, state)), "")
        record = state["dispatches"][request["id"]]
        check_eq("and the record's input hash is what the packet copied",
                 good["input_hash"], record["input_hash"])

        for field, value in (("stage", "S3"), ("role", "qa-worker"),
                             ("scope", ["TC-099"]), ("input_hash", "other-input")):
            message = refusal(lambda: controller.apply("dispatch", dict(good, **{field: value})))
            check_in(f"a relaunch that changes {field} is refused", "relaunch_of", message)
            check_in(f"and says it is {field} that differs", f"differs in {field}", message)
            check_in("and what the dispatch it names has", repr(record[field]), message)
            check_in("and the door: the packet next prints, dispatched as it stands",
                     "dispatch_request", message)
            check_in("and that different work is a dispatch of its own", "new dispatch", message)
        message = refusal(lambda: controller.validate(
            "dispatch", dict(good, role="qa-worker", scope=["TC-099"]), state))
        check_in("every difference is named in the one refusal", "differs in role, scope", message)
        check_eq("none of them left a receipt", sorted(controller.state()["dispatches"]),
                 sorted(state["dispatches"]))
        # A scope that is absent on the record is the same as an empty one.
        bare = dict(record, id="S4-qa-case-designer-8", scope=None)
        bare_state = dict(state, dispatches=dict(state["dispatches"], **{bare["id"]: bare}))
        check_eq("an absent scope on the dispatch is an empty scope, not a difference",
                 refusal(lambda: controller.validate(
                     "dispatch", dict(good, relaunch_of=bare["id"], scope=[]), bare_state)), "")

        # A name that is not even a string: a bare `TypeError: unhashable` from a dict lookup.
        for field in ("relaunch_of", "parent_retry"):
            for value in (["S4-qa-case-designer-2"], {"id": "S4-qa-case-designer-2"}):
                packet = dict(good, **{field: value}, checkpoint={"remaining": ["TC-082"]})
                if field == "parent_retry":
                    packet.pop("relaunch_of")
                try:
                    controller.validate("dispatch", packet, state)
                    message, kind = "", "no refusal"
                except StateConflict as exc:
                    message, kind = str(exc), "refusal"
                except Exception as exc:  # noqa: BLE001 - the point: nothing bare may come out
                    message, kind = str(exc), type(exc).__name__
                check_eq(f"{field} = {type(value).__name__}: a refusal, not {kind}", kind, "refusal")
                check_in(f"{field} = {type(value).__name__}: it says it names no dispatch",
                         "names no dispatch", message)
                check_in(f"{field} = {type(value).__name__}: and the door", "controller.py --operation next",
                         message)

        gone = dict(good, id="S4-qa-case-designer-9", parent_retry="S4-qa-case-designer-99",
                    checkpoint={"remaining": ["TC-082"]}, idempotency_key="dispatch:gone")
        gone.pop("relaunch_of")
        for name, call in (("validate", lambda: controller.validate("dispatch", dict(gone), state)),
                           ("apply", lambda: controller.apply("dispatch", dict(gone)))):
            try:
                call()
                message, bare_key = "", False
            except KeyError:
                message, bare_key = "", True
            except (ValueError, StateConflict) as exc:
                message, bare_key = str(exc), False
            check_eq(f"{name}: a parent_retry that names no dispatch is no bare KeyError", bare_key, False)
            check_in(f"{name}: it is refused, naming it", "S4-qa-case-designer-99", message)
            check_in(f"{name}: and the door: the packet next or recover prints", "controller.py --operation next",
                     message)
        check_eq("and no receipt was left", sorted(controller.state()["dispatches"]),
                 sorted(state["dispatches"]))
        check_eq("a relaunch that repeats the same work is not touched",
                 refusal(lambda: controller.apply("dispatch", dict(good))), "")
    finally:
        cleanup(root)


def a_completion_cannot_bind_a_record_that_has_no_binding():
    """`request_binding` is written once, from the dispatch request. A record with none (imported
    from a pre-controller pipeline) must not be given one by a checkpoint or an accept payload:
    a continuation would then be built from words the request never carried."""
    from controller import projection
    legacy = {"id": "legacy:S1", "stage": "S1", "role": "legacy", "status": "incomplete",
              "checkpoint": {"remaining": ["S1"]}, "reason": "imported", "imported": True}
    start = {"type": "initialize", "sequence": 1, "payload": {
        "scope": [], "source_revision": "s", "known_paths": {},
        "legacy_import": {"stages": {"S1": {"status": "incomplete", "dispatch_id": "legacy:S1",
                                            "imported": True}},
                          "dispatches": {"legacy:S1": legacy}, "decisions": {}}}}
    forged = {"reason": "forged", "rework_of": "S1-x-1", "case_version_links": [{"case_id": "TC-1"}]}
    for kind, payload in (
            ("checkpoint", {"id": "legacy:S1", "status": "paused", "reason": "r",
                            "checkpoint": {"remaining": ["S1"]}, "request_binding": forged}),
            ("accept", {"id": "legacy:S1", "status": "accepted", "stage_complete": True,
                        "evidence_refs": [{"path": "a", "sha256": "0" * 64}],
                        "request_binding": forged})):
        record = projection([start, {"type": kind, "sequence": 2, "payload": payload}]
                            )["dispatches"]["legacy:S1"]
        check_eq(f"{kind}: the rest of the payload still lands", record["status"], payload["status"])
        check_eq(f"{kind}: but no binding is set on a record that had none",
                 "request_binding" in record, False)
        check_eq(f"{kind}: so a continuation of it falls back to the four fields",
                 Controller._original_request(record), {})


def no_bare_key_error_reaches_a_reader():
    root = temp_project("qa-key-error-")
    try:
        controller = SCOPED.gate_a_task(root)
        message = ""
        try:
            s5_apply(controller, {"id": "x", "stage": "S5", "role": "qa-automator",
                                          "scope": ["TC-1"], "input_hash": "s5", "budget": {},
                                          "known_paths": {}, "idempotency_key": "k",
                                          "model_policy": {"parent": {"model": "m"}}})
        except (ValueError, KeyError) as exc:
            message = str(exc)
        check("a missing model_policy field is no longer the bare key the CLI printed",
              message != "'supported'", message)
        check_in("it names the field the request is missing", "model_policy requires", message)
        check_in("and the other one beside it", "'parent'", message)
        check_in("and says what omitting the policy does", "inherit", message)

        result = run_script("controller.py", "--task-root", root, "--operation", "teleport")
        check_in("an unknown operation is answered with the list of operations",
                 "must be one of", result.stderr)
        check_in("which includes the ones a person actually types", "gate-decision", result.stderr)
    finally:
        cleanup(root)


def the_cli_records_a_gate_decision_and_a_rework():
    root = temp_project("qa-cli-ops-")
    try:
        controller = Controller(root)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                        "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
        for number in range(5):
            BASE.accept_stage(controller, root, f"S{number}")
        result = run_script("controller.py", "--task-root", root, "--operation", "gate-decision",
                            "--gate", "A", "--words", "approve, keep all automate")
        check("the CLI records the gate decision in one call", result.returncode == 0,
              result.stderr)
        recorded = json.loads(result.stdout)
        check_eq("and says so", recorded["recorded"], True)
        check_eq("with the next action in the same answer",
                 recorded["next_action"]["stage"], "S5")
        check_eq("the person's words are what was recorded",
                 Controller(root).state()["decisions"]["gateA-" + root.name]["authorization_source"],
                 "approve, keep all automate")
        result = run_script("controller.py", "--task-root", root, "--operation", "rework",
                            "--stage", "S4", "--role", "qa-worker", "--cases", "TC-1",
                            "--reason", "carry the case ids into the plan", "--build-only")
        check("a rework request can be inspected before it is sent", result.returncode == 0,
              result.stderr)
        built = json.loads(result.stdout)
        check_eq("and nothing was dispatched by the inspection", built["dispatched"], False)
        check_eq("the request is complete enough to send as it stands",
                 sorted(k for k in ("id", "stage", "role", "scope", "input_hash", "budget",
                                    "known_paths") if k in built["request"]),
                 ["budget", "id", "input_hash", "known_paths", "role", "scope", "stage"])
    finally:
        cleanup(root)


# --- C1-2 (conductor/1, C4, FR-8): a rework takes the person's words from a file ------------------------------------

def rework_takes_the_persons_words_from_a_file():
    """`rework --words-file` goes through `person_words.read`, so a multi-line reason (CRLF included) is stored whole; both
    `--reason` and `--words-file` are refused (exit 2) before any event; the inline `--reason` is untouched, also under the
    cmd launcher, where `gate-decision --words` inline is refused (the control that proves the marker is on)."""
    import os
    root = temp_project("qa-rework-words-")
    try:
        controller = Controller(root)
        controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                        "known_paths": {"root": str(root)}, "idempotency_key": "init"})
        BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
        for number in range(5):
            BASE.accept_stage(controller, root, f"S{number}")
        words = root / "words.txt"
        raw = b"the export test checks only the status code\r\nplease check the body too\r\n"
        words.write_bytes(raw)
        base = ("--task-root", root, "--operation", "rework", "--stage", "S4", "--role", "qa-worker", "--cases", "TC-1")
        before = Controller(root).state()["revision"]
        result = run_script("controller.py", *base, "--words-file", words, "--build-only")
        check("C4: --words-file alone builds the request", result.returncode == 0, result.stderr)
        check_eq("C4: the request's reason is the file's bytes, CRLF and two lines whole",
                 json.loads(result.stdout)["request"]["reason"].encode("utf-8"), raw)
        result = run_script("controller.py", *base, "--words-file", words)
        check("C4: and it dispatches", result.returncode == 0, result.stderr)
        stored = [d.get("reason") for d in Controller(root).state()["dispatches"].values() if d.get("rework_of")]
        check_eq("C4: the stored receipt keeps the reason whole", [r.encode("utf-8") for r in stored if r], [raw])
        after_one = Controller(root).state()["revision"]
        check("C4: that dispatch is an event", after_one > before)
        result = run_script("controller.py", *base, "--words-file", words, "--reason", "inline words")
        check_eq("C4: both flags are refused with exit 2", result.returncode, 2)
        check_in("C4: ...and the refusal names both options", "--reason and --words-file", result.stderr)
        check_eq("C4: ...and no event was recorded", Controller(root).state()["revision"], after_one)
        result = run_script("controller.py", *base, "--words-file", root / "missing.txt")
        check_eq("C4: a missing file is refused with exit 2", result.returncode, 2)
        check_eq("C4: ...and records no event", Controller(root).state()["revision"], after_one)
        # the inline path is untouched, also under the cmd launcher (the factory's own finding text goes there)
        via_cmd = dict(os.environ, QA_FACTORY_LAUNCHER="cmd")
        refused = run_script("controller.py", "--task-root", root, "--operation", "gate-decision", "--gate", "A",
                             "--words", "approve", "--build-only", env=via_cmd)
        check_eq("C4 control: under the cmd launcher an inline person's words (gate-decision --words) are refused",
                 refused.returncode, 2)
        inline = run_script("controller.py", *base, "--reason", "the refusal, verbatim", "--build-only", env=via_cmd)
        check("C4: inline --reason is still accepted under the cmd launcher", inline.returncode == 0, inline.stderr)
        check_eq("C4: ...and is stored as given", json.loads(inline.stdout)["request"]["reason"], "the refusal, verbatim")
    finally:
        cleanup(root)


def main():
    a_repair_request_carries_the_current_pinned_versions()
    the_binding_of_a_repair_follows_the_pins_it_can_find()
    a_paused_repair_resumes_with_its_original_request()
    a_never_started_repair_relaunches_with_its_original_request()
    a_relaunch_of_a_test_defect_round_is_not_a_second_round()
    a_record_without_a_binding_falls_back_to_the_four_fields()
    a_continuation_packet_takes_its_paths_from_the_stamp_and_its_plan_rows_by_presence()
    a_made_up_relaunch_is_refused_and_a_new_dispatch_is_judged_as_before()
    a_continuation_is_tied_to_the_dispatch_it_names()
    a_completion_cannot_bind_a_record_that_has_no_binding()
    no_bare_key_error_reaches_a_reader()
    the_cli_records_a_gate_decision_and_a_rework()
    rework_takes_the_persons_words_from_a_file()
    finish("test_controller_rework_repair_binding")


# split: runner piece 1
if __name__ == "__main__":
    main()
