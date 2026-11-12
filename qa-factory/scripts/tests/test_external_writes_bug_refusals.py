"""external_writes.process_bug_proposal: every refusal text of a bug record's write, one test each (B-309 item "zh", FR-1).

The bug's command transport is `_run_command_transport` (a bug's and a case's copies became one function in t-422), and
the refusals in front of it are `process_bug_proposal`'s own. No test read ANY of these texts: a reword that dropped the
word a person acts on (`reconcile`, `qa-onboarding`, `create the bug first`) kept every suite green. Each test below
builds the smallest proposal that reaches ONE text, quotes the text, and asserts

  * the status word (`REJECT` = the proposal is refused and unchanged, `FAIL` = the write was tried and broke,
    `NOT_CONFIGURED` = the channel has nothing to write with), and
  * what is wrong, in the words the text uses today, and
  * what is expected or the move that follows, where the text states one (FR-1: a refusal says what is wrong, what it
    expected and how to satisfy it).

Seven texts state the problem and not a move (T1 `unreadable proposal`, T5 `missing 'bug_file'`, T6 `bug_file not found`,
T11 `no confirmed remote ID`, T14 `command did not start`, T15 `command exited`, T16 `outcome unknown`): the test pins what
each says today and the report lists them as the FR-1 finding; no text was reworded here (the task adds tests, not behaviour).

The command is a fake `invoke`: nothing is spawned. Runnable on its own: `python -B scripts/tests/test_external_writes_bug_refusals.py`."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import external_writes as EW  # noqa: E402
import hooklib  # noqa: E402

TICKET = "QA-9"
SCOPES = {"create_issue", "add_comment"}
COMMAND = ["fake-tracker"]
DASH = chr(0x2014)       # the em dash the two NOT_CONFIGURED texts carry


class Rig:
    """One throwaway project with one bug file and one proposal, and a fake `invoke` that records its calls."""

    def __init__(self, root: Path):
        self.root = root
        (root / "qa-factory" / "bugs").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        (root / "qa-factory" / "bugs" / "BUG-1.md").write_text("# BUG-1\n\nA sixth tag is accepted.\n", encoding="utf-8")
        self.proposal = root / "proposals" / "bug-1.json"
        self.proposal.parent.mkdir()
        self.calls = []
        self.answer = subprocess.CompletedProcess(COMMAND, 0, '{"external_id": "JIRA-1"}', "")
        self._invoke = EW.invoke
        EW.invoke = self.fake_invoke

    def fake_invoke(self, argv):
        self.calls.append(list(argv))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def close(self):
        EW.invoke = self._invoke

    def write(self, **fields) -> None:
        body = {"kind": "bug", "bug_file": "bugs/BUG-1.md", "action": "create", "fields": {"summary": "tag"}, "witness": {}}
        body.update(fields)
        self.proposal.write_text(json.dumps(body), encoding="utf-8")

    def run(self, ew: dict | None = None, scopes=SCOPES, channel: str = "jira") -> list:
        status = []
        ew = {"commands": {"jira": COMMAND}} if ew is None else ew
        EW.process_bug_proposal(self.proposal, TICKET, ew, set(scopes), status, channel=channel, cfg={})
        return status

    def stored(self) -> dict:
        return json.loads(self.proposal.read_text(encoding="utf-8"))


def one(status: list, word: str, label: str) -> str:
    """The single status row of a run, its word checked; returns its text."""
    check_eq(f"{label}: exactly one status row", len(status), 1)
    got_word, name, text = status[0]
    check_eq(f"{label}: the word is {word}", got_word, word)
    check_eq(f"{label}: it names the proposal file", name, "bug-1.json")
    return text


def names(label: str, text: str, *needles: str) -> None:
    for needle in needles:
        check_in(f"{label}: the text says {needle!r}", needle, text)


def test_refusals_in_front_of_the_transport(rig: Rig) -> None:
    # 1. "unreadable proposal: <parse error>" (a file that is not JSON)
    rig.proposal.write_text("{not json", encoding="utf-8")
    text = one(rig.run(), "REJECT", "T1 invalid JSON")
    names("T1", text, "unreadable proposal:", "Expecting")
    # 1b. "unreadable proposal: not an object" (JSON that is not an object)
    rig.proposal.write_text("[1, 2]", encoding="utf-8")
    text = one(rig.run(), "REJECT", "T1b a list")
    check_eq("T1b: the whole text", text, "unreadable proposal: not an object")

    # 2. "kind must be 'bug', got 'case'"
    rig.write(kind="case")
    text = one(rig.run(), "REJECT", "T2 wrong kind")
    check_eq("T2: the whole text (what is wrong: the kind; what is expected: 'bug')", text, "kind must be 'bug', got 'case'")

    # 3. "action must be create|comment, got 'delete'"
    rig.write(action="delete")
    text = one(rig.run(), "REJECT", "T3 wrong action")
    check_eq("T3: the whole text (expected: create|comment)", text, "action must be create|comment, got 'delete'")

    # 4. "'create' needs write_scope 'create_issue', not permitted (write_scopes: ['add_comment'])"
    rig.write()
    text = one(rig.run(scopes={"add_comment"}), "REJECT", "T4 scope")
    check_eq("T4: the whole text (the action, the scope it needs, what is permitted)", text,
             "'create' needs write_scope 'create_issue', not permitted (write_scopes: ['add_comment'])")

    # 5. "missing 'bug_file'"
    body = {"kind": "bug", "action": "create", "fields": {}}
    rig.proposal.write_text(json.dumps(body), encoding="utf-8")
    text = one(rig.run(), "REJECT", "T5 no bug_file")
    check_eq("T5: the whole text", text, "missing 'bug_file'")

    # 6. "bug_file not found: bugs/NOPE.md"
    rig.write(bug_file="bugs/NOPE.md")
    text = one(rig.run(), "REJECT", "T6 bug file absent")
    check_eq("T6: the whole text", text, "bug_file not found: bugs/NOPE.md")

    # 7. "comment needs an external_id (create the bug first)"
    rig.write(action="comment")
    text = one(rig.run(), "REJECT", "T7 comment on a bug with no id")
    check_eq("T7: the whole text (what is wrong, and the move: create the bug first)", text,
             "comment needs an external_id (create the bug first)")
    check("T7: nothing was tried: no command, no pending marker", not rig.calls and "pending" not in rig.stored())


def test_channel_without_a_way_to_write(rig: Rig) -> None:
    # 8. agent channel with an empty invoke name -> NOT_CONFIGURED
    rig.write()
    ew = {"channels": {"jira": {"method": "agent", "invoke": ""}}}
    text = one(rig.run(ew), "NOT_CONFIGURED", "T8 agent without a name")
    check_eq("T8: the whole text (what is empty, where, and the move: run qa-onboarding)", text,
             "channel 'jira' is delivered by an agent but external_writes.channels.jira.invoke is empty " + DASH + " run qa-onboarding")
    check("T8: no pending marker was written", "pending" not in rig.stored())

    # 12. command channel with no command -> NOT_CONFIGURED naming both keys that would configure it
    rig.write()
    text = one(rig.run({}), "NOT_CONFIGURED", "T12 no delivery")
    check_eq("T12: the whole text (what is missing and the two keys that fix it)", text,
             "no delivery configured for channel 'jira' " + DASH + " set external_writes.commands.jira or external_writes.channels.jira")
    check("T12: nothing was tried", not rig.calls and "pending" not in rig.stored())


def test_direct_api_refusals(rig: Rig) -> None:
    ew = {"channels": {"jira": {"method": "direct_api"}}}
    real = EW.direct_api_execute
    try:
        # 9. a pending direct attempt: no blind retry
        rig.write(pending={"method": "direct_api", "at": "2026-10-09T10:00:00+00:00", "payload": {}})
        EW.direct_api_execute = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called"))
        text = one(rig.run(ew), "REJECT", "T9 direct, prior attempt pending")
        check_eq("T9: the whole text (what is unknown, and the move: reconcile the remote ID before a retry)", text,
                 "unknown prior transport outcome; reconcile remote ID before retry")
        # 11. the tracker answered with no id
        rig.write()
        EW.direct_api_execute = lambda cfg, action, payload: ({}, "")
        text = one(rig.run(ew), "REJECT", "T11 direct, no id")
        check_eq("T11: the whole text", text, "tracker accepted the request but returned no confirmed remote ID")
        check("T11: the pending marker stays, so a re-run is refused until a person reconciles", "pending" in rig.stored())
    finally:
        EW.direct_api_execute = real


def test_the_command_transport(rig: Rig) -> None:
    # 13. a command attempt is already pending: no blind retry, the command is not called
    rig.write(pending={"method": "command", "at": "2026-10-09T10:00:00+00:00", "payload": {}})
    text = one(rig.run(), "REJECT", "T13 command, prior attempt pending")
    check_eq("T13: the whole text (what is unknown, and the move: reconcile the remote ID before a retry)", text,
             "unknown prior transport outcome; reconcile remote ID before retry")
    check("T13: the command was not called", not rig.calls)

    # 14. the command cannot start
    rig.write()
    rig.answer = FileNotFoundError("fake-tracker")
    text = one(rig.run(), "FAIL", "T14 command did not start")
    check_eq("T14: the whole text (the cause is the exception's own words)", text, "command did not start: fake-tracker")
    check("T14: the pending marker is left in place on purpose (a re-run is refused until reconciled)",
          rig.stored().get("pending", {}).get("method") == "command" and "result" not in rig.stored())

    # 15. the command exits non-zero: the last three lines of its own output are the evidence
    rig.write()
    rig.answer = subprocess.CompletedProcess(COMMAND, 7, "one\ntwo\nthree\nfour\n", "ignored")
    text = one(rig.run(), "FAIL", "T15 command exited")
    check_eq("T15: the whole text (exit code, the last three lines of stdout)", text, "command exited 7 | two | three | four")
    rig.write()
    rig.answer = subprocess.CompletedProcess(COMMAND, 2, "", "boom")
    text = one(rig.run(), "FAIL", "T15b stderr when stdout is empty")
    check_eq("T15b: the whole text", text, "command exited 2 | boom")
    check("T15: the pending marker stays", "pending" in rig.stored())

    # 16. exit 0 but no remote id in the answer
    rig.write()
    rig.answer = subprocess.CompletedProcess(COMMAND, 0, "not json at all", "")
    text = one(rig.run(), "REJECT", "T16 no id")
    check_eq("T16: the whole text", text, "transport returned no confirmed remote ID; outcome unknown")
    check("T16: no result was invented, the pending marker stays", "result" not in rig.stored() and "pending" in rig.stored())

    # the transport's other side, so the refusals above are refusals of a working path: exit 0 with an id is OK
    rig.write()
    rig.answer = subprocess.CompletedProcess(COMMAND, 0, '{"external_id": "JIRA-77", "url": "http://t/JIRA-77"}', "")
    status = rig.run()
    check_eq("T0 control: a confirmed id is OK", [row[0] for row in status], ["OK"])
    check_in("T0 control: and names the id", "JIRA-77", status[0][2])
    check_eq("T0 control: the command got the payload as its last argument",
             json.loads(rig.calls[-1][-1])["action"], "create")


def test_every_refusal_text_is_covered() -> None:
    """The class, not the instance: a refusal text added to the bug path without a test above is found here. The texts are
    the string literals of the two functions' `status.append((<word>, ...))` rows."""
    import ast
    source = Path(EW.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    texts, passed_through = [], []
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in ("process_bug_proposal", "_run_command_transport"):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "status"):
                    row = node.args[0]
                    if isinstance(row, ast.Tuple) and isinstance(row.elts[0], ast.Constant) and row.elts[0].value in (
                            "REJECT", "FAIL", "NOT_CONFIGURED"):
                        (passed_through if isinstance(row.elts[2], ast.Name) else texts).append(
                            ast.get_source_segment(source, row.elts[2]))
    check_eq("C1 the refusal rows of the bug path that carry a text of their own: 15, T1-T16 reach each (T1b is T1's)",
             len(texts), 15)
    check_eq("C1 the one row that carries another function's text (`direct_api_execute`'s error) is not a text of this path",
             passed_through, ["error"])


if __name__ == "__main__":
    root = temp_dir("qa-bug-refusals-")
    rig = None
    try:
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            rig = Rig(root)
            test_refusals_in_front_of_the_transport(rig)
            test_channel_without_a_way_to_write(rig)
            test_direct_api_refusals(rig)
            test_the_command_transport(rig)
            test_every_refusal_text_is_covered()
    finally:
        if rig is not None:
            rig.close()
        cleanup(root)
    finish("external_writes_bug_refusals")
