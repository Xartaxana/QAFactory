"""driver_gates.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hooklib  # noqa: F401 (console setup, K7)
import json
import re
import subprocess
import sys
import human_text
import person_words
from driver_core import GATE_KINDS, Person, Refusal, RepairFailed, ReworkRefused, _now, _read_answer, json_record


# --- the gate-entry repair table (t-211, F-cmp2-17) ----------------------------------------------

# (gate, `check` id of a `factory_fixable` finding of gate_preflight, precondition, move): the names of
# `Driver` methods, in the order a round runs them (the re-pin comes BEFORE the critic: a review is bound to
# the pinned case versions, so one dispatched earlier is stale on arrival and buys a second identical round).
# A code table in the shape of KNOWN_REFUSALS, and kept in code on purpose (FR-13): its entries are moves
# with state preconditions (controller calls), which no data file can carry. A project cannot bring a new
# `check` id - gate_preflight emits them - so no value is left for a role to judge; what a role judges (the
# critic's verdict, the designer's cases) stays with the role. No gate B row: at B every finding goes to the
# conductor until a B move exists. `tests` read every `check` here against gate_preflight's own ids.
#
# t-261 (critic t-244, t-241): two rows more, both CODE only and before the paid ones. `unraised_questions` runs the S4
# exit's own command (`critic_rollcall.py --apply-fixes`: it raises what the designer, with no Bash, could only name, and
# re-pins) for a Then that reached gate A with no question; `s5_runtime_probe` writes the stand probe the rehearsal derived
# and proved (`runtime_probe.py --suggest --write`, its argv travelling in the finding's `argv` FIELD - FR-12 - in the
# portable form the config stores, resolved here before it runs). Neither is a new kind of person's question.
#
# B-416 (D-0031): `s5_reporter` is the third code-only row. When the probe's report reads under exactly ONE reader and the profile's report
# kind is empty, the finding carries the exact `report_adapt.py kind` command in its `argv` FIELD and the driver runs it (FR-48: a fixed
# command is not the conductor's); with no such field the finding is the conductor's, and only AFTER its one turn per command (the driver's
# own `not_adapted` row ends the bound) does the person get a card.
GATE_REPAIRS = (
    ("A", "unraised_questions", "raise_precondition", "raise_move"),
    ("A", "s5_runtime_probe", "probe_precondition", "probe_move"),
    ("A", "s5_reporter", "adapt_precondition", "adapt_move"),
    ("A", "case_versions", "pin_precondition", "pin_move"),
    ("A", "gate_decision", "review_precondition", "review_move"),
)

FACTORY_FIXABLE = "factory_fixable"     # gate_preflight.FACTORY_FIXABLE (a test holds the two equal)

GATE_REPAIR_CAP = 2                      # rounds per series (F4): AT 2 runs, BEYOND 3 is refused

GATE_STAGE_OF = {"A": "S4", "B": "S8"}   # the stage that stands in front of each gate

# Findings no move of ours can repair AND nobody else can either (the conductor's only move would be
# `ask_person`): they go straight into the list shown at the top of the gate (C8).
GATE_DIRECT_CHECKS = ("question_branches",)

GATE_TOP_LIMIT = 12                      # findings listed at the top of a gate packet; the rest is counted

CHECK_WORDS = {"case_versions": "case versions", "gate_decision": "design review",
               "question_branches": "question branches", "unraised_questions": "questions not yet raised",
               "s5_runtime_probe": "stand probe to register", "s5_reporter": "report kind to record"}


class DriverGates:
    def gate_answer_told(self, gate: str, out: str) -> dict:
        """The controller's answer (or refusal) of a gate decision, read and TOLD (DC1-19; AR-22, AR-24: what the register, the plan or the
        journal did, or did not do, is printed on this road): the plan lines (`questions.lines`, the manual-agent pass), what was not read
        (`unread`), an id named with no answer recorded (`named_not_recorded`), a recorded answer the plan still branches on
        (`plan_not_changed`), the case tokens a refusal did not apply (`not_applied_yet`), the journal line that was not written
        (`risks.line`). A rework the answers owe (`questions.rework`) goes to `merge_answer_rework` - EXCEPT after a RECORDED `approve as
        is` (`questions.rework_left`, F-4): the person's word wins, S3/S4 are not opened on the plan the approval just hashed, the queued
        item of an earlier refusal is dropped, and the controller's sentence (the door of a later rework) is printed; the rework runs only
        by the person's word. The answer is the last line that is a JSON object; one that is none is printed (200 characters) and the
        decision stands (P1)."""
        answer = _read_answer(out) or {}
        if not answer:
            if str(out or "").strip():
                print(f"gate {gate}: the controller's answer could not be read as JSON: {str(out).strip()[:200]}")
            return {}
        questions = answer.get("questions") if isinstance(answer.get("questions"), dict) else {}
        for line in [*(answer.get("manual_pass") or []), *(questions.get("lines") or [])]:
            print(str(line) if str(line).startswith(f"gate {gate}") else f"gate {gate}: {line}")
        for item in questions.get("unread") or []:
            if isinstance(item, dict):
                print(f"gate {gate}: not recorded - {item.get('line')}: {item.get('why')}")
        for item in questions.get("named_not_recorded") or []:
            if isinstance(item, dict):
                print(f"gate {gate}: {item.get('id')} is named in your words but no answer was recorded for it - {item.get('line')}")
        for item in questions.get("plan_not_changed") or []:
            if isinstance(item, dict):
                print(f"gate {gate}: {item.get('id')} is recorded, but the plan still branches on it in {', '.join(map(str, item.get('rows') or []))}"
                      ": the plan was not changed")
        if questions.get("not_applied_yet"):
            print(f"gate {gate}: not applied (the decision did not record): " + ", ".join(map(str, questions["not_applied_yet"])))
        risks = answer.get("risks") if isinstance(answer.get("risks"), dict) else {}
        if risks.get("line"):
            print(f"gate {gate}: {risks['line']}")
        rework = [r for r in questions.get("rework") or [] if isinstance(r, dict)]
        if questions.get("rework_left"):
            print(f"gate {gate}: {questions['rework_left']}")
            self.drop_record("answer_rework")
        elif rework:
            try:
                self.merge_answer_rework(rework)
            except Exception as exc:
                print(f"note: the rework your answers owe could not be queued ({type(exc).__name__}: {' '.join(str(exc).split())[:160]})")
        return answer

    # --- gates -----------------------------------------------------------------------------

    def gate_text(self, gate: str) -> str:
        parts = []
        code, brief = self.py("gate_brief.py", "--task", self.task, "--gate", gate)
        if code == 0:
            parts.append(brief)
        else:
            # t-370 (b): a person never reads a script name or an exit code. They read that the brief could not be built and the
            # brief's own first line (unless that line itself names a script, a flag or an exit code: then the line is not
            # shown); the code and the whole output go to the driver log.
            first = next((" ".join(row.split()) for row in brief.splitlines() if row.strip()), "")
            if any(p["rule"] in ("script_name", "flag", "exit_code") for p in human_text.problems(first, kind="report")):
                first = ""
            print(f"gate {gate}: the gate brief did not build (exit {code}): {' '.join(brief.split())[:400]}")
            parts.append("The gate brief could not be built" + (f" ({first})" if first else "") + ".")
        code, rehearsal = self.py("gate_preflight.py", "--task", self.task, "--gate", gate, "--text")
        # t-342: the heading used to name the script and its flag (`gate_preflight --gate B`): jargon in the body of a
        # question (human-questions.md, rule 5). What follows it is `gate_preflight --text`, whose own lines still
        # carry commands for the factory's findings - reported, not fixed here (another file's text).
        parts.append(f"## Rehearsal of gate {gate}\n" + rehearsal)
        # t-363 B1: `--list` is the PERSON form (one line per waiver, in words: stage, the block, their word whole,
        # the date) - this section used to carry the command's machine lines, with a script name and a timestamp. A
        # failed call (no readable pipeline.json) prints a sentence for whoever ran it: it is never a section.
        code, waivers = self.py("waiver.py", "--task", self.task, "--list")
        if code == 0 and waivers.strip():
            parts.append("## Blocks passed by your word so far\n" + waivers)
        if gate == "A":
            code, late = self.py("ticket_adapter.py", "review", "--output",
                                 f"qa-factory/artifacts/{self.task}/work/source-inventory.json", "--pending-only")
            if code == 0 and late.strip():
                parts.append("## Sources found after the S1 review\n" + late)
            word = self.approval_word("A")
            parts.append(
                (f"Approval is its own word: write `{word}` on the first line when the plan and the cases are approved as they "
                 "stand, then answer every item under 'After your approval' by name. To change something first, say what in your "
                 f"own words instead of `{word}`: nothing is approved, and you get the choices with what each costs; after a "
                 "change, this message comes again.") if word else
                ("Answer in your own words: say whether the plan and the cases are approved as they stand, then answer every "
                 "item under 'After your approval' by name."))
        else:
            # t-250 §4 (F10): what an agent checked BY HAND - the same block the report holds (FR-10: one renderer feeds
            # the report and this packet) - stands before the ledger and is never cut. Its writer is another task's
            # (`report_facts.manual_checks_text`), so a renderer that is not there yet, or one that fails, is ONE line
            # saying so (FR-41), never a missing section that reads like "nothing was checked by hand".
            parts.append(self.manual_checks_part())
            ledger = self.task_root / "work/ledger.md"
            if ledger.is_file():
                parts.append("## The checks ledger (work/ledger.md)\n" + ledger.read_text(encoding="utf-8", errors="replace")[:12000])
            report = self.task_root / "test-report.md"
            if report.is_file():
                parts += self.report_parts()
                parts.append(f"The whole report: qa-factory/artifacts/{self.task}/test-report.md")
            # An experiment opens no merge request (t-017 D3, FR-36): the instruction does not ask
            # whether one is opened, nor for a reason to deliver with known gaps - nothing is delivered.
            # t-342 (B-271, owner 02.10): the retro is ALWAYS full - the person is not offered a choice about it, so
            # the packet says nothing of it (its twin is phases/s8.md, item "The retro"). The `retro_mode` branches
            # in `stage_S9` stay for now; this is the sentence that offered them.
            # t-305 N8 (R6): the packet never offers an act the guard will refuse. The MR is offered on `yes` and on
            # `after_checks` (its description carries what is left with the person); on `no` the only item is
            # "deliver with known gaps" with its reason - and it is the MR's word only: a bug is filed from the numbers the
            # person answers (the driver records every gate B decision with `--bugs ordered`), never through that word.
            word = self.delivery_word()
            approve = self.approval_word("B")
            # C1-4b (FR-10): the approval line is prepended to EACH variant below, from the same word the check reads
            lead = (f"To approve, write `{approve}` on the first line of your answer; the rest of it is read as before. To have "
                    "something changed first — a test, the report, a case — write what, in your own words, instead of "
                    f"`{approve}`: nothing is recorded as approved, and you get the choices with what each costs. ") if approve else ""
            if self.no_trace():
                parts.append(lead + "Answer by number for the bugs to file.")
            elif word == "yes":
                parts.append(lead + "Answer by number for the bugs to file; say whether the MR is opened (Draft) or not; a "
                             "'deliver with known gaps' needs its reason.")
            elif word == "after_checks":
                parts.append(lead + "Answer by number for the bugs to file; say whether the MR is opened (Draft) - its "
                             "description carries what is left with you; a 'deliver with known gaps' needs its reason.")
            else:
                # HF8-23: the form is the one `gate_brief.risk_form` prints in the skill road's packet (one text, AR-19)
                import gate_brief
                form = gate_brief.risk_form()
                parts.append(lead + "Answer by number for the bugs to file. The checks do not say the delivery is ready, so no "
                             "MR is offered: to open one, " + (form + "." if form else "say 'deliver with known gaps' and give your reason."))
        return "\n\n".join(parts)

    def report_parts(self) -> list:
        """The report's verdict block and its `## Left with you` section, WHOLE (t-305 N8, Q22): the packet used to find
        "section 3" by a regex no report matches and fell back to the first 4000 characters, so a Left with you that
        began later was never shown. A part that is absent is one line saying so (FR-41), never a silent gap. When a
        stand-gap answer below could change the verdict, ONE sentence says it was computed before the answer and is
        computed again before anything goes out (C7)."""
        import grammar as G
        import report_facts
        out = []
        try:
            text = (self.task_root / "test-report.md").read_text(encoding="utf-8-sig", errors="replace")
            verdict = G.find_blocks(text).get("verdict")
        except Exception:
            verdict = None
        out.append("## The verdict (test-report.md)\n" + (verdict[2].strip("\n") if verdict else
                                                           "the report holds no verdict block yet"))
        if self.verdict_may_change():
            out.append("This verdict was computed before your answer; an answer to a stand gap below can change it, "
                       "and it is computed again before anything goes out.")
        try:
            left = report_facts.left_with_you_text(self.task_root)
        except Exception:
            left = None
        out.append(left.rstrip("\n") if left else "## Left with you (test-report.md)\nthe report holds no such section yet")
        return out

    def verdict_may_change(self) -> bool:
        """Could an answer at this gate change the verdict word? Yes while a stand gap waits for a card answer, or an
        ENV_ISSUE has no closed decision (the ledger's own kind `env_undecided`)."""
        try:
            import gate_brief
            import contract as C
            if gate_brief.gate_b_gaps(self.task_root):
                return True
            ledger = C.load_json(C.artifact(self.task_root, "ledger.json"))
            return any(isinstance(r, dict) and r.get("kind") == "env_undecided" for r in ledger.get("reason_records") or [])
        except Exception:
            return False

    def manual_checks_part(self) -> str:
        """The block of what an agent checked by hand, as `report_facts.manual_checks_text(task_root)` renders it, whole.

        The import is guarded: until the renderer exists the line is "manual checks: renderer not installed". A render
        that raises, or prints nothing, is one line each - the packet is still shown (P1)."""
        try:
            import report_facts
            render = report_facts.manual_checks_text
        except (ImportError, AttributeError):
            return "manual checks: renderer not installed"
        try:
            text = render(self.task_root)
        except Exception as exc:
            return f"manual checks: could not be shown ({type(exc).__name__}: {' '.join(str(exc).split())[:160]})"
        if not isinstance(text, str) or not text.strip():
            return "manual checks: the renderer printed nothing"
        return text

    NOTE_QUOTE_LIMIT = 200

    def gate_rework_note(self, gate: str) -> str:
        """The line at the top of a gate asked AGAIN after a rework (I5, FR-7, H7): the person's words, the stage that was done again and
        the stages that ran again after it. Derived from EVERY accepted rework (`rework_of`) registered since this gate was last shown
        - not only the stamped ones - so a rework with nothing after it (an S8 scribe) still changes the text and an unchanged packet is
        never shown without a note. The ids shown are kept in `gate_noted[gate]` when the gate is raised; a gate never shown before
        (no key) says nothing and seeds the list, so the repair rounds of the stages before the first show are not "a rework". A rework
        of the B-364 road (`ticket_changed`) has its own note. Only a record marked `person_words` (the controller sets it for `--words-file`)
        is quoted as the person's words; any other rework is told neutrally, without its code-typed reason. Never raises: no note is better than no gate."""
        try:
            noted = self.state.setdefault("gate_noted", {})
            seen = noted.get(gate)
            made = [d for d in (self.controller_state().get("dispatches") or {}).values()
                    if isinstance(d, dict) and d.get("rework_of") and d.get("status") == "accepted"
                    and d.get("repair_cause") != "ticket_changed"]
            noted[gate] = list(dict.fromkeys(list(seen or []) + [str(d.get("id")) for d in made]))
            if seen is None:
                return ""
            names = self.stages()

            def label(stage: str) -> str:
                name = str((names.get(stage) or {}).get("name") or "").strip().lower()
                return f"{name} ({stage})" if name else stage
            sentences = []
            for d in made:
                if str(d.get("id")) in seen:
                    continue
                if d.get("person_words") is not True:
                    # t-694 F1: a rework the driver or the conductor asked for (a reason typed by code) is never shown as the
                    # person's words, and a record without the mark (an older controller wrote it) is treated the same way (FR-59).
                    cause = " ".join(str(d.get("repair_cause") or "test_defect").replace("_", " ").split())
                    sentences.append(f"{label(str(d.get('stage') or ''))} ran again after a repair round of the factory's own ({cause})")
                    continue
                words = " ".join(str(d.get("reason") or "").split())
                quote = words[:self.NOTE_QUOTE_LIMIT] + ("..." if len(words) > self.NOTE_QUOTE_LIMIT else "")
                later = [label(s) for s in (d.get("rerun_after") or {}).get("stages") or []] if isinstance(d.get("rerun_after"), dict) else []
                sentences.append(f"on your words \"{quote}\", {label(str(d.get('stage') or ''))} was done again"
                                 + (f", then {', '.join(later)} ran again" if later else ""))
            return f"Gate {gate} is asked again: " + "; and ".join(sentences) + "." if sentences else ""
        except Exception:
            return ""

    def gate(self, gate: str, top: str = "") -> None:
        """The gate question. `top` is the factory's own list of what it could not repair before asking
        (`gate_repair`, F5 b): it stands above the packet, so the person reads first that these are not theirs."""
        self.boundary = f"gate_{gate}"
        # B-364 R17: the line that says why this gate comes again, once, at the top. One carrier, `gate_note` (the writer is
        # `ticket_reopen_gate_a`; t-694 F4 renamed it from `ticket_gate_note`, the old key is no longer read).
        said = []
        held = self.state.get("gate_note")
        if isinstance(held, dict) and held.get(gate):
            said.append(held.pop(gate))
        again = self.gate_rework_note(gate)
        if again:
            said.append(again)
        if gate == "B":                       # the question lines of the findings this packet shows; a `open` one asked again says so (FR-7)
            left_open = self.keep_shown_exploratory()
            if left_open:
                said.append(left_open)
        if said:
            top = "\n\n".join(said) + ("\n\n" + top.strip() if top.strip() else "")
        head =f"# Gate {gate} — {self.task}\n\n" + (top.strip() + "\n\n" if top.strip() else "")
        # t-369 N-2: the doors this packet SHOWS, by finding id - the block and stage each id's door passes. An answer's
        # door line is read only against these (`read_finding_doors`): ids are ordinal and a message does not bind a block.
        # Best effort: a rehearsal that cannot run stores none, and then no door line is read by code (the conductor is).
        # The doors are those of the rehearsal the repair step just ran (`rehearse` keeps them): no second rehearsal is run for them.
        shown_doors = dict((self.state.get("last_rehearsal_doors") or {}).get(gate) or {})
        self.state.setdefault("shown_doors", {})[gate] = shown_doors
        # B-414 M12: the stand gaps (and the ones the environment record covered) of the rehearsal that built THIS packet - bound
        # to what the person is shown, like the doors: a later `rehearse()` (the answer's own) must not rewrite what they saw
        self.state.setdefault("shown_gaps", {})[gate] = dict((self.state.get("last_rehearsal_gaps") or {}).get(gate) or {})
        body = self.gate_text(gate)       # built first: the brief reads the PREVIOUS `shown_attachments` from disk, the line below replaces it
        if gate == "A":                   # S6 1c: the attachments this packet names, so a later gate A says what is new
            import gate_brief
            gate_brief.keep_shown_attachments(self.task_root, self.state)
        raise Person(f"gate_{gate}", head + body, "S4" if gate == "A" else "S8")

    def rehearse(self, gate: str) -> dict:
        """The gate's rehearsal as data: `gate_preflight.py --task T --gate X` (read-only, JSON). A seam: the
        tests replace it. Anything that is not a result raises, and the caller shows the gate without it."""
        code, out = self.py("gate_preflight.py", "--task", self.task, "--gate", gate)
        if code:
            raise RuntimeError(f"gate_preflight.py exited {code}: {' '.join(out.split())[-200:]}")
        try:
            data = json.loads(out[out.index("{"):out.rindex("}") + 1])
        except ValueError as exc:
            raise RuntimeError("gate_preflight.py printed no readable JSON") from exc
        if not isinstance(data, dict):
            raise RuntimeError("gate_preflight.py printed no JSON object")
        # t-369 N-2: the doors of THIS rehearsal by finding id, kept for `gate()` (the packet shown right after it)
        self.state.setdefault("last_rehearsal_doors", {})[gate] = {
            str(f["id"]): [d for d in f.get("waives") or [] if isinstance(d, dict)]
            for f in data.get("findings") or [] if isinstance(f, dict) and f.get("id")}
        # B-414 R8(c): the stand gaps of this rehearsal and the gaps the environment record covered (no card), kept for `gate()`;
        # `carry_environment_properties` reads them - it runs no rehearsal of its own
        try:
            import stand_gaps
            self.state.setdefault("last_rehearsal_gaps", {})[gate] = {
                "gaps": [{"id": str(g["id"]), "case_id": str(g.get("case") or ""), "cases": [str(c) for c in g.get("cases") or []]}
                         for g in data.get("stand_gaps") or [] if isinstance(g, dict) and g.get("id")],
                "covered": stand_gaps.covered_a(self.task_root, data)}
        except Exception:
            self.state.setdefault("last_rehearsal_gaps", {})[gate] = {"gaps": [], "covered": []}
        return data

    @staticmethod
    def fixable_findings(findings: list) -> list:
        """The `factory_fixable` findings, normalised: a finding that is no object, or has no `class`, or no
        text `check`, is not one of them (a story from an older build is shown as it always was)."""
        out = []
        for item in findings:
            if (isinstance(item, dict) and item.get("class") == FACTORY_FIXABLE
                    and isinstance(item.get("check"), str) and item["check"].strip()):
                out.append(dict(item, check=item["check"].strip(),
                                message=" ".join(str(item.get("message") or "").split())))
        return out

    @staticmethod
    def key_set(fixable: list) -> list:
        """The sorted, de-duplicated (check, message) pairs. NEVER the finding's positional `id`
        (`gate_decision-1` names the first finding of its check, whichever row it is about: a different
        row under the same id is a different finding), and never a count."""
        return [list(key) for key in sorted({(f["check"], f["message"]) for f in fixable})]

    @staticmethod
    def attempted_rounds(rounds) -> list:
        """The rounds that spent something: every record that is not a stop (a stop is `same_set`, `cap` or
        `no_move`; a `failed` round did try its move and counts)."""
        return [r for r in rounds if isinstance(r, dict) and (not r.get("stop") or r.get("stop") == "failed")]

    def gate_series(self, gate: str) -> dict:
        """The series of repair rounds of this gate, kept in `driver-state.json` (an exit-3 relaunch counts from
        the same place; the conductor's calls, kept in memory, do not survive one). A series is the factory's
        own bookkeeping of ONE story revision (C7): it is dropped when `source_revision` changed since it began
        (a reopen), or when the gate is approved at the current revision; the next one starts empty."""
        state = self.controller_state()
        revision = state.get("source_revision")
        approved = any(isinstance(d, dict) and d.get("gate") == gate and d.get("status") == "approved"
                       and d.get("source_revision") == revision for d in (state.get("decisions") or {}).values())
        held = self.state.get("gate_repair")
        if not isinstance(held, dict):
            held = self.state["gate_repair"] = {}
        series = held.get(gate)
        if isinstance(series, dict) and (series.get("source_revision") != revision or approved):
            held.pop(gate)
            series = None
        if not isinstance(series, dict) or not isinstance(series.get("rounds"), list):
            series = held[gate] = {"source_revision": revision, "rounds": []}
        return series

    def kept_answer(self, gate: str) -> dict:
        """The person's answer to this gate that was heard but not recorded (`record_by_code` failed and the
        words went to the conductor), or {}. Stamped with the revision it was given at (C3): an answer to a
        reopened story's old gate is not an answer to the new one."""
        kept = self.state.get("gate_answer_kept")
        if (isinstance(kept, dict) and kept.get("gate") == gate and str(kept.get("words") or "").strip()
                and kept.get("source_revision") == self.controller_state().get("source_revision")
                and (kept.get("approved_by") in ("option", "token") or self.gate_approval(f"gate_{gate}", str(kept["words"])))):
            return kept
        return {}

    def old_kept_answer(self, gate: str) -> str:
        """The words of a `gate_answer_kept` an OLDER driver wrote (any gate words, prose), dropped from the state and returned so the
        caller hands them to the seam once (C1-4b, H8): they were never an approval, so the controller never "refused" them and the
        person is not told it did. "" when there is none, it is an approval (`approved_by` or the approval word), it belongs to another
        gate, or it was given at another revision of the story (dropped silently: an answer to a reopened story's old gate)."""
        kept = self.state.get("gate_answer_kept")
        if not isinstance(kept, dict) or kept.get("gate") != gate or not str(kept.get("words") or "").strip():
            return ""
        if kept.get("approved_by") in ("option", "token") or self.gate_approval(f"gate_{gate}", str(kept["words"])):
            return ""
        self.state.pop("gate_answer_kept", None)
        self.save_state()
        return str(kept["words"]) if kept.get("source_revision") == self.controller_state().get("source_revision") else ""

    def design_reviews(self, gate: str) -> list:
        """The design reviews the controller would bind into this gate's decision (`build_gate_decision`, which
        writes nothing: the rehearsal reads the same). [] when they cannot be built - then no move applies."""
        try:
            from controller import Controller
            request = Controller(self.task_root).build_gate_decision(gate, "<the words the person is about to say>")
            reviews = request.get("design_reviews")
            return [r for r in reviews if isinstance(r, dict)] if isinstance(reviews, list) else []
        except Exception:
            return []

    def accept_order(self) -> dict:
        """dispatch id -> the position of its `accept` event in `state/events.jsonl` (the order work was
        accepted in; dispatch numbers and registration order say nothing about it). The one reader is
        `Controller.accept_order`; this only delegates (AR-13)."""
        from controller import Controller
        return Controller(self.task_root).accept_order()

    def pin_precondition(self, gate: str, findings: list, *, pin_planned: bool = False, rounds=()):
        """`case_versions`: no precondition. The gate approves what is on disk, and pinning is idempotent."""
        return {"pins": True}

    def review_precondition(self, gate: str, findings: list, *, pin_planned: bool = False, rounds=()):
        """`gate_decision`: which role goes back, read from the controller's own design reviews and the order of
        the `accept` events - never from a finding's wording (FR-12).

        (1) a designer accepted AFTER the critic reviewed (the rework changed what the critic saw): the critic
            reviews again, over the cases that designer reworked. The review is bound to the pinned case
            versions, so the round re-pins first; `pin_planned` says it is about to.
        (2) otherwise a critic whose declared verdict is not approving, with no designer round after it: the
            designer reworks the cases of the critic dispatch's own scope - but only while a round is left for
            the critic that must follow it (the series cap) AND the designer's own repair cap has room; if not,
            this is `direct`: the person is told, once, at the gate (F2 c).
        None when neither holds, or the scope is empty (F8: a rework with an empty scope passes every later
        check, so it is never registered)."""
        reviews = self.design_reviews(gate)
        if not reviews:
            return None
        dispatches = self.controller_state().get("dispatches") or {}
        order = self.accept_order()
        from controller import Controller
        later = []
        for review in reviews:
            # the one staleness predicate (AR-13): `Controller.review_is_stale`, not a second loop of the same rule
            author = str(review.get("author_dispatch_id") or "")
            if Controller.review_is_stale(review, order) and author not in later:
                later.append(author)

        def scope_of(ids) -> list:
            return sorted({str(c) for i in ids for c in ((dispatches.get(i) or {}).get("scope") or [])})
        if later:
            scope = scope_of(later)
            if not pin_planned:
                pinned = set(self.pinned_cases())
                scope = [c for c in scope if c in pinned]
            return {"kind": "critic", "scope": scope, "authors": later} if scope else None
        refusing = [r for r in reviews if str(r.get("verdict") or "accepted") != "accepted"]
        if not refusing:
            return None
        critics = sorted({str(r.get("reviewer_dispatch_id")) for r in refusing if r.get("reviewer_dispatch_id")})
        scope = scope_of(critics)
        if not scope:
            return None
        if all(r.get("verdict_basis") == "round_word_rule" for r in refusing):
            # HF4-11: the critic's word contradicts its own cells - the cases are fine, only the `Verdict:` line is
            # wrong, and only the critic can rewrite it. A designer round would have nothing to fix. The invariant: no
            # designer round for a refusal that is not about a case; the cap still ends at the person (`direct`), and a
            # round of the critic needs no round after it, so one round of the series is enough. A mixed set (some row
            # refused for another reason) keeps the designer route below - that round is followed by the critic anyway.
            if len(self.attempted_rounds(rounds)) + 1 > GATE_REPAIR_CAP:
                return {"direct": True, "why": "no round is left for the critic to rewrite its `Verdict:` line"}
            return {"kind": "critic", "scope": scope, "authors": critics, "rule": "round_word_rule"}
        if len(self.attempted_rounds(rounds)) + 2 > GATE_REPAIR_CAP:
            return {"direct": True, "why": "no round is left for the critic that would follow a designer round"}
        budget = self.budget_or_none("S4", "qa-case-designer", scope) or {}
        counted, cap = budget.get("counted"), budget.get("cap")
        if not (isinstance(counted, int) and isinstance(cap, int) and counted < cap):
            return {"direct": True, "why": "the designer's repair cap is spent (or could not be read)"}
        return {"kind": "designer", "scope": scope, "critics": critics, "counted": counted, "cap": cap}

    def repair_plan(self, gate: str, fixable: list, rounds) -> tuple:
        """(plan, direct): the table's rows whose check is among the findings and whose precondition holds, in
        the table's order; and the findings that go straight into the list at the top of the gate (a check
        only a person's word can pass, or a critic that did not approve with no round left). Reads state,
        writes nothing."""
        plan, direct = [], [f for f in fixable if f["check"] in GATE_DIRECT_CHECKS]
        pin_planned = False
        for row_gate, check, precondition, move in GATE_REPAIRS:
            mine = [f for f in fixable if f["check"] == check]
            if row_gate != gate or not mine:
                continue
            found = getattr(self, precondition)(gate, mine, pin_planned=pin_planned, rounds=rounds)
            if not found:
                continue
            if found.get("direct"):
                direct += mine
                continue
            plan.append((precondition, move, mine, found))
            pin_planned = pin_planned or bool(found.get("pins"))
        return plan, direct

    def pin_move(self, gate: str, findings: list, found: dict, record: dict) -> None:
        try:
            self.pin_cases()
        except Refusal as exc:
            record["moves"].append("pin_cases (failed)")
            raise RepairFailed("case_versions.py --all, then --verify", exc.text) from exc
        record["moves"].append("pin_cases")
        print(f"gate {gate} repair: the cases are pinned again at their current bytes")
        # C11 (t-214 C1): the controller's approved scope follows the pinned cases, exactly as stage_S4 does it
        # (`pin_cases()` then `revise_plan()`). A designer round at the gate may add or drop a case; without
        # this the gate decision binds the OLD scope and the person approves a scope without that case.
        try:
            self.revise_plan()
        except Refusal as exc:
            record["moves"].append("revise_plan (failed)")
            raise RepairFailed("controller.py --operation revise_plan", exc.text) from exc
        record["moves"].append("revise_plan")

    def review_move(self, gate: str, findings: list, found: dict, record: dict) -> None:
        scope = found["scope"]
        if found["kind"] == "critic" and found.get("rule") == "round_word_rule":
            authors = ", ".join(found["authors"])
            print(f"gate {gate} repair: the case critic rewrites the `Verdict:` line of {authors} "
                  f"(no case fails; the cases are unchanged): {', '.join(scope)}")
            role, move = "qa-case-critic", "critic_rework"
            reason = (f"gate {gate} repair: your round's Verdict line contradicts your own cells (no failing case); "
                      f"rewrite the Verdict line - the cases were not changed ({authors})")
            extra = ["Write a new round on top of the findings file with the Verdict line your cells earn "
                     "(`approve_with_concerns` when no case fails); earlier rounds are never edited."]
        elif found["kind"] == "critic":
            authors = ", ".join(found["authors"])
            print(f"gate {gate} repair: the case critic reviews again the {len(scope)} case(s) the designer "
                  f"reworked in {authors}: {', '.join(scope)}")
            role, move = "qa-case-critic", "critic_rework"
            reason = (f"gate {gate} repair: the case designer reworked these cases after your review ({authors}); "
                      "review them again at their pinned versions")
            extra = ["Review only the pinned versions; your roll-call names every case in scope."]
        else:
            critics = ", ".join(found["critics"])
            print(f"gate {gate} repair: the case designer reworks the {len(scope)} case(s) the critic did not "
                  f"approve in {critics}: {', '.join(scope)} (designer round {found['counted'] + 1} of {found['cap']})")
            findings_file = self.s4_findings()
            role, move = "qa-case-designer", "designer_rework"
            reason = ("critic round: " + findings_file.read_text(encoding="utf-8", errors="replace")[:1200]
                      if findings_file else
                      f"gate {gate} repair: the case critic ({critics}) did not approve these cases; "
                      "its findings are in the case folder")
            extra = [f"Repair round {found['counted'] + 1} of {found['cap']}: the critic's findings are in "
                     + (findings_file.relative_to(self.task_root).as_posix() if findings_file else "the case folder")
                     + "; change only what they name."]
        record["moves"].append(move)
        try:
            # `cause` is the controller's own default for a round about the test (the only one that spends
            # the repair cap, and no value of REPAIR_CAUSES names "a second review"): a critic round over
            # reworked cases is a round of the same repair, so it is counted as one.
            self.rework("S4", role, scope, reason, cause="test_defect", extra=extra)
        except ReworkRefused as exc:
            record["moves"][-1] = move + " (refused)"
            raise RepairFailed(f"controller.py --operation rework --stage S4 --role {role}", exc.text) from exc

    def raise_precondition(self, gate: str, findings: list, *, pin_planned: bool = False, rounds=()):
        """`unraised_questions`: no precondition beyond the finding itself - `critic_rollcall.py --apply-fixes` is
        idempotent (a Then already raised is keyed by (case, then) and raises nothing twice). It re-pins what it
        writes, so a pin is planned (the critic's scope is cut by the pinned cases)."""
        return {"pins": True}

    def raise_move(self, gate: str, findings: list, found: dict, record: dict) -> None:
        """The S4 exit's own command, run for a Then that reached gate A with no question to ask the person (t-227 O4).

        Exit 0: every `raise` is now a question id. Exit 1 is the command's own word for "some could not be raised
        or fixed" - it printed which, and the finding it leaves is judged again by the next rehearsal (the same set
        is a recorded stop, FR-4: nothing is repeated blindly). Anything else is a failed move."""
        code, out = self.py("critic_rollcall.py", "--apply-fixes", "--task-root", str(self.task_root))
        if code not in (0, 1):
            record["moves"].append("critic_rollcall --apply-fixes (failed)")
            raise RepairFailed("critic_rollcall.py --apply-fixes", f"(exit {code})\n{out}")
        record["moves"].append("critic_rollcall --apply-fixes")
        print(f"gate {gate} repair: the questions the designer could only name are raised by code"
              + ("" if code == 0 else f" (some could not be: {' '.join(out.split())[-160:]})"))
        try:
            self.pin_cases()
        except Refusal as exc:
            record["moves"].append("pin_cases (failed)")
            raise RepairFailed("case_versions.py --all, then --verify", exc.text) from exc
        record["moves"].append("pin_cases")

    def probe_precondition(self, gate: str, findings: list, *, pin_planned: bool = False, rounds=()):
        """`s5_runtime_probe`: the rehearsal derived a probe, proved the stand against it and put the exact command
        that registers it in the finding's `argv` FIELD (a list of strings; FR-12: the sentence is never read). A
        finding with no such field has no move here - it is left to the conductor and the top of the gate."""
        argvs = [(str(f.get("profile") or ""), list(f["argv"])) for f in findings
                 if isinstance(f.get("argv"), list) and f["argv"] and all(isinstance(a, str) and a for a in f["argv"])]
        return {"argvs": argvs} if argvs else None

    UNKNOWN_TOKEN_RE = re.compile(r"\{[A-Za-z_][\w-]*\}")

    def run_argv(self, argv: list) -> tuple:
        """Run one command line as it is written, from the project root: (exit code, stdout+stderr). A seam: the
        tests replace it. `py` runs the plugin's own scripts by name; the argv of a registered probe is any command
        line (an older config holds an absolute one), so it is run as given."""
        done = subprocess.run([str(a) for a in argv], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=str(self.project), env=self.env)
        return done.returncode, (done.stdout + ("\n" + done.stderr if done.stderr.strip() else "")).strip()

    def probe_move(self, gate: str, findings: list, found: dict, record: dict) -> None:
        """Register the probes the rehearsal derived: `runtime_probe.resolve_argv(argv)` FIRST (the config's portable
        form - `{python}`, `{plugin_root}` - means this machine's interpreter and plugin; a legacy ABSOLUTE argv has no
        token and runs as written), then the command. INVARIANT: an argv that still holds a `{token}` after that is NOT
        executed - it would run with a brace word as an argument - and is refused naming the two tokens that exist."""
        self.typed_argv_move(gate, found["argvs"], record, "runtime_probe --suggest --write", "runtime_probe.py --suggest --write",
                             "probe", lambda profile: f"the probe the stand proved is registered for `{profile}`")

    def typed_argv_move(self, gate: str, pairs: list, record: dict, move: str, command: str, what: str, done) -> None:
        """Run the typed `argv` of each `(profile, argv)` a finding carried - ONE implementation for the two code-only rows that run one
        (`probe_move`, `adapt_move`): `runtime_probe.resolve_argv` first, an argv that still holds a `{token}` is refused unrun, a non-zero exit
        is a `RepairFailed` (the conductor gets the command and its last lines), a success is one line. `move` is what the round records,
        `command` what a failure names, `what` the noun of the refusal, `done(profile)` the success line. The config is read again after:
        both moves change it."""
        import runtime_probe
        for profile, argv in pairs:
            resolved = [str(a) for a in runtime_probe.resolve_argv(argv)]
            unknown = sorted({m for a in resolved for m in self.UNKNOWN_TOKEN_RE.findall(a)})
            if unknown:
                record["moves"].append(f"{move} {profile} (refused)")
                raise RepairFailed(
                    command,
                    f"the command for the `{profile}` {what} holds {', '.join(unknown)}, which is not one of the two words "
                    f"this factory fills in ({runtime_probe.PY_TOKEN} for the interpreter, {runtime_probe.PLUGIN_TOKEN} "
                    "for the plugin folder), so it was not run")
            code, out = self.run_argv(resolved)
            if code:
                record["moves"].append(f"{move} {profile} (failed)")
                raise RepairFailed(f"{command} --profile {profile}", f"(exit {code})\n{out}")
            record["moves"].append(f"{move} {profile}")
            print(f"gate {gate} repair: {done(profile)}")
        try:
            import hooklib
            self.config = hooklib.load_config() or self.config
        except Exception:
            pass

    def adapt_precondition(self, gate: str, findings: list, *, pin_planned: bool = False, rounds=()):
        """`s5_reporter` (B-416 N4, N6): a finding that carries the typed `argv` of the one `report_adapt.py kind` command (exactly one reader
        fits and the declared kind is empty) has a code move; one without it is left to the conductor and the top of the gate."""
        argvs = [(str(f.get("profile") or ""), list(f["argv"])) for f in findings
                 if isinstance(f.get("argv"), list) and f["argv"] and all(isinstance(a, str) and a for a in f["argv"])]
        return {"argvs": argvs} if argvs else None

    def adapt_move(self, gate: str, findings: list, found: dict, record: dict) -> None:
        """Run `report_adapt.py kind` for the findings that carry it: the same typed-argv mechanism (and the same refusal of an unknown `{token}`)
        as `probe_move`. A refusal of `kind` itself (a kind a person recorded, bytes that moved) is a `RepairFailed`: the conductor gets the
        output and the door `understood`."""
        self.typed_argv_move(gate, found["argvs"], record, "report_adapt kind", "report_adapt.py kind", "report adaptation",
                             lambda profile: f"the report of `{profile}` is read as the one reader that fits it, recorded by the helper")

    def gate_entry_steps(self, gate: str) -> None:
        """What the stage in front of this gate still owes, when its refused finish skipped it (C10): the
        row `gate_stage` lets that finish go on, and the code after it in `stage_S4` (the case appendix) and
        `stage_S8` (the report rebuild, t-204's position: after the scribe, before the gate packet) never ran."""
        owed = self.state.get("gate_entry_owed")
        stage = GATE_STAGE_OF.get(gate, "")
        if not isinstance(owed, dict) or not owed.pop(stage, None):
            return
        self.save_state()
        if gate == "A":
            self.render_appendix()
        else:
            self.rebuild_report()

    def finding_counts(self, fixable: list) -> str:
        counts: dict = {}
        for item in fixable:
            counts[item["check"]] = counts.get(item["check"], 0) + 1
        return ", ".join(f"{CHECK_WORDS.get(check, check.replace('_', ' '))} {counts[check]}" for check in sorted(counts))

    def unrepaired_text(self, gate: str, fixable: list) -> str:
        """The block at the top of the gate packet (F5 b): what the factory could not repair, stated as its
        own (FR-3) - the person is told, not asked. At most GATE_TOP_LIMIT lines; the rest is counted."""
        seen, lines = set(), []
        # what only a person's word passes (question branches) first: a long list must not cut it off
        for item in sorted(fixable, key=lambda f: f["check"] not in GATE_DIRECT_CHECKS):
            if item["message"] not in seen:
                seen.add(item["message"])
                lines.append(item["message"])
        shown = lines[:GATE_TOP_LIMIT]
        out = ["## What the factory could not repair before asking you", "",
               "These are the factory's own to repair, not questions for you: it tried every move it has, and they "
               "are still open. Your answer does not depend on them, and your word passes them - it is recorded "
               "as the reason the story carries.", ""]
        out += [f"- {line}" for line in shown]
        if len(lines) > len(shown):
            out.append(f"- (and {len(lines) - len(shown)} more in the rehearsal below)")
        if gate == "A" and any(item["check"] == "gate_decision" for item in fixable):
            # the case critic reviews at gate A only (at B the same check id is about the delivery decision)
            findings_file = self.s4_findings()
            if findings_file:
                out += ["", "The case critic's own findings: "
                        f"qa-factory/artifacts/{self.task}/{findings_file.relative_to(self.task_root).as_posix()}"]
        return "\n".join(out)

    KEPT_REFUSAL_LIMIT = 2000

    def kept_answer_text(self, kept: dict) -> str:
        """The block at the top of a gate asked AGAIN over a kept answer (t-214 C3, FR-7): when their words were
        given, the first 200 characters of them, and the controller's refusal verbatim (cut at KEPT_REFUSAL_LIMIT
        characters, and it says so). The packet differs from the one they answered, and says why."""
        words = " ".join(str(kept.get("words") or "").split())
        said = words[:200] + ("..." if len(words) > 200 else "")
        if self.question_lines_note:
            # GW1-34 F4: the kept approval was held on lines about register questions, not refused by the controller - say so, and
            # let a plain `approve` be a knowing pass (FR-4). The note is told once (F5).
            shown, self.question_lines_note = self.question_lines_shown, ""
            first = shown.split(":", 1)[0].strip() or "Q1"
            return "\n".join(["## Your approval is kept, and it waits for your word on these lines", "",
                              f"You answered this gate at {kept.get('at') or 'an earlier time'}: \"{said}\"", "",
                              f"These lines about open questions could not be read, so nothing is recorded yet: {shown}.", "",
                              f"Answer `{self.approval_word(str(kept.get('gate') or '')) or 'approve'}` with each of them as `{first}: <letter>`, "
                              f"`{first}: not needed` or `{first}: until the report` on its own line; or `approve as is` to approve and leave them open."])
        refusal = str(self.gate_refusal or "").strip() or "(the controller printed nothing)"
        cut =len(refusal) > self.KEPT_REFUSAL_LIMIT
        items = self.gate_open_items(self.gate_refusal)
        record, _ = json_record(str(self.gate_refusal or ""))
        if items:
            # RH1-6 (A-AC5): the refusal is the ITEMS' - the approval stands and waits for the person's word on each; it is not
            # the factory's to repair (the owner is named from the field, never from the sentence). The factory's OWN sentences, when
            # the same record holds some, are told apart by the controller's `item_problems_from` and printed under their own owner
            # line, never as the person's (FR-10, FR-3); `approve as is` is offered only when there are none (it does not pass them).
            import gate_brief
            factory, listed = self.gate_refusal_parts(self.gate_refusal)
            as_is = "" if factory else gate_brief.as_is_word_of(str(kept.get("gate") or ""))
            out = ["## Your approval is kept, and it waits for your word on the items below", "",
                   f"You answered this gate at {kept.get('at') or 'an earlier time'}: \"{said}\""]
            if factory:
                out += ["", "First, the factory's own to repair, not questions for you:", ""]
                out += [f"- {line}" for line in factory] + [""]
            out += ["Your approval is kept. The factory records a gate A approval only over the items you have worded; these have no "
                    "word of yours yet, so nothing is recorded as approved:", ""]
            out += [f"- {line}" for line in listed] or [refusal[:self.KEPT_REFUSAL_LIMIT]]
            out += ["", "Word each item in your own words" + (f", or answer `{as_is}` to approve over all of them, each recorded with your words."
                                                             if as_is else ".")]
            return "\n".join(out)
        # A refusal this driver can READ as the controller's own record, with no open items, is the factory's (an older controller never
        # refuses over items either); text it cannot read names no owner (FR-41).
        owner = ("That is the factory's to repair, not a question for you; what it said, word for word"
                 if isinstance(record, dict) and isinstance(record.get("problems"), list)
                 else "It is not known whose to repair this is; what it said, word for word")
        out = ["## Your earlier answer is kept, and it did not record", "",
               f"You answered this gate at {kept.get('at') or 'an earlier time'}: \"{said}\"",
               "The factory kept your words, tried to record them as the decision, and its own check refused. "
               + owner + (f" (cut at {self.KEPT_REFUSAL_LIMIT} characters)" if cut else "") + ":", "",
               refusal[:self.KEPT_REFUSAL_LIMIT], "",
               self.kept_answer_close(str(kept.get("gate") or ""))]
        return "\n".join(out)

    def approval_word(self, gate: str) -> str:
        """The word that approves gate `gate`, as the data file spells it (`gate_brief.approval_words`, the one reader); "" when the
        file cannot be read - then no packet text names a word (FR-10: the line and the check read the same source)."""
        import gate_brief
        words = gate_brief.approval_words(gate)
        return words[0] if words else ""

    def kept_answer_close(self, gate: str) -> str:
        """The last line of a gate asked again over a kept approval: an approval is its own word, a change is the person's own words."""
        word = self.approval_word(gate)
        if not word:
            return "Answer this gate again in your own words."
        return (f"If your approval still stands, answer `{word}` again; to change something first, say what in your own words.")

    def conductor_text(self, gate: str, why: str, rest: list, tried: str) -> str:
        """What the conductor is handed for a list code could not repair (FR-1): what is unrepaired, what was
        tried and with what output, and the doors. At most 20 findings; the rest is counted."""
        out = [f"Gate {gate} is about to be shown to the person, and the driver's own rehearsal still lists "
               f"{len(rest)} finding(s) of class factory_fixable that its code moves did not repair ({why}). The "
               "person has NOT been asked, and nothing here is theirs to decide: these are the factory's own.", "",
               "What the driver tried: " + (tried or "nothing - no code move applies to these checks") + ".", "",
               "The findings:"]
        for item in rest[:20]:
            line = f"- [{item.get('id') or item['check']}] {item['check']}: {item['message']}"
            if str(item.get("fix") or "").strip():
                line += "\n    fix: " + " ".join(str(item["fix"]).split())
            # t-364: the `fix` is words for a person; the block a person's word passes is the finding's `waives`
            # (gate_preflight), printed here for the conductor and for nobody else
            for door in item.get("waives") or []:
                if isinstance(door, dict) and door.get("block"):
                    line += (f"\n    a person's word passes block `{door['block']}` at {door.get('stage') or 'its stage'} "
                             f"(word option `{door.get('option')}`)")
            out.append(line)
        if len(rest) > 20:
            out.append(f"- (and {len(rest) - 20} more: `gate_preflight.py --task {self.task} --gate {gate} --text`)")
        out += ["", "Repair what you can with the factory's own commands (each finding's `fix` names its door), then "
                "answer `continue`: the driver shows the gate once, with whatever is left stated at its top as the "
                "factory's own. Answer `ask_person` only for a finding that needs a decision of theirs."]
        return "\n".join(out)

    def record_round(self, gate: str, series: dict, record: dict) -> None:
        """Round bookkeeping goes to the state file (the cap outlives the process) and to the driver journal."""
        if not any(r is record for r in series["rounds"]):
            series["rounds"].append(record)
        self.save_state()
        self.journal_run({"kind": "gate_repair", "gate": gate,
                          "round": next(i for i, r in enumerate(series["rounds"], 1) if r is record),
                          "keys": len(record["keys"]), "moves": record["moves"], "outcome": record["outcome"],
                          "stop": record["stop"]})

    def gate_repair(self, gate: str) -> dict:
        """The step in front of the gate packet. Returns {"ran": True} when a repair round was run (the loop goes
        back to `where`, which rehearses again), else {"ran": False, "top": <text>} - the caller shows the gate.

        POSITION INVARIANTS (t-211): (i) Person(gate_X) is never raised while the rehearsal holds an unwaived
        `factory_fixable` finding that a move can still address in this series - what no move addresses is
        shown, stated, at the top (F5 b); (ii) a round whose key set equals that of any earlier round of the
        series is refused; (iii) nothing is repaired under an open question about this gate (the packet a
        person is reading never changes under them); (iv) nothing is repaired after the person has spoken
        (a kept, unrecorded answer is recorded again, never asked again - FR-7). Every failure to rehearse
        shows the gate, as before."""
        shown = {"ran": False, "top": ""}
        self.boundary = f"gate_{gate}"
        if self.dry:
            print(self.gate_repair_would(gate))
            return shown
        asked = self.state.get("asked") or {}
        if asked.get("kind") == f"gate_{gate}" and self.question_path().is_file():
            print(f"gate {gate}: a question about this gate is already open — nothing is repaired under it")
            return shown
        old = self.old_kept_answer(gate)
        if old:
            # H8 (temporal): an answer kept by the driver before C1-4b holds prose that was never an approval. It goes to the seam
            # ONCE, whole, from its own words file; nothing says the controller refused it.
            print(f"gate {gate}: an answer kept by an older driver is not an approval - it goes to the conductor once")
            self._answer = {"text": old, "rel": None}
            try:
                self.unread(f"gate_{gate}", GATE_STAGE_OF.get(gate, ""), "", self.generic_prompt(f"gate_{gate}", GATE_STAGE_OF.get(gate, ""), ""), words=old)
            finally:
                self._answer = None
            return dict(shown, ran=True)
        kept = self.kept_answer(gate)
        if kept:
            print(f"gate {gate}: the person's answer is already kept ({len(str(kept['words']))} characters) - "
                  "nothing is repaired under it; the decision is recorded again with those words")
            self.gate_refusal = ""
            # H4: the mark that made the kept words an approval (`option`: the person chose it; `token`: the approval word) travels with them
            marks = {"approved_by": kept["approved_by"]} if kept.get("approved_by") else {}
            if kept.get("apply"):                    # a second answer's decision: its card lines are the new answer's alone (t-891 F-2)
                marks["apply_words"] = str(kept["apply"])
            if self.record_by_code(f"gate_{gate}", GATE_STAGE_OF.get(gate, ""), str(kept["words"]), again=True, **marks):
                self.save_state()
                shown["ran"] = True
                return shown
            # t-214 C3 (FR-7): the gate is asked again, but never with the SAME packet: the person is told their
            # words are kept, which they were, and why they did not record - the controller's refusal verbatim.
            return dict(shown, top=self.kept_answer_text(kept))

        if gate == "A" and self.apply_question_answers("A")["opened"]:
            # HF2-7 (M5, H28): an answer recorded after the last stop reaches the plan HERE, before the rehearsal reads it. POSITION
            # INVARIANT: after the open-packet return (iii) and the kept-answer branch (iv) - a packet the person is reading, or an answer
            # already given, never sees the plan move (F-13) - and before `gate_entry_steps` and the rehearsal. A rework that is owed
            # ends the call as a repair round does: the loop goes back to `where`, the step runs it, the gate is rehearsed again.
            return dict(shown, ran=True)
        if gate == "A":
            # t-2142 PK0-3 (AR-21, AR-28): a role the strategist named that the project does not know yet is recorded as noticed, not
            # confirmed. POSITION INVARIANT: after the open-packet return (iii) and the kept-answer returns (iv) - nothing is written
            # once the person has spoken - and before the rehearsal that builds the packet, which shows the noticed rows. Never raises.
            try:
                import project_knowledge
                project_knowledge.notice_from_handoff(self.project, self.task_root, str(self.pipeline().get("ticket") or self.task))
            except Exception as exc:
                print(f"project_knowledge: noticed roles were not recorded ({type(exc).__name__}: {str(exc)[:120]})", file=sys.stderr)
        self.gate_entry_steps(gate)
        try:
            result = self.rehearse(gate)
            findings = result.get("findings") if isinstance(result, dict) else None
            if not isinstance(findings, list):
                raise ValueError("the rehearsal's `findings` is not a list")
        except Exception as exc:
            print(f"gate {gate} rehearsal could not run ({type(exc).__name__}: {' '.join(str(exc).split())[:160]}); "
                  "the gate is shown without it")
            return shown
        fixable = self.fixable_findings(findings)
        if not fixable:
            print(f"gate {gate} rehearsal: nothing the factory has to repair — the gate is shown")
            return shown
        series, stage = self.gate_series(gate), GATE_STAGE_OF.get(gate, "")
        rounds, keys = series["rounds"], self.key_set(fixable)
        if any(isinstance(r, dict) and r.get("stop") for r in rounds):
            # B-416 N4: a series that has stopped only LISTS what is left - but a test report the conductor has not had its turn for is
            # handed over ONCE (the driver's own row after the call ends the bound); the person's card follows the next rehearsal.
            unread = self.unadapted_reporters(fixable)
            if unread:
                print(f"gate {gate} repair: the series has stopped, but {len(unread)} test report(s) the code could not read have not "
                      "had the helper's turn - handed to the conductor once")
                return self.hand_to_conductor(gate, stage, "a test report the code could not read", unread, [], "", fixable)
            # C6: once a series has stopped, whatever its key set the gate is shown with the list (the bound
            # does not depend on `conductor_calls`, which lives in memory and is reset by a relaunch).
            print(f"gate {gate} repair: the series has stopped — the gate is shown with {len(fixable)} thing(s) "
                  "the factory could not repair stated at its top")
            return dict(shown, top=self.unrepaired_text(gate, fixable))
        spent = self.attempted_rounds(rounds)
        plan, direct = self.repair_plan(gate, fixable, rounds)
        same = next((i for i, r in enumerate(spent) if r.get("keys") == keys), None)
        if same is not None:
            reason = "same_set"
        elif len(spent) >= GATE_REPAIR_CAP:
            reason = "cap"
        elif not plan:
            reason = "no_move"
        else:
            reason = ""
        if reason:
            return self.gate_stop(gate, series, stage, fixable, direct, keys, reason, same)
        number = len(spent) + 1
        print(f"gate {gate} rehearsal: {len(fixable)} thing(s) the factory repairs before anyone is asked "
              f"({self.finding_counts(fixable)}) — repair round {number} of {GATE_REPAIR_CAP}")
        before = list(rounds)       # what the preconditions count: this round is not spent yet
        record = {"at": _now(), "keys": keys, "moves": [], "outcome": "started", "stop": ""}
        self.record_round(gate, series, record)
        # The plan was made BEFORE the first move; each precondition is read again at its turn, because the
        # moves before it change what it reads (the re-pin makes the reworked cases pinned, which the
        # critic's scope is cut by).
        for precondition, move, mine, _planned in plan:
            found = getattr(self, precondition)(gate, mine, pin_planned=False, rounds=before)
            if not found or found.get("direct"):
                continue
            try:
                getattr(self, move)(gate, mine, found, record)
            except RepairFailed as failure:
                # A failed repair is never silent and never repeated blindly: it is printed, recorded as the
                # round's outcome (the series stops), and the conductor gets the command and the last 20
                # lines of its output.
                code = re.search(r"\(exit (\d+)\)", failure.text)
                what = f"{failure.what} failed" + (f" (exit {code.group(1)})" if code else "")
                print(f"gate {gate} repair: {what} — its output goes to the conductor")
                record.update(outcome="failed", stop="failed")
                self.record_round(gate, series, record)
                tried = (f"{what}; the last lines of its output:\n"
                         + "\n".join(failure.text.splitlines()[-20:]))
                rest = [f for f in fixable if f not in direct]
                return self.hand_to_conductor(gate, stage, "a repair command failed", rest, direct, tried, fixable)
        rest = [f for f in fixable if f not in direct]
        if not record["moves"]:
            # every precondition that held at planning time no longer held at its turn: nothing was done
            record.update(outcome="to_conductor" if rest else "shown", stop="no_move")
            self.record_round(gate, series, record)
            return self.hand_to_conductor(gate, stage, "no code move applied when its turn came", rest, direct,
                                          "", fixable)
        record["outcome"] = "repaired"
        self.record_round(gate, series, record)
        # t-214 C2: the moves changed what the stage's closing step rendered (the case appendix embeds the
        # pinned cases; the report block follows the facts), so the next gate entry renders it again, AFTER them.
        self.state.setdefault("gate_entry_owed", {})[stage] = _now()
        self.save_state()
        shown["ran"] = True
        return shown

    def gate_stop(self, gate: str, series: dict, stage: str, fixable: list, direct: list, keys: list,
                  reason: str, same) -> dict:
        """The series stops (F4, C12): the stop is a record of its own, with its reason; what is not `direct`
        goes to the conductor ONCE (a following await_gate shows the gate: C6); what is `direct` is only listed."""
        rest = [f for f in fixable if f not in direct]
        spent = self.attempted_rounds(series["rounds"])
        if reason == "same_set":
            print(f"gate {gate} repair: round {len(spent)} left the same {len(fixable)} thing(s) as round "
                  f"{same + 1} — the list goes to the conductor; no further round")
            why = f"round {len(spent)} left the same findings as round {same + 1}"
        elif reason == "cap":
            print(f"gate {gate} repair: the cap of {GATE_REPAIR_CAP} rounds is spent with {len(fixable)} thing(s) "
                  "left — the list goes to the conductor; no further round")
            why = f"the cap of {GATE_REPAIR_CAP} repair rounds is spent"
        else:
            print(f"gate {gate} repair: {len(fixable)} thing(s) no code move repairs — "
                  + ("the list goes to the conductor" if rest else "the gate is shown with them at its top"))
            why = "no code move applies to them"
        tried = "; ".join(f"round {i}: " + (", ".join(r.get("moves") or []) or "no move") + f" ({r.get('outcome')})"
                          for i, r in enumerate(spent, 1))
        record = {"at": _now(), "keys": keys, "moves": [], "outcome": "to_conductor" if rest else "shown",
                  "stop": reason}
        self.record_round(gate, series, record)
        return self.hand_to_conductor(gate, stage, why, rest, direct, tried, fixable)

    def hand_to_conductor(self, gate: str, stage: str, why: str, rest: list, direct: list, tried: str,
                          fixable: list) -> dict:
        """The list goes to the conductor through `conductor_round` - the call an unmatched refusal gets - and
        NOT through `handle_refusal`: that matches its table anywhere in the text, and a finding that holds
        `already completed` or `expected_revision` would turn into `continue` or `retry`. Nothing for the
        conductor (only `direct` findings): the gate is shown, with them stated at its top."""
        if not rest:
            return {"ran": False, "top": self.unrepaired_text(gate, fixable)}
        self.boundary = f"gate_{gate}"
        try:
            self.conductor_round(Refusal(self.conductor_text(gate, why, rest, tried)), stage)
        finally:
            self.close_reporter_bound(rest)       # B-416 N4: the bound is the CALL - it runs whatever the conductor did or raised
        return {"ran": True, "top": ""}

    def unadapted_reporters(self, fixable: list) -> list:
        """The `s5_reporter` findings of a list that have NO countable row of the helper's yet (B-416 N4): the test reports the conductor has
        not had its one turn for. A finding whose bound could not be recorded (`adapt_handed`) is left to the top of the gate, never handed
        again and again."""
        import report_adapt
        stuck = set(self.state.get("adapt_handed") or [])
        return [f for f in fixable if f.get("check") == "s5_reporter" and f.get("profile") and f.get("argv_digest")
                and f"{f['profile']}|{f['argv_digest']}" not in stuck
                and report_adapt.countable(self.project, str(f["profile"]), str(f["argv_digest"]))["state"] == "none"]

    def close_reporter_bound(self, findings: list) -> None:
        """B-416 N4 (G5, G10): after the conductor's turn, an `s5_reporter` finding with still no countable row gets the driver's own
        `not_adapted` row (`by: driver`, "the helper was called and recorded nothing"), so the NEXT rehearsal cards the person - exactly one
        conductor call per command since its last proof, whatever the conductor wrote, hit or did not. A row the conductor did write
        (`kind`, `understood`) is left alone; an unreadable record reads as a row (FR-59) and gets none. A failed append is printed and
        remembered (`adapt_handed`): it is not tried again and the finding stays at the top of the gate. Never raises."""
        try:
            import report_adapt
            for finding in [f for f in findings if f.get("check") == "s5_reporter" and f.get("profile") and f.get("argv_digest")]:
                profile, digest = str(finding["profile"]), str(finding["argv_digest"])
                key = f"{profile}|{digest}"
                if report_adapt.countable(self.project, profile, digest)["state"] != "none":
                    self.state["adapt_handed"] = [k for k in self.state.get("adapt_handed") or [] if k != key]
                    continue
                row, problem = report_adapt.append(self.project, {"kind": "not_adapted", "by": "driver", "profile_id": profile,
                                                                  "argv_digest": digest, "story": self.task,
                                                                  "understood": report_adapt.NOT_CALLED_TEXT})
                if row is None:
                    print(f"gate repair: the helper's turn for `{profile}` could not be recorded ({problem}); the report stays at the top of the gate")
                    self.state["adapt_handed"] = list(dict.fromkeys(list(self.state.get("adapt_handed") or []) + [key]))
                else:
                    print(f"gate repair: the helper recorded nothing for `{profile}`: {row['id']} - the person is asked about it at the gate")
            self.save_state()
        except Exception as exc:
            print(f"gate repair: the helper's turn could not be closed ({type(exc).__name__}: {' '.join(str(exc).split())[:120]})")

    def gate_repair_would(self, gate: str) -> str:
        """`--dry-run`: what the step would do, from the rehearsal alone. Writes nothing and dispatches
        nothing; preconditions that read the controller are not evaluated (they are read at their turn)."""
        try:
            result = self.rehearse(gate)
            findings = result.get("findings") if isinstance(result, dict) else None
            if not isinstance(findings, list):
                raise ValueError("the rehearsal's `findings` is not a list")
        except Exception as exc:
            return (f"would: rehearse gate {gate}, which could not run now ({type(exc).__name__}: "
                    f"{' '.join(str(exc).split())[:120]}); the gate would be shown without it")
        fixable = self.fixable_findings(findings)
        if not fixable:
            return f"would: rehearse gate {gate}, then show the gate: nothing the factory has to repair"
        moves = []
        for row_gate, check, _pre, move in GATE_REPAIRS:
            if row_gate == gate and any(f["check"] == check for f in fixable):
                moves.append(f"{check}: {move.replace('_', ' ')}")
        left = sorted({f["check"] for f in fixable} - {check for g, check, _p, _m in GATE_REPAIRS if g == gate})
        if left:
            moves.append("to the conductor or the top of the gate: " + ", ".join(left))
        return (f"would: rehearse gate {gate}, then repair: " + "; ".join(moves)
                + f" (at most {GATE_REPAIR_CAP} rounds)")

    def gate_approval(self, kind: str, words: str) -> bool:
        """Is this answer the gate's APPROVAL WORD? Its first non-empty line, read with the one normalizer (`s0_normalize`: BOM, quotes,
        one full stop, case and spaces only), equals a word of `gate_brief.approval_words(gate)` read the same way. Never a phrase
        (FR-12): `approve, but fix the export test`, `I approve`, `approved`, `do not approve`, a first line that is a code fence, or the
        word on a later line are NOT approvals. The allowed error is not approving (the words go to the conductor); the forbidden one is
        approving words that are not the word. An unreadable word list approves nothing (FR-59). The rest of the answer is not read here:
        the cards of gate A and the stand-gap lines are read by their own readers, and the words are kept whole by the decision."""
        if kind not in GATE_KINDS:
            return False
        import gate_brief
        wanted = {self.s0_normalize(word) for word in gate_brief.approval_words(kind[-1])} - {""}
        if not wanted:
            if not getattr(self, "_approval_words_reported", False):      # ONE defect per process: every gate answer meets this
                self._approval_words_reported = True
                self.file_defect(self.boundary, "owner: factory — the approval words of the gates could not be read "
                                                "(references/gate-approval-words.json): no gate is recorded by code, every gate "
                                                "answer goes to the conductor")
            return False
        return self.first_line(words) in wanted

    def gate_lines_over_approval(self, kind: str, words: str, stand: dict, asked_unread) -> bool:
        """GW1-33: may the gate's approval be put to the controller although `stand["unread"]` holds lines nobody could read? Yes
        exactly when the gate is A (only gate A's controller call refuses an approval over an open item: `open_gate_items` returns
        nothing for gate B), the answer IS the approval (`gate_approval`), there is such a line, none of them is held for the
        conductor (`stand["hold"]`: a record the story REFUSED, an `ask again`, a line with `?` - understood but not carried out, or
        a question, never consent) and none is the exploratory reader's (`asked_unread`: a `bug` beside `approve` is a
        contradiction the conductor resolves, FR-12; on gate A this is always empty - kept for a word about gate B). The allowed
        error is NOT recording: this only lets the caller ASK the controller, which refuses an approval over an item still open,
        and then the whole answer stays kept for the conductor (`_unread_kept_gate`). An unread line removes no item."""
        return bool(kind == "gate_A" and self.gate_approval(kind, words) and isinstance(stand, dict)
                    and stand.get("unread") and not stand.get("hold") and not asked_unread)

    def first_line(self, words) -> str:
        """The first non-empty line of an answer, read with the one normalizer (`s0_normalize`) - THE one reader of "the word the person
        said" for `gate_approval` and `as_is_word` (M4, AR-13)."""
        first = next((line for line in str(words or "").replace(self.BOM, "").splitlines() if line.strip()), "")
        return self.s0_normalize(first)

    def as_is_word(self, kind: str, words: str) -> bool:
        """Is this answer a gate's `approve as is`? The same first-line reading as `gate_approval` (`first_line`), against
        `gate_brief.as_is_words(gate)` - the words whose data row says `passes_open_items`. False for gate B (no such row) and for
        an unreadable list (FR-59). Never a phrase (FR-12): `approve as is, but fix X` is not the word and goes to the conductor."""
        if kind not in GATE_KINDS:
            return False
        import gate_brief
        wanted = {self.s0_normalize(word) for word in gate_brief.as_is_words(kind[-1])} - {""}
        return bool(wanted) and self.first_line(words) in wanted

    @staticmethod
    def gate_refusal_parts(refusal_text):
        """`(the factory's own sentences, the items' sentences)` of a gate decision's refusal, each a whitespace-normalised list. The
        controller marks where the items' sentences start (`item_problems_from`); a record without the mark (an older controller) holds
        no factory sentence in front of the items. Nothing is sliced by a count of items."""
        doc, _ = json_record(str(refusal_text or ""))
        problems = [" ".join(str(p).split()) for p in (doc.get("problems") or []) if str(p).strip()] if isinstance(doc, dict) else []
        start = doc.get("item_problems_from") if isinstance(doc, dict) else 0
        start = start if isinstance(start, int) and not isinstance(start, bool) and 0 <= start <= len(problems) else 0
        return problems[:start], problems[start:]

    @staticmethod
    def gate_open_items(refusal_text):
        """The open items a gate decision's refusal carries (`open_items` of the controller's `{"recorded": false, ...}` record), as a
        list of dicts; None when the text holds no such record or no list under that key (unreadable - the caller names no owner,
        FR-41). Read by FIELD from the one JSON reader (`json_record`, AR-13/axis 16), the first object in the joined stdout and
        stderr: a line the controller printed before it does not hide it."""
        doc, _ = json_record(str(refusal_text or ""))
        items = doc.get("open_items") if isinstance(doc, dict) else None
        if not isinstance(items, list) or not all(isinstance(i, dict) and str(i.get("id") or "").strip() for i in items):
            return None
        return items

    def open_items_text(self, items: list, words: str, factory=()) -> str:
        """What the conductor is handed over a kept approval that waits for the person's word on open items (RH1-6, A-AC5): that the
        approval word was HEARD and kept - the refusal is the items', not a mistake of the answer - every item with its id, message and
        what it needs, the RECORDING COMMAND for each item the conductor can read (a `line` or `words` block; the file holds
        `accept - the person wrote: <their words>`, the form `_record_door_lines` writes, so the first word is the option), `approve as
        is` for one it cannot name a block for, and the person's whole words. `factory`: the factory's own sentences of the same refusal
        (`gate_refusal_parts`) - listed under their own owner, and `approve as is` is then not offered (the controller skips it while
        they stand)."""
        import gate_brief
        as_is = "" if factory else gate_brief.as_is_word_of("A")
        out = ["The person's approval word was heard and kept. The factory records a gate A approval only over items the person has "
               "worded, and these items have no recorded word, so nothing is recorded as approved yet. Their words, whole:",
               "", str(words or "").strip() or "(empty)", ""]
        if factory:
            out += ["The factory's own problems, not the person's to word (they stand first, and no word of the person passes them):"]
            out += [f"- {line}" for line in factory] + [""]
        out += [f"Open items ({len(items)}):"]
        for item in items:
            door = item.get("door") if isinstance(item.get("door"), dict) else {}
            out.append(f"- [{item.get('id')}] {' '.join(str(item.get('message') or '').split())} - needs: {door.get('says') or 'their word'}")
            if door.get("kind") in ("line", "words") and str(door.get("block") or "").strip():
                command = person_words.door(f"python {self.scripts / 'waiver.py'} --task {self.task} --stage {door.get('stage') or 'S5'} "
                                            f"--block \"{door['block']}\"")
                out.append(f"  record their word on it: {command}  (the file starts `accept - the person wrote: ` and holds their words "
                           "about this item; `run` instead of `accept` when they said they will run it themselves, if the item offers that)")
            else:
                out.append("  no block can be named for it: " + (f"only the person's `{as_is}` passes it" if as_is
                                                                  else "ask the person for their word on it, in a closed question"))
        out += ["", "When every item has a word, the kept approval records on its own. If their words are not about an item, ask a "
                "closed question for it (references/human-questions.md); never record `--block \"*\"` for these items."]
        return "\n".join(out)

    def report_attribution(self, gate: str, words: str) -> dict:
        """Which items of the gate packet the answer names, and which it does not — printed.

        P3's second half. The decision keeps the whole answer, and that is not the same as
        knowing what it settled: on TP1-15045 the six readings the person signed lived in
        `stage_overrides[]` and nothing checked that each item of the packet had a record. It
        worked because the wordings happened to match the cards. What is not named is printed as
        not named — never dropped, and never read as settled (FR-41).
        """
        try:
            import gate_brief
            items = gate_brief.packet_items(self.task_root, gate)
            said = gate_brief.attribute(items, words)
        except Exception as exc:                         # pragma: no cover - a broken checkout
            print(f"gate {gate}: the answer could not be read against the packet "
                  f"({type(exc).__name__}: {exc})")
            return {}
        if said["named"]:
            print(f"gate {gate}: their answer names {', '.join(said['named'])}")
        if said["not_named"]:
            print(f"gate {gate}: NOT named in their answer, so nothing here is settled by it: "
                  + ", ".join(said["not_named"][:20]))
        self.answer_row(f"gate {gate} decision recorded with {len(words)} characters; items "
                        f"named: {', '.join(said['named']) or 'none'}; not named: "
                        f"{', '.join(said['not_named']) or 'none'}", "", what=f"the note of your gate {gate} decision", extra=("--by", "driver"))
        return said

    def gate_question_lines_note(self, words: str) -> str:
        """GW1-34: the note for the conductor when the gate A words hold a line about an open register question that no reader
        understood, or when the register cannot be read (an unknown is never a pass, FR-59); "" when there is none."""
        import question_register as QR
        self.question_lines_shown = ""
        tail = "the lines about its questions were not checked, so the approval is not recorded."
        try:
            view = QR.load(self.task_root)
        except Exception as exc:                 # F6: `load` can raise; not knowing is the conductor's, the driver does not stop (FR-59)
            return f"\n\nThe question register could not be read ({type(exc).__name__}: {exc}); {tail}"
        if view["skipped"]["unreadable_file"] or (view["problems"] and not view["questions"]):
            why = (view["problems"] or ["the answers file could not be read"])[0]
            return f"\n\nThe question register could not be read ({why}); {tail}"
        lines = QR.question_lines_unread(words, view["questions"])
        if not lines:
            return ""
        shown = "; ".join(f"{item['id']}: \"{item['line']}\"" for item in lines)
        self.question_lines_shown = shown        # F4: the person's text for these lines (no commands), read by `kept_answer_text`
        # GW1-42: a line that seems to answer with one letter (`Q1: a (see the ticket)`) is named with that letter, so the closed question
        # to the person is `confirm Q1 - a?`; the letter is a hint, the code records nothing (FR-12). A line cut for display is not read.
        letters = {q["id"]: q.get("letters") for q in view["questions"] if isinstance(q, dict)}
        near = []
        for item in lines:
            found = QR._TOKEN.fullmatch(item["line"])
            letter = None if item["line"].endswith("...") or not found else QR.near_answer(found.group("value"), letters.get(item["id"]))
            if letter:
                near.append(f"{item['id']} - {letter}")
        hint = (" Seems to answer with one letter: " + "; ".join(near) + ". Ask the person \"confirm "
                + "?\" / \"confirm ".join(near) + "?\" as a closed question; record the letter only on their yes.") if near else ""
        return ("\n\nLines about questions the code could not read: " + shown + "." + hint + " Record each with `question_register.py --answer <id> "
                "--reading <letter>` (ask the person a closed question where the words are unclear) or keep it open (`--defer`), then the "
                "kept approval records.")

    def record_by_code(self, kind: str, stage: str, words: str, again: bool = False, approved_by: str = "", apply_words: str = "") -> bool:
        """The person's words, put on the record by the command the boundary already implies.

        A GATE is recorded here only as an approval (C1-4b, I1): `approved_by == "option"` (the person chose `approve` from the
        seam's own options; `words` are the original answer's) or `approved_by == "token"` (the answer was read as the approval word
        when it was kept, `gate_approval`), or the words themselves are the gate's approval word (`gate_approval`). Any other words
        return False before anything is applied or written - the position invariant: nothing at a gate is stamped as an approval
        that is not one, whichever caller (`take_answer`, the kept road of `gate_repair`) comes here.

        Each gate A answer is recorded against the fingerprint its card carried in the packet the person was
        shown (`shown_packet`, `gate_brief.shown_hashes`), so a row that changed between the card and the answer
        reads `changed_since_answer`.

        TP1-13797, 26.09: of seventeen conductor calls, six were exactly this — running
        `waiver.py --remark`, `accept-gap` or `story_step finish` with words the driver was
        already holding ($3.18), and seven more ended `ask_person` with an empty `did` ($6.05).
        The conductor is a helper for a problem; a recording is not a problem. A gate keeps the
        whole answer, not its first sentence: `authorization_source` came out 215 characters long
        while the readings the person signed lived only in stage overrides.

        `apply_words` (t-891 F-2): the part of `words` the card lines are read from ("" = all of `words`). A second answer at a gate
        carries the earlier one as a tail of `words` (the decision keeps both); the plan takes the NEW answer's lines alone, so a
        correction `Q5: a` after `Q5: b` applies `a` and is no conflict for `parse_choices`."""
        if kind in ("gate_A", "gate_B"):
            gate = kind[-1]
            if approved_by not in ("option", "token") and not self.gate_approval(kind, words):
                return False
            # GW1-34: the decision SEALS the plan, so a line about a register question that no reader understood (`Q1:`, `Q1: a (note)`)
            # is read BEFORE it is recorded - by the conductor, who asks the person a closed question where the words are unclear. The
            # code never guesses the letter. Position invariant: after `gate_approval` (only an approval gets here) and before the
            # controller call (nothing is recorded); `approve as is` (the person's words are stronger) and a dry run do not return.
            self.question_lines_note = ""
            self.gate_refusal = ""               # F5: an older refusal gives no items to this call
            if gate == "A" and not self.dry and not self.as_is_word(kind, words):
                self.question_lines_note = self.gate_question_lines_note(apply_words or words)
                if self.question_lines_note:
                    print(f"gate {gate}: lines about questions the code could not read; the conductor takes the answer")
                    return False
            # DC1-19: what the person's answers DECIDE is recorded and applied by the ONE executor, `controller.py --operation
            # gate-decision`, the same call the conductor makes (AR-15): gate A lays them over the plan BEFORE the decision is built,
            # gate B records them and touches no plan. This call hands over what only the driver holds, BY FILE: the NEW answer's lines
            # without the earlier answer it keeps (`apply_words`; a correction `Q5: a` after `Q5: b` is no conflict), the stand gaps
            # the person ACCEPTED, a LEVEL accept's remedy per case, and the card hashes the person was shown (t-279 F5).
            # A dry run records no answer (`--no-answers`). The controller's answer is printed (P1).
            try:
                import gate_brief
                shown = gate_brief.shown_hashes(self.shown_packet(kind))
            except Exception:                    # a broken checkout: the answers are still recorded, unfingerprinted
                shown = {}
            # t-364: a stand gap the person ACCEPTED at this gate (`<case id>: accept`, read by `take_stand_gap_answers`) is handed to
            # the executor in its own token, so the waiver and the `blocked_by_env` row are two records of ONE read line; a token the
            # person wrote themselves is not repeated
            lines = apply_words or words
            accepted = [] if gate != "A" else [case for case in self.state.get("stand_accept_cases") or []
                                               if not re.search(r"^\s*(?:[-*•]\s+)?`?" + re.escape(case) + r"`?\s*:\s*accept as blocked",
                                                                lines, re.IGNORECASE | re.MULTILINE)]
            # B-414 F19 (a): a LEVEL accept blocks each of its cases by the level gap's own remedy (`{case: remedy}`) - the
            # executor's `_stand_remedy` derives one from the case's own preconditions and blocks nothing for a case
            # whose preconditions are all met. REACH (M6 iv): `acceptance.blocked_instances` blocks a row that names no
            # instance only for a single-instance case whose instance proves no other case; a test proving two level-
            # accepted cases is skipped silently (`outside`), and a multi-instance case is refused to the automator.
            remedies = (self.state.get("stand_accept_remedies") or {}) if gate == "A" else {}
            answer_args = ["--no-answers"] if self.dry else [
                "--answers-by", "driver",
                *(["--answers-file", str(self.words_file(lines + "".join(f"\n{case}: accept as blocked" for case in accepted), f"answers{gate}"))]
                  if lines.strip() else []),
                *(["--shown-file", str(self.json_file(shown, f"shown{gate}"))] if shown else []),
                *(["--remedies-file", str(self.json_file(remedies, f"remedies{gate}"))] if remedies else [])]
            # RH1-6: `approve as is` (a closed data word of gate A, `gate_brief.as_is_words`) is declared to the controller by a flag; the
            # controller then records one waiver per open item with these words (never `*`) before the decision. Any other approval
            # records only over items the person has already worded.
            code, out = self.py("controller.py", "--task-root", str(self.task_root),
                                "--operation", "gate-decision", "--gate", gate,
                                *(["--as-is"] if self.as_is_word(kind, words) else []),
                                # gate B: the bug reporter runs on the person's words even with no draft chosen (13797), so the
                                # driver's decision orders it (`--bugs ordered`, t-1509 GB-1b); gate A has no orders
                                *(["--bugs", "ordered"] if gate == "B" else []),
                                *answer_args, *self.words_args(words, f"gate{gate}"))
            self.gate_answer_told(gate, out)
            if code:
                self.gate_refusal = out
                # `again`: the words are already kept (`gate_repair`, C3) and the conductor has had them once.
                print(f"gate {gate}: the decision did not record by code ({out[-200:]}); "
                      + ("the gate is shown again" if again else "the conductor takes it"))
                return False
            # B3: the stand-gap state is consumed only by a call that RECORDED. A refused call applied none of the tokens and the kept
            # road re-sends only the person's words, so what `take_stand_gap_answers` read from them must still be here
            if not self.dry:
                self.state.pop("stand_accept_cases", None)
                self.state.pop("stand_accept_remedies", None)
            print(f"gate {gate}: recorded by code, {len(words)} characters of the person's own words")
            # t-211: this gate's series of repair rounds and the kept answer are over with its decision.
            self.state.pop("gate_answer_kept", None)
            if isinstance(self.state.get("gate_repair"), dict):
                self.state["gate_repair"].pop(gate, None)
            self.report_attribution(gate, words)
            return True
        # Everything else — a block lifted, a contract changed, a dead dispatch released — is a
        # judgement about WHICH block the words pass, and that is what the conductor is for.
        return False

    def keep_shown_exploratory(self) -> str:
        """Gate B is being shown: keep the question lines of the findings it shows (`state["shown_exploratory"]`, from the function
        that renders them), so an answer is read against what the person SAW (a line corrected since is unread, never answered).
        Returns the sentence for the top of the packet when a question the person left `open` at their last answer is asked again
        (FR-7: the same boundary is not re-asked with the same text); "" otherwise. Never raises: no map, no answer read by code."""
        try:
            import gate_brief
            shown = gate_brief.exploratory_shown(self.task_root)
        except Exception:
            shown = []
        self.state["shown_exploratory"] = shown
        left = self.state.get("exploratory_open")
        ids = {s["line"] for s in shown}
        kept = {line: case for line, case in (left if isinstance(left, dict) else {}).items() if line in ids}
        self.state["exploratory_open"] = kept
        cases = sorted({case for case in kept.values() if case})
        return ("Still open from your last answer: " + ", ".join(cases) + " - you left "
                + ("it" if len(cases) == 1 else "them") + " open, nothing was recorded for "
                + ("it" if len(cases) == 1 else "them") + ", so the question is asked again.") if cases else ""
