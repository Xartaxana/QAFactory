"""CX1-9 (FB-16, TP2-2406): a native resume is judged by its RECIPIENT's story.

A Codex `followup_task` to 2406's case designer carried no slug in `task_name` and an opaque message;
2406's S4 was accepted with blocked rework (not `running`), so `resolve_ticket` fell through to the single
running story and checked the resume against 2534. The receipt the host (or `story_step bind`) wrote for the
recipient is the record that ties it to its story, and it is read before the text and single-story steps.
A recipient no receipt names resolves nothing, and with stories on disk that is a refusal, never an allow.
A name two stories hold names no story; a receipt vouches only for a dispatch this story can still resume
(not `superseded`, not released); `host_dispatch.binding_names` is the one reader of a receipt's names.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     mark_project, temp_dir)

sys.path.insert(0, str(SCRIPTS))
import controller as CTL  # noqa: E402
import hooklib  # noqa: E402
import host_dispatch as HD  # noqa: E402
import stage_guard as SG  # noqa: E402
from host_adapter import normalize  # noqa: E402
from host_dispatch import (binding_names, binding_path, matching_binding_paths,  # noqa: E402
                           receipt_files, resolve_binding_path)

TARGET = "/root/qa_case_designer__tp2_2406"
AGENT = "designer-2406-id"
REAL_PATH = "/root/qa_test_strategist__tp2_2406"
REAL_NAME = REAL_PATH.rsplit("/", 1)[1]
OPAQUE = "gAAAAAB" + "x" * 60
STORIES = ("TP2-2406", "TP2-2520", "TP2-2530", "TP2-2534")


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def story(root: Path, ticket: str, status: str, agent: str) -> None:
    write(root / "qa-factory/artifacts" / ticket / "pipeline.json", {
        "ticket": ticket, "gates": {},
        "stages": {"S4": {"status": status, "agent_id": agent, "later_work_status": "blocked"}}})


def add_record(root: Path, ticket: str, dispatch: str, **row) -> None:
    """One dispatch record of the story's controller (created on the first call); `row` replaces the record."""
    path = root / "qa-factory/artifacts" / ticket / "state/controller.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"dispatches": {}}
    state["dispatches"][dispatch] = dict({"id": dispatch}, **row)
    write(path, state)


def receipt(root: Path, identity: str, ticket, dispatch, **extra) -> Path:
    """A `story_step bind`-shaped receipt, hashed by `identity`."""
    path = binding_path(root, identity)
    write(path, dict({"agent_id": identity, "agent_type": "qa-scout", "task_id": ticket,
                      "dispatch_id": dispatch, "status": "running", "bound_by": "story_step"}, **extra))
    return path


def project() -> Path:
    """2406 accepted with blocked rework and its designer bound; 2534 the only running story."""
    root = mark_project(temp_dir("qa-factory-resume-isolation-"))
    story(root, "TP2-2406", "done", AGENT)
    story(root, "TP2-2534", "running", "")
    add_record(root, "TP2-2406", "S4-qa-case-designer-1", role="qa-case-designer",
               agent_id=AGENT, status="accepted")
    receipt(root, AGENT, "TP2-2406", "S4-qa-case-designer-1", agent_type="qa-case-designer",
            task_path=TARGET, task_name=TARGET.rsplit("/", 1)[1])
    return root


def project_real(stories=STORIES) -> Path:
    """The stand as it was: 2406 done with blocked rework and its strategist bound by story_step (a receipt
    with the full path in `agent_id` and no `task_name` / `task_path`: the shape written BEFORE CX1-9),
    2520 and 2530 open with no running stage, 2534 the only story with a `running` stage."""
    root = mark_project(temp_dir("qa-factory-resume-real-"))
    for ticket in stories:
        stage = {"status": "running" if ticket == "TP2-2534" else "done"}
        if ticket == "TP2-2406":
            stage.update(agent_id=REAL_PATH, later_work_status="blocked")
        if ticket == "TP2-2534":
            stage.update(agent_id="")
        write(root / "qa-factory/artifacts" / ticket / "pipeline.json",
              {"ticket": ticket, "gates": {}, "stages": {"S3": stage}})
    if "TP2-2406" in stories:
        add_record(root, "TP2-2406", "S3-qa-test-strategist-5", role="qa-test-strategist",
                   agent_id=REAL_PATH, status="running")
        receipt(root, REAL_PATH, "TP2-2406", "S3-qa-test-strategist-5",
                agent_type="qa-test-strategist", bound_at=1792155473.69)
    return root


def shared_receipts(root: Path) -> None:
    """Two agents that share a basename and live under different roots, in two stories - each with the
    controller record its receipt names (a receipt whose dispatch has no record here vouches for nothing)."""
    for path, ticket in (("/root/qa_scout__shared", "TP2-2406"),
                         ("/other/qa_scout__shared", "TP2-2534")):
        receipt(root, path, ticket, "S1-qa-scout-1")
        add_record(root, ticket, "S1-qa-scout-1", role="qa-scout", agent_id=path, status="running")


def event(root: Path, target: str = TARGET, tool: str = "collaborationfollowup_task",
          message: str = "opaque", **extra) -> dict:
    return normalize(dict(tool_name=tool, host="codex", cwd=str(root),
                          tool_input={"target": target, "message": message}, **extra))


def checked(ev: dict) -> int:
    with contextlib.redirect_stderr(io.StringIO()):
        return SG._check(ev)


@contextlib.contextmanager
def in_project(root: Path):
    """Pin the hook layer to `root` for the block, and put the environment back after it."""
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    with hooklib.selftest_root_restored():
        hooklib._PROJECT_ROOT_CACHE = root
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        try:
            yield
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = saved


def refused_naming(label: str, ev: dict, recipient: str) -> None:
    """The fail-closed refusal of a resume no receipt identifies: it says no story was chosen, names the
    recipient, and names no story that was never asked about (13:11:21Z named 2534)."""
    check_eq(f"{label}: no story resolves", SG.requested_ticket(ev), "")
    check_eq(f"{label}: the resume is refused", checked(ev), SG.DENY)
    message = SG.LAST_DENIAL["message"]
    check_in(f"{label}: the refusal says no story was selected", "No story was selected", message)
    check_in(f"{label}: and names the recipient", recipient, message)
    check_not_in(f"{label}: and no other story", "TP2-2534", message)


def refused_as(label: str, ev: dict, *needles: str) -> None:
    """A refusal that ran: the resume is DENIED and its text carries every needle."""
    check_eq(f"{label}: is refused", checked(ev), SG.DENY)
    for needle in needles:
        check_in(f"{label}: the refusal says {needle!r}", needle, SG.LAST_DENIAL["message"])


def desktop_spawn(root: Path) -> dict:
    """A Codex Desktop `spawn_agent`: `task_name` with no story slug, an opaque message."""
    return normalize(dict(
        tool_name="collaboration.spawn_agent", host="codex", cwd=str(root),
        tool_input={"agent_type": "qa-automator", "task_name": "qa_automator__unmatched_1",
                    "fork_turns": "none", "message": OPAQUE}))


def real_checks() -> None:
    """t-031: the follow-up of 16.10 (TP2-2406 S3-5) and the classes around it."""
    root = project_real()
    other = None
    try:
        with in_project(root):
            for label, target in (("full path", REAL_PATH), ("bare name", REAL_NAME)):
                ev = event(root, target, message=OPAQUE)
                check_eq(f"real receipt, {label}: resolves 2406", SG.requested_ticket(ev), "TP2-2406")
                check_eq(f"real receipt, {label}: is allowed", checked(ev), SG.ALLOW)
                check_eq(f"real receipt, {label}: the source is the recipient binding",
                         SG.resolve_ticket(ev)[1]["explicit_source"], "the recorded resume recipient binding")

            # (b) an identity-less follow-up must not borrow the running story's identity
            refused_naming("unbound recipient", event(root, "qa_nobody__tp2_9999"),
                           "qa_nobody__tp2_9999")
            # FR-2: a Desktop followup_task carries no task_id, so the door is the bind command
            check_in("unbound recipient: the refusal names the door `story_step.py bind`",
                     "`story_step.py bind --task <TICKET> --dispatch-id <DISPATCH> --agent-id <recipient>`",
                     SG.LAST_DENIAL["message"])
            check_eq("unbound recipient: the refusal still ends with the registry's last sentence",
                     SG.LAST_DENIAL["message"].endswith("No story was selected."), True)

            # (c) a stale, unrelated running story is no better a guess
            write(root / "qa-factory/artifacts/TP2-2534/pipeline.json", {
                "ticket": "TP2-2534", "gates": {},
                "stages": {"S3": {"status": "running", "agent_id": "", "started_at": "2026-10-01T09:00:00+00:00"}}})
            refused_naming("stale running story", event(root, "qa_nobody__tp2_9999"),
                           "qa_nobody__tp2_9999")
            write(root / "qa-factory/artifacts/TP2-2534/pipeline.json", {
                "ticket": "TP2-2534", "gates": {}, "closed_at": "2026-10-02T09:00:00+00:00",
                "stages": {"S3": {"status": "running", "agent_id": ""}}})
            for ticket in ("TP2-2520", "TP2-2530"):
                (root / "qa-factory/artifacts" / ticket / "pipeline.json").unlink()
            check_eq("one open story: the unbound recipient still resolves nothing",
                     SG.requested_ticket(event(root, "qa_nobody__tp2_9999")), "")
            check_eq("one open story: and is refused", checked(event(root, "qa_nobody__tp2_9999")), SG.DENY)

            # (f) a person's word still wins over the withheld guess
            os.environ["QA_FACTORY_TASK"] = "TP2-2406"
            try:
                check_eq("QA_FACTORY_TASK names the story of an unbound recipient",
                         SG.requested_ticket(event(root, "qa_nobody__tp2_9999")), "TP2-2406")
            finally:
                os.environ["QA_FACTORY_TASK"] = ""

        other = project_real(("TP2-2406",))
        with in_project(other):
            refused_naming("a project with ONE story", event(other, "qa_nobody__tp2_9999"),
                           "qa_nobody__tp2_9999")
    finally:
        cleanup(root)
        if other is not None:
            cleanup(other)


def guess_for_dispatches_checks() -> None:
    """(e) the single-running-story guess still serves what is not a Codex resume, and E8: on the Claude
    host a SendMessage keeps main's identity (the guess), while a project with no story is still not refused."""
    root = project_real()
    try:
        with in_project(root):
            check_eq("a desktop spawn_agent still takes the single running story",
                     SG.requested_ticket(desktop_spawn(root)), "TP2-2534")
            claude = {"tool_name": "SendMessage", "cwd": str(root), "tool_input": {"to": "agent-1"}}
            check_eq("the Claude host's SendMessage still takes it too", SG.requested_ticket(claude), "TP2-2534")
            ev = event(root, REAL_PATH, "followup_task")
            ev["tool_input"].update(recipient="", target="")
            ev["_qa_host"]["input"] = {"message": OPAQUE}
            check_eq("a Codex resume with no recipient at all resolves nothing", SG.requested_ticket(ev), "")
            check_eq("and is not the guard's business (allowed)", checked(ev), SG.ALLOW)
    finally:
        cleanup(root)
    empty = mark_project(temp_dir("qa-factory-resume-empty-"))
    try:
        with in_project(empty):
            check_eq("a project with no story at all: an unbound Codex resume is not refused",
                     checked(event(empty, "qa_nobody")), SG.ALLOW)
    finally:
        cleanup(empty)


def shared_name_checks() -> None:
    """(d) two agents under different roots that share a basename; a path is never partial."""
    root = project_real()
    try:
        shared_receipts(root)
        with in_project(root):
            ev = event(root, "/root/qa_scout__shared")
            check_eq("shared name: the full path resolves its own story", SG.requested_ticket(ev), "TP2-2406")
            check_eq("shared name: and is allowed", checked(ev), SG.ALLOW)
            refused_naming("shared name, bare (two stories answer to it)",
                           event(root, "qa_scout__shared"), "qa_scout__shared")
            refused_naming("shared name, other root", event(root, "/elsewhere/qa_scout__shared"),
                           "/elsewhere/qa_scout__shared")
            refused_naming("a path never matches a basename", event(root, "/root/qa_nobody"), "/root/qa_nobody")
            refused_naming("the parent path", event(root, "/root"), "/root")
            refused_naming("a trailing slash", event(root, REAL_PATH + "/"), REAL_PATH + "/")
            refused_naming("a blank recipient beside a real one is no recipient but the real one is unbound",
                           event(root, "  qa_scout__shared  "), "qa_scout__shared")
            ev = event(root, REAL_PATH)
            ev["tool_input"]["to"] = REAL_NAME
            check_eq("two spellings of one agent in one call resolve one story", SG.requested_ticket(ev), "TP2-2406")
            check_eq("and are allowed together", checked(ev), SG.ALLOW)
            ev = event(root, "/root/qa_scout__shared")
            ev["tool_input"]["to"] = "/other/qa_scout__shared"
            check_eq("two aliases naming two stories name none", SG.requested_ticket(ev), "")
            check_eq("and the call is refused", checked(ev), SG.DENY)
    finally:
        cleanup(root)


def ambiguous_vouch_checks() -> None:
    """t-032 F-1: when step 1b answers nothing for an ambiguous bare name and a person's word or an explicit id
    names a story, that story's receipt must not vouch for the recipient: its receipts name two stories,
    and an exact receipt is one story."""
    root = project_real()
    try:
        shared_receipts(root)
        with in_project(root):
            for ticket in ("TP2-2534", "TP2-2406"):
                os.environ["QA_FACTORY_TASK"] = ticket
                try:
                    ev = event(root, "qa_scout__shared")
                    check_eq(f"QA_FACTORY_TASK={ticket}, ambiguous bare name: the person's word names the story",
                             SG.requested_ticket(ev), ticket)
                    check_eq(f"QA_FACTORY_TASK={ticket}, ambiguous bare name: the resume is refused",
                             checked(ev), SG.DENY)
                    check_in(f"QA_FACTORY_TASK={ticket}, ambiguous bare name: as not this story's dispatch",
                             "is not a dispatch this story ran", SG.LAST_DENIAL["message"])
                finally:
                    os.environ["QA_FACTORY_TASK"] = ""
            ev = event(root, "qa_scout__shared", task_id="TP2-2534")
            check_eq("explicit task_id 2534, ambiguous bare name: the id names the story",
                     SG.requested_ticket(ev), "TP2-2534")
            check_eq("explicit task_id 2534, ambiguous bare name: the resume is refused", checked(ev), SG.DENY)
            check_in("explicit task_id 2534, ambiguous bare name: as not this story's dispatch",
                     "is not a dispatch this story ran", SG.LAST_DENIAL["message"])
            os.environ["QA_FACTORY_TASK"] = "TP2-2406"
            try:
                ev = event(root, "/root/qa_scout__shared")
                check_eq("QA_FACTORY_TASK=2406, full path: resolves 2406", SG.requested_ticket(ev), "TP2-2406")
                check_eq("QA_FACTORY_TASK=2406, full path: an exact receipt is one story, allowed",
                         checked(ev), SG.ALLOW)
            finally:
                os.environ["QA_FACTORY_TASK"] = ""
            check_eq("_recipient_stories: an ambiguous bare name names both stories",
                     SG._recipient_stories(event(root, "qa_scout__shared"), SG.artifact_root(ev), "qa_scout__shared"),
                     {"TP2-2406", "TP2-2534"})
            check_eq("_recipient_stories: an unbound recipient names none",
                     SG._recipient_stories(ev, SG.artifact_root(ev), "qa_nobody"), set())
    finally:
        cleanup(root)


def same_story_checks() -> None:
    """Two receipts of ONE story answering to a bare name are one story, not an ambiguity (E2) - as long as
    every one of them names a dispatch this story can still resume (M-3: the quantifier is ALL)."""
    root = project_real()
    try:
        for path in ("/a/qa_dup", "/b/qa_dup"):
            receipt(root, path, "TP2-2406", "S1-qa-scout-1")
        add_record(root, "TP2-2406", "S1-qa-scout-1", role="qa-scout", status="running")
        with in_project(root):
            ev = event(root, "qa_dup")
            check_eq("same story, two receipts: the bare name resolves that story",
                     SG.requested_ticket(ev), "TP2-2406")
            check_eq("same story, two receipts: and is allowed", checked(ev), SG.ALLOW)

            # M-3: ONE of two receipts naming a retired dispatch vetoes the name; it is not dropped from the count
            receipt(root, "/b/qa_dup", "TP2-2406", "S1-qa-scout-2")
            add_record(root, "TP2-2406", "S1-qa-scout-2", role="qa-scout", status="superseded")
            ev = event(root, "qa_dup")
            check_eq("one of two receipts retired: the story still resolves", SG.requested_ticket(ev), "TP2-2406")
            refused_as("one of two receipts retired, bare name", ev, "qa_dup", "dispatch S1-qa-scout-2 is superseded")
            check_eq("one of two receipts retired: the exact receipt of the live one answers alone and is allowed",
                     checked(event(root, "/a/qa_dup")), SG.ALLOW)
            check_eq("one of two receipts retired: the exact receipt of the retired one is refused",
                     checked(event(root, "/b/qa_dup")), SG.DENY)
            check_in("and says which dispatch", "dispatch S1-qa-scout-2 is superseded", SG.LAST_DENIAL["message"])

            # a receipt whose dispatch has no record in this story vouches for nothing either
            add_record(root, "TP2-2406", "S1-qa-scout-2", role="qa-scout", status="running")
            check_eq("both receipts live again: the bare name is allowed", checked(ev), SG.ALLOW)
            receipt(root, "/b/qa_dup", "TP2-2406", "S1-qa-scout-404")
            refused_as("a receipt with no record here", event(root, "qa_dup"),
                       "dispatch S1-qa-scout-404 has no record in this story")
    finally:
        cleanup(root)


def retired_agent_checks() -> None:
    """F-2 (a), I-3, M-2, F-7: an agent a `superseded` or released dispatch carried is not resumable from ANY
    source, on both hosts, and the refusal says so truthfully."""
    root = project()
    try:
        with in_project(root):
            ticket = "TP2-2406"
            check_eq("pin: the unretired designer is resumable", checked(event(root, AGENT)), SG.ALLOW)
            for status in ("superseded", "released_by_person"):
                add_record(root, ticket, "S4-qa-case-designer-1", role="qa-case-designer", agent_id=AGENT, status=status)
                fact = f"dispatch S4-qa-case-designer-1 is {status}"
                for label, target in (("literal id via pipeline.json and the record", AGENT),
                                      ("full path via the receipt", TARGET)):
                    refused_as(f"{status} agent, {label}", event(root, target),
                               "1 agent recorded for this story, none resumable", fact)
                    check_not_in(f"{status} agent, {label}: and it does not say none is recorded",
                                 "no agent_id is recorded", SG.LAST_DENIAL["message"])
                claude = {"tool_name": "SendMessage", "cwd": str(root), "tool_input": {"to": AGENT, "task_id": ticket}}
                refused_as(f"{status} agent on the Claude host (F-1: the filter is shared)", claude, fact)

            # a status of a record says nothing about another record of the SAME agent
            add_record(root, ticket, "S4-qa-case-designer-2", role="qa-case-designer", agent_id=AGENT, status="running")
            check_eq("a resumable record of the same agent keeps it resumable", checked(event(root, AGENT)), SG.ALLOW)
            add_record(root, ticket, "S4-qa-case-designer-2", role="qa-case-designer", agent_id="designer-2406-retry",
                       status="running")
            # known = the retry's agent; the retired one is named with the fact, not as "never ran"
            ev = event(root, AGENT)
            refused_as("retired agent beside a live other one", ev, f"{AGENT}: dispatch S4-qa-case-designer-1 is released_by_person",
                       "designer-2406-retry")
            check_not_in("retired agent beside a live other one: it is not the 'none recorded' text",
                         "none resumable", SG.LAST_DENIAL["message"])
            check_eq("the live other agent is allowed (no receipt: the story is named by the event)",
                     checked(event(root, "designer-2406-retry", task_id=ticket)), SG.ALLOW)

            # two running records of one (stage, role) pair: both resumable; a record with no stage or role: by status
            add_record(root, ticket, "S4-qa-case-designer-3", role="qa-case-designer", stage="S4",
                       agent_id="designer-2406-b", status="running")
            add_record(root, ticket, "S4-qa-case-designer-4", role="qa-case-designer", stage="S4",
                       agent_id="designer-2406-c", status="running")
            add_record(root, ticket, "bare-1", agent_id="designer-2406-d", status="blocked")
            add_record(root, ticket, "bare-2", agent_id="designer-2406-e", status="stale")
            for agent in ("designer-2406-b", "designer-2406-c", "designer-2406-d", "designer-2406-e"):
                check_eq(f"resumable by status alone: {agent}", checked(event(root, agent, task_id=ticket)), SG.ALLOW)

            # the receipt of a RETIRED dispatch does not vouch; no record carries an agent_id, so the text does NOT
            # count the receipt's name as a recorded agent (M-1 of t-1080): it is a clause of its own
            add_record(root, ticket, "S4-qa-case-designer-1", role="qa-case-designer", status="superseded")  # no agent_id
            for dispatch in ("S4-qa-case-designer-2", "S4-qa-case-designer-3", "S4-qa-case-designer-4", "bare-1", "bare-2"):
                add_record(root, ticket, dispatch, status="superseded")
            story(root, ticket, "done", "")
            receipt(root, "/root/qa_retired", ticket, "S4-qa-case-designer-1")
            refused_as("superseded receipt does not vouch (full path)", event(root, "/root/qa_retired"),
                       "no agent_id is recorded for this story",
                       "a receipt names /root/qa_retired, but dispatch S4-qa-case-designer-1 is superseded")
            check_not_in("superseded receipt, no agent recorded: the receipt's name is not a 'recorded agent'",
                         "agent recorded for this story", SG.LAST_DENIAL["message"])
            refused_as("superseded receipt does not vouch (bare name)", event(root, "qa_retired"),
                       "a receipt names qa_retired, but dispatch S4-qa-case-designer-1 is superseded")

            # E5: a dead agent's receipt (`terminal`) is not a retired dispatch: a critic is resumed after its accept
            add_record(root, ticket, "S4-qa-case-designer-1", role="qa-case-designer", status="accepted")
            receipt(root, "/root/qa_retired", ticket, "S4-qa-case-designer-1", status="terminal", terminal_source="story_step")
            check_eq("a terminal receipt of an accepted dispatch still vouches (liveness is not identity)",
                     checked(event(root, "/root/qa_retired")), SG.ALLOW)
            check_eq("and so does its bare name", checked(event(root, "qa_retired")), SG.ALLOW)
    finally:
        cleanup(root)


def pipeline_only_checks() -> None:
    """M-4, named: an id only `pipeline.json` knows (no controller record carries it) stays known, as on main -
    on Codex too. The filter is complete only for agents a controller record carries."""
    root = project()
    try:
        with in_project(root):
            story(root, "TP2-2406", "done", "pipeline-only-agent")
            (root / "qa-factory/artifacts/TP2-2406/state/controller.json").unlink()
            ev = event(root, "pipeline-only-agent", task_id="TP2-2406")
            check_eq("pipeline.json world, no controller record: the id stays resumable (main's behaviour, named)",
                     checked(ev), SG.ALLOW)
            claude = {"tool_name": "SendMessage", "cwd": str(root),
                      "tool_input": {"to": "pipeline-only-agent", "task_id": "TP2-2406"}}
            check_eq("and on the Claude host", checked(claude), SG.ALLOW)
    finally:
        cleanup(root)


def receipt_evidence_checks() -> None:
    """E4: a receipt that names no story is neither evidence nor a veto; E12 (a): a receipt written before
    CX1-9 (no task_name / task_path) answers like a new one; E14-adjacent: odd values."""
    root = project_real()
    try:
        directory = binding_path(root, REAL_PATH).parent
        with in_project(root):
            for label, bad in (("empty task_id", {"task_id": ""}), ("no task_id", {"task_id": None}),
                               ("task_id with a slash", {"task_id": "a/b"}), ("task_id '..'", {"task_id": ".."}),
                               ("task_id with a colon", {"task_id": "C:x"}),
                               ("a story with no pipeline.json", {"task_id": "TP2-9999"}),
                               ("no dispatch_id", {"dispatch_id": ""}), ("a number task_id", {"task_id": 7})):
                write(directory / "0only.json", dict({"agent_id": "/root/qa_only", "task_id": "TP2-2406",
                                                      "dispatch_id": "S3-qa-test-strategist-5"}, **bad))
                refused_naming(f"alone, {label}", event(root, "qa_only"), "qa_only")
                # beside a real receipt of the same name it is no veto and no evidence
                receipt(root, "/elsewhere/qa_only", "TP2-2406", "S3-qa-test-strategist-5")
                check_eq(f"beside a real receipt, {label}: the name resolves the real one's story",
                         SG.requested_ticket(event(root, "qa_only")), "TP2-2406")
                check_eq(f"beside a real receipt, {label}: and is allowed", checked(event(root, "qa_only")), SG.ALLOW)
                binding_path(root, "/elsewhere/qa_only").unlink()
            (directory / "0only.json").unlink()
            # E12 (a): the pre-CX1-9 shape answers by path and by bare name (REAL_PATH has no task_name key)
            check_eq("a receipt written before CX1-9 answers to its bare name",
                     binding_names(json.loads(binding_path(root, REAL_PATH).read_text(encoding="utf-8"))),
                     {REAL_PATH, REAL_NAME})
    finally:
        cleanup(root)


STORY_A, STORY_B = "TP2-2406", "TP2-2534"


def interrupt_project() -> Path:
    """Two stories. A: running, its agent `/root/qa_a` live (record running, receipt running), a retired one
    `/root/qa_old` (record superseded, receipt terminal). B: S5 accepted, agent `/other/qa_x` (record accepted,
    receipt terminal). A bare name `qa_dup` is held by a terminal receipt of EACH story."""
    root = mark_project(temp_dir("qa-factory-resume-interrupt-"))
    story(root, STORY_A, "running", "/root/qa_a")
    story(root, STORY_B, "done", "/other/qa_x")
    add_record(root, STORY_A, "S5-qa-a-1", role="qa-automator", stage="S5", agent_id="/root/qa_a", status="running")
    add_record(root, STORY_A, "S5-qa-old-1", role="qa-automator", stage="S5", agent_id="/root/qa_old", status="superseded")
    add_record(root, STORY_B, "S5-TP3-2-1", role="qa-automator", stage="S5", agent_id="/other/qa_x", status="accepted")
    receipt(root, "/root/qa_a", STORY_A, "S5-qa-a-1")
    receipt(root, "/root/qa_old", STORY_A, "S5-qa-old-1", status="terminal")
    receipt(root, "/other/qa_x", STORY_B, "S5-TP3-2-1", status="terminal")
    receipt(root, "/a/qa_dup", STORY_A, "S5-qa-a-1", status="terminal")
    receipt(root, "/b/qa_dup", STORY_B, "S5-TP3-2-1", status="terminal")
    return root


def interrupt_event(root: Path, target: str, message: str = "rewrite your verdict", **extra) -> dict:
    """`send_input(interrupt=true)` as the host sends it: the interrupt flag rides in the normalized input and in
    the raw one the adapter keeps; `message` "" is the call with no message at all."""
    ev = event(root, target, "collaborationsend_input", message=message, **extra)
    ev["tool_input"]["interrupt"] = True
    ev["_qa_host"]["input"]["interrupt"] = True
    if not message:
        for part in (ev["tool_input"], ev["_qa_host"]["input"]):
            part.pop("message", None)
        ev["tool_input"]["content"] = ""
    return ev


def stop_message_checks() -> None:
    """B-1 of t-1080: `send_input(interrupt=true)` activates its recipient and delivers its message, so it is
    judged by the SAME recipient rule as a resume - whatever `worker_lifecycle.guard` made of the stop, and
    whether or not a message rides with it. Probes (1)-(4) of the review, each with and without a message."""
    root = interrupt_project()
    try:
        with in_project(root):
            for message in ("rewrite your verdict", ""):
                how = "with a message" if message else "with no message"
                # (1) an explicit story A aimed at B's finished agent (a terminal receipt of B)
                check_eq(f"(1) explicit story A, B's agent with a terminal receipt, {how}: denied",
                         checked(interrupt_event(root, "/other/qa_x", message, task_id=STORY_A)), SG.DENY)
                check_in(f"(1) {how}: and it is the unknown-recipient refusal of main", "is not a dispatch this story ran",
                         SG.LAST_DENIAL["message"])
                # (2) QA_FACTORY_TASK=A aimed at B's agent that has no receipt at all
                os.environ["QA_FACTORY_TASK"] = STORY_A
                try:
                    check_eq(f"(2) the person's word names A, B's agent with no receipt, {how}: denied",
                             checked(interrupt_event(root, "/elsewhere/qa_y", message)), SG.DENY)
                    # (3) a bare name two stories' terminal receipts answer to
                    check_eq(f"(3) the person's word names A, a bare name of A and B, {how}: denied",
                             checked(interrupt_event(root, "qa_dup", message)), SG.DENY)
                finally:
                    os.environ["QA_FACTORY_TASK"] = ""
                # (4) a superseded agent of A, through the receipt and through its literal id
                for target in ("/root/qa_old", "qa_old"):
                    check_eq(f"(4) a superseded agent of A ({target}), {how}: denied",
                             checked(interrupt_event(root, target, message, task_id=STORY_A)), SG.DENY)
                    check_in(f"(4) {target}, {how}: and the fact is printed", "dispatch S5-qa-old-1 is superseded",
                             SG.LAST_DENIAL["message"])
                # no story chosen at all, a recipient no receipt names: the fail-closed refusal of a resume
                check_eq(f"an unbound recipient, {how}: denied (no story is chosen for it)",
                         checked(interrupt_event(root, "qa_nobody__tp2_9999", message)), SG.DENY)
                check_eq(f"an unknown agent with an explicit story, {how}: denied",
                         checked(interrupt_event(root, "agent-unknown", message, task_id=STORY_A)), SG.DENY)

                # an interrupt to THIS story's running agent is allowed, by every way the story is named
                for label, target, extra in (("full path, explicit story", "/root/qa_a", {"task_id": STORY_A}),
                                             ("full path, the receipt names the story", "/root/qa_a", {}),
                                             ("bare name, the receipt names the story", "qa_a", {})):
                    check_eq(f"a live agent of A, {label}, {how}: allowed",
                             checked(interrupt_event(root, target, message, **extra)), SG.ALLOW)
            # the shape of the flag decides nothing: the same call without it, or with it as a string, is the same resume
            plain = event(root, "/other/qa_x", "collaborationsend_input", task_id=STORY_A)
            check_eq("the same send_input WITHOUT interrupt is refused as well", checked(plain), SG.DENY)
            odd = interrupt_event(root, "/other/qa_x", task_id=STORY_A)
            odd["tool_input"]["interrupt"] = odd["_qa_host"]["input"]["interrupt"] = "false"
            check_eq("interrupt as the string 'false' decides nothing either", checked(odd), SG.DENY)
    finally:
        cleanup(root)


def truthful_none_checks() -> None:
    """M-1 of t-1080: `SG-resume-none` says an agent is RECORDED only when a record of this story carries it; a
    receipt's veto is a clause of its own and is never counted as a recorded agent."""
    root = mark_project(temp_dir("qa-factory-resume-none-"))
    try:
        story(root, STORY_A, "done", "")
        receipt(root, "/root/qa_t", STORY_A, "S5-x-404")
        with in_project(root):
            ev = event(root, "/root/qa_t")
            check_eq("no agent recorded anywhere, a receipt for a dispatch with no record: the story is A",
                     SG.requested_ticket(ev), STORY_A)
            refused_as("no record, no agent", ev, "no agent_id is recorded for this story",
                       "a receipt names /root/qa_t, but dispatch S5-x-404 has no record in this story")
            check_not_in("no record, no agent: it does not call the receipt's name a recorded agent",
                         "agent recorded for this story", SG.LAST_DENIAL["message"])
            check_not_in("no record, no agent: and there is no '/root/qa_t (' in the agents list",
                         "/root/qa_t (", SG.LAST_DENIAL["message"])
            # an agent a record carries and the filter retired: counted once, with ITS fact; the receipt's veto apart
            add_record(root, STORY_A, "S5-old-1", role="qa-automator", agent_id="agent-old", status="superseded")
            refused_as("one agent retired, one receipt vetoed", ev, "1 agent recorded for this story, none resumable: "
                       "agent-old (dispatch S5-old-1 is superseded)",
                       "; a receipt names /root/qa_t, but dispatch S5-x-404 has no record in this story")
            # two retired agents: both counted, each with its own fact
            add_record(root, STORY_A, "S5-old-2", role="qa-automator", agent_id="agent-older", status="released_by_person")
            refused_as("two agents retired", ev, "2 agents recorded for this story, none resumable",
                       "agent-old (dispatch S5-old-1 is superseded)", "agent-older (dispatch S5-old-2 is released_by_person)")
    finally:
        cleanup(root)


def corrupt_other_receipt_checks() -> None:
    """A corrupt receipt BESIDE the real one never fails a resume open and never lets an unbound one pass."""
    root = project_real()
    try:
        directory = binding_path(root, REAL_PATH).parent
        (directory / "0corrupt.json").write_text("{not json", encoding="utf-8")
        (directory / "0notdict.json").write_text("[1, 2]", encoding="utf-8")
        # t-032 F-2: well-formed JSON whose name value is not a string (an unhashable list raised out of
        # the scan and failed the resume open).
        write(directory / "0liststr.json", {"agent_id": ["x"], "task_id": "TP2-2534", "dispatch_id": "D"})
        write(directory / "0numpath.json", {"agent_id": "n", "task_path": 7, "task_name": ["y"]})
        with in_project(root):
            for label, target in (("full path", REAL_PATH), ("bare name", REAL_NAME)):
                ev = event(root, target, message=OPAQUE)
                check_eq(f"corrupt other receipt, {label}: still resolves 2406", SG.requested_ticket(ev), "TP2-2406")
                check_eq(f"corrupt other receipt, {label}: is allowed", checked(ev), SG.ALLOW)
            refused_naming("corrupt other receipt, unbound", event(root, "qa_nobody__tp2_9999"),
                           "qa_nobody__tp2_9999")
            check_eq("corrupt other receipt: the scan skips the files that name nothing",
                     [p.name for p in matching_binding_paths(root, "qa_nobody__tp2_9999")], [])
            check_eq("corrupt other receipt: receipt_files leaves out the unreadable, the non-object and the empty",
                     [p.name for p, _ in receipt_files(root)],
                     sorted(["0liststr.json", "0numpath.json", binding_path(root, REAL_PATH).name]))
            # enrich never raises either, and a broken file beside names no story
            check_eq("enrich: the scan beside corrupt files still finds the one receipt",
                     HD.enrich({"agent_id": REAL_NAME, "cwd": str(root)}).get("task_id"), "TP2-2406")
    finally:
        cleanup(root)


def matching_paths_checks() -> None:
    """The all-matches reader: the exact receipt alone (a literally recorded bare id included, M-5), else every
    name match in file order; `resolve_binding_path` answers only with ONE (F-5); `enrich` names no story on a
    name two receipts hold."""
    root = project_real()
    try:
        shared_receipts(root)
        both = sorted(binding_path(root, p) for p in ("/root/qa_scout__shared", "/other/qa_scout__shared"))
        check_eq("matching_binding_paths: a bare name finds every receipt, in sorted order",
                 matching_binding_paths(root, "qa_scout__shared"), sorted(both, key=lambda p: p.as_posix()))
        check_eq("matching_binding_paths: a full path finds its own receipt only",
                 matching_binding_paths(root, "/root/qa_scout__shared"), [binding_path(root, "/root/qa_scout__shared")])
        check_eq("resolve_binding_path: two matches answer none (the absent direct path, not the first file)",
                 resolve_binding_path(root, "qa_scout__shared"), binding_path(root, "qa_scout__shared"))
        check_eq("resolve_binding_path: ... and that path is absent", binding_path(root, "qa_scout__shared").is_file(), False)
        check_eq("resolve_binding_path: exactly one match answers", resolve_binding_path(root, REAL_NAME),
                 binding_path(root, REAL_PATH))
        with in_project(root):
            check_eq("enrich: a name two stories hold names no story (no task_id on the event)",
                     HD.enrich({"agent_id": "qa_scout__shared", "cwd": str(root)}).get("task_id"), None)
            check_eq("enrich: control - the exact path of one of them names its story",
                     HD.enrich({"agent_id": "/root/qa_scout__shared", "cwd": str(root)}).get("task_id"),
                     "TP2-2406")
        # M-5: a bare id recorded literally (bind --agent-id qa_scout__shared) matches FIRST and alone
        receipt(root, "qa_scout__shared", "TP2-2534", "S1-qa-scout-1")
        check_eq("matching_binding_paths: the exact receipt answers alone",
                 matching_binding_paths(root, "qa_scout__shared"), [binding_path(root, "qa_scout__shared")])
        check_eq("resolve_binding_path: ... and resolve_binding_path returns it",
                 resolve_binding_path(root, "qa_scout__shared"), binding_path(root, "qa_scout__shared"))
        check_eq("matching_binding_paths: a name nobody has finds nothing", matching_binding_paths(root, "qa_nobody"), [])
        check_eq("matching_binding_paths: an empty identity finds nothing", matching_binding_paths(root, ""), [])
        check_eq("matching_binding_paths: a non-string identity finds nothing", matching_binding_paths(root, ["x"]), [])
        check_eq("resolve_binding_path: no match returns the absent direct path",
                 resolve_binding_path(root, "qa_nobody"), binding_path(root, "qa_nobody"))
    finally:
        cleanup(root)


def binding_names_checks() -> None:
    """(g) the one reader of a receipt's names."""
    full = {"agent_id": "/root/qa_x", "task_path": "/root/qa_x", "task_name": "qa_x"}
    check_eq("binding_names: a full receipt answers to its path and its name", binding_names(full), {"/root/qa_x", "qa_x"})
    check_eq("binding_names: five names across two spellings of the key set",
             len(binding_names({"agent_id": "/a/b", "task_path": "/c/d", "task_name": "e"})), 5)
    check_eq("binding_names: the story_step receipt keys of before CX1-9 (path only)",
             binding_names({"agent_id": REAL_PATH}), {REAL_PATH, REAL_NAME})
    check_eq("binding_names: the SubagentStart receipt (uuid, bare task_name, bare task_path)",
             binding_names({"agent_id": "019e-uuid", "task_name": "qa_x", "task_path": "qa_x"}), {"019e-uuid", "qa_x"})
    check_eq("binding_names: an empty receipt names nothing", binding_names({}), set())
    check_eq("binding_names: a receipt that is no object names nothing", binding_names([1, 2]), set())
    check_eq("binding_names: an id without a slash is one name", binding_names({"agent_id": "agent-1"}), {"agent-1"})
    check_eq("binding_names: empty and None values are dropped",
             binding_names({"agent_id": "", "task_path": None, "task_name": ""}), set())
    check_eq("binding_names: a list, a number and None name nothing, with no exception",
             binding_names({"agent_id": ["x"], "task_path": 7, "task_name": None}), set())
    check_eq("binding_names: a non-string value beside a string one leaves the string's names",
             binding_names({"agent_id": ["x"], "task_path": "/root/qa_y"}), {"/root/qa_y", "qa_y"})
    check_eq("binding_names: a trailing slash adds no empty name", binding_names({"agent_id": "/root/"}), {"/root/"})
    check_eq("binding_names: 'root' is a name only of a path ending in it",
             binding_names({"agent_id": "/root"}), {"/root", "root"})
    check_eq("binding_names: a task_name is never split", binding_names({"task_name": "a/b"}), {"a/b"})


def vocabulary_checks() -> None:
    """The retired-status words are the controller's own (FR-13: a dictionary, not project variety)."""
    check_eq("UNRESUMABLE is the controller's superseded status and its released one",
             SG.UNRESUMABLE, ("superseded", CTL.RELEASED))
    check_eq("the aliases a resume is read under are the adapter's one tuple (M-1 of the plan)",
             SG.resume_targets({"tool_input": {"to": "a", "id": "b", "target": "c"},
                                "_qa_host": {"input": {"recipient": "d", "agent_id": "e", "to": "a"}}}),
             ["a", "b", "c", "d", "e"])


def main() -> None:
    root = project()
    saved_env = os.environ.get("QA_FACTORY_TASK")
    os.environ["QA_FACTORY_TASK"] = ""
    try:
        real_checks()
        guess_for_dispatches_checks()
        shared_name_checks()
        ambiguous_vouch_checks()
        same_story_checks()
        retired_agent_checks()
        pipeline_only_checks()
        receipt_evidence_checks()
        stop_message_checks()
        truthful_none_checks()
        corrupt_other_receipt_checks()
        matching_paths_checks()
        binding_names_checks()
        vocabulary_checks()
        with hooklib.selftest_root_restored():
            hooklib._PROJECT_ROOT_CACHE = root
            os.environ["CLAUDE_PROJECT_DIR"] = str(root)

            ev = event(root)
            check_eq("resume: 2534 running does not capture 2406's rework resume", SG.requested_ticket(ev), "TP2-2406")
            check_eq("resume: the bound designer's resume is allowed", checked(ev), SG.ALLOW)
            check_eq("resume: the facts name the binding as the source",
                     SG.resolve_ticket(ev)[1]["explicit_source"], "the recorded resume recipient binding")

            for tool in ("followup_task", "collaboration.followup_task", "collaborationfollowup_task", "send_input"):
                for target in (TARGET, AGENT, TARGET.rsplit("/", 1)[1]):
                    ev = event(root, target, tool)
                    check_eq(f"resume: {tool} to {target!r} resolves 2406", SG.requested_ticket(ev), "TP2-2406")
                    check_eq(f"resume: {tool} to {target!r} is allowed", checked(ev), SG.ALLOW)

            # The alias the host keeps in its raw input counts as much as the normalized one.
            ev = event(root)
            ev["tool_input"]["recipient"] = ""
            ev["_qa_host"]["input"] = {"id": AGENT, "message": "opaque"}
            check_eq("resume: a recipient only in the raw host `id` resolves 2406", SG.requested_ticket(ev), "TP2-2406")

            story(root, "TP2-2406", "running", AGENT)
            check_eq("resume: two running stories still resolve the recorded recipient",
                     SG.requested_ticket(event(root)), "TP2-2406")
            check_eq("resume: an unknown recipient beside two running stories is refused",
                     checked(event(root, "unknown-id")), SG.DENY)
            story(root, "TP2-2406", "done", AGENT)

            ev = event(root, task_id="TP2-2534")
            check_eq("resume: an explicit other story wins over the binding", SG.requested_ticket(ev), "TP2-2534")
            check_eq("resume: and does not authorize 2406's worker", checked(ev), SG.DENY)

            for target in ("unknown-id", "/root"):
                check_eq(f"resume: unknown or parent recipient {target!r} remains refused",
                         checked(event(root, target)), SG.DENY)

            ev = event(root, "unknown-id")
            ev["tool_input"]["host_binding"] = str(binding_path(root, AGENT))
            check_eq("resume: a forged binding argument cannot select the story", checked(ev), SG.DENY)

            # Fail closed: no story resolves, a recipient is named, stories exist on disk.
            for ticket in ("TP2-2406", "TP2-2534"):
                story(root, ticket, "done", "")
            ev = event(root, "unknown-id")
            check_eq("resume: no story resolves for an unbound recipient", SG.requested_ticket(ev), "")
            check_eq("resume: an unidentified resume beside existing stories is refused", checked(ev), SG.DENY)
            check("resume: the refusal names the missing identity",
                  "resume story identity is missing or ambiguous" in SG.LAST_DENIAL["message"])

            # A corrupt receipt names nothing and does not crash the resolver.
            binding_path(root, AGENT).write_text("{not json", encoding="utf-8")
            check_eq("resume: an unreadable binding resolves nothing", SG.requested_ticket(event(root)), "")
    finally:
        if saved_env is None:
            os.environ.pop("QA_FACTORY_TASK", None)
        else:
            os.environ["QA_FACTORY_TASK"] = saved_env
        cleanup(root)
    finish("test_resume_story_isolation")


if __name__ == "__main__":
    main()
