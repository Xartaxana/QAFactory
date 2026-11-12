"""t-1547 (HF5-18, GB-2): the bug reporter is opened by the RECORDED gate B decision, not by the delivery verdict.

Keys K1-K6 of the spec (docs/tasks/specs/t-1509-gate-b-executors-and-closure.md, 5.2). The fixture
`run-12586-reporter-guard` is the live run's own `pipeline.json` (gate B recorded verbatim, words in English) and
`work/ledger.json` (verdict `no`): on that input the old rule refused the reporter with line 1 of the run's
`dispatch-denials.jsonl`, and the person's own decision (two drafts, "I will check by hand", "no MR needed") was ignored.
"""
import contextlib
import copy
import io
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import gate_brief  # noqa: E402
import hooklib  # noqa: E402
import human_text  # noqa: E402
import runtime_paths as RP  # noqa: E402
import stage_guard as SG  # noqa: E402

TICKET = "TP1-12586"
SOURCE = FIXTURES / "run-12586-reporter-guard"
ALLOW, DENY = SG.ALLOW, SG.DENY
VERDICTS = {"yes": {"delivery_verdict": "yes", "delivery_ready": True},
            "after_checks": {"delivery_verdict": "after_checks", "delivery_ready": False},
            "no": {"delivery_verdict": "no", "delivery_ready": False}}
RECORDED = {"status": "approved", "decision": "approved", "selected_drafts": ["d-1", "d-2"]}


class Story:
    """A temp project holding the fixture story; `reporter()` / `command()` are the guard as the hook runs it."""

    def __init__(self) -> None:
        self.root = temp_project("qa-gate-ordered-")
        self.art = self.root / "qa-factory" / "artifacts" / TICKET
        shutil.copytree(SOURCE / TICKET, self.art)
        use_project(self.root)
        self.pipeline = json.loads((self.art / "pipeline.json").read_text(encoding="utf-8"))
        self.ledger = json.loads((self.art / "work" / "ledger.json").read_text(encoding="utf-8"))

    def write(self, gate_b="keep", verdict=None, gates="keep") -> None:
        pipeline = copy.deepcopy(self.pipeline)
        if gates != "keep":
            pipeline["gates"] = gates
        elif gate_b == "absent":
            pipeline["gates"].pop("B", None)
        elif gate_b != "keep":
            pipeline["gates"]["B"] = gate_b
        (self.art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        if verdict:
            ledger = dict(copy.deepcopy(self.ledger), **VERDICTS[verdict])
            (self.art / "work" / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")

    def journal(self, *events: dict) -> None:
        path = RP.record(self.root, "journal.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def reporter(self, role: str = "qa-bug-reporter") -> tuple:
        event = {"tool_name": "Task", "cwd": str(self.root), "task_id": TICKET,
                 "tool_input": {"subagent_type": role, "prompt": TICKET}}
        return self.run(SG.check, event)

    def command(self, text: str = "glab mr create --fill") -> tuple:
        return self.run(SG.check, {"tool_name": "Bash", "cwd": str(self.root), "task_id": TICKET,
                                   "tool_input": {"command": text}})

    @staticmethod
    def run(function, event) -> tuple:
        SG.LAST_DENIAL["message"] = ""
        with contextlib.redirect_stderr(io.StringIO()):
            code = function(event)
        return code, SG.LAST_DENIAL.get("message") or ""


def key_one_the_live_run(story: Story) -> None:
    """K1 (the seam): the live pipeline.json + ledger (verdict `no`) + a journal without `deliver_with_risks` -> ALLOW."""
    story.write()
    check_eq("K1 the fixture is the live shape: gate B recorded approved, two drafts chosen, verdict no",
             (story.pipeline["gates"]["B"]["status"], len(story.pipeline["gates"]["B"]["selected_drafts"]),
              story.ledger["delivery_verdict"]), ("approved", 2, "no"))
    code, message = story.reporter()
    check_eq("K1 the reporter is ALLOWED on the recorded gate B decision although the verdict is no", code, ALLOW)
    recorded = json.loads((SOURCE / "dispatch-denial-line1.jsonl").read_text(encoding="utf-8").splitlines()[0])
    # the red control: the SAME input through the rule this change took away from roles (it still guards COMMANDS) gives
    # the very text that refused the reporter on the live run, line 1 of its dispatch-denials.jsonl
    # RD1-4 (B-304 G6): the rule's HEAD was reworded (it named the wrong condition), so the live record is compared by an exact
    # substitution of the one head middle for the other, and the record itself is never rewritten (its sha256 is pinned)
    import hashlib
    fixture = SOURCE / "dispatch-denial-line1.jsonl"
    old_mid = f" is blocked — delivery_ready is not yes for {TICKET}: "
    new_mid = (f" is blocked — the delivery verdict for {TICKET} is `no`; it opens at yes or after_checks, or with a "
               "deliver_with_risks line in the journal: ")
    check_eq("K1: the live record is byte-identical (sha256 pinned)", hashlib.sha256(fixture.read_bytes()).hexdigest(),
             "ba02d7e5e0aee1b9fd756349318e790fa8a79cc97946097d90952a9055c9bcf8")
    new = f"{TICKET}: {SG.rule_delivery(TICKET, 'dispatching qa-bug-reporter')}"
    check_eq("K1: the old head middle is in the record exactly once", recorded["reason"].count(old_mid), 1)
    check_eq("K1 red control: the rule on the same input is line 1 of dispatch-denials.jsonl with ONE head middle replaced",
             recorded["reason"].replace(old_mid, new_mid, 1), new)
    check_in("K1 ... and the record is the one that blamed the verdict, not the decision (a record of the past, unchanged)",
             "delivery_ready is not yes", recorded["reason"])
    check_eq("K1: the fixture is still the same bytes after the run", hashlib.sha256(fixture.read_bytes()).hexdigest(),
             "ba02d7e5e0aee1b9fd756349318e790fa8a79cc97946097d90952a9055c9bcf8")


def key_two_the_matrix(story: Story) -> None:
    """K2: {no decision, declined, deferred, edit, approved, approved + orders.bugs not_ordered} x {yes, after_checks, no}."""
    rows = [("no record", "absent", DENY), ("empty record", {}, DENY),
            ("declined", {"status": "declined", "decision": "declined"}, DENY),
            ("deferred", {"status": "deferred", "decision": "deferred"}, DENY),
            ("edit", {"decision": "edit"}, DENY),
            ("approved", RECORDED, ALLOW),
            ("approved, orders.bugs not_ordered, no drafts (F9: the controller refuses, the guard does not)",
             dict(RECORDED, selected_drafts=[], orders={"bugs": "not_ordered", "mr": "due"}), ALLOW)]
    for word in ("yes", "after_checks", "no"):
        for name, record, want in rows:
            story.write(gate_b=record, verdict=word)
            code, message = story.reporter()
            check_eq(f"K2 {name} x verdict {word}: {'ALLOW' if want == ALLOW else 'DENY'}", code, want)
            if want == DENY:
                check_in(f"K2 {name} x {word}: the refusal names the gate B decision door",
                         "--operation gate-decision --gate B", message)
    story.write(gate_b="absent", verdict="no")
    story.journal({"event": "deliver_with_risks", "task": TICKET, "reason": "release window"})
    check_eq("K2 deliver_with_risks without a gate B decision does not open the reporter", story.reporter()[0], DENY)
    story.write(gate_b="absent", verdict="yes")
    story.journal()
    check_eq("K2 `yes` without a decision is DENY (it used to open the reporter before the gate)", story.reporter()[0], DENY)
    # the damaged shapes of the record (FR-59: an unknown never opens)
    for name, gates in (("gates is a list", []), ("gates is a string", "B"), ("gates is null", None),
                        ("gates.B is a string", {"B": "approved"}), ("gates.B is a list", {"B": ["approved"]}),
                        ("gates.B is null", {"B": None})):
        story.write(gates=gates, verdict="no")
        check_eq(f"K2 {name}: DENY", story.reporter()[0], DENY)
    for name, damaged in (("no gates", {}), ("gates is a string", {"gates": "B"}), ("gates is a list", {"gates": ["B"]}),
                          ("gates.B is a string", {"gates": {"B": "approved"}}), ("gates.B is null", {"gates": {"B": None}})):
        said = SG.rule_gate_ordered(damaged, TICKET, "qa-bug-reporter", "B")
        check("K2 the rule itself, " + name + ": a refusal with the gate B door",
              bool(said) and "--operation gate-decision --gate B" in said and "--words-file" in said, str(said))
    check_eq("K2 the rule itself: the recorded decision opens", SG.rule_gate_ordered({"gates": {"B": RECORDED}}, TICKET, "qa-bug-reporter", "B"), None)
    # the generous reader (documented direction: only toward open; the controller and the role's halt are behind it)
    for name, record, want in (("decision `Approved ` (case, blanks)", {"decision": "Approved "}, ALLOW),
                               ("hand-written deferred status + approve decision", {"status": "deferred", "decision": "approve"}, ALLOW),
                               ("status approved over a declined decision word", {"status": "approved", "decision": "declined"}, ALLOW),
                               ("decision edit with status edit", {"decision": "edit", "status": "edit"}, DENY)):
        story.write(gate_b=record, verdict="no")
        check_eq(f"K2 reader direction: {name}", story.reporter()[0], want)
    # the position: rules 1-3 speak first, the gate B decision does not carry a dispatch past them
    pipeline = copy.deepcopy(story.pipeline)
    pipeline["gates"]["B"] = RECORDED
    pipeline["stages"]["S7"] = {"status": "pending"}
    (story.art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    code, message = story.reporter()
    check_eq("K2 position: S7 pending refuses the reporter although gate B is approved (rule 1 speaks first)", code, DENY)
    check_in("K2 position: ... with the order rule's text", "required stages are not done", message)


def key_three_commands(story: Story) -> None:
    """K3: the MR command keeps the verdict rule: after_checks opens, no refuses (text as before), no + deliver_with_risks opens."""
    story.journal()
    story.write(gate_b=RECORDED, verdict="after_checks")
    check_eq("K3 glab mr create at after_checks: ALLOW", story.command()[0], ALLOW)
    story.write(gate_b=RECORDED, verdict="yes")
    check_eq("K3 glab mr create at yes: ALLOW", story.command()[0], ALLOW)
    story.write(gate_b=RECORDED, verdict="no")
    code, message = story.command()
    check_eq("K3 glab mr create at no (a recorded gate B decision is not an MR word): DENY", code, DENY)
    check_in("K3 ... with the text of the delivery rule, unchanged: the command it names",
             "this delivery command (`glab mr create`, from ", message)
    check_in("K3 ... and its head (RD1-4: the verdict word and every opener)",
             " is blocked — the delivery verdict for " + TICKET + " is `no`; it opens at yes or after_checks, or with a "
             "deliver_with_risks line in the journal: ", message)
    # HF8-23: gate B IS recorded here, so the refusal no longer asks the person to say it at gate B (FR-7); it names the door that opens
    check_in("K3 ... and its door: gate B is recorded, no decision to deliver with known gaps, the journal line by file",
             "Gate B is recorded, and it records no decision to deliver with known gaps", message)
    check_in("K3 ... the line's command", "log_append.py --event deliver_with_risks --task " + TICKET + " --reason-file", message)
    check_not_in("K3 ... and not the old ask", "have the human say", message)
    story.journal({"event": "deliver_with_risks", "task": TICKET, "reason": "release window"})
    check_eq("K3 glab mr create at no + deliver_with_risks: ALLOW", story.command()[0], ALLOW)
    story.journal()
    story.write(gate_b="absent", verdict="after_checks")
    check_eq("K3 the MR command at after_checks does not wait for a gate B record (the rule for commands is the verdict's)",
             story.command()[0], ALLOW)


def key_four_other_roles(story: Story) -> None:
    """K4: a role outside gate_orders behaves as before; the pair role -> gate is data."""
    story.write(gate_b="absent", verdict="no")
    check_eq("K4 qa-doc-scribe (S8, no order) is not gated by gate B", story.reporter("qa-doc-scribe")[0], ALLOW)
    check_eq("K4 a foreign agent is never touched", story.reporter("general-purpose")[0], ALLOW)
    check_eq("K4 qa-bug-reporter -> gate B, from the table", SG.gate_of_executor("qa-bug-reporter"), "B")
    check_eq("K4 qa-doc-scribe -> no gate", SG.gate_of_executor("qa-doc-scribe"), "")
    model = SG.stage_model()
    changed = copy.deepcopy(model)
    changed["stages"][-2]["gate_orders"]["bugs"]["gate"] = "A"          # S8
    check_eq("K4 the gate is the TABLE's: another row, another gate (no literal in the guard)",
             SG.gate_of_executor("qa-bug-reporter", changed), "A")
    changed["stages"][-2]["gate_orders"] = {"bugs": "not an object", "mr": {"gate": "B", "executor": "delivery"}}
    check_eq("K4 a damaged row names no executor; the delivery-step executor (a string) is no role",
             (SG.gate_of_executor("qa-bug-reporter", changed), SG.gate_of_executor("delivery", changed)), ("", ""))
    check_eq("K4 the table of stages.json carries no `delivery_gated_roles` key any more",
             any("delivery_gated_roles" in stage for stage in model["stages"]), False)


def key_five_the_packet() -> None:
    """K5: the gate B packet on a `no` verdict offers the MR road only, and its sentence passes the human-text detector."""
    base = Path(temp_dir("qa-gate-ordered-packet-")) / "qa-factory"
    task_root = base / "artifacts" / TICKET
    try:
        (task_root / "work").mkdir(parents=True)
        (base / "config.json").write_text("{}", encoding="utf-8")
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [{"id": "Q-1", "question": "Which reviewer?", "severity": "low", "owner_role": "qa-story"}]}),
            encoding="utf-8")
        for word in ("no", "after_checks"):
            (task_root / "work" / "ledger.json").write_text(json.dumps(dict(VERDICTS[word], rows=[])), encoding="utf-8")
            packet = gate_brief.render_gate_b(TICKET, task_root)
            check_in(f"K5 verdict {word}: the closing sentence is there", "None of this blocks you:", packet)
            check_not_in(f"K5 verdict {word}: the packet does not send a bug through 'deliver with known gaps'", "file a bug", packet)
        (task_root / "work" / "ledger.json").write_text(json.dumps(dict(VERDICTS["no"], rows=[])), encoding="utf-8")
        packet = gate_brief.render_gate_b(TICKET, task_root)
        sentence = next(line for line in packet.splitlines() if line.startswith("None of this blocks you:"))
        check_in("K5 on `no` the MR road stays, with its reason: the approval word first, then the line of its own (HF8-23)",
             "to open one, write `approve` on the first line of your answer, then, on a line of its own, `deliver with known gaps: <your reason>`.",
             sentence)
        check_eq("K5 the sentence passes human_text.problems", human_text.problems(sentence, kind="report"), [])
    finally:
        cleanup(base.parent)


def key_six_the_old_key_is_gone() -> None:
    """K6: `delivery_gated_roles` is read by nobody and carried by nothing in the package (case-insensitive; the control finds `gate_orders`)."""
    package = SCRIPTS.parent
    found, control = [], []     # CHANGELOG.md and the fragments of changelog.d/ are release notes: they name the removed key
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".md", ".json", ".yaml", ".yml", ".txt") \
                or path.name == "CHANGELOG.md" or "changelog.d" in path.parts \
                or "__pycache__" in path.parts or path.name == Path(__file__).name \
                or SOURCE in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if "delivery_gated_roles" in text:
            found.append(str(path.relative_to(package)))
        if "gate_orders" in text:
            control.append(path.name)
    check_eq("K6 no file of the package outside CHANGELOG.md names delivery_gated_roles", found, [])
    check("K6 control: the same walk finds gate_orders", "stages.json" in control and "stage_guard.py" in control, str(control))
    check_eq("K6 the fixture carries no Cyrillic and no Windows path",
             [p.name for p in SOURCE.rglob("*") if p.is_file() and (any(ord(c) > 0x3FF and ord(c) < 0x500 for c in p.read_text(encoding="utf-8"))
                                                                   or ":\\" in p.read_text(encoding="utf-8").replace("\\\\", "\\"))
              and p.suffix in (".json", ".jsonl")], [])    # the data; README.txt names its source outside the repository


def main() -> None:
    with hooklib.selftest_root_restored():
        story = Story()
        try:
            key_one_the_live_run(story)
            key_two_the_matrix(story)
            key_three_commands(story)
            key_four_other_roles(story)
        finally:
            cleanup(story.root)
    key_five_the_packet()
    key_six_the_old_key_is_gone()
    finish("test_gate_ordered_reporter")


if __name__ == "__main__":
    main()
