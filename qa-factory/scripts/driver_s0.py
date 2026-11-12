"""driver_s0.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import adapter_forms as AF
import no_move as NM
import person_words
import ticket_light as TL
from driver_core import DriverCore, Person, Refusal, _append_jsonl, _now, _read_answer, _read_json, _write_json, gate_refusal, json_record
from driver_dialog import question_body_sha


# The three answers `phases/s0.md` section 2b gives for a ticket whose requirements moved while the story waited, word
# for word (test_story_run_freshness_k15_k26.py holds this string against that file: the prose twin is not copied by hand and
# left to drift). They are put to the person as they are (an en dash and middle dots, as in that file).
# TICKET_CHANGED_TOKENS are the words the person answers with: the factory's own fixed words for ONE
# question, never variety across projects (FR-13: the precedent is the `package` tokens and S0_DOOR_WORDS), and the
# code reads a token, never a meaning (FR-12).
TICKET_CHANGED_OPTIONS = ("re-run S2–S3 against the new text · continue on the old text with that stated "
                          "as a known gap · stop here.")

TICKET_CHANGED_TOKENS = ("new text", "old text", "stop")


class DriverS0:
    # --- S0: the story's one ticket snapshot, and a door on every stop (t-017 D1) ------------

    #
    # B-008 / FR-49. The snapshot is `work/ticket-snapshot.json`: the stdout of
    # `ticket_adapter get <T> [--ticket-file F] --json`, byte for byte, and nothing else (t-267: but for the
    # `disagreements[]` a person's text carries when the tracker was read beside it, `s0_compare`). It used
    # to be written as `.md` from the glued stdout+stderr of that call, while the scout's brief
    # (`brief_pack`) names `.json` - so the brief never carried the snapshot the story was
    # built on, and a warning on stderr ended up inside the file.
    #
    # B-004 / FR-4. Every stop S0 raises used to promise "answer `go on`" and then never read
    # the answer: `take_answer` sent it to a conductor that could not act on it (there is no
    # pipeline.json for `waiver.py` to write into), and S0 met the same block again. Now an
    # answer is stored, the step is entered again, and s0 reads it (`s0_read_word`): only the
    # tokens the stop itself offered, or a configured stand's name, or a pasted ticket. Anything
    # else comes back as a question with a CHANGED body (FR-7); nobody parses the person's
    # wording (FR-12) and no conductor is called for it (FR-48).
    SNAPSHOT = "ticket-snapshot.json"

    QUOTE_LIMIT = 300

    # What a pass is called in the story's own record: the pipeline warning gate A shows.
    S0_PASS_NAMES = {"ticket_incomplete": "the criteria-reading check", "ticket_title": "the ticket-title check",
                     "stand": "the stand question", "readiness": "the readiness check",
                     "source_list": "the list of sources not to read", "key_form": "the ticket key form check"}

    # Any non-empty text is taken and the ticket reader decides what it found (t-267 C9: the old check
    # of the exact shape was a phrase list, FR-12). The shape below is what lets the reader find the
    # criteria and the comments; the header between the dashes is welcome and not required. The text is
    # read by the same parser as a description fetched from the tracker (t-281 F1): a section named like the
    # criteria, then a list - any bullet or number.
    PASTE_SHAPE = ("paste the ticket here as text: the title on the first line (a line that starts with `# ` is "
                   "taken as the title wherever it stands), then the description, then a section named "
                   "`Acceptance criteria` with a list - bullets or numbers - and then a `## Comments` section "
                   "with one line per comment as `- **author** (date): text`, if the ticket has any; a header "
                   "between two lines of three dashes (key, type, status, parent) is welcome and not required")

    # The one reality word of a side that code reads as "real" (t-2181 PC-2): it must be in `references/side-realities.json`
    # `realities` (test_no_mr_entry.py pins it). QUEUE: fold it into `contract` beside `PARKING_REALITY` once PC-3 is closed to it.
    SIDE_REAL = "real"

    # The paste door of every S0 question that takes the ticket as text: ONE definition (t-684 F6). It has no token - the text
    # itself is the answer (`s0_is_text`) - and its price row is `paste`.
    PASTE_OPTION = {"answer": "paste", "says": f"{PASTE_SHAPE} - I use that instead", "slots": {"what": "paste the ticket"}}

    # The words every S0 stop takes as a door (the tokens of its blocks, see `s0_stop`): a one-word answer that
    # is one of them is the person's word to a stop, never a ticket (a `go on` pasted into `ticket_read`).
    S0_DOOR_WORDS = ("go on", "retry", "not needed", "read", "skip", "mr", "branch", "commit", "no ticket", "current code", "change",
                     "ungrounded", "not built yet", "ours", "another team's", "stop")

    @staticmethod
    def json_object(text: str):
        """The JSON object in `text`, or None - a list, a scalar and prose are not a ticket."""
        try:
            data = json.loads(text)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def ticket_get(self, *extra, echo: bool = True) -> tuple:
        """`ticket_adapter get <T> <extra> --json`: (exit code, stdout, ticket or None, what it said, failure).

        Exit 0 with a stdout that is not one JSON object is a refusal that names the call and the
        head of what it printed, and nothing is written: a snapshot of prose would be read as a
        ticket by every stage after it. It is never a halt for the person (nothing they could
        answer would mend an adapter that printed something else). `echo=False`: the adapter's
        stderr is not printed (the comparison read says its own ONE line, `s0_compare`).

        A non-zero exit carries `failure`, the adapter's error OBJECT (`ticket_failure`): the owner decides the
        move and `retry_at` is read from it, not from the sentence. "What it said" is then the human sentence
        on stderr (the object is its own carrier)."""
        code, out, err = self.py_stdout("ticket_adapter.py", "get", self.task, *extra, "--json", echo=echo)
        both = (out + ("\n" + err if err.strip() else "")).strip()
        ticket = self.json_object(out) if code == 0 else None
        if code == 0 and ticket is None:
            raise Refusal(f"ticket_adapter get {self.task} {' '.join(str(e) for e in extra)} --json "
                          f"exited 0 but printed no JSON object, so no ticket snapshot was written. "
                          f"Expected: the ticket as one JSON object on stdout. It began: "
                          f"{out.strip()[:300]!r}")
        failure = None
        if code:
            failure = self.ticket_failure(code, out, err)
            if failure["from_object"]:
                both = err.strip() or failure["message"]
        return code, out, ticket, both, failure

    NO_ERROR_OBJECT = "the adapter printed no error object"

    def ticket_failure(self, code: int, out: str, err: str) -> dict:
        """The failure of a `ticket_adapter get --json` as `{owner, status, retry_at, message, file, from_object}`.
        The adapter prints ONE error object on stdout on any non-zero exit (FR-14: the machine carrier, so no
        sentence is matched). Exit 5 is auth whatever stdout holds. An exit with no readable object (an older
        adapter, a crash before it printed) is the FACTORY's: it says so in words and is never a question - a
        question to the person cannot mend an adapter that printed something else (FR-3).
        The owner words an object may carry are the adapter's own list, `ticket_adapter.OWNERS` (t-329 item 6: a
        literal copy here had four of the five, so the adapter's `person` - a ticket or paste file that is missing or
        empty - read as "no error object" and turned the person's own missing file into a factory refusal)."""
        import ticket_adapter
        obj = self.json_object(out)
        if obj is not None and obj.get("ok") is False and obj.get("owner") in ticket_adapter.OWNERS:
            return {"owner": obj["owner"], "status": obj.get("status"), "retry_at": obj.get("retry_at") or None,
                    "message": " ".join(str(obj.get("message") or "").split()), "file": obj.get("file") or None,
                    "from_object": True}
        if code == ticket_adapter.EXIT_AUTH_LOST:
            return {"owner": "auth", "status": None, "retry_at": None, "message": " ".join(str(err or "").split()),
                    "file": None, "from_object": False}
        return {"owner": "factory", "status": None, "retry_at": None, "message": self.NO_ERROR_OBJECT,
                "file": None, "from_object": False}

    def ticket_is_factory_fault(self, code: int, failure: dict | None) -> bool:
        """Exit 4, or an object that names the factory as the owner: the factory's own fault, not the tracker's."""
        import ticket_adapter
        return code == ticket_adapter.EXIT_FACTORY_FAULT or bool(failure and failure.get("owner") == "factory")

    def ticket_factory_refusal(self, code: int, failure: dict, said: str = "") -> "Refusal":
        """The factory's own fault while reading the story's ticket: REPORTED, never put to the person as a choice
        (FR-3). Names the file or the config key the adapter named, what was expected and how to restore it
        (FR-1); when the adapter named nothing (no error object) it says so and quotes what the adapter printed."""
        named = failure.get("file")
        what = (f"`{named}` is missing or not usable. " if named else "")
        head = f" It printed: {' '.join(str(said or '').split())[:300]!r}." if failure.get("message") == self.NO_ERROR_OBJECT and said else ""
        return Refusal(
            f"ticket {self.task} could not be read, and the cause is the factory's own - not the tracker's, not "
            f"your ticket: {what}The adapter said: {failure.get('message')} (exit {code}).{head} Expected: the "
            f"factory's own data and settings in order. {'Restore ' + named if named else 'Restore what the message names'}"
            " - a data file from the plugin package, a setting from qa-factory/config.json - and run the same command "
            "again; nothing was asked of you and nothing was written for this story.")

    def write_snapshot(self, out: str) -> None:
        target = self.task_root / "work" / self.SNAPSHOT
        target.parent.mkdir(parents=True, exist_ok=True)
        # bytes, not write_text: the file is the adapter's stdout and must not pick up the
        # host's newline translation on the way to disk.
        target.write_bytes(out.encode("utf-8"))

    def adopt_legacy_snapshot(self) -> None:
        """A story begun before the JSON canon has `work/ticket-snapshot.md` and no `.json`: the
        scout's brief would say "not written yet" for the rest of it. The `.md` (whatever it
        holds - the markdown shape, or the adapter's JSON with a stderr tail, which is what the
        old driver wrote) is read by the adapter and its stdout becomes the `.json`. The `.md`
        stays; an existing `.json` is never overwritten; a failure is one line and writes
        nothing."""
        work = self.task_root / "work"
        legacy, canon = work / "ticket-snapshot.md", work / self.SNAPSHOT
        if not (self.task_root / "pipeline.json").is_file() or canon.is_file() or not legacy.is_file():
            return
        code, out, err = self.py_stdout("ticket_adapter.py", "get", self.task, "--ticket-file",
                                        str(legacy), "--json", echo=False)
        if code == 0 and self.json_object(out) is not None:
            self.write_snapshot(out)
            print(f"{self.task}: work/ticket-snapshot.md is now also work/ticket-snapshot.json, the "
                  "form the scout's brief reads (the old file stays)")
        else:
            why = (err.strip() or out.strip() or "no output")[:200].replace("\n", " ")
            print(f"{self.task}: work/ticket-snapshot.md could not be turned into work/ticket-snapshot.json "
                  f"(the ticket reader exited {code}: {why}); nothing was written and the scout's brief "
                  "will say the snapshot is not written yet")

    # -- the ticket moves while the story waits (B-364 = B-259, D-0027) -----------------------------------
    # ONE command with ONE trigger on both paths, the skill's and the driver's (phases/s0.md section 2b): when the
    # last comparison is older than the freshness window, or unknown, `ticket_adapter.py freshness` reads the ticket
    # now, compares it with the baseline and journals `ticket_changed` itself. The rule is the adapter's
    # (`TA.check_is_due`), never re-stated here; what the driver adds is WHERE it runs (a resumed story, and before
    # gate B is asked), how each answer of the adapter is branched (as the skill branches it), the one question the
    # person gets when the requirements moved, and what each of the three answers does. The branch's driver code
    # (commit 0275882) is the input; the 0.8.1 snapshot reader and the words-by-file doors are what it is built on.
    FRESHNESS_TIMEOUT_S = 300           # a tracker that never answers must not hold a resumed story without a word (R15)

    @staticmethod
    def ticket_field_words(names: list) -> str:
        """Field names -> the plain words a person reads, `a, b and c` (the adapter's own `FIELD_WORDS`). "" for no names
        (an unreadable file, an adapter that named none): the caller says its own fallback - this never raises, because
        a crash here with the question open would meet the person on every run and every answer (FR-40/42)."""
        import ticket_adapter as TA
        said = [TA.FIELD_WORDS.get(name, str(name).replace("_", " ")) for name in names or []]
        if len(said) < 2:
            return said[0] if said else ""
        return ", ".join(said[:-1]) + " and " + said[-1]

    def ticket_changed_text(self, changed: list, pasted: bool, first: str = "") -> str:
        """The body of the changed-ticket question, in the story's words: what changed, that the old text is kept and the new one
        set aside, then the three answers with what each costs and does (`fresh.ticket_changed` of question-prices.json; the
        priced section ends the text). No path, no command and no field name in the body (references/human-questions.md): the file
        of a pasted story goes in the answer block (`answer_note`). `first`: what a re-ask says before all of it (FR-7)."""
        what = self.ticket_field_words(changed) or "something in the requirements"
        lead = (f"The ticket text you gave me for {self.task} changed after the plan of this story was made."
                if pasted else f"The ticket {self.task} was edited in the tracker after the plan of this story was made.")
        return self.closed_question(
            "fresh.ticket_changed",
            f"{first}{lead} What changed: {what}.\n\n"
            "The factory kept the text the story was built on and set the new text aside, so nothing has been "
            "replaced yet. It cannot tell by itself which text the story should follow: the requirements, the "
            "test plan and the test cases were all written from the old one.\n\n"
            f"What should happen? {TICKET_CHANGED_OPTIONS}\n"
            "(S2 is the step where the requirements are written down from the ticket, S3 the test plan.)",
            [{"answer": "new text", "token": "new text", "slots": {"stages": "the requirements and the test plan (S2 and S3)"},
              "says": "re-run the requirements and the plan against the new text"},
             {"answer": "old text", "token": "old text",
              "says": "continue on the old text with that stated as a known gap; anything you write after the first line is kept "
                      "with your answer for gate B"},
             self.STOP_OPTION])

    def ticket_changed_person(self, changed: list, detail=None, revisions=None, lead: str = "") -> "Person":
        """The changed-ticket question as a `Person`: the details file carries what moved in the adapter's own
        words, and a pasted story names the person's own file in the answer block (FR-15: the path is given, in
        the one place a path is an instruction). `lead` is what a re-ask says first (FR-7: it comes back changed)."""
        ticket_file = self.s0_flags()["ticket_file"]
        return Person("ticket_changed", self.ticket_changed_text(changed, bool(ticket_file), lead), "S0",
                      details=json.dumps({"changed": changed, "detail": detail, "revisions": revisions},
                                         indent=2, ensure_ascii=False),
                      answer_note=(f"The ticket text you gave me is read from: {self.s0_rel_path(ticket_file)}"
                                   if ticket_file else ""))

    def ticket_changed_from_files(self, lead: str = "") -> "Person":
        """The question again, rebuilt from the two files on disk and never from the tracker: the baseline the story
        was built on against the new text that waits beside it. A file that cannot be read still gets the question
        (the person decides), with what moved left unnamed and the factory's own reason in the details."""
        import ticket_adapter as TA
        found = TA.find_baseline(self.task_root, self.task)
        _, waiting_path, _ = TA.snapshot_paths(self.task_root)
        waiting, why = TA.read_stored_snapshot(waiting_path, self.task)
        if found["ticket"] is None or waiting is None:
            return self.ticket_changed_person([], {"unreadable": found["problem"] or why}, None, lead)
        moved = TA.diff_objects(found["ticket"], waiting)
        return self.ticket_changed_person(
            moved["changed"], moved["detail"],
            {key: moved[key] for key in ("old_revision", "new_revision", "old_fetched_at", "new_fetched_at")}, lead)

    def ticket_unchecked(self, reason: str, now=None) -> str:
        """The look did not come (a tracker that does not answer, a protection service, a check that did not finish):
        ONE line, the story goes on with the text it was built on - an informed pass (FR-4), never a stop - and
        `ticket_unchecked` goes to the journal at most once per freshness window. An unknown is not a change (FR-41):
        its own event. The adapter stamped nothing, so the check stays due; only the journal line is throttled, and
        a throttle stamp from the future (a clock that was wrong) reads as unknown: the line is journaled."""
        import ticket_adapter as TA
        reason = " ".join(str(reason or "").split())[:300]
        print(f"ticket not checked: {reason}; the story goes on with the text it was built on")
        moment, last = now or datetime.now(timezone.utc), self.state.get("ticket_unchecked_at")
        if TA.baseline_is_stale(last, moment) or TA.stamp_is_ahead(last, moment):
            code, _ = self.py("log_append.py", "--event", "ticket_unchecked", "--task", self.task, "--notes", reason)
            if not code:                        # a journal that did not take the line is tried again at the next one
                self.state["ticket_unchecked_at"] = TA.now_iso(moment)
                self.save_state()
        return "unchecked"

    def ticket_look_failed(self, code: int, out: str, err: str, now=None) -> str:
        """A non-zero exit of `freshness`, branched as phases/s0.md section 2b branches it; "unchecked" or a raise.
        Exit 124 (the check did not finish, R15) is read as exit 3. Exit 5 whose error object names owner
        `intermediary` (B-408: a protection service answered, not the tracker, the token was NOT judged) is the exit-3
        class too and is read BEFORE the lost login below, from the object's field and never from a sentence;
        every other exit 5, or owner `auth`, stops the run with the door named. A fault of the factory is reported,
        never an informed pass."""
        import ticket_adapter as TA
        if code == 124:
            return self.ticket_unchecked(err or "the ticket check did not finish", now)
        failure = self.ticket_failure(code, out, err)
        said = " ".join((err.strip() or failure["message"] if failure["from_object"] else (out + "\n" + err)).split())
        if code == TA.EXIT_AUTH_LOST and failure["owner"] == "intermediary":
            return self.ticket_unchecked("a protection service in front of the tracker answered, not the tracker "
                                         f"({failure['message']})", now)
        if code == TA.EXIT_AUTH_LOST or failure["owner"] == "auth":
            raise self.ticket_auth_person(said)
        if code == TA.EXIT_USAGE or self.ticket_is_factory_fault(code, failure):
            raise self.ticket_factory_refusal(code, failure, said)
        if code == TA.EXIT_NOT_CONFIGURED or (code == TA.EXIT_NOT_FOUND and failure["owner"] == "tracker"):
            return self.ticket_unchecked(failure["message"] or said, now)
        if code == TA.EXIT_NOT_FOUND:           # another owner (the person's own file is gone, a setting): its refusal, said, not journaled
            print(f"ticket not checked: {failure['message'] or said}")
            return "unchecked"
        raise self.ticket_factory_refusal(code, dict(failure, owner="factory"), said)

    def ticket_freshness(self, now=None) -> str:
        """Look at the ticket when the story stood still, and say what the adapter found.

        Returns "skipped" (not due: no subprocess, no print), "baseline_written", "none", "context", "declined" or
        "unchecked", or raises: the changed-ticket `Person`, a lost login (the `ticket_auth` `Person`), a fault of the factory
        (`Refusal`). Only the adapter's `result` decides, never this driver's reading of a ticket:
          baseline_written - the story had none; one line.
          none             - silence (stamped; the baseline is not rewritten).
          context          - one line naming what changed; the baseline is replaced and the story goes on.
          requirements     - the person's question; the baseline is kept, the new text waits beside it. A text the
                             person already declined (`already_answered`) is one line, never asked again (FR-7).
        On a story launched with `--ticket-file` the same file is passed: the adapter re-reads that file alone."""
        import ticket_adapter as TA
        if not TA.check_is_due(self.task_root, now):
            return "skipped"
        ticket_file = self.s0_flags()["ticket_file"]
        code, out, err = self.py_stdout("ticket_adapter.py", "freshness", self.task, "--task-root", str(self.task_root),
                                        "--json", *(["--ticket-file", ticket_file] if ticket_file else []),
                                        echo=False, timeout=self.FRESHNESS_TIMEOUT_S)
        if code:
            return self.ticket_look_failed(code, out, err, now)
        if err.strip():
            print(err.strip())                  # what the adapter said beside its result (an unreadable record, a stale file)
        result = self.json_object(out) or {}
        kind, changed = result.get("result"), result.get("changed") or []
        if kind == "baseline_written":
            print("ticket snapshot: the story had none to compare with; the ticket as it stands is now the baseline")
        elif kind == "context":
            print(f"ticket {self.task} changed while the story waited ({self.ticket_field_words(changed) or 'something'}); "
                  "the story goes on")
        elif kind == "requirements" and result.get("already_answered"):
            print(f"ticket {self.task}: the new text ({self.ticket_field_words(changed) or 'the requirements'}) is the one declined on "
                  f"{str(result.get('declined_at') or '')[:10] or 'an earlier date'}; the story goes on with the old text")
            return "declined"
        elif kind == "requirements":
            raise self.ticket_changed_person(changed, result.get("detail"), result.get("revisions"))
        elif kind != "none":
            said = (f"it answered result {kind!r}, which the driver does not know" if result
                    else "it exited 0 but printed no JSON object")
            raise self.ticket_factory_refusal(0, {"owner": "factory", "message": said, "file": None, "from_object": False}, out)
        return kind

    def ticket_freshness_entry(self) -> str:
        """The doors in front of `ticket_freshness`, in the order that keeps each invariant; the word is why it did not run.
        Another question open: never stacked (an open `ticket_changed` is the exception: it is asked again from the
        files, with no tracker read). The run that carries the changed-ticket answer: no second look - the person
        has just chosen. No `state/controller.json`: silent, the loop's own `initialize` repairs first and
        `source_revision` is the hash of the S0 snapshot - a rewrite before it would make `initialize` hash the new
        text. The person's word that the ticket is not needed (`launch.ticket_not_needed`, written by S0 before its
        answers were popped): one line, no look. A closed story: one line, no look (the controller's one reading)."""
        import controller as C
        import ticket_adapter as TA
        asked = str((self.state.get("asked") or {}).get("kind") or "")
        if self.answer_kind == "ticket_changed" or (asked and asked not in ("ticket_changed", "ticket_auth")):
            return "held"
        if not (self.state_dir / "controller.json").is_file():
            return "no_controller"
        if (self.state.get("launch") or {}).get("ticket_not_needed"):
            print(f"{self.task}: you said the ticket is not needed, so it is not looked at again")
            return "not_needed"
        import hooklib
        if hooklib.story_closure(C.closure_view(self.controller_state(), self.pipeline()))["state"] != "open":      # executing too: gate B is decided (GB-1b)
            print(f"{self.task}: this story is closed, so its ticket is not looked at again")
            return "closed"
        passed = (self.state.get("s0_answers") or {}).get("fresh.ticket_auth")
        if passed == "go on":
            # G3 (FR-7, FR-4): the person said to go on without the look. It holds for the freshness window - measured from the
            # `ticket_unchecked` stamp their word left - and is asked again only when the window has run out or the stamp is not
            # readable as a past time (an unknown is not a fresh one, FR-41).
            moment, last = datetime.now(timezone.utc), self.state.get("ticket_unchecked_at")
            if not TA.baseline_is_stale(last, moment) and not TA.stamp_is_ahead(last, moment):
                print(f"{self.task}: you said to go on without looking at the ticket, so it is not looked at again until the check "
                      "is due again")
                return "unchecked"
            self.state["s0_answers"].pop("fresh.ticket_auth", None)
            self.save_state()
        if asked == "ticket_auth":
            # Open and unanswered by a plain rerun: the check runs again - a token that works clears the question, one that does not
            # raises it again from `ticket_look_failed`; never a silent pass (G3).
            self.state["asked"] = {}
            self.save_state()
            print(f"{self.task}: the tracker login is checked again; {self.reconcile_question()}")
        if asked == "ticket_changed":
            if TA.snapshot_paths(self.task_root)[1].is_file():
                raise self.ticket_changed_from_files()
            # The new text no longer waits (an adopt or a newer check settled it): nobody can answer about it. The flag
            # is cleared the way `reconcile_question` clears one, and the ticket is looked at as usual.
            self.state["asked"] = {}
            self.save_state()
            print(f"{self.task}: the new ticket text no longer waits; {self.reconcile_question()}")
        return self.ticket_freshness()

    def ticket_record_words(self, stage: str, how: str, words: str, what: str = "ticket changed") -> None:
        """The person's answer to the changed-ticket question (`what`: or to the lost-login one) on the journal's record, WHOLE
        (FR-8): every later brief reads a `human_answer` note as their standing instruction. `how` says which road it took."""
        self.answer_row(f"{stage} {what} ({how}): ", words.strip(), what="your answer about the ticket")

    def ticket_ask_again(self, words: str, qtext: str, stage: str, lead: str, *, unread: bool = False) -> None:
        """The answer could not be carried out, or was not one of the three: the words are recorded FIRST (FR-8: the
        journal's `human_answer` and `driver-answers.jsonl`, whole), then the question comes back changed (FR-7) -
        `lead` says what the answer did not settle - rebuilt from the files, never from the tracker. `unread`: the words are
        not a token, so the seam reads them first (D-0041; its doors are the three tokens, its fallback this same question). A
        conductor `continue` / `retry` brings the question back too - never `--adopt`: an unread answer adopts nothing (G1)."""
        self.ticket_record_words(stage, "asked again", words)
        _append_jsonl(self.state_dir / "driver-answers.jsonl",
                      {"ts": _now(), "kind": "ticket_changed", "stage": stage, "dispatch": "",
                       "question_sha": question_body_sha(qtext), "words": words})
        if unread:
            self.unread("ticket_changed", stage, "", qtext, words=words, doors=TICKET_CHANGED_TOKENS, lead=lead.strip(),
                        again=lambda said: self.ticket_changed_from_files(said + "\n\n"))
        raise self.ticket_changed_from_files(lead)

    def take_ticket_auth_answer(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the `ticket_auth` question of the freshness check (FR-9: each token has an executor): `retry` - the words
        are recorded and the check runs again in this process (a token that still fails raises the question again); `go on` - the
        words are recorded, `ticket_unchecked` says the look was skipped (the informed pass, FR-4) and the word is kept as
        `s0_answers["fresh.ticket_auth"]`, honoured by `ticket_freshness_entry` for the freshness window (FR-7: a later process within
        it does not ask again); `stop` - the question is held (exit 3). Anything else is new words the code cannot read: the seam
        (D-0041) with `retry` / `go on` as its doors; a conductor `continue` / `retry` leaves the check to run again, which decides."""
        token = self.s0_normalize(words)
        self.ticket_record_words(stage, token if token in ("retry", "go on", "stop") else "unread", words, "ticket login lost")
        if token == "stop":
            raise self.held_question(self.stop_held("If you want the factory to go on after all, answer `retry` or `go on`."))
        if token == "go on":
            self.ticket_unchecked("the tracker login is lost and the person said to go on without the look")
            self.state.setdefault("s0_answers", {})["fresh.ticket_auth"] = "go on"
            self.save_state()
        elif token == "retry":
            print(f"{stage}: nothing is passed; the ticket is looked at again")
        else:
            lead = self.unread_lead(words)
            self.unread("ticket_auth", stage, "", qtext, words=words, doors=("retry", "go on"), lead=lead,
                        again=lambda said: self.held_question(said))

    def take_ticket_answer(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to the changed-ticket question: the FIRST non-empty line is a token (`s0_normalize`: BOM,
        quotes, a full stop, case and spaces only), and each of the three has an executor (FR-9):
          old text - `freshness --decline` with the WHOLE answer as the words (kept as a remark of S0, shown at gate B);
          new text - `freshness --adopt`, the words recorded, then S2 and S3 owed again (`ticket_rework_step`, R12);
          stop     - the words recorded, nothing runs, the question comes back.
        Any other answer is recorded and asked again, quoted (FR-7). The adapter's refusals: exit 2 (nothing waits any
        more) is printed and the story goes on; any other non-zero exit asks again, saying that the choice could not be
        carried out. Nothing here reads what the person MEANT (FR-12); `dispatch` is unused (the question names none)."""
        first = next((line for line in str(words).splitlines() if line.strip()), "")
        token = self.s0_normalize(first)
        if token not in TICKET_CHANGED_TOKENS:
            self.ticket_ask_again(words, qtext, stage, self.unread_lead(words) + "\n\n", unread=True)
        if token == "stop":
            self.ticket_ask_again(words, qtext, stage, self.stop_held("Answer `new text` or `old text` when you decide.") + "\n\n")
        import ticket_adapter as TA
        flags = ["--decline", *self.words_args(words, "ticketdecline")] if token == "old text" else ["--adopt"]
        code, out, err = self.py_stdout("ticket_adapter.py", "freshness", self.task, "--task-root", str(self.task_root),
                                        *flags, "--json", echo=False, timeout=self.FRESHNESS_TIMEOUT_S)
        failure = self.ticket_failure(code, out, err) if code else {}
        said = " ".join((err.strip() or failure.get("message") or f"the adapter exited {code}").split()).removeprefix(
            "ticket_adapter: ")[:300]
        if code == TA.EXIT_USAGE:
            # Nothing waits any more (the text was settled by a later look) or the adapter refused its arguments: the
            # words are on the record all the same (FR-8), the story goes on, and the next look decides what is owed.
            print(f"{self.task}: {said}")
            self.ticket_record_words(stage, f"{token}, nothing waited", words)
            return
        if code:
            self.ticket_ask_again(words, qtext, stage, f"Your choice could not be carried out: {said}\n\n")
        if token == "old text":
            print(f"{self.task}: the story goes on with the old ticket text; your words are kept for gate B and the "
                  "new text is not asked about again")
            return
        self.ticket_record_words(stage, "new text", words)
        state = self.controller_state()
        owed = [s for s in ("S2", "S3") if (((state.get("stages") or {}).get(s) or {}).get("status")) == "completed"]
        if not owed:
            print(f"{self.task}: the new ticket text is adopted; the requirements and the plan are not finished yet, "
                  "so they are made from it when they run")
            return
        self.state["ticket_rework"] = {"stages": owed, "words": words, "at": _now(),
                                       "before": sorted(self.rework_dispatches(state.get("dispatches") or {}, "ticket_changed", by_person=False))}
        self.save_state()
        print(f"{self.task}: the new ticket text is adopted; the requirements and the plan are made again from it")

    def ticket_rework_step(self) -> bool:
        """One move of the ticket rework the person chose (`state["ticket_rework"]`), or False when none is owed.

        S2 and S3 go back over their accepted work with cause `ticket_changed` and `complete=True` (the plan baseline
        is re-captured, so the re-run's changes are never later counted as the person's overrides), ONE stage at a time:
        the controller refuses a second running dispatch, so S3 is registered only after S2's was accepted. A stage with
        no accepted work gets no rework and one line. The rework is found by the cause on the stage's dispatch that is
        NOT in `before` (the ones a former answer made), so a second ticket change is owed its own rework. It acts
        only when the controller holds no running dispatch; a dispatch of its own that is not accepted is the loop's to
        resolve (`where`); one that was set aside (released, superseded, stale: the controller's `DISCOUNTED`) ends the
        re-runs with one line and the gate A move still follows.
        When the list is empty gate A is asked again (`ticket_reopen_gate_a`). True: this turn moved something, ask
        `where` on the next one - nothing `where` could say may come before what is owed."""
        owed = self.owed_rework("ticket_rework")
        if owed is None:
            return False
        pending, dispatches = owed
        import controller as C
        set_aside = C.DISCOUNTED - {C.NEVER_STARTED}
        stages = list(pending.get("stages") or [])
        while stages:
            stage = stages[0]
            mine = [d for did, d in self.rework_dispatches(dispatches, "ticket_changed", by_person=False, stage=stage).items()
                    if did not in (pending.get("before") or [])]
            status = mine[-1].get("status") if mine else None
            if status == "accepted":
                stages.pop(0)
                pending["stages"] = stages
                self.save_state()
                continue
            if mine and status in set_aside:
                # The controller's own vocabulary (`DISCOUNTED` less `never_started`, which `where` relaunches), never a
                # literal: a person's release (`released_by_person`), a retry that took its place (`superseded`, written by
                # code) or an invalidation (`stale`). The re-run will not happen, so the rest of the list is dropped, but the
                # person's choice of the new text stands: gate A is still asked again (below), never left on the old text.
                print(f"{self.task}: the re-run of {stage} was set aside before it was accepted (a person's word, a retry that "
                      "took its place, or an invalidation); nothing more is made again, and gate A is still asked again")
                stages = []
                pending["stages"] = stages
                self.save_state()
                break
            if mine:
                return False
            roles = [d.get("role") for d in dispatches.values() if d.get("stage") == stage and d.get("status") == "accepted"
                     and (stage != "S3" or d.get("role") == "qa-test-strategist")    # a first look accepted after the strategist is not the author
                     # B2 (critic t-2548): the S1 twin - the reference window's runner, accepted after the scout, is not the author either; the
                     # scout is reworked and `rework` re-enters the window. A story with no reference has only the scout here: as before
                     and (stage != "S1" or d.get("role") == (self.stages().get("S1", {}).get("roles") or [""])[0])]
            if roles and stage == "S3":
                # G1-11: ONE paid dispatch labels and plans (a rework of S3 is never two); the table is prepared first
                # (a pre-node S3 with no table gets it built), and the dispatch closes through the one S3 completion.
                self.s3_prepare()
                self.rework(stage, str(roles[-1]), [], str(pending.get("words") or ""), cause="ticket_changed",
                            complete=self.s3_ticket_completion(),
                            extra=self.s3_strategist_lines({"repair_cause": "ticket_changed"}))
                return True
            if roles:
                self.rework(stage, str(roles[-1]), [], str(pending.get("words") or ""), cause="ticket_changed", complete=True)
                return True
            print(f"{self.task}: {stage} has no accepted work to make again; skipped")
            stages.pop(0)
            pending["stages"] = stages
            self.save_state()
        self.ticket_reopen_gate_a(pending)
        self.drop_record("ticket_rework")
        return True

    def owed_rework(self, key: str):
        """The start both rework steps share (`ticket_rework_step`, `seam_rework_step`): `(record, the controller's dispatches)` when the
        record `state[key]` may be acted on now, else None - no record, no controller state, or a dispatch running (`where` leads it)."""
        pending = self.state.get(key)
        if not isinstance(pending, dict) or not (self.state_dir / "controller.json").is_file():
            return None
        dispatches = self.controller_state().get("dispatches") or {}
        if any(d.get("status") == "running" for d in dispatches.values()):
            return None
        return pending, dispatches

    def drop_record(self, key: str) -> None:
        """Drop the record `state[key]` and save: the step that owed it is done with it (or can never do it)."""
        self.state.pop(key, None)
        self.save_state()

    def ticket_reopen_gate_a(self, pending: dict) -> None:
        """After S2 and S3 were made again from the new text: a gate A decision given on the old requirements does not
        survive the person's choice (R17, F9 a). `semantic_reopen` stales it and returns S4 to pending - nothing more
        of the work is lowered (a completed stage is never lowered by later work, `controller.set_stage`) - so the accepted
        dispatches of S5-S8 on the story's scope are invalidated too (whatever the stage's status), the controller's own
        move for it, and the stages are redone on the new plan: no test or report built on the old requirements survives.
        A completed stage code cannot set aside (no dispatch of the scope names it) is NAMED in a line and at gate A's top.
        Each step is recorded in `ticket_rework` as it lands, so a restart goes on where it stopped. No approved gate A,
        or no scope: one line, no reopen. `expected_revision` is the controller's `revision`, read right before each call.
        What the driver does when the S4 re-run meets 'cumulative packet budget reached' (the S4 designer's budget is
        story-wide): nothing of its own - the refusal takes the existing road (the conductor, then the person)."""
        state = self.controller_state()
        revision = state.get("source_revision")
        approved = any(d.get("gate") == "A" and d.get("status") == "approved" and d.get("source_revision") == revision
                       for d in (state.get("decisions") or {}).values())
        scope = list(state.get("scope") or [])
        if not pending.get("reopened") and not (approved and scope):   # once reopened the decision is stale: that is no absence
            print(f"{self.task}: no approved gate A to ask again; the story goes on from the new text")
            return
        reason, key = "the person chose the changed ticket text: " + str(pending.get("words") or "")[:1500], pending.get("at")
        if not pending.get("reopened"):
            self.controller("semantic_reopen", input_data={"reason": reason, "affected_scope": scope,
                                                           "idempotency_key": f"semantic_reopen:ticket:{key}",
                                                           "expected_revision": state.get("revision", 0)})
            pending["reopened"] = True
            self.save_state()
        # The accepted work of S5-S8 on the story's scope is set aside WHATEVER the stage's status: a half-done S5 (pending,
        # with accepted windows) keeps windows built on the old plan as surely as a completed one. A dispatch already `stale`
        # still counts as covering its stage, so a restart after the invalidate names the same stages.
        late_stages = ("S5", "S6", "S7", "S8")
        mine = {did: d for did, d in (state.get("dispatches") or {}).items()
                if d.get("stage") in late_stages and d.get("status") in ("accepted", "stale") and set(d.get("scope") or []) & set(scope)}
        stale = [did for did, d in mine.items() if d.get("status") == "accepted"]
        if stale and not pending.get("invalidated"):
            self.controller("invalidate", input_data={"reason": reason, "affected_scope": scope, "dispatch_ids": stale,
                                                      "decision_ids": [], "idempotency_key": f"invalidate:ticket:{key}",
                                                      "expected_revision": self.controller_state().get("revision", 0)})
        pending["invalidated"] = True
        self.save_state()
        # A completed stage with no such dispatch (a stage closed by code, or one whose dispatches carry no scope) cannot be
        # set aside by code: it is NAMED, in the line and at the top of gate A, never left silent (FR-41).
        covered = {d.get("stage") for d in mine.values()}
        names = self.stages()
        left = [f"{str((names.get(s) or {}).get('name') or s).lower()} ({s})" for s in late_stages
                if (((state.get("stages") or {}).get(s) or {}).get("status")) == "completed" and s not in covered]
        note = "Gate A is asked again: you chose the new ticket text, and the requirements and the plan were made again from it."
        if left:
            kept = f"what {', '.join(left)} hold was made from the old text, and nothing here could set it aside"
            print(f"{self.task}: {kept}")
            note += f" Note that {kept}."
        self.state.setdefault("gate_note", {})["A"] = note
        print(f"{self.task}: gate A is asked again on the requirements and the plan made from the new text")

    def s0_note_launch(self) -> None:
        """First entry into s0: what the command line said is kept, so that a later entry - the
        one that follows an answer, run with no flags - starts from the same launch."""
        if "launch" in self.state:
            return
        ns = self.flags
        given = {"mr": getattr(ns, "mr", None), "branch": getattr(ns, "branch", None),
                 "commit": getattr(ns, "commit", None), "ticket_file": getattr(ns, "ticket_file", None),
                 "env": getattr(ns, "env", None), "ungrounded": bool(getattr(ns, "ungrounded", False)),
                 # t-2181 PC-2: `--side <name>=<reality>` and `--reference <side>=<stand>` (pairs, repeated), kept as {name: word}
                 "side": dict(getattr(ns, "side", None) or ()), "reference": dict(getattr(ns, "reference", None) or ())}
        self.state["launch"] = {key: value for key, value in given.items() if value}
        self.save_state()

    def s0_keep_late_launch(self) -> None:
        """A launch word on a LATER entry is kept in `launch` too (t-586 F-1): `s0_note_launch` writes once, so the `--mr` of the
        restart the no-change question prints (the `change` door) was lost, and a later process with no flags told the scout
        `Launch flags: none` and asked the same question again (FR-7). The person's answers (`keep`, `mr_dropped`) are applied
        by `s0_flags` AFTER this, so a kept word is never undone here."""
        ns, launch = self.flags, self.state.setdefault("launch", {})
        changed = False
        for key in ("mr", "branch", "commit"):
            value = getattr(ns, key, None)
            if value and launch.get(key) != value:
                launch[key] = value
                changed = True
        if getattr(ns, "ungrounded", False) and not launch.get("ungrounded"):
            launch["ungrounded"] = True
            changed = True
        # t-2181 PC-2: a side or a reference word on a LATER entry (the relaunch that tells the factory a side is real now) is
        # kept as the restart's own word, name by name: a later word for a name replaces the earlier one, the other names stay.
        for key in ("side", "reference"):
            given = dict(getattr(ns, key, None) or ())
            if given and any((launch.get(key) or {}).get(name) != word for name, word in given.items()):
                launch[key] = {**(launch.get(key) or {}), **given}
                changed = True
        if changed:
            self.save_state()

    def launch_flags(self) -> dict:
        """The launch flags, this command line first, else what S0 kept in `launch` (`s0_note_launch`): a PURE reader - nothing is
        written, no answer is applied. The one place the two sources are joined: `s0_flags` builds on it, and the scout's
        "Launch flags" line (`role_lines`) reads it, so an `--answer` process names the kept `--mr` (F8)."""
        ns, kept = self.flags, self.state.get("launch") or {}
        flags = {key: getattr(ns, key, None) or kept.get(key) or None
                 for key in ("mr", "branch", "commit", "ticket_file", "env")}
        flags["ungrounded"] = bool(getattr(ns, "ungrounded", False) or kept.get("ungrounded"))
        # SS1-13: the person's answer to the no-change question (`s0_read_word`); no command-line flag carries it, only `launch`.
        flags["implementation_source"] = kept.get("implementation_source") or None
        # t-2181 PC-2: the sides the person named at launch (this command line over what was kept, name by name) and the answer
        # `not built yet` (`s0_read_word`); never None, so a reader asks `if flags["side"]`.
        for key in ("side", "reference"):
            flags[key] = {**(kept.get(key) or {}), **dict(getattr(ns, key, None) or ())}
        flags["not_built_yet"] = bool(kept.get("not_built_yet"))
        # `--side product=absent` IS the person's `not built yet` in flag form (F1): no change is read, so the scout does not halt on
        # the missing diff and the no-change question is not asked (FR-7). With a change named it is only a record of the side.
        import contract   # late, as the other uses in this file
        if (flags["side"].get("product") == contract.PARKING_REALITY
                and not (flags["mr"] or flags["branch"] or flags["commit"])):
            flags["ungrounded"] = True
        return flags

    def s0_flags(self) -> dict:
        """The launch flags as they stand: this command line first, else what was kept; then what
        the person has answered on top (their word is later than the flag it corrects)."""
        ns, kept = self.flags, self.state.get("launch") or {}
        flags = self.launch_flags()
        flags["skip_sources"] = getattr(ns, "skip_sources", None) or kept.get("skip_sources") or None
        answers = self.state.get("s0_answers") or {}
        if answers.get("keep"):
            for key in ("mr", "branch", "commit"):
                if key != answers["keep"]:
                    flags[key] = None
        if answers.get("mr") == "skip":
            flags["mr"] = None        # the person chose the list's word over the flag's (`source_list` question)
        for key in ("env", "ticket_file"):
            if not answers.get(key):
                continue
            cli = getattr(ns, "ticket_file", None) if key == "ticket_file" else None
            if cli and "ticket_file_cli" in answers and cli != answers["ticket_file_cli"]:
                # t-281 F2: a `--ticket-file` on THIS command line that is not the flag the stored paste was
                # answered under is the person's newer word: it wins, and the older paste is dropped so that a
                # later entry with no flag does not go back to it. The same flag repeated beside the answer
                # (`continue_command` repeats every launch flag) is NOT a newer word: the paste, typed after it,
                # stays - else a pasted answer would be discarded by the very command that carries it. A paste
                # stored by an older driver (no `ticket_file_cli`) keeps its old precedence (builder rule 9).
                for stale in ("ticket_file", "ticket_file_cli"):
                    answers.pop(stale, None)
                self.state.setdefault("launch", {})["ticket_file"] = cli
                self.save_state()
                continue
            if cli and answers[key] != cli:
                # t-287 item 6: the stored paste wins over the SAME flag repeated beside it; say so once on entry,
                # with the file that will be read and the door that replaces it
                print(f"reading the ticket text you gave earlier ({self.s0_rel_path(answers[key])}); "
                      "give a different --ticket-file to replace it")
            flags[key] = answers[key]
        return flags

    def s0_rel_path(self, path) -> str:
        """The file as a person finds it from the project: relative to the project root, forward slashes; a path
        outside the project (a ticket file the person keeps elsewhere) is shown as it was given."""
        try:
            return Path(str(path)).resolve().relative_to(self.project).as_posix()
        except (OSError, ValueError):
            return str(path)

    def s0_stop(self, block: str, kind: str, text: str, doors: dict, details: str = "",
                problems: list | None = None, paste: bool = False, answer_note: str = "") -> None:
        """Raise the person's question for one S0 block, with what `s0_read_word` needs to read
        the answer: the block's key, its text and the tokens it offers (token -> the value it
        stands for), stored BEFORE the raise. The text is kept whole so that an answer this
        question does not take can be met with the same question and one changed sentence in
        front of it, without repeating the work that led here."""
        doors = self.s0_doors(doors)
        self.state["s0_block"] = block
        self.state["s0_ask"] = {"kind": kind, "text": text, "details": details, "doors": doors,
                                "problems": list(problems or []), "paste": paste, "answer_note": answer_note}
        self.save_state()
        raise Person(kind, text, "S0", details=details, answer_note=answer_note)

    @staticmethod
    def s0_doors(doors) -> dict:
        """The tokens an S0 stop takes: the block's own plus `stop` (C1-3: every S0 question offers it, and a whole-answer `stop`
        has an executor in `s0_read_word`). Added at READ time as well, so an `s0_ask` stored by an older driver takes it too."""
        return {"stop": "stop", **(doors or {})}       # a door the block already holds under `stop` is never silently replaced (F4)

    def s0_again(self, block: str, ask: dict, lead: str) -> Person:
        """The S0 question of `ask` kept for the next answer (`s0_block` / `s0_ask` stored again) and returned as the Person to raise,
        with `lead` in front of its whole text: the one form of an S0 re-ask (an answer it does not take, or a `stop`)."""
        self.state["s0_block"], self.state["s0_ask"] = block, ask
        self.save_state()
        return Person(ask.get("kind") or "halt", lead + "\n\n" + str(ask.get("text") or ""), "S0",
                      details=str(ask.get("details") or ""), answer_note=str(ask.get("answer_note") or ""))

    def s0_offered(self, ask: dict, with_stop: bool = True) -> list:
        """The answers of a stored S0 question as a person reads them: each door's token once, backquoted, then the paste when the
        question takes the ticket as text. `with_stop` False leaves the `stop` door out (the sentence after a `stop` names the others)."""
        doors = self.s0_doors(ask.get("doors"))
        offered = [f"`{value}`" for value in dict.fromkeys(doors.values()) if with_stop or value != "stop"]
        return offered + (["the ticket itself as text"] if ask.get("paste") else [])

    def s0_read_word(self) -> None:
        """The answer to the S0 stop this run is entered after, if there is one.

        Only what the stop offered acts: `retry` changes nothing (the step simply runs again);
        `go on` becomes a pass for THAT block only; a stand's name or a kept launch source
        corrects the launch; a pasted ticket becomes the ticket file; the whole answer `stop`
        holds the question (exit 3, nothing runs). Anything else is not guessed at by code (FR-12): it is NEW words the code cannot
        read, so it goes to the conductor (D-0041, FR-48: a problem, not a command - the seam `unread` with the question's own
        doors), and the question comes back changed and priced when the conductor cannot answer (FR-7). The signal to the callers
        is None: "nothing is decided - run the step again" (a conductor `continue` / `retry` leaves no block stored); a question
        raised by that road stores the block again, ONLY on a raise (`except Person`), never store-then-clear."""
        pending = self.state.setdefault("pending_words", {})
        words = pending.pop("S0", None)
        # The block is open only until THIS entry: cleared on every entry, answered or not, and set
        # again by `s0_stop` or by the re-ask below. A block that outlived an entry with no answer
        # would capture the answer to a LATER, unrelated stop at S0 (the env_probe halt, a refusal)
        # and show the old question again.
        ask, block = self.state.pop("s0_ask", None) or {}, self.state.pop("s0_block", None) or ""
        if not words or not block or not ask:
            self.save_state()
            return
        door = self.s0_doors(ask.get("doors")).get(self.s0_normalize(words))
        answers = self.state.setdefault("s0_answers", {})
        launch = self.state.setdefault("launch", {})
        if door == "stop":
            # The WHOLE answer `stop` (C1-3, FR-9: no question offers a decision nobody executes). It has its executor here, like the
            # halt's: the question is held with a changed first line (FR-7), exit 3, no conductor, nothing run or spent. `stop please`
            # is not this door - it takes the re-ask below like any other words.
            raise self.s0_again(block, ask, self.stop_held(
                "If you want the factory to go on after all, answer " + " or ".join(self.s0_offered(ask, False)) + "."))
        elif door == "retry":
            if block == "ticket_read":              # P01: the earlier `not needed` is dropped, the ticket is read again. ONLY at the
                answers.pop("ticket_read", None)    # ticket's own question: at any other block it is a word that must survive (G19)
        elif door == "go on":
            self.state.setdefault("s0_passes", {})[block] = {
                "words": words, "at": _now(), "problems": list(ask.get("problems") or []),
                # What the person was shown, cut to 300 characters on one line: the finding's
                # witness. Kept here so that it is the same text every time the pass is applied.
                "witness": " ".join(str(ask.get("text") or "").split())[:300] or f"S0 {block}"}
        elif block == "source_list" and door in ("read", "skip"):
            # The two words of one person that disagree (t-172 C5b): `read` drops the line of the list,
            # `skip` drops the flag (kept apart from `keep`, which chooses among --mr/--branch/--commit).
            answers["mr"] = door
            if door == "skip":
                dropped = launch.pop("mr", None) or getattr(self.flags, "mr", None)
                if dropped:
                    launch["mr_dropped"] = dropped
        elif block == "flags" and door:
            answers["keep"] = door
            for key in ("mr", "branch", "commit"):
                if key != door:
                    launch.pop(key, None)
        elif block == "stand" and door:
            answers["env"] = launch["env"] = door
        elif block == "key_form" and door == "no ticket":
            # The key is made by a command, not in this process (a key changed in a live process would leave every launch word
            # under the old name): the command is printed and the question is held (FR-9: its executor is the command).
            raise self.s0_again(block, ask, self.NO_TICKET_LEAD)  # remains: the person's own question comes back with the command printed (FR-9); nothing was accepted
        elif block == "no_change" and door == "change":
            # SS1-13: the change is given on the command line of a NEW entry (`--mr`, `--branch`, `--commit`); there is no executor
            # in this process (a flag cannot be added to a running command), so the command is printed and the question is held (FR-9).
            raise self.s0_again(block, ask, self.NO_CHANGE_LEAD)  # remains: the person's own question comes back with the command printed (FR-9); nothing was accepted
        elif block == "no_change" and door in ("current code", "ungrounded", "not built yet"):
            # SS1-13: the answer goes straight into `launch` (as the stand's `env`): `s0_note_launch` keeps only the FIRST entry's flags,
            # and the entry after this answer asks nothing again because the value is there (FR-7). The readers: `launch_flags`
            # (`ungrounded`), `role_lines` (the scout's line) and `s0_rest` (`pipeline.json`'s `implementation_source`).
            if door == "current code":
                launch["implementation_source"] = "current-code"
            else:
                launch["ungrounded"] = True     # no change is read: the scout does not halt on the missing diff
                if door == "not built yet":
                    launch["not_built_yet"] = True      # `s0_sides_sets` records the side `absent` (t-2181 PC-2)
        elif block.startswith("deliverable:") and door in ("ours", "another team's"):
            # t-2181 PC-2 (F-12): whose a non-real side is; the block names the side (`deliverable:<side>`, the name is open, AR-2).
            self._keep_sides_answer(block.partition(":")[2], door)
        elif block in ("ticket_read", "ticket_auth") and door == "not needed":
            # F3: the story's own ticket is "not needed". What that does is decided where the ticket is read
            # (`s0_ticket`): it goes on with a snapshot that is already there, and ends honestly without one.
            answers["ticket_read"] = "not needed"
        elif ask.get("paste") and self.s0_is_text(words):
            # Any non-empty text (t-267 C9): the ticket reader decides what it found, and no-criteria is the
            # `ticket_incomplete` question, not a refusal of the paste. Kept as typed: a tidied ticket is a
            # paraphrase of the requirements (references/templates/ticket-snapshot.md).
            target = self.state_dir / "driver-tmp" / f"ticket-{self.task}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(words, encoding="utf-8")
            answers.pop("ticket_read", None)        # G19: a pasted ticket is read; an earlier `not needed` must not set `ticket_not_needed`
            answers["ticket_file"] = launch["ticket_file"] = str(target)
            # the flag on the command line that carried this answer: a later `--ticket-file` that DIFFERS from it
            # is a newer word than the paste (`s0_flags`); the same flag repeated is not
            answers["ticket_file_cli"] = str(getattr(self.flags, "ticket_file", None) or "")
        else:
            doors = self.s0_doors(ask.get("doors"))
            lead = self.unread_lead(words)
            try:
                self.unread(ask.get("kind") or "halt", "S0", "", str(ask.get("text") or "") + "\n\n" + str(ask.get("details") or ""),
                            words=words, doors=tuple(doors), lead=lead, again=lambda said: self.s0_again(block, ask, said))
            except Person:
                # G1: the block is stored ONLY on a raise path, here, beside the `stop` branch - never stored first and cleared on a
                # return (a `Stop` / `InfraStop` out of `run_claude` would leave it alive past this entry, and a later S0 question
                # would be read against these doors). A conductor `continue` / `retry` returns: no key stored, the step runs again.
                self.state["s0_block"], self.state["s0_ask"] = block, ask
                self.save_state()
                raise
        self.save_state()

    LOCAL_KEY_COMMAND = "`ticket_adapter.py local-key --words-file <file>` (the file holds the story's text) prints a key"

    NO_TICKET_LEAD = ("The key is made by a command, not in this process: the command is in the answer block below. "
                      "Nothing was started under this name.")

    NO_CHANGE_LEAD = ("The change is given on the command line of a new start, not in this process: the story is started again with the same "
                      "command and one more flag, --mr <link>, --branch <name> or --commit <sha>. Nothing has been started on it yet.")

    def s0_is_local(self) -> bool:
        """Is this story local (SS1-14)? The ONE reader is `local_keys.is_local` (AR-13); it never raises, and False is the safe side."""
        import local_keys
        return local_keys.is_local(self.task, self.project)

    def s0_local_file(self, ticket_file):
        """The ticket file of S0: the one given, else - for a local story - its text file `qa-factory/local-tickets/<KEY>.md`."""
        if ticket_file or not self.s0_is_local():
            return ticket_file
        import local_keys
        return str(local_keys.ticket_path(self.task, self.project))

    def s0_key_form(self) -> None:
        """SS1-14 (M6): a NEW story whose launch key is not a key of this project's tracker is the person's question, before anything
        is read (CART-1 lost 38 minutes to `ADD-TO-CART`). Only a new story is checked: a `pipeline.json` or a snapshot on disk is an
        older story, which goes on under any name. ERROR DIRECTION: a false question costs one answer; a false pass costs the whole
        story under a name its cases are never recognised by. The same `AF.key_refused` as `ticket_adapter get --output` (AR-15, AR-19);
        a guess of the tracker's form is no refusal (`key_refused` says so). The pass is asked LAST (`s0_passed` records a use)."""
        if not AF.key_refused(self.task, self.config):
            return
        if (self.task_root / "pipeline.json").exists() or (self.task_root / "work" / self.SNAPSHOT).exists():
            return
        if self.s0_passed("key_form"):
            return
        # The commands and the setting's name are INSTRUCTIONS: they stand in the answer block (human-questions.md rule 5, FR-6), the
        # options say the same thing in the story's words.
        options = [{"answer": "no ticket", "token": "no ticket",
                    "says": "the story has no ticket: its text gets a key made by the factory, and you start the story again under that key"}]
        doors = {"no ticket": "no ticket", "go on": "go on"}
        note = f"To get a key for the text: {self.LOCAL_KEY_COMMAND}, then start again with --task <that key>."
        if AF.key_pattern_honoured(self.config):
            options.append({"answer": "key_pattern", "token": "retry",
                            "says": "tell the factory the shape of this project's keys (the setting is named below), then answer retry"})
            doors["retry"] = "retry"
            note += " The setting: adapters.ticket.key_pattern in qa-factory/config.json is the shape of one key."
        options += [{"answer": "go on", "token": "go on", "says": "cases under this name will not be recognised"}, self.STOP_OPTION]
        # The body gives the example only: the pattern (`[A-Z0-9]`...) reads as an internal id to the person (human-text `refusal_id`);
        # the whole description goes beside the question, in the details.
        example = AF.key_form(self.config, floor=True).example
        shape = f"a key looks like {example}" if example else AF.describe_key_form(self.config)
        self.s0_stop(
            "key_form", "halt",
            self.closed_question(
                "s0.key_form",
                f"`{self.task}` is not a key of this project's tracker: {shape}. "
                "Nothing has been read or written yet.\n\nWhat I need from you is one of these:", options),
            doors, details=f"launch key: {self.task}\nThe tracker's key form: {AF.describe_key_form(self.config)}", answer_note=note)

    def s0_references_allow_no_change(self) -> bool:
        """Condition 2 of the no-change question (SS1-13): `work/ticket-references.json` is readable and holds NO row whose kind is a change
        to the code (`ticket_light.change_kinds`, the table's `is_change`). ERROR DIRECTION: a file that is absent or unreadable, rows that
        are not a list, or a kinds table that cannot be read is False - no question, the old road (the scout's cascade, `s1.no_diff`): a
        wrong question asked of a story whose text DOES point at a change costs a person's answer, a missed one only an extra dispatch."""
        try:
            kinds = TL.change_kinds()
            rows = _read_json(self.task_root / "work" / "ticket-references.json").get("rows")
        except Exception:
            return False
        if not isinstance(rows, list):
            return False
        return not any(isinstance(row, dict) and row.get("kind") in kinds for row in rows)

    def s0_no_change_entry(self, flags: dict) -> None:
        """SS1-13 (owner, 31.10.2026: a real ticket with no merge request - the scout looks itself, no question; t-526 section 5): a LOCAL
        story started with no change to ground on is the person's question BEFORE the scout is dispatched. Asked when ALL hold: (1) no
        `--mr` / `--branch` / `--commit` / `--ungrounded` and no answer already in `launch` (`implementation_source`); (2) the story's
        references name no merge or pull request (`s0_references_allow_no_change`); (3) the story is local (`local_keys.is_local`) -
        ONLY that: a real ticket with no flags goes the old road, because the scout's cascade finds the change the text did not name.
        THE CALL STANDS OUTSIDE `if not kept` in `s0`: the entry after the answer finds the snapshot kept, and the answer is already in
        `launch` (FR-7: the question is not asked twice). Four answers (`current code` only where `code_repos` records a repository)."""
        if (flags.get("mr") or flags.get("branch") or flags.get("commit") or flags.get("ungrounded")
                or flags.get("implementation_source") or flags.get("not_built_yet")):
            return
        if not self.s0_is_local() or not self.s0_references_allow_no_change():
            return
        repos = bool(self.config.get("code_repos"))
        options = []
        doors = {"change": "change", "ungrounded": "ungrounded", "not built yet": "not built yet"}
        if repos:
            options.append({"answer": "current code", "token": "current code",
                            "says": "(Recommended) test the feature as it is now: what the code does is shown as how it behaves now, "
                                    "never as the expected value"})
            doors["current code"] = "current code"
        options += [{"answer": "change", "token": "change",
                     "says": "give me the change: a merge request, a branch or a commit, and start the story again with it"},
                    {"answer": "ungrounded", "token": "ungrounded", "says": self.UNGROUNDED_SAYS},
                    # t-2181 PC-2 (D2): the code is not written yet. Its twin is the `not built yet` option of `halt_text` (`s1.no_diff`, AR-19).
                    {"answer": "not built yet", "token": "not built yet", "says": self.NOT_BUILT_YET_SAYS},
                    self.STOP_OPTION]
        why = ("" if repos else " This project records no code repository, so there is no code in place to test the story against.")
        self.s0_stop(
            "no_change", "halt",
            self.closed_question(
                "s0.no_change",
                f"No merge request, branch or commit was given for {self.task}, and its text holds no link to one. It is a local story, "
                f"so no tracker holds a change tied to it.{why} Nothing has been run for it yet.\n\n"
                "Testing without a change to ground on is a decision, so pick one:", options),
            doors, details=f"local story {self.task}: no --mr, --branch, --commit or --ungrounded; work/ticket-references.json holds no row "
                           "of a kind that is a change",
            answer_note="To give the change: start the story again with --mr <link>, --branch <name> or --commit <sha>.")

    def _sides_entries(self, env=None) -> dict:
        """`{"entries": {side name: {reality, source[, deliverable][, settles_by][, reference]}}, "problem": str, "names": [...]}`.
        `entries` is what the registry (t-2181 PC-1b: `contract.registry_sides`, for the stand SELECTED at S0 (`env`), else the one
        the launch named with `--env`; later wins) and the person's launch words name, or {} when nothing makes a record owed (S13: an all-real launch with no reference
        writes nothing, and every reader derives the default). `problem` is why the registry leg could not be read or holds a
        malformed side row ("" when it read; those sides are left out of `entries`, never read as real); `names` are the side names
        the registry records on any stand, for the case check (C15)."""
        import contract   # late, as the other uses in this file
        flags = self.launch_flags()
        answers = (self.state.get("launch") or {}).get("sides_answers") or {}
        read = contract.registry_sides(self.project, env or flags.get("env"))
        entries = {}
        for name, row in read["sides"].items():
            if not row["reality"]:
                continue
            entry = {"reality": row["reality"], "source": "registry"}
            if row["deliverable"] is not None:
                entry.update(deliverable=row["deliverable"], settles_by=row["settles_by"])
            if row["reference"]:
                entry["reference"] = row["reference"]
            entries[name] = entry
        for name, word in flags["side"].items():
            entries.setdefault(name, {})
            entries[name].update(reality=word, source="launch")
        if flags["not_built_yet"]:
            entries["product"] = {"reality": contract.PARKING_REALITY, "deliverable": True, "source": "person"}
        for name, stand in flags["reference"].items():
            entries.setdefault(name, {"reality": self.SIDE_REAL, "source": "launch"})["reference"] = stand
        for name, ours in answers.items():
            if name in entries:
                entries[name].update(deliverable=bool(ours), source="person")
        if not any(entry["reality"] != self.SIDE_REAL or entry.get("reference") for entry in entries.values()):
            entries = {}
        return {"entries": entries, "problem": read["problem"], "names": read["names"]}

    def s0_write_sides(self, environment=None) -> None:
        """t-2181 PC-2: the question of the story's sides - `sides.deliverable` for a non-real side whose `deliverable` nothing says,
        on a story that names a side other than `product` (a single-side story is never asked: the default is true). Called in `s0`,
        after the stand is selected (`environment`, so a side known only from that stand's row is asked, never silently deliverable):
        the question must stand BEFORE `pipeline.json`. The record itself is `s0_sides_sets`
        (built into `pipeline.json` by `s0_rest`). Sides come from `--side <name>=<reality>`, `--reference <side>=<stand>`, the answer
        `not built yet` and the answers kept by `_keep_sides_answer`; the registry's rows come first (PC-1b), so a side whose
        `deliverable` a `product.sides` row says is not asked again (the second story of a project).
        C15 (INVARIANT: a side is one name everywhere, so `UI` never lives beside a recorded `ui`): a `--side` / `--reference` name that
        is not a recorded side name but equals one but for letter case is REFUSED, naming the recorded name; the offending name is
        dropped from the kept launch first, so the corrected flag on the next start is the door (it is not met again)."""
        got = self._sides_entries(environment)
        entries = got["entries"]
        flags = self.launch_flags()
        recorded = set(got["names"])
        for key in ("side", "reference"):
            for name in flags[key]:
                twins = sorted(r for r in recorded if r != name and r.casefold() == name.casefold()) if name not in recorded else []
                if twins:
                    launch = self.state.setdefault("launch", {})
                    (launch.get(key) or {}).pop(name, None)
                    self.save_state()
                    raise Refusal(f"the side `{name}` given with --{key} is not a side of this project, but `{twins[0]}` is, and side "
                                  f"names are compared exactly, so they would be two sides. Start again with --{key} using `{twins[0]}`, "
                                  f"or have the conductor record `{name}` as a new side (project_knowledge.py side --name {name} "
                                  "--deliverable yes|no --words-file <file>). Nothing was run for the story.")
        if not entries or all(name == "product" for name in entries):
            return
        for name in sorted(entries):
            if entries[name]["reality"] == self.SIDE_REAL or "deliverable" in entries[name]:
                continue
            self.s0_stop(
                f"deliverable:{name}", "halt",
                self.closed_question(
                    "sides.deliverable",
                    f"You started {self.task} with the side `{name}` marked as `{entries[name]['reality']}`. Whether this story "
                    f"delivers `{name}` or another team does decides what the story waits for and what the report hands to whoever "
                    "makes it real. Nothing has been run for it yet.\n\nWhose is it?",
                    [{"answer": "ours", "token": "ours",
                      "says": f"this story delivers `{name}`: the checks that need the real one wait until it exists"},
                     {"answer": "another team's", "token": "another team's",
                      "says": f"another team makes `{name}` real: this story does not wait for it, and the report lists what was not "
                              "checked against it"},
                     self.STOP_OPTION]),
                {"ours": "ours", "another team's": "another team's"},
                details=f"side {name}: reality {entries[name]['reality']}; no record says whether this story delivers it")

    def s0_sides_sets(self, environment=None) -> dict:
        """`{"sides.<name>.<attribute>": value}` for `pipeline.sides` - or {} when no record is owed (S13) - each value validated by the
        writer's own check (`stage_done.coerce_value`, never a second validator). `s0_rest` applies it to the `pipeline` dict
        (`stage_done.apply_facts`) BEFORE `pipeline.json` is written, so the file is born with its sides in ONE write and S0 is never
        recorded done without them: a refused value is a `Refusal` there and S0 replays whole (INVARIANT: a side the person marked
        non-real is recorded before any stage after S0 can read it, never recorded as real by this function, AR-28).
        When a record is owed and the merged entries do not name `product`, the record also carries `product: real, deliverable: true,
        source: default` exactly when no entry is a real side of this team (`contract.product_implied`: `deliverable` true or absent;
        an entry with no reality is not real; PC2-7, t-043): whatever earlier stories recorded and with or without `--no-trace`, so no
        reader loses the implicit side (the Lead's call, t-2378 (b))."""
        import contract
        import stage_done
        got = self._sides_entries(environment)
        entries, sets, now = got["entries"], {}, _now()
        if got["problem"]:
            # PC-1b (S12): a registry that could not be read, or a malformed side row, is written down as `sides_unknown` - the
            # stamp carries it and the ledger never reads those Thens as proved; the unknown side itself is never recorded as real
            try:
                sets = {"sides_unknown.at": stage_done.coerce_value("sides_unknown.at", now),
                        "sides_unknown.why": stage_done.coerce_value("sides_unknown.why", got["problem"])}
            except ValueError as exc:
                raise Refusal(f"the story's sides cannot be recorded: {exc}") from exc
        if not entries:
            return sets
        if contract.product_implied(entries):   # no entry is a real side of this team: `product` is implied (PC2-7; as story_sides(root=) reads it)
            entries.setdefault("product", {"reality": self.SIDE_REAL, "deliverable": True, "source": "default"})
        try:
            for name in sorted(entries):
                entry = entries[name]
                raw = {"reality": entry["reality"], "deliverable": "true" if entry.get("deliverable", True) else "false",
                       "source": entry["source"], "at": now}
                if entry.get("settles_by"):
                    raw["settles_by"] = entry["settles_by"]
                if entry.get("reference"):
                    raw["reference"] = entry["reference"]
                for attr, value in raw.items():
                    key = f"sides.{name}.{attr}"
                    sets[key] = stage_done.coerce_value(key, value)
        except ValueError as exc:
            raise Refusal(f"the story's sides cannot be recorded: {exc}") from exc
        return sets

    def _keep_sides_answer(self, name: str, door: str, words: str = "", where: str = "") -> list:
        """t-2181 PC-2 (writer 2 of the sides): the person's answer to `sides.deliverable` for the side `name` is kept in the launch
        record (`launch.sides_answers`), the one place that outlives the S0 stop; `s0_sides_sets` carries it into
        `pipeline.sides` with `source: person`. The question is asked once per side, because the next entry finds the answer here.
        t-2559 (W2 B3): `words` (the person's own words, default the closed answer) and `where` (what the answer was to) let the S5
        hold's `not ours` answer use this ONE writer; `door == "ours"` is the only true. Returns the lines of this call that say the
        registry did not take the answer (t-2562 F-1: the S5 caller carries them to `pipeline.warnings`, `s0_rest` reads the launch list)."""
        launch = self.state.setdefault("launch", {})
        launch.setdefault("sides_answers", {})[name] = (door == "ours")
        self.save_state()
        said: list = []

        def not_kept(line: str) -> None:
            # the line goes to stdout AND to `launch.sides_not_kept`, which `s0_rest` turns into `pipeline.warnings` (a carrier the
            # report and gate A read; stdout is lost once the process ends)
            print(line)
            said.append(line)
            lines = launch.setdefault("sides_not_kept", [])
            if line not in lines:
                lines.append(line)
            self.save_state()
        # PC-1b, writer 2 of the registry (`by: driver`, `source: person`): the project keeps the answer, so the next story is not
        # asked. An experiment (`--no-trace`) records nothing (P8): the answer stays in this story's `pipeline.sides`, and one line
        # says so. The words are the closed answer the person gave (the caller hands over the door, not the raw text).
        if getattr(self.flags, "no_trace", False) or launch.get("no_trace"):
            not_kept(f"your answer about {name} was kept for this story only (an experiment leaves no trace)")
            return said
        try:
            import project_knowledge as PK
            row, problem, _ = PK.record(self.project, key=PK.SIDES_KEY, environment="", element=name, state=PK.KNOWN, scope="project",
                                        value={"deliverable": door == "ours", "settles_by": ""}, words=words or door, source="person",
                                        story=self.task, by="driver",
                                        where=where or "the answer to sides.deliverable at the start of the story")
            if row is None:
                not_kept(f"your answer about {name} was kept for this story only: the project's record of sides did not take it ({problem})")
        except Exception as exc:    # the answer is kept in the story either way; the registry is a convenience for the next one
            not_kept(f"your answer about {name} was kept for this story only: the project's record of sides could not be written "
                     f"({type(exc).__name__})")
        return said

    def s0_is_text(self, words: str) -> bool:
        """Is this answer a ticket pasted as text? Any non-empty text is (C9) - but a bare word that is a door
        of some S0 stop (`go on`, `retry`, a stand's name ...) is the person's word to a stop, never a ticket:
        `go on` typed at the `ticket_read` question must not become a one-word ticket (t-267 K6, negative).
        A closed list of the factory's own tokens is matched, never a person's wording (FR-12)."""
        one = self.s0_normalize(words)
        if not one:
            return False
        stands = {self.s0_normalize(str(e.get("name"))) for e in self.config.get("environments") or []
                  if isinstance(e, dict) and e.get("name")}
        return one not in self.S0_DOOR_WORDS and one not in stands

    def s0_passed(self, block: str, problems: list | None = None) -> bool:
        """Has the person's word already passed this block? A pass belongs to ONE block: `go on`
        on the incomplete ticket does not pass the readiness check, and a `go on` on readiness is
        a pass of its own. The incomplete-ticket pass holds only while what the check finds now
        is what the person was shown - a new problem raises the block again and names it."""
        saved = (self.state.get("s0_passes") or {}).get(block)
        if not saved:
            return False
        if problems is not None and not set(problems) <= set(saved.get("problems") or []):
            return False
        self._s0_passed.append((block, saved["words"]))
        if not saved.get("recorded"):
            self.s0_file_pass(block, saved)
        print(f"S0: {self.S0_PASS_NAMES.get(block, block)} passed by the person's word")
        return True

    def s0_file_pass(self, block: str, saved: dict, *, essence: str = "", key: str = "") -> None:
        """A pass is written down (FR-4): the block, the words, and - because every S0 block is
        the factory's own check - a finding in the person's words. The key makes it once per
        story and block. A failure is printed and never blocks the story.

        `essence` and `key` (both) file the same finding for a stop that is not a pass: the factory's
        own reader losing a criteria section (`s0_criteria_stop`, D-0050) is its defect from the moment
        it is shown, whatever the person then says - ONE filing call, not a second inline copy of it.
        `saved["witness"]` is the finding's witness; `saved["recorded"]` is set for a pass only."""
        # A refused filing is OWED (C1-7a, FR-4): the idempotency key makes the second write safe, and `recorded` below means "filed or owed"
        # (the ladder writes it again before the next brief; it ends in the seam's question, never in a print).
        self.owe_row(
            "project_decisions.py", "--root", str(self.project), "add-finding",
            "--essence", essence or f"S0 {block} passed by the person's word: {self.s0_quote(saved['words'])}",
            "--scope", "local-calibration", "--witness", saved.get("witness") or f"S0 {block}",
            "--idempotency-key", key or f"s0-pass:{self.task}:{block}",
            what=f"the finding about {'the lost read' if key else 'the pass'} at the start of the story")
        if not key:
            saved["recorded"] = True
            self.save_state()

    # --- the ticket by REST, in a light form (t-267, D-06) -----------------------------------------------

    # The tracker agent is a WRITE channel and not a data source: S0 reads the story's ticket with
    # `ticket_adapter get --raw-dir`, one call, no model. What it cannot read is the person's question
    # (`ticket_read`, FR-50's three answers); a login the tracker stopped accepting is an infrastructure
    # stop (exit 5, the door named), never a question about a ticket the person did nothing to. What the
    # parser found in what came back is judged by ONE structural check, `s0_criteria`: a title the reader took
    # from the first line and a criteria section the reader lost (a heading with text under it and no criteria
    # read, D-0050) are the person's questions (F2, F5), an empty title from the tracker is a refusal; a ticket
    # with no criteria section at all is a line in the story's record, never a question (P23); nothing reads the
    # words of the ticket for a phrase (FR-12).
    # A read that fails has one of FOUR owners, said by the adapter's exit code and error object (t-281 F3, t-287):
    # the tracker's (the `ticket_read` question; `retry_at` is read from the object), the project's setting (owner
    # `config`, the same question with the adapter's sentence verbatim), the factory's (a refusal that names the
    # file or the setting) and the login's (a stop; it also covers a token variable the shell lacks). No sentence
    # is matched.
    # The label a snapshot already on disk is reported under (K11, temporal): the route that wrote it, as
    # that snapshot named it. `jira_direct_api` is the label before t-267; `file` is the file adapter's and
    # the paste of before D-06 (the route is unknown); `agent` is the removed relay.
    SNAPSHOT_ROUTES = {"fetched": "fetched", "person_pasted": "person_pasted",
                       "jira_direct_api": "fetched (older label)",
                       "file": "file (route before D-06 unknown)",
                       "agent": "agent (route removed by D-06)"}

    def direct_api_usable(self) -> bool:
        """Is the tracker read by REST in this project? The adapter's own test (`ticket_adapter` decides what
        `usable` means, so it never drifts from what `get` really requires): a Jira adapter with a recorded
        `direct_api` whose address, auth type and secret reference are complete."""
        try:
            import ticket_adapter
            kind, adapter_cfg = ticket_adapter.resolve_adapter(self.config)
            return kind == "jira" and bool(adapter_cfg.get("direct_api")) and ticket_adapter.has_usable_direct_api(adapter_cfg)
        except Exception:               # a config nobody can read is "not usable": the question names the way on
            return False

    def tracker_door(self) -> str:
        """The environment variable that holds the tracker's token, as the project's own config names it."""
        direct = (((self.config.get("adapters") or {}).get("ticket") or {}).get("direct_api")) or {}
        return str(direct.get("secret_ref") or "").removeprefix("env:") or "the tracker token variable"

    def ticket_auth_lead(self) -> str:
        """The body both `ticket_auth` questions open with: what happened, in the story's words - no variable name, no command (the
        variable stands in the answer block, human-questions.md rule 5)."""
        return (f"The tracker no longer accepts this machine's token, so ticket {self.task} could not be looked at. Nothing about the "
                "story is wrong and nothing was recorded as not found.")

    def ticket_auth_note(self) -> str:
        return (f"The token the tracker reads is held in the environment variable {self.tracker_door()}; "
                "the shell the factory runs from needs it.")

    def s0_ticket_auth_question(self, said: str) -> None:
        """The tracker stopped accepting the token while S0 read the ticket (the adapter's exit 5, owner `auth`): the closed question
        `ticket_auth` (C1-3 F3 a; FR-50: access the work needs from outside is asked for, and the person can renew it, paste the
        ticket, or say the ticket is not needed). It is NOT the infrastructure of `claude -p` (`InfraStop`, exit 5): the person has
        something to decide, so a question exists (exit 3)."""
        line = " ".join(str(said or "").split())[:300]
        self.s0_stop(
            "ticket_auth", "halt",
            self.closed_question(
                "s0.ticket_auth",
                f"{self.ticket_auth_lead()} Nothing after this point was tried.\n\nWhat I need from you is one of these:",
                [{"answer": "retry", "token": "retry", "says": "renew the token the tracker accepts, and I read the ticket again",
                  "slots": {"what": "renew the tracker token"}},
                 {"answer": "not needed", "token": "not needed",
                  "says": "the story can go without this ticket: if I already hold part of it the story goes on with that part "
                          "and says so, and if I hold nothing the story ends here, because there is nothing to build it from"},
                 self.PASTE_OPTION, self.STOP_OPTION]),
            {"retry": "retry", "not needed": "not needed"},
            details=f"Ticket {self.task}: the tracker refused the token.\nThe tracker adapter said:\n{line or 'nothing'}",
            problems=["ticket_auth"], paste=True, answer_note=self.ticket_auth_note())

    def ticket_auth_person(self, said: str) -> "Person":
        """The same loss met by the freshness check of a story already running (`ticket_look_failed`): kind `ticket_auth`, three
        answers - `retry` (look again), `go on` (the story goes on with the text it was built on; `ticket_unchecked`, and the pass
        is kept for the freshness window, FR-4) and `stop`."""
        line = " ".join(str(said or "").split())[:300]
        text = self.closed_question(
            "fresh.ticket_auth",
            f"{self.ticket_auth_lead()} The story has its text from before, and the look at the ticket is only a check that the "
            "requirements have not moved.\n\nWhat I need from you is one of these:",
            [{"answer": "retry", "token": "retry", "says": "renew the token the tracker accepts, and I look at the ticket again",
              "slots": {"what": "renew the tracker token"}},
             {"answer": "go on", "token": "go on",
              "says": "go on with the text the story was built on, without the check; that is recorded, and I ask again only after "
                      "the check would be due again"},
             self.STOP_OPTION])
        return Person("ticket_auth", text, "S0", details=f"Ticket {self.task}: the tracker refused the token.\n"
                      f"The tracker adapter said:\n{line or 'nothing'}", answer_note=self.ticket_auth_note())

    def s0_kept_snapshot(self):
        """`(ticket, the file's text)` of the snapshot an earlier entry of S0 (or an earlier route) left, or
        None. It is read as it is and never rewritten: its sha256 is the story's `source_revision`, and a
        second REST read would change `fetched_at` and with it the hash (K11, temporal). S0 never rewrites it;
        after S0 only `ticket_adapter.py freshness` does (a `context` change, or `--adopt` after the person chose
        the new text - `Driver.ticket_freshness`, B-364), and `source_revision` stays the value `initialize` took
        (phases/s0.md section 2b): no decision goes stale silently."""
        path = self.task_root / "work" / self.SNAPSHOT
        try:
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        ticket = self.json_object(text)
        return (ticket, text) if ticket is not None else None

    def s0_ticket(self, ticket_file) -> tuple:
        """`(ticket, the snapshot's text, "from the ticket file" | "through the tracker", kept)`: the story's one
        ticket. A snapshot already on disk is the ticket (read as it is, labelled by the route that wrote it);
        else the person's file or paste (`--ticket-file`) - the requirement, with the tracker read BESIDE it
        for a comparison when REST is set up (F27); else the tracker, by REST. A LOCAL story's text file
        (`qa-factory/local-tickets/<KEY>.md`) is its ticket file (SS1-14)."""
        ticket_file = self.s0_local_file(ticket_file)
        how = "from the ticket file" if ticket_file else "through the tracker"
        kept = self.s0_kept_snapshot()
        if kept:
            ticket, text = kept
            route = str(((ticket.get("provenance") or {}).get("source")) or "")
            label = self.SNAPSHOT_ROUTES.get(route, f"{route} (older label)" if route else "unknown (no provenance recorded)")
            word = ("; you said the ticket is not needed, so the story goes on with it"
                    if (self.state.get("s0_answers") or {}).get("ticket_read") == "not needed" else "")
            print(f"S0: work/{self.SNAPSHOT} is already there ({label}); it is read as it is and not written again{word}")
            return ticket, text, how, True
        if ticket_file:
            # The person's text, parsed by the adapter with the same parser as a fetched description. With the raw
            # folder named, a read with no tracker beside it still leaves `work/ticket-references.json` (F4).
            code, out, ticket, both, failure = self.ticket_get("--ticket-file", ticket_file, *self.s0_raw_flags())
            if code:
                if self.ticket_is_factory_fault(code, failure):
                    raise self.ticket_factory_refusal(code, failure, both)
                if (failure or {}).get("owner") == "person":
                    # t-335 B-n4: the person's own file is missing or empty - theirs to supply. A raw `Refusal` here
                    # reached the conductor with the adapter's words; it is the same `ticket_read` question the
                    # tracker's failure raises, with the path in the answer block only.
                    self.s0_ticket_read_question(code, both, failure, own_file=True)
                raise Refusal(f"ticket_adapter get {self.task} (exit {code}):\n{both}")
            return ticket, self.s0_compare(ticket, out), how, False
        ticket, out = self.s0_rest_read()
        return ticket, out, how, False

    def s0_raw_flags(self) -> list:
        """The one place that builds the raw-folder flags of S0's reads (t-281 F4): the REST read of the story and
        the comparison read beside a pasted ticket pass the same `--raw-dir work/ticket-raw`, so the raw folder, the
        line view and the references exist on both legs and a paste-only read names the same folder."""
        return ["--raw-dir", str(self.task_root / "work" / "ticket-raw")]

    def s0_rest_read(self) -> tuple:
        """The ticket by REST, one call: `ticket_adapter get <T> --json --raw-dir work/ticket-raw` (the adapter
        leaves the raw responses, the line view, the references and the seeds S1 reuses beside the light
        snapshot it prints). A lost login (exit 5) is the `ticket_auth` question; any other failure is the person's
        `ticket_read` question - unless they already said the ticket is not needed, which ends the story here."""
        if (self.state.get("s0_answers") or {}).get("ticket_read") == "not needed":
            # P01 (C1-3 F2 a): not an exit with a command to run by hand but the question again, with the way on in it: `retry`
            # (the earlier `not needed` is dropped and the ticket is read again), the text itself, or `stop`.
            self.s0_stop(
                "ticket_read", "halt",
                self.closed_question(
                    "s0.ticket_read.not_needed_empty",
                    f"You said ticket {self.task} is not needed, and nothing of it was read, so there is no text to build "
                    "requirements, a plan or test cases from. The story cannot go on like this and nothing was written."
                    "\n\nWhat I need from you is one of these:",
                    [{"answer": "retry", "token": "retry",
                      "says": "I drop your earlier `not needed` and read the ticket again", "slots": {"what": "make the ticket readable"}},
                     self.PASTE_OPTION, self.STOP_OPTION]),
                {"retry": "retry"}, details=f"Ticket {self.task}: `not needed` was answered and no snapshot of the ticket exists.",
                problems=["ticket_read"], paste=True)
        code, out, ticket, both, failure = self.ticket_get(*self.s0_raw_flags())
        if code == 0 and ticket is not None:
            self.state.pop("s0_rest_failed", None)       # the tracker answers now: a later comparison reads it again
            return ticket, out
        import ticket_adapter
        if code == ticket_adapter.EXIT_AUTH_LOST and (failure or {}).get("owner") != "intermediary":
            # B-408 (E23): exit 5 with owner `intermediary` is NOT a lost login - something between this machine and the
            # tracker answered, the token was not judged - so it falls through to the `ticket_read` question below
            # (the owner is read as a field, never from the sentence, E24). Every other exit 5 is the `ticket_auth` question (F3 a).
            self.s0_ticket_auth_question(both)
        if self.ticket_is_factory_fault(code, failure):
            # The factory's own data or setting, not the tracker's: reported with the file named, never a question
            # about the network (F3, FR-3). Nothing is written for the story and no question is left open.
            raise self.ticket_factory_refusal(code, failure, both)
        self.s0_ticket_read_question(code, both, failure)

    def s0_ticket_read_question(self, code: int, said: str, failure: dict | None = None, own_file: bool = False) -> None:
        """The read did not come: the `ticket_read` question, FR-50's three answers, in the story's words. The
        text names every route tried and why it failed; the adapter's own words go to the details file. The
        register keys a repeat by this block and the story's key, and a retry that fails the same way comes back
        as the same question with the earlier answer shown (FR-7, `ask`). The time the tracker asked to be tried
        again at is `failure["retry_at"]`, the adapter's error object (t-281 F3) - no sentence is searched.
        `own_file`: the read was of the file the person NAMED (`--ticket-file`), so the project's folder of ticket
        files is not what was looked at, and the tracker was not read at all (no `s0_rest_failed` mark for the
        comparison that follows a paste)."""
        adapter = (self.config.get("adapters") or {}).get("ticket") or {}
        kind = str(adapter.get("kind") or adapter.get("name") or "").strip().lower()
        retry_at = str((failure or {}).get("retry_at") or "")
        note = ""
        if (failure or {}).get("owner") == "config":
            # t-287 item 2: the adapter said the project's own direct-API setting is incomplete (owner `config`); the
            # three answers stay (FR-50: the person may paste the ticket instead). Never "Restore what the message
            # names". t-363 B3 (B-256 g): its sentence - which keys, and the onboarding command - is an INSTRUCTION, so
            # it goes to the person WHOLE (FR-8) but into the answer block (human-questions.md rule 5), where a key
            # path and a command may stand; the body says "the setting named below" and stays answerable without them.
            tried = ("What stands in the way: the way this project reads tickets from the tracker directly is not set "
                     "up completely - the setting named below is missing or cannot be used.")
            fix = "record the setting named below for this project"
            named = " ".join(str((failure or {}).get("message") or "").split())
            note = ("The setting this is about, in the factory's own words: "
                    + (named or "the adapter named none; the onboarding step records the tracker's settings "
                       "(/qa-factory:qa-onboarding)"))
        elif kind == "file" and not own_file:
            tried = (f"I looked for the file {self.task}.md in the folder of ticket files this project names, and it "
                     "is not there or cannot be read.")
            fix = "put the ticket file in that folder"
        elif (failure or {}).get("owner") == "person":
            # t-329 item 6: the adapter said the ticket text the PERSON gave or keeps is missing or empty (owner
            # `person`), and the answer is theirs to give: the file at that path, or the text pasted (the three
            # answers stay, FR-50). The same kind of question as the `file` branch above, for a read that is not a
            # project folder's. t-335 B-n4: the path is an instruction, so it stands in the answer block and nowhere
            # in the body (human-questions.md rule 5); an adapter that names no file (an older one) is relayed as it was.
            named = str((failure or {}).get("file") or "")
            if named:
                tried = "The ticket text you gave me is missing or empty: the file named under \"How to answer\" below holds no ticket."
                fix = "put the ticket text in that file"
                note = f"The ticket file I looked for: {named}"
            else:
                tried = f"What stands in the way: {failure.get('message')}"
                fix = "put the ticket text in the file the message names"
        elif (failure or {}).get("owner") == "intermediary":
            # B-408: the adapter said what answered was not shown to be the tracker's own (owner `intermediary`: a
            # firewall, a proxy, a protection service, or an answer that could not be read) and that the token was NOT
            # judged. The body asserts no author and no token claim (FR-41); the title and the check go in the answer
            # block (`answer_note`, human-questions.md rule 5) in the factory's own words, never in the body. The three
            # answers stay (FR-50): `retry` after the check, `not needed`, or the pasted ticket.
            tried = (f"I asked the tracker for {self.task} through its web interface, and the answer did not come "
                     "from the tracker in a form I can read: something between this machine and the tracker (a "
                     "firewall, a proxy or a protection service) answered instead, or the answer could not be read. "
                     "I could not check whether the account's token works.")
            fix = ("check the tracker's address from this machine, outside the factory, with the command below: if it "
                   "answers 200 with application/json, the protection lets your machine through but not the factory's "
                   "requests — ask whoever runs it to let them through; if it does not, the network or the VPN is in "
                   "the way")
            direct = adapter.get("direct_api") if isinstance(adapter.get("direct_api"), dict) else {}
            base = str(direct.get("base_url") or "").strip()
            import http_client
            note = ("What answered, in the factory's own words: " + " ".join(str((failure or {}).get("message") or "").split())
                    + (("\nCheck: " + http_client.curl_line(f"{base.rstrip('/')}/rest/api/{direct.get('api_version') or '2'}/serverInfo"))
                       if base else ""))
        elif self.direct_api_usable():
            tried = (f"I asked the tracker for {self.task} through its web interface, with the account recorded for "
                     "this project, "
                     + ("and it answered that there is no such ticket, or that this account may not see it."
                        if code == 1 else "and it did not answer in a way I can use"
                        + (f": it asked to be asked again at {retry_at}." if retry_at else ".")))
            fix = ("fix what is in the way (the network or the VPN, this account's access to the ticket, the key "
                   "itself)")
        else:
            tried = ("No way to read a ticket is set up for this project: the tracker's web interface has no complete "
                     "address and token recorded, and the Jira assistant is not used to read tickets - it only "
                     "writes to them.")
            fix = "record the tracker's address and token for this project (onboarding does it)"
        # SS1-15: a tracker the role reads by a recorded route: the route stands in the answer block (human-questions.md rule 5),
        # the question and its three answers are the same (FR-50, FR-7)
        import ticket_adapter
        from source_inventory import tracker_route
        route = tracker_route(self.config)
        if route and ticket_adapter.reads_by_role(self.config):
            note = ((note + "\n") if note else "") + (
                f"The project's recorded route: {route['method'] + ', ' if route['method'] else ''}{route['ref']}. The conductor "
                "reads the ticket by it, saves the text and answers with the ticket file.")
        if not own_file:
            self.state["s0_rest_failed"] = (" ".join(str(said or "").split()).removeprefix("ticket_adapter: ")[:200]
                                            or f"the read ended with code {code}")
        self.s0_stop(
            "ticket_read", "halt",
            self.closed_question(
                "s0.ticket_read",
                f"I tried to read ticket {self.task} and could not, so I have no ticket text to build the story from. "
                f"{tried}\n\nI did not fill the gap with a guess: the requirements, the test plan and every test case "
                "are built from that text.\n\nWhat I need from you is one of these:",
                [{"answer": "not needed", "token": "not needed",
                  "says": "the story can go without this ticket: if I already hold part of it the story goes on with that part "
                          "and says so, and if I hold nothing the story ends here, because there is nothing to build it from"},
                 {"answer": "retry", "token": "retry", "says": f"{fix}, and I read the ticket again", "slots": {"what": fix}},
                 self.PASTE_OPTION, self.STOP_OPTION]),
            {"retry": "retry", "not needed": "not needed"},
            details=f"Ticket {self.task}: the read by code did not come.\nThe tracker adapter said:\n{(said or '').strip() or 'nothing'}",
            problems=["ticket_read"], paste=True, answer_note=note)

    def s0_compare(self, ticket: dict, out: str) -> str:
        """F27 / C6: the person's ticket (`--ticket-file`, or the paste) is the requirement; when REST is set up
        the tracker is read BESIDE it, never instead. Both present: `compare_person_vs_rest` -> ONE line (FR-25:
        which record is authoritative, and the gap) and `disagreements[]` in the snapshot. The tracker FAILING
        prints ONE line and never asks: the person gave the text because the tracker was not the way, and a
        question here would loop. A story whose read failed a moment ago is not asked again (one line, no call).
        A LOCAL story (SS1-14): no tracker holds its key, so there is nothing to compare and no call is made."""
        if self.s0_is_local():
            print("local story: no tracker holds this key, nothing to compare")
            return out
        if not self.direct_api_usable():
            return out
        failed = self.state.get("s0_rest_failed")
        if failed:
            print(f"the tracker could not be read for comparison: it could not be read a moment ago either ({failed})")
            return out
        try:
            code, rest_out, rest, both, failure = self.ticket_get(*self.s0_raw_flags(), echo=False)
        except Refusal as refusal:
            code, rest, both, failure = 1, None, refusal.text, None
        if code or rest is None:
            why = " ".join(str(both or "").split()).removeprefix("ticket_adapter: ")[:240] or f"the read ended with code {code}"
            if self.ticket_is_factory_fault(code, failure):
                # The factory's own fault is REPORTED here, in the one line: the person's text is the requirement
                # and the story goes on with it (C6: the comparison never stops the paste, never asks).
                named = f" `{failure['file']}`" if failure and failure.get("file") else ""
                why = f"the factory's own data or setting{named} is not usable ({why})"
            print(f"the tracker could not be read for comparison: {why}")
            return out
        self.s0_label_compare_view()
        import ticket_light
        found = ticket_light.compare_person_vs_rest(ticket, rest)
        print(found["line"])
        ticket["disagreements"] = found["disagreements"]
        import ticket_adapter
        return ticket_adapter.snapshot_text(ticket)       # one format function for the snapshot (L3, t-428)

    COMPARE_VIEW_LINE = ("The tracker's text, read for comparison; the story's requirement is the text the person gave "
                         "(ticket-snapshot.json)")

    def s0_label_compare_view(self) -> None:
        """The comparison read leaves `work/ticket-view.md` of the TRACKER's text beside the person's snapshot; a role
        reading it must not take it for the requirement. ONE first line says what it is (the REST leg's view is the
        story's own text and carries none). Said once: a view that already begins with it is left as it is."""
        view = self.task_root / "work" / "ticket-view.md"
        try:
            text = view.read_bytes().decode("utf-8")        # bytes: the tracker's CRLFs stay as they are
            if not text.startswith(self.COMPARE_VIEW_LINE):
                view.write_bytes((self.COMPARE_VIEW_LINE + "\n" + text).encode("utf-8"))
        except (OSError, UnicodeDecodeError):
            pass                    # no view (an older adapter): nothing to label, and the comparison goes on

    def s0_criteria(self, ticket: dict, how: str, source_file=None) -> str | None:
        """The ONE structural check of the ticket (F2, F4, F5): a title the reader took from the FIRST LINE of a
        text (no `# ` line in it) is the person's question once - `go on` keeps it, `retry` reads the file again
        after they added a title line - and the pass is written down (FR-4); a ticket read with no title at all
        (an empty summary from the tracker, a ticket file with none) is a refusal. Criteria (D-0050, P23): a ticket
        that read criteria goes on; one with NO criteria section goes on too and the return value is the line for
        the story's record (`pipeline.warnings`, the FIRST of them - gate A shows five), never a question; the only
        stop is a criteria section with text under it that the reader read nothing from (`s0_criteria_stop`: the
        factory's reader failed, not the ticket). Nothing here reads the text for a word; the parser found a
        title and a list, a heading and its lines, or it did not. The error direction is "a false question
        rather than a silent pass over a section with text in it" (I4).

        `source_file` (t-287 item 6): the file this ticket was actually read from - the person's file or the paste
        the driver stored (`driver-tmp/ticket-<T>.md`) - so that the question names the file the answer is read
        from, relative to the project; None when nothing was read from a file (the tracker, a kept snapshot)."""
        title = str((ticket.get("title") or "")).strip()
        where = f" (the file `{self.s0_rel_path(source_file)}`)" if source_file else ""
        read = f"from the ticket file `{self.s0_rel_path(source_file)}`" if source_file else how
        at_top = f"at the top of the file `{self.s0_rel_path(source_file)}`" if source_file else "at the top of your text"
        if (ticket.get("provenance") or {}).get("title_from") == "first_line":
            problems = ["title taken from the first line"]
            wiki = (ticket.get("provenance") or {}).get("markup") == "wiki"
            if wiki:
                # a text with `h2.`-style headings: `# ` is a list item there, so the title is a `title:` line of the header
                found = ("its header has no `title:` line, and a line that starts with `# ` is a list item in this kind "
                         "of text, never a title. I took this line as the title")
                put = (f"in a header {at_top}: a line `title: <the title>` between two lines of three dashes")
                seen = "no `title:` line in the header; this line was taken as the title: "
            else:
                found = "no line starts with `# `. I took its first line as the title"
                put = f"on a line that starts with `# ` {at_top}"
                seen = "no line starting with `# `; the first line was taken as the title: "
            if not self.s0_passed("ticket_title", problems):
                self.s0_stop(
                    "ticket_title", "halt",
                    self.closed_question(
                        "s0.ticket_title",
                        f"I read the ticket you gave me for {self.task}{where} and could not find a title in it: "
                        f"{found}: \"{self.s0_quote(title)}\". Nothing in "
                        "your text was changed, and the criteria and the comments are read from it as they stand."
                        "\n\nWhat I need from you is one of these:",
                        [{"answer": "go on", "token": "go on",
                          "says": "that line will do as the title; the story then carries a line saying that you accepted it"},
                         {"answer": "retry", "token": "retry", "says": f"put the title {put}, and I read it again",
                          "slots": {"what": "put the title in the ticket"}},
                         {"answer": "paste", "says": "paste the ticket again with a title - I use that instead",
                          "slots": {"what": "paste the ticket with a title"}},
                         self.STOP_OPTION]),
                    {"retry": "retry", "go on": "go on"},
                    details=f"Ticket {self.task}, read {read}.\nWhat the reader found:\n- {seen}{title}",
                    problems=problems, paste=True)
        elif not title or title == self.task:
            # P05 (C1-3 F2 a): a ticket with no title at all is the person's question - the paste door reads the ticket, which a
            # seam-raised refusal question would not (no `s0_block` is set there) - never "run the story again".
            self.s0_stop(
                "ticket_no_title", "halt",
                self.closed_question(
                    "s0.ticket_no_title",
                    f"I read ticket {self.task} {read} and it carries no title. The story needs a ticket with a title: a ticket "
                    "file holds it on a line that starts with `# `, and the tracker's summary is it for a fetched ticket. Nothing "
                    "was written.\n\nWhat I need from you is one of these:",
                    [{"answer": "retry", "token": "retry", "says": "put the title in the ticket (or the file), and I read it again",
                      "slots": {"what": "put a title in the ticket"}}, self.PASTE_OPTION, self.STOP_OPTION]),
                {"retry": "retry"}, details=f"Ticket {self.task}, read {read}.\nWhat the reader found:\n- no title",
                problems=["no title"], paste=True)
        if ticket.get("acceptance_criteria"):
            return None
        return self.s0_criteria_gap(ticket, read)

    S0_LINE_LIMIT = 180                   # gate A shows the first five warnings, each cut here (gate_brief): the line must fit whole

    def s0_criteria_scan(self, ticket: dict) -> dict:
        """What the ONE criteria-heading scanner (`ticket_light.criteria_section`) finds in the stored text of a ticket
        that read no criteria: `lost` - the first section with text under it (its heading line, line count, first line),
        `empty` - the first heading with nothing under it, `headings` - the names looked for; `unreadable` when the
        list of names cannot be built (the table is stale: nothing is established, FR-59). The text is scanned under
        BOTH markups, wiki and markdown, because a snapshot does not always say which it was (a REST one never does),
        and with the title line put back when the reader took it from the first line (the heading may be the line the
        title consumed): the scan may find a section the reader did not (a false stop), never miss one it found (I4)."""
        import ticket_adapter
        import ticket_light
        text = str(ticket.get("description") or "")
        provenance = ticket.get("provenance") or {}
        if provenance.get("title_from") == "first_line":
            text = str(ticket.get("title") or "") + "\n" + text
        lost = empty = None
        # two owners, told apart by WHICH call fails and never by the wording of the error (FR-12): the factory's own table
        # (`load_fields_table`) is the factory's, the project's `config.json` key (`acceptance_headings_for` with the table in hand) is the project's
        try:
            table = ticket_light.load_fields_table()
        except Exception as err:        # noqa: BLE001 - a table that cannot be read establishes nothing; the caller stops
            return self.s0_scan_unreadable("factory", err)
        try:
            heads = ticket_adapter.acceptance_headings_for(self.config, table)
        except Exception as err:        # noqa: BLE001 - the project's own key; the error names the key and its fix
            return self.s0_scan_unreadable("config", err)
        try:
            for markup in (("markdown", "wiki") if provenance.get("markup") == "markdown" else ("wiki", "markdown")):
                for section in ticket_light.criteria_section(text, headings=heads, section_names=table["section_names"], markup=markup)["sections"]:
                    if section["content_lines"]:
                        lost = lost or section
                    else:
                        empty = empty or section
        except Exception as err:        # noqa: BLE001 - the factory's reader failing on the text establishes nothing either
            return self.s0_scan_unreadable("factory", err)
        return {"headings": heads, "lost": lost, "empty": empty, "unreadable": False, "owner": "", "said": ""}

    @staticmethod
    def s0_scan_unreadable(owner: str, err: Exception) -> dict:
        """The scan result when the list of names cannot be built: `owner` is `config` (the project's key) or `factory` (its own file or
        reader); `said` is the error's own sentence, which names the key or the file and how to restore it (FR-1) - relayed whole (FR-8)."""
        return {"headings": None, "lost": None, "empty": None, "unreadable": True, "owner": owner, "said": " ".join(str(err).split())}

    S0_LOST_READ = "criteria section unread"                # the problem word of a section the reader lost (a pass on it covers only that)

    S0_HEADINGS_UNREADABLE = "criteria headings unreadable"  # a DIFFERENT fact: the list of names cannot be built. One word per fact:

    # a `go on` given to one stop never covers the other (`s0_passed`: "a new problem raises the block again and names it")

    def s0_criteria_gap(self, ticket: dict, read: str) -> str | None:
        """A ticket that read NO criteria (D-0050, P23). A criteria section with text under it that the reader read nothing
        from is the FACTORY's failure (FR-46): ONE closed question that says so, whose answers are only roads - paste the
        ticket again, go on with the description whole, stop (no `retry`: the reader is deterministic, the same text reads the
        same, FR-2) - and a finding the moment it is shown. A list of names that cannot be built is a stop too (FR-59: an unknown
        is not a pass), but its owner is told (the project's `config.json` key, or the factory's own file), it has its OWN problem
        word, and it never offers the paste: the same list would stop the same ticket again (FR-2). Anything else goes on: the
        return value is the line for `pipeline.warnings` (gate A), saying what was looked for, never "there are no
        requirements" (FR-41). `None` when a stored pass of the person covers the stop, the pass line being theirs to write
        (`s0_passed`; the legacy problem word of a pass stored before D-0050 covers a lost read too, FR-14)."""
        scan = self.s0_criteria_scan(ticket)
        if not (scan["lost"] or scan["unreadable"]):
            return self.s0_criteria_line(scan)
        lost = scan["lost"]
        problems = [self.S0_LOST_READ if lost else self.S0_HEADINGS_UNREADABLE]
        if self.s0_passed("ticket_incomplete", problems) or (lost and self.s0_passed("ticket_incomplete", ["no acceptance criteria"])):
            return None
        go_on = {"answer": "go on", "token": "go on",
                 "says": "go on: the requirements are read from the whole description, where that text stays; "
                         "the story then carries a line saying that you accepted it"}
        note = ""
        if lost:
            found = (f"I read ticket {self.task} {read} and found a section named `{lost['heading']}` in it, and read no "
                     "criteria from it - this is the factory's reader failing on that section, not your ticket. "
                     f"The section begins: \"{self.s0_quote(lost['first_line'])}\". Nothing in your text was changed.")
            saw = f"a section named `{lost['heading']}` with {lost['content_lines']} line(s) under it and no criteria read from it"
            witness = f"S0 {self.task}: {saw}: {self.s0_quote(lost['first_line'])}"
            essence = (f"S0: the reader found the criteria section `{lost['heading']}` in ticket {self.task} and read no "
                       "criteria from it - the factory's reader, not the ticket")
            key, paste, options = f"s0-criteria-unread:{self.task}", True, [self.PASTE_OPTION, go_on, self.STOP_OPTION]
        else:
            # the paste is NOT offered: it reads the same text against the same broken list and comes back to this stop (FR-2)
            fix_stop = {"answer": "stop", "token": "stop",
                        "says": "stop the story here; nothing runs, and you start it again once what is named below is fixed"}
            saw = "the list of names the criteria sections are looked for under could not be built"
            witness = f"S0 {self.task}: {saw}"
            key, paste, options = f"s0-headings-unreadable:{self.task}", False, [go_on, fix_stop]
            if scan["owner"] == "config":
                found = (f"I read ticket {self.task} {read}, but this project's setting for the names of the sections the criteria are "
                         "looked for under cannot be used, so I cannot tell whether the ticket has such a section. This is the "
                         "project's setting, not your ticket. Nothing in your text was changed.")
                essence = f"S0: the project's setting for the criteria heading names could not be used for ticket {self.task} - the project's config, not the ticket"
                note = "The setting this is about, in the factory's own words: " + (scan["said"] or "the adapter named none")
            else:
                found = (f"I read ticket {self.task} {read}, but I could not read the list of section names the criteria are "
                         "looked for under (a file of the factory's own is not usable), so I cannot tell whether the ticket "
                         "has such a section. This is the factory failing, not your ticket. Nothing in your text was changed.")
                essence = f"S0: the list of criteria heading names could not be built for ticket {self.task} - the factory's file, not the ticket"
                note = "The file this is about, in the factory's own words: " + (scan["said"] or "the reader named none")
        self.s0_file_pass("ticket_incomplete", {"witness": witness}, essence=essence, key=key)
        self.s0_stop(
            "ticket_incomplete", "halt",
            self.closed_question("s0.ticket_incomplete", found + "\n\nWhat I need from you is one of these:", options),
            {"go on": "go on"},
            details=f"Ticket {self.task}, read {read}.\nWhat the check found:\n- {saw}\n{self.s0_headings_looked_for()}",
            problems=problems, paste=paste, answer_note=note)

    def s0_criteria_line(self, scan: dict) -> str:
        """The line for `pipeline.warnings` of a ticket whose criteria section is absent or empty: what was looked for, in at most
        S0_LINE_LIMIT characters; the names are cut, not the sentence."""
        tail = "; the requirements are read from its description, comments, attachments and linked tickets"
        if scan["empty"]:
            heading = scan["empty"]["heading"]
            room = self.S0_LINE_LIMIT - len(f"S0: ticket {self.task} has a section `` with nothing under it{tail}")
            return (f"S0: ticket {self.task} has a section `{heading if len(heading) <= room else heading[:max(room - 3, 1)] + '...'}` "
                    f"with nothing under it{tail}")
        shown = list(scan["headings"])
        while True:
            line = f"S0: ticket {self.task} has no section named {', '.join(shown)}{' ...' if len(shown) < len(scan['headings']) else ''}{tail}"
            if len(line) <= self.S0_LINE_LIMIT:
                return line
            if len(shown) > 1:
                shown.pop()
            elif len(shown[0]) <= 4:          # nothing left to cut: the task id itself is the length
                return line
            else:                             # one name alone is too long (a long task id, a long project heading): cut the name
                shown = [shown[0][:max(len(shown[0]) - (len(line) - self.S0_LINE_LIMIT) - 3, 1)] + "..."]

    def s0_headings_looked_for(self) -> str:
        """The sentence that says where the criteria were looked for (t-281 F5): the headings verbatim, from the
        same merged list the reader used (the table of the light form plus the project's own), and the setting
        that adds a name. It states what was searched, not that nothing exists: a section named otherwise is the
        likely cause, and the person can name it. A list that cannot be built (the table is unreadable) says that
        in words; the adapter has refused the same table before this point, so this is the stale-file case."""
        import ticket_adapter
        try:
            names = ticket_adapter.acceptance_headings_for(self.config)
        except Exception:                # noqa: BLE001 - a text for a person is never lost to a table fault
            return ("I looked for a section named like the acceptance criteria, but the list of those names could not "
                    "be read.")
        return ("I looked for a section named one of: " + ", ".join(names) + ". If your ticket names that section "
                "otherwise, the name can be added to `direct_api.acceptance_headings` in `qa-factory/config.json`, "
                "and then I find it.")

    # -- the person's list of sources not to read (B-231, t-172) --------------------------------
    # `--skip-sources FILE` is the person's word given BEFORE the run: one source per line and why it is
    # left out. S0 reads it (before anything is fetched), asks about what it cannot use, and writes
    # `work/source-exclusions.json`; from then on every inventory write and every fetch door marks or
    # refuses what the record names (source_exclusions.py, source_inventory.py, ticket_adapter.py).
    SOURCE_LIST_SHOWN = 10          # problem lines one question lists; the rest read "and N more"

    LS_REMOTE_SECONDS = 10          # one ask of the remote per merge request; a slow remote is not waited for

    @staticmethod
    def list_tail(text: str) -> str:
        """The last path segment of a repository or project, lower case, without a `.git`."""
        last = [part for part in re.split(r"[/:]", str(text or "").strip().strip("/")) if part][-1:] or [""]
        return last[0].removesuffix(".git").lower()

    def checkout_for(self, repo: dict, want: str = "") -> tuple:
        """`(checkout, top, why)` for one `implementation_repos[]` entry: the folder to ask git in, the top level of
        the repository it lies in, and, when the entry cannot be used, ONE sentence for the person that carries its
        own door (the callers add only their consequence). `(None, None, "")` is an entry with no `local_path`.

        A `local_path` may name a folder INSIDE a repository (the application of a monorepo, or `.` when the code
        sits next to the project). The old test, a `.git` in that very folder, skipped such an entry without a word
        (B-412). The INVARIANT is the direction of error: git never asks a repository the config does not name.
        When the top level IS the folder, nothing more is checked (today's behaviour, worktrees and initialised
        submodules included). When the top level is ABOVE it, the repository's origin must be the one
        `remote_identity` names (host and path when both parse, the last segment otherwise) and, when `want` is
        given, the merge request's own project; anything else, or an unknown, is not used and says why. Shown
        origins are `host/path` or the last segment, never the raw URL: a remote may carry a token."""
        import test_repo_base as TRB
        import http_client
        import ticket_light
        local = str(repo.get("local_path") or "")
        if not local:
            return None, None, ""
        rid = str(repo.get("repo_id") or repo.get("name") or "the repository")
        door = f"; point `local_path` of {rid} in `qa-factory/config.json` at a checkout of that repository"
        try:
            checkout = (self.project / local).resolve()
            present, folder = checkout.exists(), checkout.is_dir()
        except (OSError, ValueError):
            return None, None, f"`{local}` cannot be read as a path{door}"
        if not present or not folder:
            return None, None, f"`{local}` " + ("is not a folder" if present else "does not exist") + door
        if shutil.which("git") is None:
            return None, None, "git is not on PATH; install git or put it on PATH"
        found = TRB._top_and_prefix(checkout)
        if found is None:
            if TRB._inside_a_repository(checkout):
                return None, None, f"git could not answer in `{local}`; `git -C {local} status` shows what git says"
            return None, None, f"`{local}` is not inside a git repository{door}"
        top = found[0]
        if TRB._same_dir(top, checkout):
            return checkout, top, ""
        try:
            where = os.path.relpath(top, self.project).replace(os.sep, "/")
        except ValueError:                # another drive: the last segment names it, and a line never crashes
            where = Path(top).name
        lead = f"`{local}` lies in the repository at `{where}`"
        identity = str(repo.get("remote_identity") or "")
        if not identity:
            return None, None, (f"{lead} and `remote_identity` of {rid} is empty; set `remote_identity` of {rid}, or "
                                "point its `local_path` at a checkout of that repository")
        origin = TRB._git(top, "config", "--get", "remote.origin.url") or ""

        def clean(text):
            """No userinfo, query or fragment: a remote may carry a credential in any of the three (E14). URLs go
            through `http_client.safe_url`; the other forms (scp `user@host:path`, a local path) are cut at the last
            `@` and at the first `?` or `#`. Every comparison and every printed value is made on this form."""
            text = str(text or "").strip()
            if "://" in text:
                return http_client.safe_url(text)
            return re.split(r"[?#]", text, maxsplit=1)[0].rsplit("@", 1)[-1]

        def parsed(text):
            host, path = ticket_light.split_remote_identity(clean(text))
            return (host.lower(), path.lower()) if host and path else None

        def shown(text):
            both = parsed(text)
            return f"{both[0]}/{both[1]}" if both else (self.list_tail(clean(text)) or "not set")

        got, named = parsed(origin), parsed(identity)
        tail = self.list_tail(clean(origin))
        if not ((got == named) if got and named else (bool(tail) and tail == self.list_tail(clean(identity)))):
            return None, None, (f"{lead} whose origin is `{shown(origin)}`, not `{shown(identity)}` that "
                                f"`remote_identity` of {rid} names in `qa-factory/config.json`; if that repository "
                                "is the right one, set `remote_identity` to its origin, otherwise point "
                                "`local_path` at a checkout of the right repository")
        if want and tail != want:
            return None, None, (f"{lead} whose origin `{tail or 'not set'}` is not the merge request's project "
                                f"`{want}`; point `local_path` of {rid} at a checkout of `{want}`")
        return checkout, top, ""

    def repo_of_project(self, project: str, why: list | None = None):
        """(repo name, checkout path) of the configured implementation repository whose remote or id ends with
        `project`'s last path segment, or None. The tail is compared WHOLE (`testproject1` is not `testproject1-ui`):
        asking the wrong project's remote for `refs/merge-requests/<iid>/head` would name the head of a
        different request with the same number. An entry that matches but cannot be used (`checkout_for`) is
        skipped, and its sentence is appended to `why` when the caller passed a list: the return shape stays."""
        wanted = self.list_tail(project)
        for repo in self.config.get("implementation_repos") or []:
            local = str(repo.get("local_path") or "")
            if not wanted or not local:
                continue
            if wanted not in (self.list_tail(repo.get("remote_identity")), self.list_tail(repo.get("repo_id"))):
                continue
            checkout, _top, reason = self.checkout_for(repo)
            if checkout:
                return str(repo.get("repo_id") or repo.get("name") or wanted), checkout
            if reason and why is not None:
                why.append(reason)
        return None

    def s0_resolve_head(self, entry: dict) -> None:
        """Best effort: the head commit of an excluded merge request, written into the entry's target
        (`head_sha`) so that a citation by commit is the same source as one by number (t-172 C2). One
        `git ls-remote` per request, LS_REMOTE_SECONDS at most. A failure is PRINTED and the word is kept
        without a commit (`head_sha` stays null): the exclusion holds by its number regardless."""
        target = entry["target"]
        target["head_sha"] = None
        name = entry["as_written"]
        unusable = []
        found = self.repo_of_project(target.get("project") or "", why=unusable)
        if not found and unusable:
            # An entry that names the project but cannot be asked is not "no checkout configured" (B-412).
            print(f"{name}: " + "; and ".join(unusable) + "; so the head commit of this merge request is not looked "
                  "up, and the word holds by the number")
            return
        if not found:
            print(f"{name}: no local checkout of `{self.list_tail(target.get('project'))}` is configured, so the "
                  "head commit of this merge request is not looked up; the word holds by the number, and a "
                  "line naming a commit or `branch:<name>` names it another way")
            return
        _label, checkout = found
        head, why = self.ls_remote_head(checkout, f"refs/merge-requests/{target['iid']}/head",
                                        "the merge request is not listed there (a merged or closed one is pruned)")
        if not head:
            print(f"{name}: the head commit of this merge request could not be looked up ({why}); the word holds "
                  "by the number")
            return
        target["head_sha"] = head

    def ls_remote_head(self, checkout, ref: str, missing: str = "the name is not listed there") -> tuple:
        """THE one ask of a remote for one ref (AR-15): `git -C <checkout> ls-remote origin <ref>`, LS_REMOTE_SECONDS at most, no prompt.
        `(sha, "")` or `("", why)`. Only the row of `ref` itself counts (`ls-remote` matches a pattern from the end of a name) and only
        when it is a 40-hex commit id; a failed command gives the first line of git's own words, a clean answer with no such row gives
        `missing`. The WORDS of `why` are the caller's to show or to put in plain words (a person never reads them as they are)."""
        try:
            done = subprocess.run(["git", "-C", str(checkout), "ls-remote", "origin", ref], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=self.LS_REMOTE_SECONDS,
                                  env=dict(self.env, GIT_TERMINAL_PROMPT="0"))
        except subprocess.TimeoutExpired:
            return "", f"the remote did not answer within {self.LS_REMOTE_SECONDS} seconds"
        except OSError as exc:
            return "", f"git could not be run ({type(exc).__name__})"
        rows = [line.split()[0] for line in done.stdout.splitlines() if re.fullmatch(r"[0-9a-f]{40}\s+" + re.escape(ref), line.strip())]
        if done.returncode or not rows:
            return "", (done.stderr.strip().splitlines() or [missing])[0][:160]
        return rows[0], ""

    def s0_resolve_branch(self, entry: dict) -> None:
        """Best effort: the commit a `branch:<name>` word stands for, written into its target (`sha`), so that
        `git_route` and the manifest detector see the branch's head too: a branch word alone did nothing there
        (B-231, critic t-192). The word names no project, so every configured implementation repository with a
        local checkout is asked, `git ls-remote origin refs/heads/<name>`, LS_REMOTE_SECONDS at most each. The
        INVARIANT is the direction of error: the commit is kept only when the answers agree on ONE id; none,
        a failure, or two different ids (the same branch name in two repositories) leave `sha` null, print one
        line, and the word holds by the branch name. Never a refusal. A word that already carries a commit, or
        names no branch, is left as it is."""
        target = entry["target"]
        branch = target.get("branch")
        if target.get("sha") or not branch:
            return
        target["sha"] = None
        name = entry["as_written"]
        import test_repo_base as TRB
        checkouts, tops, with_path = [], [], False
        for repo in self.config.get("implementation_repos") or []:
            if not str(repo.get("local_path") or ""):
                continue
            with_path = True
            checkout, top, reason = self.checkout_for(repo)
            if not checkout:
                print(f"{name}: {reason}; the word holds by the branch name")
                continue
            # One repository counts once, however many folders of it are configured: the "agree on ONE id" rule
            # below counts repositories (B-412).
            if not any(TRB._same_dir(top, seen) for seen in tops):
                checkouts.append(checkout)
                tops.append(top)
        if not checkouts:
            if not with_path:
                print(f"{name}: no local checkout of an implementation repository is configured, so the commit of "
                      "this branch is not looked up; the word holds by the branch name")
            return
        found, why = [], ""
        ref = f"refs/heads/{branch}"
        for checkout in checkouts:
            head, said = self.ls_remote_head(checkout, ref, "the branch is not listed there")
            if not head:
                why = why or said
                continue
            found.append(head)
        if len(set(found)) == 1:
            target["sha"] = found[0]
            return
        if found:
            why = "the branch has a different commit in each repository that lists it"
        print(f"{name}: the commit of this branch could not be looked up ({why}); the word holds by the branch name")

    @staticmethod
    def mr_conflicts(mr: str, entries: list) -> list:
        """The entries of the list that name the merge request the launch flag `--mr` names (F10). A bare `!N`
        or `N` has no project and is equal by number alone: asking too often costs one answer, a silent
        choice between two words of one person is the defect."""
        import source_exclusions as SE
        text = str(mr or "").strip()
        bare = re.fullmatch(r"!?(\d+)", text)
        short = None if bare else re.fullmatch(r"([\w.][\w./-]*)!(\d+)", text)
        hits = []
        for entry in entries:
            target = entry.get("target") or {}
            if target.get("kind") != "mr":
                continue
            iid = str(target.get("iid") or "").lstrip("0")
            if bare:
                hit = bare.group(1).lstrip("0") == iid
            elif short:
                mine, theirs = short.group(1).lower(), str(target.get("project") or "").lower()
                hit = short.group(2).lstrip("0") == iid and (
                    mine == theirs or mine.endswith("/" + theirs) or theirs.endswith("/" + mine))
            else:
                hit = SE.matches(entry, url=text)
            if hit:
                hits.append(entry)
        return hits

    @staticmethod
    def merge_list_entries(clean: list, loose: list) -> list:
        """The clean entries and the ones a problem line carried (their TARGET read, their reason did not:
        none, or it starts like a target), in line order. Dropping them would read what the person named
        (t-172 C5c). The same thing named twice keeps one entry, every reason and every line number."""
        import source_exclusions as SE
        merged = [dict(entry) for entry in clean]
        for entry in loose:
            same = next((m for m in merged if SE._identity(m["target"]) == SE._identity(entry["target"])), None)
            if same is None:
                merged.append(dict(entry))
                continue
            if entry.get("reason"):
                same["reason"] = (same["reason"] + " | " if same["reason"] else "") + entry["reason"]
            lines = same["line"] if isinstance(same["line"], list) else [same["line"]]
            same["line"] = lines + (entry["line"] if isinstance(entry["line"], list) else [entry["line"]])
        first = lambda e: e["line"][0] if isinstance(e["line"], list) else e["line"]
        return sorted(merged, key=first)

    def s0_source_list(self, flags: dict) -> None:
        """Read the person's list of sources not to read, before anything is fetched (P4, C1, C5).

        Without the flag: nothing is written and nothing is printed - a story with no list is today's story.
        A story whose inventory already exists: the list cannot apply (a source already read cannot be left
        out before the run), so the person is asked, never told in passing. A file that is missing, too large,
        not text, or has a line the code cannot use: a question with `retry` and `go on`; `go on` applies the
        lines whose TARGET read and never the others. The launch's `--mr` naming the same request as a line:
        its own question (`read` / `skip`)."""
        listed = flags.get("skip_sources")
        if not listed:
            return
        import source_exclusions as SE
        work = self.task_root / "work"
        # An inventory that S0's OWN read seeded (the REST read leaves `field_ids` and `prefix_probes` there,
        # t-267 C3) or marked (`auth_stop`) is no source collected: when the record of THIS list - the same
        # bytes - is already written, the list was applied before anything was read and a later entry of S0
        # (after a stand or readiness answer) must not ask "too late". A list not yet applied, or other bytes
        # than the record holds, still meets the question: what was read cannot be left out afterwards.
        if (work / "source-inventory.json").is_file() and not self.s0_list_applied(Path(listed)):
            self.s0_list_too_late()
            return
        data, problems, entries, loose, parsed = None, [], [], [], []
        try:
            data = Path(listed).read_bytes()
        except OSError as exc:
            problems.append(("file", f"I cannot open `{listed}` ({type(exc).__name__}): nothing is there to read."))
        if data is not None:
            entries, parsed = SE.parse_bytes(data, self.task)
            problems += [(f"line {p['line']}: {p['code']}", p["message"]) for p in parsed]
            loose = [p["entry"] for p in parsed if p.get("entry")]
        applied = self.merge_list_entries(entries, loose)
        keys = [key for key, _ in problems]
        if problems and not self.s0_passed("source_list", keys):
            shown = [message for _key, message in problems[:self.SOURCE_LIST_SHOWN]]
            more = len(problems) - len(shown)
            usable = len(applied)
            # The two kinds of problem are told apart by COUNT (FR-10: what the text says is what `go on` does):
            # a line whose source I could not read is never applied; a line whose source I read but which has a
            # problem of its own (no reason, a second source after it) IS applied on `go on`. The counts are of
            # ALL the lines, not of the ones shown.
            unread = sum(1 for p in parsed if not p.get("entry"))
            flawed = sum(1 for p in parsed if p.get("entry"))
            plural = lambda n, one, many: one if n == 1 else many
            parts = []
            if data is None:
                parts.append("The list itself could not be opened, so no source of it is left out.")
            if unread:
                parts.append(f"{unread} {plural(unread, 'line names', 'lines name')} no source I can read: "
                             f"{plural(unread, 'it is', 'they are')} not applied, so "
                             f"{plural(unread, 'that source', 'those sources')} would be read like any other.")
            if flawed:
                parts.append(f"{flawed} {plural(flawed, 'line names', 'lines name')} a source I can read but "
                             f"{plural(flawed, 'has', 'have')} a problem of {plural(flawed, 'its', 'their')} own (no "
                             f"reason, or a second source after it): if you answer `go on`, "
                             f"{plural(flawed, 'it is', 'they are')} applied anyway and the problem is noted.")
            parts.append(f"{usable} {'line' if usable == 1 else 'lines'} of the list I can use.")
            self.s0_stop(
                "source_list", "halt",
                self.closed_question(
                    "s0.source_list",
                    f"Before starting {self.task} I read the list of sources you asked me not to read ({listed}), "
                    f"and {len(problems)} {'problem' if len(problems) == 1 else 'problems'} stopped me:\n\n"
                    + "\n".join("- " + message for message in shown)
                    + (f"\n- and {more} more (all of them are in the file named below)" if more else "")
                    + "\n\nNothing has been read or fetched yet. " + " ".join(parts)
                    + "\n\nWhat I need from you is one of these:",
                    [{"answer": "retry", "token": "retry", "says": "fix the file, and I read it again",
                      "slots": {"what": "fix the list file"}},
                     {"answer": "go on", "token": "go on",
                      "says": "start the story with the lines I could read; a line I could not read is not applied, and the "
                              "story carries a line saying that you accepted it"},
                     self.STOP_OPTION]),
                {"retry": "retry", "go on": "go on"},
                details="\n".join(f"{key}: {message}" for key, message in problems), problems=keys)
        if data is None:
            print(f"S0: {listed} could not be read; the story starts without a list of sources not to read")
            return
        answers = self.state.get("s0_answers") or {}
        mr = flags.get("mr")
        if mr and answers.get("mr") != "skip":
            hits = self.mr_conflicts(mr, applied)
            if hits and answers.get("mr") == "read":
                applied = [entry for entry in applied if entry not in hits]
                for entry in hits:
                    print(f"{entry['as_written']}: you chose to read it, so its line of the list is not applied")
            elif hits:
                first = hits[0]
                self.s0_stop(
                    "source_list", "halt",
                    self.closed_question(
                        "s0.source_list.conflict",
                        f"You started {self.task} with a merge request to take the code from ({mr}), and your list of "
                        f"sources not to read names the same one: {first['as_written']} - \"{SE.clip(first['reason'])}\". "
                        "The two cannot both stand, because the story's code comes from that merge request.\n\n"
                        "Nothing has been read or fetched yet. Which of your two words stands?",
                        [{"answer": "read", "token": "read",
                          "says": "the story starts from that merge request, and its line of the list is dropped"},
                         {"answer": "skip", "token": "skip",
                          "says": "it stays on the list, and the story starts without that merge request named; the "
                                  "implementation is then looked for another way"},
                         self.STOP_OPTION]),
                    {"read": "read", "skip": "skip"}, details=f"--mr: {mr}\nlist line: {first['as_written']}")
        self.s0_write_list(SE, applied, listed, data, dropped=answers.get("mr") == "read")

    def s0_list_applied(self, listed: Path) -> bool:
        """Does this story's exclusion record hold exactly the bytes of the list file now on disk? A record that
        cannot be read, or a list that cannot be opened, is not "applied"."""
        import source_exclusions as SE
        try:
            record = SE.read_record(self.task_root / "work")
            return bool(record) and record.get("list_sha256") == hashlib.sha256(listed.read_bytes()).hexdigest()
        except (SE.ExclusionRecordError, OSError):
            return False

    def s0_write_list(self, SE, applied: list, listed: str, data: bytes, dropped: bool = False) -> None:
        """Write the record once per list: the same bytes on a later entry are a no-op (the heads are not
        asked for again); other bytes replace an unrevoked record (S0 is the only writer and nothing has been
        read yet), and a record that holds a revocation is kept as it is, with a line saying so."""
        work = self.task_root / "work"
        try:
            record = SE.read_record(work)
        except SE.ExclusionRecordError as exc:
            raise Refusal(str(exc))
        digest = hashlib.sha256(data).hexdigest()
        if record is not None:
            if record.get("list_sha256") == digest:
                return
            if any(e.get("revoked_at") for e in record.get("exclusions") or []):
                print(f"S0: {listed} changed, but the record of this story holds a word you took back, so it is "
                      "kept as it is")
                return
            SE.record_path(work).unlink()
        for entry in applied:
            if entry["target"]["kind"] == "mr":
                self.s0_resolve_head(entry)
            elif entry["target"]["kind"] == "ref":
                self.s0_resolve_branch(entry)
        record = SE.write_record(self.task_root, applied, listed, data)
        for exclusion in record["exclusions"]:
            print(SE.console_line(exclusion))
        if not record["exclusions"] and not dropped:
            print("the list names no source")

    def s0_list_too_late(self) -> None:
        """`--skip-sources` on a story whose sources were already collected (C1): the question, unless the
        person already passed it. `go on` ignores the list; the way to leave a source out now is the source
        review, and the person is told so."""
        if self.s0_passed("source_list", ["inventory_exists"]):
            print("the list of sources not to read is ignored for this story")
            return
        inventory = self.task_root / "work" / "source-inventory.json"
        try:
            day = datetime.fromtimestamp(inventory.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d")
        except OSError:
            day = "earlier"
        import source_exclusions as SE
        try:
            reviewed = SE.s1_completed(self.task_root)
        except Exception:               # a pipeline nobody can read is today's text: the review may still be ahead
            reviewed = False
        if reviewed:
            # The source review is over: promising it would be a door that is shut. What the person can still do
            # is say so in their own words at gate A, where a word of theirs is recorded; nothing already read
            # is un-read, and the record of the list is not written (there is none).
            way = ("the story goes on and the list is ignored. Nothing that was already read "
                   "is un-read; if you still want a source treated as left out, say so in your own words at gate "
                   "A (the review of the plan and the test cases), where your word is recorded and shown in "
                   "the report")
            details = ("Recording a person's word about a source to leave out (references/conductor.md; the gate decision itself is "
                       "never recorded by the conductor): "
                       + person_words.door(f"waiver.py --task {self.task} --remark --stage S0"))
        else:
            way = ("the story goes on and the list is ignored; at the source review you can name "
                   "the sources you do not want read, and they are not read after that")
            details = ""
        self.s0_stop(
            "source_list", "halt",
            self.closed_question(
                "s0.source_list.late",
                f"You started this run with a list of sources not to read, but the sources of {self.task} were already "
                f"collected on {day}, and a source that has been read cannot be left out before the run. So the list "
                "cannot apply to this story, and I have changed nothing.\n\nWhat I need from you is one of these:",
                [{"answer": "go on", "token": "go on", "says": way},
                 {"answer": "stop", "token": "stop",
                  "says": "stop here and start the story again from a fresh copy, where the list is read before anything is fetched",
                  "slots": {"what": "start the story again from a fresh copy"}}]),
            {"go on": "go on"}, details=details, problems=["inventory_exists"])

    def skip_sources_late(self) -> None:
        """`--skip-sources` on a command line of a story whose S0 is over, and the answer to the question
        that raises (C1 replaces edge 8's "printed only" for a story with an inventory). The list is never
        read here: only a story that STARTS reads it. No inventory yet: one printed line says so. An inventory:
        the question of `s0_list_too_late`, whose answer is read here because S0 is not entered again."""
        if not (self.task_root / "pipeline.json").is_file():
            return
        listed = getattr(self.flags, "skip_sources", None)
        answered = bool((self.state.get("pending_words") or {}).get("S0")) and self.state.get("s0_block") == "source_list"
        if not listed and not answered:
            return
        self.boundary = "S0:source_list"
        self._s0_passed = []
        self.s0_read_word()
        if listed:
            if (self.task_root / "work" / "source-inventory.json").is_file():
                self.s0_list_too_late()
            else:
                started = str((((self.pipeline().get("stages") or {}).get("S0") or {}).get("started")) or "")[:10]
                print(f"{self.task}: the list of sources not to read is read only when a story starts; this story "
                      f"started {started or 'earlier'}; at the source review, name the sources to leave out")
        elif self.s0_passed("source_list", ["inventory_exists"]):
            print("the list of sources not to read is ignored for this story")
        for block, words in self._s0_passed:
            # The pipeline is written already, so the pass joins its warnings through the one command that
            # appends one (it never records the same line twice): gate A shows it. A refused line is owed (FR-4, C1-7a).
            self.owe_row("stage_done.py", "--task", self.task, "--warn",
                         f"S0: {self.S0_PASS_NAMES.get(block, block)} passed by the person's word: "
                         f"\"{self.s0_quote(words)}\"", what="the warning about the pass you gave at the start of the story", stage="S0")

    def s0(self) -> None:
        self.boundary = "S0"
        self._s0_passed = []
        self.s0_note_launch()
        self.s0_keep_late_launch()
        self.s0_read_word()
        flags = self.s0_flags()
        # t-017 D3 (B-003): an experiment is decided at the launch and must survive the S0 stops -
        # the entry that follows an answer runs with no flags, and pipeline.json is written only at
        # the end of S0. `s0_note_launch` (just above) made `launch`; the flag is kept in it, next
        # to the sources the person may still correct.
        launch = self.state.setdefault("launch", {})
        no_trace = bool(getattr(self.flags, "no_trace", False) or launch.get("no_trace"))
        if no_trace and not launch.get("no_trace"):
            launch["no_trace"] = True
            self.save_state()
        # The same for the list of sources not to read (t-172 C5a): `s0_note_launch` keeps only the FIRST
        # entry's flags, and the entry that follows an answer runs with whatever its command line says.
        listed = getattr(self.flags, "skip_sources", None)
        if listed and launch.get("skip_sources") != listed:
            launch["skip_sources"] = listed
            self.save_state()
        # SS1-14 (M6): the launch key is checked HERE and nowhere earlier. INVARIANT of the position: every launch word (`--no-trace`,
        # the source list) is kept above, before the first stop of S0; and nothing is read or written for the story below this
        # line - only the driver's state, which holds the question.
        self.s0_key_form()
        given = [key for key in ("mr", "branch", "commit") if flags[key]]
        if len(given) > 1:
            names = {"mr": "a merge request", "branch": "a branch", "commit": "a commit"}
            self.s0_stop(
                "flags", "halt",
                self.closed_question(
                    "s0.flags",
                    f"You started the story for {self.task} with more than one place to take the code "
                    "from: " + ", ".join(f"{names[key]} (`{key}`)" for key in given) + ". I can work "
                    "from only one of them, and which one is the right one is your call - nothing here "
                    "tells them apart. Nothing has been read or written yet.\n\nWhich one should I keep?",
                    [{"answer": key, "token": key, "says": f"keep {names[key]} and drop the other "
                                                           f"{'one' if len(given) == 2 else 'ones'}"} for key in given]
                    + [self.STOP_OPTION]),
                {key: key for key in given}, details="\n".join(f"{key}: {flags[key]}" for key in given))
        # After the more-than-one-source check and before the first fetch (`ticket_get`): the person's word
        # about sources comes first, so nothing it names is ever fetched (B-231).
        self.s0_source_list(flags)
        # The story's ONE ticket (t-267, D-06): a snapshot already on disk, else the person's file or paste,
        # else the tracker by REST. No model is asked at any point of it.
        ticket_file = self.s0_local_file(flags["ticket_file"])       # a local story's text file is its ticket file (SS1-14)
        ticket, out, how, kept = self.s0_ticket(ticket_file)
        criteria_line = self.s0_criteria(ticket, how, None if kept else ticket_file)
        parent =str(ticket.get("parent") or "").split()[0] if ticket.get("parent") else None
        (self.task_root / "work" / "evidence").mkdir(parents=True, exist_ok=True)
        (self.task_root / "work" / "proposals").mkdir(parents=True, exist_ok=True)
        (self.task_root / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
        if not kept:
            self.write_snapshot(out)
        # SS1-13: OUTSIDE `if not kept` - the entry after the person's answer finds the snapshot kept (the question is in `launch` by then).
        # After `work/ticket-references.json` is written (by the read above), before the stand and before any dispatch of the scout.
        self.s0_no_change_entry(flags)
        print("QA Factory v0 covers functional testing only. Non-functional checks (performance, security, "
              "accessibility, localization, compatibility, privacy) are out of scope in this version.")
        sel_args = ["--config", "qa-factory/config.json"] + (["--requested", flags["env"]] if flags["env"] else [])
        code, out = self.py("environment_selection.py", *sel_args)
        # a deliberate `raw`: no readable answer is the NAMED status `unknown` (never a pass), handled below like any other status
        selection = _read_answer(out) or {"status": "unknown", "raw": out}
        status = selection.get("status")
        # t-017 D2 (B-005): `environment_pending` is true until a stand has ANSWERED the check -
        # "no stand is confirmed as usable", whether there is no name at all or a name whose probe
        # failed. A stand is confirmed only by a probe that exits 0 (below) or by a word of the
        # person's (`stand_check`, before S5/S6); S0 itself never stops on a stand.
        environment, pending, warnings = None, True, []
        if status == "selected":
            environment = selection.get("environment_id")
        elif status == "question_required":
            if selection.get("no_environments_configured"):
                print("this project records no stand; /qa-factory:qa-onboarding adds one")
        elif self.s0_passed("stand"):
            # The person said to go on without a stand for now: the same state as a project that
            # records none - pending, and asked again before any test is run.
            pending = True
        else:
            names = [str(e.get("name")) for e in self.config.get("environments") or [] if e.get("name")]
            # G7: a stand named like a word of the factory's own (`stop`, `retry`, `go on`, `restart` ...) cannot be a door: one word
            # would have two readings and code never guesses which one was meant. It is left out of the doors and the options, and a
            # finding names it (owner: environment, the project's setting); the rest of the stands are offered as usual, and the question
            # itself names the left-out stand(s) and says they need renaming (FR-3, FR-41: never "no stand configured" when there are some).
            reserved = NM.reserved_tokens(NM.data(), self.s0_normalize)
            clash = [name for name in names if self.s0_normalize(name) in reserved]
            left_out = ""
            if clash:
                many = len(clash) > 1
                left_out = (f"{'These stands are' if many else 'This stand is'} named like an answer to this question, so "
                            f"{'they cannot' if many else 'it cannot'} be chosen by name: " + ", ".join(f"`{name}`" for name in clash)
                            + f". {'They need' if many else 'It needs'} renaming in the project's list of stands.")
                self.file_defect(self.boundary, "owner: environment — the stand(s) " + ", ".join(f"`{name}`" for name in clash)
                                 + " are named like an answer of the factory, so they cannot be chosen by name at S0; rename them in "
                                   "qa-factory/config.json")
                names = [name for name in names if name not in clash]
            doors = {self.s0_normalize(name): name for name in names}
            doors["go on"] = "go on"
            self.s0_stop(
                "stand", "halt",
                self.closed_question(
                    "s0.stand",
                    f"I could not settle which stand the tests of {self.task} should run on: "
                    + ("the stand named at launch could not be matched to one this project has configured. "
                       "The configured stands are " + ", ".join(f"`{name}`" for name in names) + "."
                       if names else ("none of the stands this project has configured can be chosen by name." if clash
                                      else "this project has no stand configured."))
                    + (" " + left_out if left_out else "")
                    + " Everything before the tests - the ticket, the requirements, the plan - can go on "
                    "without one, and I will ask again before any test is run.\n\nWhat I need from you:",
                    [{"answer": "stand", "token": name, "says": "run the tests of this story on that stand; it is checked when "
                                                               "the stage starts"} for name in names]
                    + [{"answer": "go on", "token": "go on", "says": "go on without a stand for now"}, self.STOP_OPTION]),
                doors, details=f"environment selection answered: {out.strip()[-600:]}")
        # t-2181 PC-2: the `sides.deliverable` question (the record is written in `s0_rest`). POSITION (PC-1b F2): after the stand is
        # selected, so a side known only from that stand's `environments.sides` row is asked; INVARIANT: the question still stands
        # BEFORE `pipeline.json` (written in `s0_rest`), and a side is never silently `deliverable: true`.
        self.s0_write_sides(environment)
        # An experiment hands the flag to BOTH calls: neither probes the tracker's write right
        # (readiness.py --no-trace), so S0 asks a tracker nothing it is not going to be sent (FR-36).
        trace = ["--no-trace"] if no_trace else []

        def readiness_then_rest() -> None:
            # G1 (C1-7b): `state/readiness.json` is read by gate_preflight, gate_brief, stage_guard, story_step and more; a stale or
            # absent file is an unwritten product. The refusal's retry runs THIS function (B-4 ii): a successful retry CONTINUES the
            # rest of S0 (the requirement check, the stand probe, pipeline.json, stage_done S0, initialize) and never returns to
            # the caller with the rest unrun. INVARIANT: S0 does not close over a readiness file the check did not write.
            try:
                self.py("readiness.py", "--write", "--probe-vcs", *trace, check=True,
                        expect="state/readiness.json rewritten")
            except Refusal as refusal:
                refusal.retry = readiness_then_rest
                raise
            self.s0_rest(environment, pending, warnings, parent, criteria_line, no_trace, trace)
        readiness_then_rest()

    def s0_rest(self, environment, pending, warnings: list, parent, criteria_line: str, no_trace: bool, trace: list) -> None:
        """The rest of S0 after the readiness file is written (split out of `s0` for C1-7b B-4 ii: the retry of G1 runs it).
        R3 / F6: the required capabilities are read from `readiness.py --require ... --json` - the record, never the exit code
        alone (FR-46, FR-59). A `missing` capability is the person's question (`s0_stop`); a record with none missing goes on; no
        record, or an exit outside {0, 1}, or an exit 1 that names no missing capability, is the FACTORY's own fault (a crash or a
        usage error) and a G refusal - never put to the person as "something required is missing", never a pass.
        ERROR DIRECTION: one question too many is allowed; a crash read as an answer is not."""
        import readiness as RD
        warnings = list(warnings)
        # A local story has no tracker to reach (SS1-14): the tracker route is not a capability it needs. The error direction:
        # a real key is never local (`is_local` is False on any doubt), so a tracker story still requires its route.
        wanted = ["test_repo", "vcs", "config_schema"] if self.s0_is_local() else ["ticket_adapter", "test_repo", "vcs", "config_schema"]
        code, out = self.py("readiness.py", "--require", ",".join(wanted), "--json", *trace)
        doc, after = json_record(out)
        caps = doc.get("capabilities") if isinstance(doc, dict) else None
        missing = ([name for name in wanted if isinstance((caps or {}).get(name), dict) and caps[name].get("status") == RD.MISSING]
                   if isinstance(caps, dict) else [])
        if code not in (0, 1) or not isinstance(caps, dict) or (code == 1 and not missing):
            raise gate_refusal("readiness.py", code, out, "the statuses of the capabilities the story needs (a readiness record)",
                               retry=lambda: self.s0_rest(environment, pending, warnings, parent, criteria_line, no_trace, trace))
        report = "\n".join(f"{name}: {caps[name].get('status')} - {caps[name].get('note')} (owner: {caps[name].get('owner')})"
                           for name in wanted if isinstance(caps.get(name), dict))
        out = after                                                       # the lines after the record: the WARN lines
        if missing and not self.s0_passed("readiness"):
            self.s0_stop(
                "readiness", "refusal",
                self.closed_question(
                    "s0.readiness",
                    f"Before starting {self.task} I checked that the project has what the story needs - "
                    "access to the ticket, the tests folder, version control and valid settings - and "
                    "something required is missing. The check's own report says which one; it is in the "
                    "file named below.\n\nWhat I need from you is one of these:",
                    [{"answer": "retry", "token": "retry", "says": "fix what the report names, and I check again",
                      "slots": {"what": "fix what the report names"}},
                     {"answer": "go on", "token": "go on",
                      "says": "start the story anyway; that is recorded as your decision, and the story carries a line saying so"},
                     self.STOP_OPTION]),
                {"retry": "retry", "go on": "go on"}, details=report + ("\n" + out if out else ""))
        warnings += [line.strip() for line in out.splitlines() if line.strip().startswith("WARN")]
        if environment:
            code, out = self.py("env_probe.py", "--env", environment, "--task", self.task)
            if code == 0:
                pending = False
            else:
                # A stand that does not answer is not a reason to stop the ticket, the requirements
                # or the plan: only what RUNS on it is blocked, and `stand_check` asks before that
                # (the old halt here cost a person's word for a story that had not touched the
                # stand yet). Any exit but 0 leaves it unconfirmed - a crashed probe confirms
                # nothing (FR-41). The name stays, so the check before the tests probes THIS stand.
                warnings.append(
                    f"stand {environment}: it did not answer the check ({self.probe_reason(out)}); "
                    "the story goes on and the stand is checked again before tests run")
                print(f"stand `{environment}` did not pass the check; the probe said:\n{out}")
            warnings += [line.strip() for line in out.splitlines()
                         if line.strip().startswith("data_cleanup") and "available" not in line]
        # Each block the person's word passed is a line of the story's own record, and gate A
        # shows the warnings: a pass is never a silent one (FR-4).
        warnings += [f"S0: {self.S0_PASS_NAMES.get(block, block)} passed by the person's word: "
                     f"\"{self.s0_quote(words)}\"" for block, words in self._s0_passed]
        # SS1-13: the person's `current code` answer (kept in `launch` by `s0_read_word`) is the story's `implementation_source` (a value
        # `stage_done.py` allows) and a line of its record: gate A shows the first five warnings, and this one goes right after the criteria line.
        source = (self.state.get("launch") or {}).get("implementation_source") or None
        if source:
            warnings.insert(0, "no change to ground on: tests are grounded on the current code, how it behaves now, not what is expected "
                               "(the person's word)")
        if criteria_line:
            # FIRST of the story's own lines (D-0050, t-957 F-6): gate A shows the first five warnings, and a ticket that carried no
            # criteria section is what the person should see before the probes' lines. Only the experiment line below goes before it.
            warnings.insert(0, criteria_line)
        env_word = ((environment + (" (not confirmed)" if pending else "")) if environment else "pending")
        if no_trace:
            # FIRST: gate A shows the first five warnings, and this is the one that says what the run is.
            warnings.insert(0, "this run is an experiment: nothing leaves the project — no merge request, "
                               "no tracker write; bugs stay as files")
        # t-2181 PC-1b (F5): the lines of a side answer the registry did not take are lines of the story's record, right after the
        # experiment line and the criteria line (gate A shows the first five warnings)
        for offset, line in enumerate((self.state.get("launch") or {}).get("sides_not_kept") or []):
            warnings.insert((1 if no_trace else 0) + (1 if criteria_line else 0) + offset, line)
        pipeline = {"ticket": self.task, "parent_feature": parent, "size": None, "environment": environment,
                    "environment_pending": pending, "implementation_source": source, "warnings": warnings,
                    "stages": {"S0": {"status": "done", "started": _now(), "finished": _now(), "role": None,
                                      "digest": f"preflight green, env={env_word}"}},
                    "gates": {}, "halts": []}
        if no_trace:
            pipeline["no_trace"] = True   # the record every reader of the experiment reads (closed_by_run)
        # t-2181 PC-2 (B2): the story's sides are built into the dict BEFORE the file is written - `pipeline.json` is born with its
        # sides, so S0 is never done without them; a refused value raises here and S0 replays whole (the writer's own functions, one writer)
        sides = self.s0_sides_sets(environment)
        if sides:
            import stage_done
            stage_done.apply_facts(pipeline, sides, [])
        _write_json(self.task_root / "pipeline.json", pipeline)
        # S0 is over: what it kept for the answers of its own stops goes. `launch` stays - it is
        # what the story was started with, as the person corrected it.
        # B-364 (R13): the person's word that the ticket is not needed outlives S0 - it is written to `launch` BEFORE
        # `s0_answers` is popped below, because the freshness check (`ticket_freshness_entry`) reads it there and
        # would otherwise look at a ticket the person said not to read.
        if (self.state.get("s0_answers") or {}).get("ticket_read") == "not needed":
            self.state.setdefault("launch", {})["ticket_not_needed"] = True
        for key in ("s0_block", "s0_ask", "s0_passes", "s0_answers", "s0_rest_failed"):
            self.state.pop(key, None)
        self.state["pending_words"].pop("S0", None)
        self.save_state()
        self.py("stage_done.py", "--task", self.task, "--stage", "S0", "--status", "done",
                "--digest", f"preflight green, env={env_word}", check=True)
        self.initialize()

    def stand_names(self) -> list:
        """The stands the project's config records, by name."""
        return [str(e.get("name")) for e in self.config.get("environments") or []
                if isinstance(e, dict) and e.get("name")]

    @staticmethod
    def probe_reason(out: str) -> str:
        """The first line `env_probe.py` gives as the reason the stand cannot be used, on one line,
        cut at 200 characters. It reads our own script's output shape (the list under `THE
        ENVIRONMENT CANNOT BE USED`, or the one-line `ENVIRONMENT: not configured`), never
        anybody's words (FR-12); nothing found is said as nothing found (FR-41)."""
        lines = [line.strip() for line in str(out or "").splitlines()]
        found = ""
        for index, line in enumerate(lines):
            if line.startswith("THE ENVIRONMENT CANNOT BE USED"):
                found = next((item[2:].strip() for item in lines[index + 1:] if item.startswith("- ")), "")
                break
        found = found or next((line for line in lines if line.startswith("ENVIRONMENT:")), "")
        found = found or next((line for line in reversed(lines) if line), "") or "the probe printed nothing"
        return found if len(found) <= 200 else found[:200] + DriverCore.CUT

    @staticmethod
    def side_set_args(name: str, **attrs) -> list:
        """`["sides.<name>.<attr>=<value>", ...]` - the `stage_done.py --set` items of ONE side's record (the one spelling for the arrival
        and for the S1 `not built yet` answer; the twin of `s0_sides_sets`, which applies the same keys before `pipeline.json` exists)."""
        return [f"sides.{name}.{attr}={value}" for attr, value in attrs.items()]
