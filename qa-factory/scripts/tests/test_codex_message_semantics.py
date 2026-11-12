"""FB-13 (TP2-2406): a child's progress message to its parent is not a worker resume.

The desktop host's `send_message` queues a message; her sweep of the 2406 run found it cannot start an idle
worker, yet `host_adapter.normalize` folded it into `SendMessage` with `send_input` and `followup_task`, so rule 6
refused every progress note addressed to `/root` as a resume of an agent the story never ran. That premise (the
host's `send_message` never wakes a worker) is the host's property and has not been measured by us, so the exemption
is as narrow as the observation: `send_message` becomes `AgentMessage`, which no guard rule reads, ONLY when every
recipient it names, under ANY of the five aliases rule 6 reads (`to`, `recipient`, `agent_id`, `id`, `target`), is
exactly `/root` - or it names none. Any other recipient, in any alias, keeps `SendMessage` and rule 6; so do
`send_input` and `followup_task`, which activate the recipient. The class comes from the native tool name and the
recipient alone, never from a message field a caller could set, and never from a transport record a caller sent.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import stage_guard as SG  # noqa: E402
import host_adapter as H  # noqa: E402
from host_adapter import normalize  # noqa: E402

NAMES = ("send_message", "collaboration.send_message", "collaborationsend_message", "functions.send_message")


def main() -> None:
    root = temp_dir("qa-factory-message-semantics-")
    pipeline = root / "pipeline.json"
    story = {"ticket": "QA-2406", "gates": {}, "stages": {"S1": {"status": "running", "agent_id": "scout-id"}}}
    pipeline.write_text(json.dumps(story), encoding="utf-8")
    saved = SG.requested_ticket, SG.artifacts_dir
    SG.requested_ticket = lambda event: "QA-2406"
    SG.artifacts_dir = lambda ticket, event=None: root

    def event_of(tool: str, **fields) -> dict:
        return normalize(dict(tool_name=tool, host="codex", cwd=str(root), tool_input=dict(message="Progress", **fields)))

    def checked(tool: str, target: str = "/root", **extra) -> tuple:
        event = event_of(tool, target=target, **extra)
        with contextlib.redirect_stderr(io.StringIO()):
            return event, SG._check(event)

    def klass(**fields) -> str:
        return event_of("send_message", **fields)["tool_name"]

    try:
        with hooklib.selftest_root_restored():
            hooklib._PROJECT_ROOT_CACHE = root
            for name in NAMES:
                event, code = checked(name)
                check_eq(f"message: {name} to the parent normalizes to AgentMessage", event["tool_name"], "AgentMessage")
                check_eq(f"message: {name} to the parent is allowed", code, SG.ALLOW)
                check_eq(f"message: {name} keeps its recipient", event["tool_input"]["recipient"], "/root")
                check_eq(f"message: {name} keeps its native name", event["_qa_host"]["name"], name)

            pipeline.write_text(json.dumps({"ticket": "QA-2406", "stages": {}}), encoding="utf-8")
            check_eq("message: progress to the parent needs no recorded worker binding",
                     checked("collaborationsend_message")[1], SG.ALLOW)
            pipeline.write_text(json.dumps(story), encoding="utf-8")

            # F-3: every alias of rule 6 is a recipient, and ONE that is not the parent keeps rule 6 (I2)
            check_eq("alias: no recipient at all is a note (AgentMessage)", klass(), "AgentMessage")
            for key in H.RECIPIENT_ALIASES:
                check_eq(f"alias: {key}=/root alone is a note to the parent", klass(**{key: "/root"}), "AgentMessage")
                check_eq(f"alias: {key}=' /root ' (padded) is the parent too", klass(**{key: " /root "}), "AgentMessage")
                check_eq(f"alias: {key}='/root/x' is not the parent", klass(**{key: "/root/x"}), "SendMessage")
                check_eq(f"alias: {key}='root' is not the parent", klass(**{key: "root"}), "SendMessage")
                check_eq(f"alias: {key}=agent-99 is a recipient", klass(**{key: "agent-99"}), "SendMessage")
                check_eq(f"alias: {key}=['/root'] (not text) is not the parent", klass(**{key: ["/root"]}), "SendMessage")
                others = [other for other in H.RECIPIENT_ALIASES if other != key]
                for other in others:
                    check_eq(f"alias: {key}=/root beside {other}=agent-99 keeps rule 6", klass(**{key: "/root", other: "agent-99"}),
                             "SendMessage")
                check_eq(f"alias: {key}=agent-99 beside blank aliases keeps rule 6",
                         klass(**{key: "agent-99", others[0]: "  ", others[1]: ""}), "SendMessage")
            check_eq("alias: /root under two aliases is still the parent only",
                     klass(id="/root", target="/root", to="/root"), "AgentMessage")
            event = event_of("send_message", id="/root", to="agent-99")
            with contextlib.redirect_stderr(io.StringIO()):
                code = SG._check(event)
            check_eq("alias: id=/root beside to=agent-99 reaches rule 6 and is refused", (event["tool_name"], code),
                     ("SendMessage", SG.DENY))
            check_eq("alias: the unknown id is the one named in the refusal", "agent-99" in SG.LAST_DENIAL["message"], True)
            event = event_of("send_message", target="/root", agent_id="scout-id")
            with contextlib.redirect_stderr(io.StringIO()):
                code = SG._check(event)
            check_eq("alias: /root beside a RECORDED worker is a SendMessage, and rule 6 (every recipient must be recorded) refuses it",
                     (event["tool_name"], code), ("SendMessage", SG.DENY))

            # F-2 (spec): a recipient the story never ran keeps rule 6 - the exemption is for the parent
            for name in NAMES:
                event, code = checked(name, "foreign-id")
                check_eq(f"message: {name} to a recipient the story never ran stays SendMessage", event["tool_name"], "SendMessage")
                check_eq(f"message: {name} to a recipient the story never ran is refused by rule 6", code, SG.DENY)
                check_eq(f"message: {name} to the recorded worker is allowed", checked(name, "scout-id")[1], SG.ALLOW)

            for tool in ("send_input", "followup_task", "collaboration.followup_task", "collaborationfollowup_task",
                         "functions.send_input"):
                for target in ("/root", "foreign-id"):
                    event, code = checked(tool, target)
                    check_eq(f"resume: {tool} to {target!r} normalizes to SendMessage", event["tool_name"], "SendMessage")
                    check_eq(f"resume: {tool} to {target!r} is still refused", code, SG.DENY)
                check_eq(f"resume: {tool} to the recorded worker is still allowed", checked(tool, "scout-id")[1], SG.ALLOW)

            check_eq("class: message fields cannot disguise an activating tool",
                     checked("followup_task", "/root", type="notification", operation="send_message")[1], SG.DENY)
            check_eq("class: message fields cannot turn a send_message to a stranger into a note",
                     checked("send_message", "foreign-id", type="notification", operation="progress")[0]["tool_name"], "SendMessage")
            event = normalize({"tool_name": "SendMessage", "tool_input": {"recipient": "/root"},
                               "_qa_host": {"name": "send_message"}})
            with contextlib.redirect_stderr(io.StringIO()):
                code = SG._check(event)
            check_eq("class: a transport record cannot disguise an activating tool", code, SG.DENY)
            event = normalize({"tool_name": "send_input", "host": "codex", "tool_input": {"id": "/root"},
                               "_qa_host": {"name": "send_message", "codex": True}})
            check_eq("class: nor a send_input into a note", event["tool_name"], "SendMessage")
            check("class: a Claude SendMessage is untouched", normalize({"tool_name": "SendMessage", "tool_input": {"to": "a"}})["tool_name"] == "SendMessage")
    finally:
        SG.requested_ticket, SG.artifacts_dir = saved
        cleanup(root)
    finish("test_codex_message_semantics")


if __name__ == "__main__":
    main()
