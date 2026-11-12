"""driver_stage_s6.py - Driver members homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import json
import re
import sys
import time
from pathlib import Path
import hooklib
from driver_chains import ChainKind
from controller import MANUAL_WINDOW_CASES, lane_keys, manual_blocks, manual_done_cases, walk_lanes
import project_decisions
import waiver
from driver_core import BY_PERSON, CODE_CLOSE_SITES, InfraStop, OpenWork, Person, Refusal, _read_json, open_work_reason, seam_rank
from driver_dispatch import WALK_ACCOUNT_TRIGGERS


class DriverStageS6:
    def walk_next_id(self, dispatches, start: int, avoid=()) -> str:
        """TR3-10d L1: the first `S6-qa-runner-<n>` from `n = start` that no controller dispatch carries and that is not in `avoid` (the ids other
        lanes reserved). The one chooser: `walk_assign_step` reserves with it and `run_manual_lane` takes the first free number with it."""
        taken = {str(k) for k in dispatches or ()} | {str(v.get("id")) for v in (dispatches or {}).values() if isinstance(v, dict)} | {str(a) for a in avoid}
        number = max(1, int(start))
        while f"S6-qa-runner-{number}" in taken:
            number += 1
        return f"S6-qa-runner-{number}"

    def walk_refuse_gaps(self, plan: dict) -> None:
        """TR1-4: lanes of `plan["blocks"]` whose account has no pair are NOT walked on the old road: each case is refused `not walked:
        <reason>` (request, `plan["refused"]`, printed), one finding per lane is filed, and the run goes on to the next lane with no
        question. POSITION INVARIANT: before the dispatch of the first lane is registered, so a lane that cannot walk costs no role.

        TR3-10d D3b-2 (item 13, trigger (i) `no_pair`; AR-25, AR-24): where the gap is a ROLE the stand records no pair for, the cases are closed
        exactly as before (the finding unchanged: before an answer the behaviour is today's) and, AFTER the loop, the account question of that
        role is raised (`walk_account_raise`, one per role); it holds the tied cases, so it waits like any case question. It applies at
        `walkers` 1 too (D.5): the one place of Part D that does. The role is read BEFORE the cases are closed (a closed case's request no
        longer carries its key)."""
        kept, asking = [], {}
        for lane in plan["blocks"]:
            why = self.walk_account_gap(lane)
            if not why:
                kept.append(lane)
                continue
            role = self.walk_gap_role(lane) if "no_pair" in WALK_ACCOUNT_TRIGGERS else ""
            if role:
                asking.setdefault(role, []).extend(case for case in lane if case not in asking.get(role, []))
            reason = f"not walked: {why}"
            door = ("record the account's two keys on the stand (credentials_by_role: `<role>: <login key> / <password key>`), "
                    "or check the case yourself")
            for case in lane:
                self.refuse_case(plan, case, reason, door, "left_unchecked", by_first=True)
                print(f"S6: {case}: {reason}")
            self.owe_row("project_decisions.py", "--root", str(self.project), "add-finding",
                         "--essence", f"S6 lane of {', '.join(lane)} not walked: {why}"[:500], "--scope", "local-calibration",
                         "--witness", f"walk lane {lane[0]}", "--idempotency-key", f"walk-account-gap:{self.task}:{lane[0]}",
                         what="the finding about a lane whose account has no pair", stage="S6")
        plan["blocks"] = kept
        if asking:
            self.walk_account_raise(asking)

    def walk_gap_role(self, lane: list) -> str:
        """The ROLE a lane that cannot walk lacks a pair for, else "" (trigger (i) `no_pair`; no guess). Only a one-part key `stand_account:
        <role>` names one; a guest, `env:`, a many-account key, the reserved role `default`, a key that cannot be read, a role the stand
        already records with a pair (the gap is then something else) and any failure are "" - today's close, no question. ERROR DIRECTION:
        a doubt asks nothing."""
        try:
            import config_contract as CC
            import gate_preflight as GP
            import manual_capture as MC
            key = lane_keys(self.task_root, lane).get(lane[0])
            parts = [part for part in key.split("+") if part] if isinstance(key, str) else []
            if len(parts) != 1 or not parts[0].startswith("stand_account:"):
                return ""
            role = parts[0].partition(":")[2].strip()
            if not role or CC.reserved_role(role):
                return ""
            try:
                cfg = MC.load_config(self.task_root)[0]
            except ValueError:
                cfg = {}
            stand = next((e for e in (cfg.get("environments") if isinstance(cfg, dict) else None) or [] if isinstance(e, dict)), {})
            roles = stand.get("credentials_by_role")
            real = GP.account_role(roles, role) if isinstance(roles, dict) else None
            if real is not None and len(GP.account_keys(roles[real])) == 2:
                return ""
            return role
        except Exception:       # noqa: BLE001 - a doubt asks nothing: the lane closes as it always did
            return ""

    def walk_account_raise(self, asking: dict) -> None:
        """TR3-10d D3b-2 (spec item 13; D.5, D.11): ONE `walk_account` question per role of `asking` (`{role: [tied cases]}`), after the
        cases were closed. The row: `walk_ask_once` with the role's pointer `/environments/<stand>/credentials_by_role/<role>` (the pointer
        `project_decisions.py stand-account` writes, so the conductor's `stand-account` reuses this open row and resolves it; FR-7). NOT asked
        again: a role already in `walk_account_asked` / `walk_account_roles` (this story), or one whose cases a deferred `walk_account` item
        holds. An `add` that fails, a stand the registry cannot name or a builder that refuses (a role with a space, non-ASCII) is ONE
        note and today's close: the cases were closed before this runs, so none is left without an outcome. Every question but the last
        is set aside (`defer_question`); the last is raised - or the first that `deferrable` says must be asked at once, the rest unasked
        (their records dropped). INVARIANT: before any answer the behaviour is today's."""
        import manual_capture as MC
        try:
            index = project_decisions._stand_of(MC.load_config(self.task_root)[0])[0]
        except ValueError as exc:
            print(f"note: S6: the account question was not raised ({' '.join(str(exc).split())[:200]}); the checks stay unchecked", flush=True)
            return
        held, seen = self.state.get("walk_account_asked"), self.state.get("walk_account_roles")
        held, seen = held if isinstance(held, dict) else {}, seen if isinstance(seen, dict) else {}
        waiting = {str(case) for item in self.deferred_items() if item.get("kind") == "walk_account" for case in item.get("holds") or []}
        owed = []
        for role, cases in asking.items():
            if role in seen or any(isinstance(v, dict) and v.get("role") == role for v in held.values()) or waiting & set(cases):
                continue
            lines = self.case_lines(cases)
            if not role or not str(role).isascii() or any(ch.isspace() for ch in str(role)):
                # N4: the role is checked BEFORE the registry row is opened - an unaskable role leaves no open row; the same note as
                # below, the same close (the refusal text itself stays in `walk_account_person`, which checks again at the build)
                print(f"note: S6: the question about the {role} account was not raised (walk_account: the role {role!r} cannot be named as "
                      "an account key (it is empty, has a space or a non-ASCII character); the account question was not raised); "
                      "its checks stay unchecked", flush=True)
                continue
            try:
                # remains: the closed question of the person's own account is built by design (item 13), not a state with no move; its executor is `_answer_walk_account`
                build = lambda row, role=role, cases=cases, lines=lines: self.walk_account_person(row, role, cases, lines)
                # remains: the closed question of the person's own account is raised by design (item 13), not a state with no move; its executor is `_answer_walk_account`
                person = self.walk_ask_once(
                    "walk_account", [f"/environments/{index}/credentials_by_role/{project_decisions._ptr(role)}"],
                    f"the account of the role {role} on the stand",
                    str(self.walk_account_text(role, cases, lines)), build)
            except Person:
                raise
            except Exception as exc:    # noqa: BLE001 - D.11: the raise informs, it never stops S6; the cases are already closed
                print(f"note: S6: the question about the {role} account was not raised ({' '.join(str(exc).split())[:200]}); "
                      "its checks stay unchecked", flush=True)
                continue
            if person is not None:
                owed.append((role, person))
        for at, (role, person) in enumerate(owed):
            if at == len(owed) - 1 or not self.deferrable(person):
                for later, _person in owed[at + 1:]:
                    self.state["walk_account_asked"] = {k: v for k, v in self.state["walk_account_asked"].items() if v.get("role") != later}
                    self.state["walk_account_roles"].pop(later, None)
                self.save_state()
                raise person
            self.defer_question(person)

    # --- X7-6 / X7-6b / X7-6c: a stage accepted by its CONSUMER role - S6 by the failure analyst (who works in S7), S7 by the doc scribe (who works
    # in S8). ONE table and ONE helper set (t-1860 Q8): the two stages differ only in the data below, so every fix is made once. ------------
    CONSUMER_ROUTES = {
        "S6": {"consumer_stage": "S7", "author": "qa-runner", "who": "failure analyst", "what": "the runner's handoff",
               "closes_when": lambda closes: closes is True,
               "awaits": "the runner stopped; S6 awaits the acceptance of {consumer}, which judges the run report and the case records from its own form",
               "rework_complete": lambda driver: driver.consumer_awaits("S6", True)},
        "S7": {"consumer_stage": "S8", "author": "qa-failure-analyst", "who": "doc scribe", "what": "the analyst's handoff",
               "closes_when": lambda closes: closes is None,
               "awaits": "the failure analyst stopped; S7 awaits the acceptance of {consumer}, which judges the triage and the bug drafts from its own form",
               # read AFTER the role wrote: repairs still owed keep S7 open
               "rework_complete": lambda driver: (lambda digest: driver.consumer_awaits("S7", driver.s7_open_work()))},
    }

    def consumer_awaits(self, stage: str, closes):
        """The author's `complete` under a consumer: a finish that WOULD close `stage` (the table's `closes_when`) is the open-work word
        `stage_awaits_acceptance` instead (POSITION: the author never closes the stage, §3); anything else is passed through as it was.
        With no consumer `closes` comes back unchanged (temporal: older pipelines behave as today)."""
        import acceptance
        consumer, route = acceptance.consumer_of(stage), self.CONSUMER_ROUTES.get(stage) or {}
        if consumer and route and route["closes_when"](closes):
            return OpenWork(acceptance.AWAITS_WORD, open_work_reason(route["awaits"].format(consumer=consumer), ""))
        return closes

    def consumer_pending(self, stage: str) -> bool:
        """True when `stage` has a consumer, is not completed, its author ran, and an `accept` record stands for the author's LAST dispatch of
        the current life: the stage is owed its close (a restart between the consumer's record and the close lands here)."""
        import acceptance
        if not acceptance.consumer_of(stage):
            return False
        state = self.controller_state()
        if ((state.get("stages") or {}).get(stage) or {}).get("status") == "completed":
            return False
        return acceptance.accepted_for(self.pipeline(), stage, acceptance.stage_author_dispatch(state, acceptance.stage_def_of(stage)))

    def consumer_close_words(self, stage: str) -> tuple:
        """B-20 N4 (AR-27, FR-35): `(reason, digest)` of the close of a stage judged by its consumer, from the acceptance RECORD - never from a
        refusal's words. A driver accept whose quote starts `by: person` for the author's LAST dispatch is the person's pass: the words say a
        person's word accepted it. Any other record (the consumer role's own) and no record give the default words (`CODE_CLOSE_SITES`,
        the consumer's name). INVARIANT: a person's pass is never reported as a role's verdict. An unreadable state gives the default."""
        import acceptance
        route = self.CONSUMER_ROUTES.get(stage) or {}
        reason = CODE_CLOSE_SITES.get(f"{stage.lower()}.accepted", ("", "the consumer accepted the handoff"))[1]
        digest = f"accepted by the {route.get('who', 'consumer')}"
        try:
            pipeline = self.pipeline()
            author = acceptance.stage_author_dispatch(self.controller_state(), acceptance.stage_def_of(stage))
            record = acceptance.stage_acceptance(pipeline, stage) or {}
            by_person = (acceptance.accepted_for(pipeline, stage, author, acceptor=acceptance.DRIVER_ACCEPTOR)
                         and str(record.get("quote") or "").startswith(BY_PERSON))
        except Exception:  # noqa: BLE001 - a record that cannot be read names nobody: the default words
            by_person = False
        if by_person:
            return f"a person's word passed the acceptance of {route.get('what', 'the handoff')}", "accepted by a person's word"
        return reason, digest

    def consumer_word_step(self) -> bool:
        """B-20 (AR-24): the person's `stage acceptance` word reaches a stage that awaits its consumer from ANY driver position, before `where`
        reads on. For each stage of `CONSUMER_ROUTES` that `acceptance.awaits_acceptance` names (the author's last dispatch is accepted and no
        record stands - a dispatch that is running or was superseded awaits nothing, so no word binds to it), a live word that was written AFTER
        that dispatch was accepted passes it through `consumer_person_pass` (the one writer, AR-14). A time that cannot be read is not honoured
        (FR-4: a word never accepts work the person never saw). True when a pass was recorded (the turn is spent); False and nothing written
        otherwise. It never asks and never stops the driver. Census: shape, owner intent - it carries a word, it does not read its meaning."""
        import acceptance
        moved = False
        for stage in self.CONSUMER_ROUTES:
            author = acceptance.awaits_acceptance(self.controller_state(), stage, self.pipeline())
            if author and self.consumer_person_pass(stage, author):
                moved = True
        return moved

    def accepted_at(self, author: str) -> str:
        """When the dispatch `author` was last accepted, as `controller.stamp_utc` (the last `accept` event of the controller's store); `""`
        when it cannot be read (no event, no store). The ONE reader of that time (B-20 F1): a word dated before it was said about work the
        person had not yet seen."""
        try:
            from controller import Controller, stamp_utc
            times = [e.get("created_at") for e in Controller(self.task_root).store.read()
                     if e.get("type") == "accept" and (e.get("payload") or {}).get("id") == author]
            return stamp_utc(times[-1]) if times else ""
        except Exception:  # noqa: BLE001 - an acceptance time that cannot be read is the safe side: the word is not honoured
            return ""

    def consumer_person_pass(self, stage: str, author: str, answer: str = "") -> bool:
        """P13 (M3 of t-1860): the person's word moves the factory. True when an `accept` record stands for `author` already, or when a
        person's word passes the acceptance - `answer` (the words of a recorded `close` answer, given by the caller) or a live
        `waiver.py --block` of the stage-acceptance phrase (`acceptance.STAGE_ACCEPTANCE_PHRASE`) of this stage (`waiver.split_overridden`, the one reader) - and then the pass is RECORDED
        first: `stage_done.py --acceptance <the author's form> --acceptor driver --verdict accept --quote "by: person - <words>"`, the one
        writer, so every reader of the record (the close sites, `awaits_acceptance`, `stage_done`) sees it. False: nothing passes it.
        B-20 F1 (FR-4), at EVERY site: a live waiver is honoured only when its `at` is LATER than the acceptance of `author` (`accepted_at`);
        a time that cannot be read is not honoured. `answer` is a fresh word (given by the caller this turn) and is exempt. A Refusal of the
        recording carries the WHOLE pass as its `retry`, so the finding is filed after a retry too (P13)."""
        import acceptance
        if not author:
            return False
        if acceptance.accepted_for(self.pipeline(), stage, author):
            return True
        line = f"{acceptance.STAGE_ACCEPTANCE_PHRASE}: no accept record stands for {author}"
        since = ""
        if not " ".join(str(answer or "").split()):
            since = self.accepted_at(author)
            if not since:
                return False
        try:
            heard = self.person_pass(stage, author, line, answer, since=since)
        except Refusal as refusal:
            refusal.retry = lambda: self.consumer_person_pass(stage, author, answer)
            raise
        if not heard:
            return False
        # P13: a pass by the person's word is a finding, filed once per stage and author dispatch (the key makes a second write safe)
        self.owe_row("project_decisions.py", "--root", str(self.project), "add-finding",
                     "--essence", f"{stage} acceptance of {author} passed on the person's word: {str(heard.get('decision') or '')[:500]}",
                     "--scope", "local-calibration", "--witness", f"{stage} person's word at {heard.get('at') or ''}",
                     "--idempotency-key", f"stage-acceptance-pass:{self.task}:{stage}:{author}",
                     what="the finding about the stage acceptance you passed", stage=stage)
        return True

    def person_pass(self, stage: str, author: str, line: str, answer: str = "", since: str = "") -> dict:
        """The body of the pass (F3, B-6): the person's word - `answer` (given by the caller) or a live `waiver.py --block` that passes `line`
        (`waiver.split_overridden`, the ONE reader, AR-13) - is RECORDED as the driver accept of `author` for `stage` (the one writer,
        `stage_done.py --acceptance`), and then True. `since` (non-empty): a waiver is honoured only when its `at` is LATER than `since` -
        both read through `controller.stamp_utc`; an `at` or a `since` that cannot be read is not honoured (a word never accepts an author
        dispatch the person never saw, FR-4). Returns the honoured entry (`{"decision": <words>, "at": <when or "">}`) once the pass is
        recorded, `{}` when nothing passes: no `author` -> `{}`, no accept record without an author dispatch."""
        import acceptance
        if not author:
            return {}

        def stamp(value) -> str:
            """One normal form for an `at` / `since`: `controller.stamp_utc` of the epoch second; `""` when it is no time (or has no zone)."""
            from datetime import datetime
            from controller import stamp_utc
            if isinstance(value, str):
                try:
                    moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                    return stamp_utc(moment.timestamp()) if moment.tzinfo is not None else ""
                except (ValueError, OverflowError, OSError):
                    return ""
            return "" if isinstance(value, bool) or value is None else stamp_utc(value)
        words = " ".join(str(answer or "").split())
        heard = {}
        if not words:
            import waiver
            _blocking, passed = waiver.split_overridden([line], self.pipeline(), stage)
            if passed and since and not (stamp(passed[0].get("at")) > stamp(since) > ""):
                passed = []
            heard = dict(passed[0]) if passed else {}
            words = " ".join(str(heard.get("decision") or "").split())
        if not words:
            return {}
        if getattr(self, "dry", False):      # B-20 F2: `--dry-run` runs nothing and writes nothing - the pass is only said
            print(f"{stage}: dry run - a person's word would pass the acceptance of {author}; nothing is recorded")
            return {}
        self.py("stage_done.py", "--task", self.task, "--stage", stage, "--acceptance", f"work/handoffs/{author}.yaml",
                "--acceptor", acceptance.DRIVER_ACCEPTOR, "--verdict", "accept", "--quote", f"{BY_PERSON} - " + words[:500], check=True,
                expect=f"the person's pass recorded as the acceptance of {stage} for {author}")
        print(f"{stage}: a person's word passes the acceptance of {author}; recorded as a driver accept (by: person)")
        return {"decision": words, "at": heard.get("at") or ""}

    def consumer_need_record(self, stage: str, site: str) -> None:
        """The close sites of a stage with a consumer (S6: `s6_reentry`, `s6_reprobed_close`, `manual_close`; S7: `s7_close`): with an author that
        ran, a close needs the `accept` record of the author's LAST dispatch - or a person's pass (`consumer_person_pass`, M3). A Refusal names
        the missing record and the door (FR-1, FR-2); with no consumer, no author dispatch, or the stage completed already, nothing."""
        import acceptance
        consumer = acceptance.consumer_of(stage)
        if not consumer:
            return
        state = self.controller_state()
        if ((state.get("stages") or {}).get(stage) or {}).get("status") == "completed":
            return
        author = acceptance.stage_author_dispatch(state, acceptance.stage_def_of(stage))
        if not author or self.consumer_pending(stage) or self.consumer_person_pass(stage, author):
            return
        raise Refusal(f"{stage} cannot be closed at {site}: no accept record of {consumer} stands for {author}. The consumer judges "
                      f"{(self.CONSUMER_ROUTES.get(stage) or {}).get('what', 'the handoff')} from its own form (`stage_done.py --task {self.task} "
                      f"--stage {stage} --acceptance work/handoffs/<{consumer} dispatch>.yaml`), or a person's word passes it (`waiver.py "
                      f"--task {self.task} --stage {stage} --block \"{acceptance.STAGE_ACCEPTANCE_PHRASE}\"`).")

    def consumer_counts(self, stage: str, reviewed: str) -> tuple:
        """`(counted, cap)` of the author's repair rounds on the dispatch the consumer REVIEWED, as the controller counts them (`prepare` carries
        `repair_budget` for `REPAIR_LOOP_ROLES`; the packet is asked for the reviewed dispatch's own scope and half, so the ledger key is the
        first dispatch's). Read ONLY after a verdict `reject` is known (B1). `(None, None)` when the controller cannot say."""
        dispatch = (self.controller_state().get("dispatches") or {}).get(reviewed) or {}
        extra = ({"execution_kind": str(dispatch.get("execution_kind") or ""), "manual_case_ids": [str(c) for c in dispatch.get("manual_case_ids") or []]}
                 if stage == "S6" else {})
        budget = self.budget_or_none(stage, self.CONSUMER_ROUTES[stage]["author"], list(dispatch.get("scope") or []), ref=reviewed, **extra) or {}
        return budget.get("counted"), budget.get("cap")

    def consumer_exhausted(self, stage: str, record: dict, dispatch: str, form: str, counted, cap):
        """A `reject` with no round left, or none that can be counted: the ONE seam (`stage_review_exhausted`), never a code decision. The text says
        which of the two it is (FR-41: an unknown is not «no round is left»)."""
        route = self.CONSUMER_ROUTES[stage]
        text = ""
        if not (isinstance(counted, int) and isinstance(cap, int)):
            text = (f"the {route['who']} rejected {stage} and the factory could not count the repair rounds of {route['author']}, so none is "
                    f"started: {record.get('quote') or ''}")
        return self.stage_review_exhausted(stage, route["author"], dispatch, record, form, text=text)

    def consumer_completion(self, stage: str, inner, dispatch_id=None):
        """The `complete` callable of the consumer's finish while `stage` awaits it (the shape of `stage_critic_completion`): write the record from
        the consumer's form FIRST (`stage_acceptance_write`, the one writer), then `accept` -> the consumer's own completion `inner` (a VALUE: a
        callable is called); `reject` with a round left -> `OpenWork("stage_superseded")` (its work is stale, E-24); `reject` with none left (or
        none countable) -> the conductor through the ONE seam. A verdict word the table does not know goes to the same seam. The repair budget
        is read only on a reject (B1)."""
        import acceptance
        route = self.CONSUMER_ROUTES[stage]

        def complete(digest: str):
            def own():
                return inner(digest) if callable(inner) else inner       # a VALUE: `finish` takes no callable from a callable
            dispatch = str(getattr(self, "last_dispatch", "") or "") if dispatch_id is None else str(dispatch_id or "")
            form = f"work/handoffs/{dispatch}.yaml" if dispatch else ""
            if not dispatch or not self.stage_verdict_known(form):
                return self.stage_review_exhausted(stage, route["author"], dispatch, None, form, unreadable=True)
            self.stage_acceptance_write(stage, dispatch)
            record = acceptance.stage_acceptance(self.pipeline(), stage) or {}
            if record.get("verdict") == "accept":
                return own()
            counted, cap = self.consumer_counts(stage, str(record.get("reviewed_dispatch") or ""))
            if isinstance(counted, int) and isinstance(cap, int) and counted < cap:
                return OpenWork(acceptance.SUPERSEDED_WORD, open_work_reason(
                    f"the {route['who']} sent {route['what']} back: {record.get('quote') or ''}", f"... [list: {form}]"))
            outcome = self.consumer_exhausted(stage, record, dispatch, form, counted, cap)
            return own() if outcome is None else outcome
        return complete

    def consumer_settled(self, stage: str, state: dict, awaiting: str, done: bool, ran: bool = False) -> bool:
        """What follows the consumer's finish while `stage` awaited it, and the recovery of a restart. True = this entry is done.
        - an `accept` record for `awaiting`: `stage` closes by it on the loop's next entry; True on a recovery entry, False right after the
          consumer ran (`ran`: its own stage is still to finish).
        - a `reject` record: a person's pass (`consumer_person_pass`) takes it as the accept; else the author's repair round NOW, ONCE per
          round, in a fresh context (`rework`: the controller reads the scope from the record, B2), within the repair cap (read only here, B1);
          no round left -> the conductor through the ONE seam (`consumer_exhausted`); True.
        - no record but an accepted, not superseded consumer dispatch CREATED AFTER `awaiting` (the finish died after the dispatch, M2): the
          record is written from its form, then the cases above. Otherwise False: the consumer is still to be dispatched."""
        import acceptance
        route, consumer = self.CONSUMER_ROUTES[stage], acceptance.consumer_of(stage)
        record = acceptance.stage_acceptance(self.pipeline(), stage) or {}
        mine = acceptance.consumer_dispatch(state, route["consumer_stage"], consumer, awaiting)
        if record.get("reviewed_dispatch") != awaiting and done:
            if not mine:
                return False
            self.stage_acceptance_write(stage, mine)
            record = acceptance.stage_acceptance(self.pipeline(), stage) or {}
        if record.get("reviewed_dispatch") != awaiting:
            return False
        if record.get("verdict") == "accept" or self.consumer_person_pass(stage, awaiting):
            return not ran
        form = f"work/handoffs/{mine or getattr(self, 'last_dispatch', '')}.yaml"
        counted, cap = self.consumer_counts(stage, awaiting)
        if not (isinstance(counted, int) and isinstance(cap, int) and counted < cap):
            self.consumer_exhausted(stage, record, mine, form, counted, cap)      # the ONE seam; a driver accept stands as a record
            return True
        self.rework(stage, route["author"], [], f"{route['who']}, acceptance record of {stage} for {awaiting}: " + str(record.get("quote") or ""),
                    cause="test_defect", complete=route["rework_complete"](self),
                    extra=[f"Repair round {counted + 1} of {cap}: the {route['who']}'s verdict is in {form}; change only what it names."])
        return True

    def stage_S6(self) -> None:
        import acceptance
        auto = self.stage_scope("S6", "automation")
        manual = self.stage_scope("S6", "manual")
        for kind, got in (("automation", auto), ("manual", manual)):
            if not isinstance(got.get("scope"), list):
                # t-2020 (AR-28, FR-41): an answer without a scope is an UNKNOWN scope, not an empty one; "nothing to execute" below
                # is a close by code and is reached only over a scope the controller said was empty.
                raise Refusal(f"S6: the controller's stage-scope answer for the {kind} half has no `scope` list (expected "
                              f"`{{\"scope\": [...]}}`; got keys: {', '.join(sorted(map(str, got))) or 'none'}); the stage is not closed "
                              "over a scope nobody could read - run the step again, and if it repeats, read the controller's output")
        state = self.controller_state()
        done = [d for d in (state.get("dispatches") or {}).values() if d.get("stage") == "S6" and d.get("status") == "accepted"]
        auto_done = any(d.get("execution_kind") == "automation" or not d.get("execution_kind") for d in done)
        auto_scope, manual_scope = list(auto.get("scope") or []), list(manual.get("scope") or [])
        if self.consumer_pending("S6") and not manual_scope and "s6_probe_after" not in self.state:
            # X7-6. POSITION: the consumer's `accept` record stands and nothing more is owed to S6 (no live check to prove again, no manual
            # half): S6 closes HERE, by the record - never by the runner's own finish. A mark `s6_probe_after` or a manual half left
            # falls through to the flow below, whose close sites find the record (`consumer_need_record`).
            reason, digest = self.consumer_close_words("S6")        # N4: who accepted, from the record (the analyst, or the person's word)
            self.close_by_code("S6", reason, ["work/run-report.json"], finalize=False, site="s6.accepted", digest=digest)
            return
        if not auto_scope and not manual_scope:
            # t-305 N1 (Q19 a): the reduction comes FIRST, as in the freshness branch below and in `manual_close` -
            # S7 reads the run report of THIS close (`execution_status: not_executed`, accepted after an S6 code-only
            # receipt by `failures_to_triage`), and a close over a report nobody could build is refused, not recorded.
            # (The controller's projection reduces again after the receipt; this call fixes the ORDER and the refusal.)
            code, out = self.py("finalize_task.py", str(self.task_root))
            if code:
                raise Refusal(f"S6 nothing to execute: finalize_task.py exit {code}: " + (out.splitlines()[-1] if out else ""))
            self.close_by_code("S6", "nothing to execute: the approved plan names no automate or manual-agent case",
                               ["work/automation-manifest.json", "work/test-plan.json"], finalize=False, site="s6.nothing",
                               digest="nothing to execute")
            return
        # only a stage that has something to run asks about the stand - and says what it will run
        running_auto = bool(auto_scope) and not auto_done
        run_kind = "both" if running_auto and manual_scope else ("automation" if running_auto else "manual")
        self.stand_check("S6", run_kind)
        self.build_check("S6", run_kind, cases=(auto_scope if running_auto else []) + manual_scope)    # t-300
        no_stand = self.s6_no_stand()
        if auto_scope and not auto_done:
            fresh = self.s6_freshness(auto_scope)
            probes, attempted = fresh.get("probes") or {}, False
            if fresh["decided"] and not fresh["run"] and not manual_scope:
                # Every automated instance holds a result on its current bytes, on this stand and version:
                # nothing is launched and no runner is dispatched (t-043 D1, F2 a). A red result that
                # stands is not lost: `finalize_task` reduces the whole story, run-report.json says
                # `failed`, and S7 triages it. The code-only receipt closes the whole stage, so this
                # branch is taken only when no manual half is still to run (see `s6_freshness`).
                # The reduction comes FIRST: the receipt closes the stage, so it is written only over a
                # run-report.json the reducer just wrote. A reducer that fails (a corrupt run block) is
                # a doubt like any other: the runner is dispatched as today and told why.
                if probes:
                    # HF2-11b: the runs stand, the live checks of some changed tests do not - proved again here,
                    # BEFORE the reduction (invariant: a probe is never next to code that has no run on its current bytes)
                    attempted = True
                    code = self.s6_reprobed_close(probes, auto_scope, no_stand=no_stand, unrun=[], strict=False, reason=(
                        "every automated test has a result on its current bytes, on the same stand and version: "
                        f"{fresh['passed']} passed, {fresh['failed']} failed - reused, nothing re-run"),
                        base="every automated result stands; nothing re-run")
                    if not code:
                        return
                    fresh = dict(fresh, decided=False, why=f"finalize_task exit {code}")
                else:
                    code, out = self.py("finalize_task.py", str(self.task_root))
                    if code:
                        print(f"S6: finalize_task.py exit {code}: " + (out.splitlines()[-1] if out else ""))
                        fresh = dict(fresh, decided=False, why=f"finalize_task exit {code}")
                    else:
                        self.close_by_code("S6", "every automated test has a result on its current bytes, on the same "
                                           f"stand and version: {fresh['passed']} passed, {fresh['failed']} failed - "
                                           "reused, nothing re-run", ["work/automation-manifest.json", "state/execution-jobs"],
                                           finalize=False, site="s6.results_stand", digest="every automated result stands; nothing re-run")
                        return
            # HF2-11b: with live checks to prove again the runner does NOT close the stage - this driver closes it on its
            # return (`s6_reentry`), after the proofs, so a probe never comes before the runs of the current bytes
            owed = bool(probes) and not manual_scope and not no_stand and not attempted
            held = "s6_probe_after" in self.state
            if owed:
                self.state["s6_probe_after"] = ""        # set before the runner: a crash mid-run still owes the close
            elif held:
                del self.state["s6_probe_after"]         # a mark of an earlier life of S6 is not this one's
            if owed or held:
                self.save_state()
            left = []
            if no_stand:            # K4: no run, no probe - what changed is left for a run on a stand, and the digest says how many
                changed = [i for i, row in self.s6_changed(auto_scope).items() if "stale" in (row["run"][0], row["probe"]["state"])]
                left = [self.S6_LEFT.format(n=len(changed))] if changed else []
                for line in left:
                    print(f"S6: {line}")
            # X7-6: with a consumer the final runner window (no manual half) stops AWAITING its acceptance, `owed` included (the proofs
            # then run in `s6_reentry` after the record, whose close site finds it); `consumer_awaits` is the identity with no consumer.
            self.run_role("S6", "qa-runner", scope=auto_scope,
                          complete=(self.consumer_awaits("S6", True) if not manual_scope else False) if acceptance.consumer_of("S6") else (not manual_scope and not owed),
                          extra=["Execution kind: automation — run only instances whose evidence is missing or stale; "
                                 "reuse fresh receipts; then `finalize_task.py <task root>` writes run-report.json."]
                                + self.s6_freshness_lines(fresh) + left + self.role_lines("S6", "qa-runner"))
            if owed:
                self.state["s6_probe_after"] = str(getattr(self, "last_dispatch", "") or "")
                self.save_state()
            if manual_scope:
                self.state["s6_manual_runner"] = str(getattr(self, "last_dispatch", "") or "")    # HF8-18: read, then dropped, by N2
                self.save_state()
                return  # the loop comes back for the manual block
        elif auto_scope and not manual_scope:
            self.s6_reentry(auto_scope, no_stand)       # `auto_done`: the runner came back (HF2-11b)
        elif auto_scope and not self.manual_done():
            self.s6_reprove_before_manual(auto_scope, no_stand)     # HF8-18: the runner is accepted, no manual block yet
        if manual_scope:
            self.run_manual_block(manual_scope)

    def s6_freshness(self, cases: list) -> dict:
        """What the story already holds of the automated cases of S6, decided by code (t-043 D1).

        `{"decided": bool, "why": str, "stand": [instance ids], "run": {instance id: why},
        "passed": n, "failed": n, "probes": {instance id: replay}}`. `run` empty and `decided` True means every
        instance has a result that stands (`execution_request.fresh_evidence`, the builder `--mine` uses, AND
        `proof_level.staleness`: a result the evidence function keeps but the run row's own per-test shas say ran
        other code - a helper module `helper_files` does not name - moves from `stand` to `run`, so S6 and the
        ledger decide freshness by ONE predicate, HF2-11b). `probes` holds each instance whose live check is stale
        (`probe_freshness`), with its `replay` (what `probe_by_code.py` needs) or None when code cannot replay it. It is passed no
        `collect`, so ids come from the source, not from a real collection: a test with parameters
        can read `missing` here where `--mine` would answer `reused`. That is the safe side - one
        extra runner dispatch, never a stage closed on a guess.

        ERROR DIRECTION (a doubt never closes a stage): anything the driver cannot settle - no budget
        data, a stand nobody could look at, an evidence function that raises, an empty answer, a
        state or outcome it does not know - is `decided: False` with the reason, and the runner is
        dispatched exactly as before and told why (P1: code informs, it does not stop the factory;
        FR-41: an unknown is not reported as a fact). It reads and writes nothing of the story."""
        def undecided(why: str) -> dict:
            return {"decided": False, "why": why, "stand": [], "run": {}, "passed": 0, "failed": 0, "probes": {}}

        try:
            import execution_request
            import run_suite
            found = execution_request.fresh_evidence(self.project, self.task, list(cases), cfg=self.config,
                                                     probe=run_suite.probe_runtime)
        except Exception as exc:
            text = " ".join(str(exc).split())
            return undecided(f"{type(exc).__name__}: " + (text if len(text) <= 200 else text[:200] + self.CUT))
        instances = found.get("instances") if isinstance(found, dict) else None
        if not isinstance(instances, dict):
            return undecided("the evidence came back in a shape this driver does not know")
        if found.get("observed") is not True:
            first = next((r.get("why") for r in instances.values() if isinstance(r, dict) and r.get("why")), "")
            return undecided(str(found.get("why") or first or "the stand's version was not observed"))
        if not instances:
            return undecided("no test of these cases could be listed")
        try:
            held = self.s6_changed(cases, list(instances), strict=True)
        except Exception as exc:
            text = " ".join(str(exc).split())
            return undecided(f"{type(exc).__name__}: " + (text if len(text) <= 200 else text[:200] + self.CUT))
        stand, run, passed, failed = [], {}, 0, 0
        for instance, row in instances.items():
            state = row.get("state") if isinstance(row, dict) else None
            ran = (held.get(instance) or {}).get("run") or ("unknown", "")
            if state == "result" and row.get("outcome") in ("passed", "failed") and ran[0] == "stale":
                run[instance] = str(ran[1] or "its run is of other code")      # the evidence keeps it; the run row's shas do not
            elif state == "result" and row.get("outcome") in ("passed", "failed"):
                stand.append(instance)
                passed, failed = passed + (row["outcome"] == "passed"), failed + (row["outcome"] == "failed")
            elif state in ("stale", "missing"):
                run[instance] = str(row.get("why") or state)
            else:
                return undecided(f"{instance}: state `{state}` with outcome `{(row or {}).get('outcome')}` "
                                 "is not one this driver knows")
        probes = self.s6_probes(held)
        return {"decided": True, "why": "", "stand": stand, "run": run, "passed": passed, "failed": failed, "probes": probes}

    def s6_freshness_lines(self, fresh: dict) -> list:
        """The runner's extra lines for what `s6_freshness` found: which results stand and which
        instances are to run (with why), or - when code could not decide - the note saying so."""
        if not fresh["decided"]:
            return [f"The factory could not decide freshness ({fresh['why']}): decide per instance."]
        if not fresh["stand"]:
            return []
        run = "; ".join(f"{iid} ({why})" for iid, why in fresh["run"].items())
        return ["Results that stand: " + ", ".join(fresh["stand"]) + "; run only: " + (run or "nothing") + "."]

    # --- HF2-11b: the live checks of the tests that changed after their run are proved again by code, before S6 closes ------

    # The runs are the runner's (as before); the new move is ONE: `probe_by_code.py` per stale live check, run by the driver
    # (FR-33, FR-48: not the conductor, not a person), AFTER every automated run stands on the current bytes and BEFORE the last
    # `finalize_task.py` (invariants: a probe is never next to code that has no run on its current bytes; the reducer and the
    # ledger read the new receipt; S6 is not closed over a stale live check that could have been proved). No ceiling on how many
    # (F-7 a): the time they took is in the digest. Every failure is a digest line, never a question to a person (P1).
    # With no S6 dispatch running the probe goes in the close context of S6 (`--s6-close`, HF3-6): the tool allows it only
    # when the controller would take the S6 code-only receipt, and the receipt names each probe record.
    S6_LEFT = "{n} tests changed after their run are left for a run elsewhere"

    def s6_no_stand(self) -> bool:
        """The stage goes on WITHOUT a confirmed stand, on a person's word: no stand is confirmed and the word
        `stand not confirmed` is recorded for S5 or S6 - the carrier is the recorded word (`waiver.split_overridden`,
        the reader `stand_check` itself uses), not the answer that was given. A confirmed stand is never "no stand"."""
        pipeline = self.pipeline()
        environment = str(pipeline.get("environment") or "")
        if environment and not pipeline.get("environment_pending"):
            return False
        block = (f"{waiver.STAND_NOT_CONFIRMED_BLOCK}: " + (f"stand `{environment}` is not confirmed as usable"
                                                            if environment else "no stand is confirmed for this story"))
        return any(waiver.split_overridden([block], pipeline, owner)[1] for owner in self.STAND_STAGES)

    def s6_changed(self, cases, ids=None, *, strict: bool = False) -> dict:
        """`proof_level.staleness` over `ids` (default: the instances of the automation manifest that prove `cases`):
        `{instance id: {"run": (state, why), "probe": {"state", "why", "replay"}}}`. Reads only. `strict` lets an exception
        out (`s6_freshness` turns it into `undecided`); otherwise it is printed and nothing is known, so nothing is proved."""
        try:
            import contract as C
            import proof_level
            manifest = self.s6_manifest()
            if ids is None:
                wanted = {str(case) for case in cases}
                ids = [C.test_instance_id(t) for t in C.manifest_tests(manifest) if wanted & {str(c) for c in C.manifest_test_links(t)}]
            return proof_level.staleness(self.task_root, manifest, list(ids))
        except Exception as exc:
            if strict:
                raise
            print(f"S6: what the tests changed since their run could not be read ({type(exc).__name__}); nothing is proved again")
            return {}

    def s6_manifest(self):
        """The task's automation manifest as read (`work/` first, then the task root), or what `_read_json` gives for none."""
        return (_read_json(self.task_root / "work" / "automation-manifest.json")
                or _read_json(self.task_root / "automation-manifest.json"))

    @staticmethod
    def s6_probes(changed: dict) -> dict:
        """`{instance id: replay or None}` of the instances of `s6_changed` whose live check is `stale` - the ONE comprehension."""
        return {i: (row.get("probe") or {}).get("replay") for i, row in changed.items() if (row.get("probe") or {}).get("state") == "stale"}

    @staticmethod
    def s6_unrun(changed: dict, here: bool) -> list:
        """The instances with no run on their current bytes, next to which no probe goes: a `stale` run always; one that is not `fresh`
        (`unknown`: the row recorded no identity) unless `here` - the runner that has just run it is accepted (the ONE expression of
        `s6_reentry` and `s6_reprove_before_manual`; an unknown is never a license without the runner, FR-59)."""
        return [i for i, row in changed.items() if row["run"][0] == "stale" or (row["run"][0] != "fresh" and not here)]

    def s6_accepted(self, dispatch) -> bool:
        """Is the dispatch `dispatch` (an id; "" or None = none) accepted in the controller's state?"""
        return bool(dispatch) and ((self.controller_state().get("dispatches") or {}).get(str(dispatch)) or {}).get("status") == "accepted"

    def s6_reprove(self, probes: dict, cases, *, no_stand: bool, unrun: list) -> tuple:
        """`(digest lines, n proved, seconds, probe record paths)` for `probes` (`{instance id: replay or None}`). In this
        order, the first that applies: no stand (the word `stand not confirmed`) - no probe, `S6_LEFT`; a test with no run on
        its current bytes (`unrun`) - no probe, said; else the context (HF3-6): an S6 dispatch that is `running` and covers the
        cases - the tool is called with `--dispatch <id>` (it accepts only a `running` one); none - with `--s6-close`, the
        close context of S6, which opens no dispatch and which the tool itself refuses (one digest line, S6 still closes)
        unless the controller would take the S6 code-only receipt. Each `replay` goes to `probe_by_code.py` (`--oracle` when
        the record had one); an exit other than 0 or a verdict other than `intended_failure` is one line, no question, and the
        others go on. A `replay` of None names the instance. The last element names the probe records this pass went through
        (`work/probes/<...>.json` or, for an `already_probed` answer by a product record, `work/probes/product/<...>.json`,
        from the tool's own output) - the evidence of the close receipt. An `already_probed` answer answers only over the
        SAME bytes, so its standing record is exactly what the close stands on for that instance (decided, t-1277)."""
        if not probes:
            return [], 0, 0.0, []
        if no_stand:
            return [self.S6_LEFT.format(n=len(probes))], 0, 0.0, []
        if unrun:
            return [f"re-probe skipped: {len(unrun)} tests have no run on their current bytes ({', '.join(unrun[:5])}"
                    + (self.CUT if len(unrun) > 5 else "") + ")"], 0, 0.0, []
        running = [d for d in (self.controller_state().get("dispatches") or {}).values()
                   if isinstance(d, dict) and d.get("stage") == "S6" and d.get("status") == "running" and d.get("id")]
        covering = [d for d in running if {str(c) for c in cases} <= {str(s) for s in d.get("scope") or []}]
        dispatch = str(((covering or running) or [{}])[0].get("id") or "")
        context = ["--dispatch", dispatch] if dispatch else ["--s6-close"]
        records = []

        def cut(text) -> str:
            text = " ".join(str(text or "").split())
            return text if len(text) <= 200 else text[:200] + self.CUT
        lines, proved, tried, started = [], 0, 0, time.monotonic()
        for iid, replay in probes.items():
            if not replay:
                lines.append(f"{iid}: not proved again - the probe cannot be replayed by code (it recorded no test or mutation, or "
                             "the probe's line anchor moved with the edit); place it again by hand")
                continue
            tried += 1
            args = ["--task", self.task, *context, "--test", replay["test"], "--instance", replay["instance"],
                    "--mutation", replay["mutation"], "--json"] + (["--oracle", replay["oracle"]] if replay.get("oracle") else [])
            code, out = self.py("probe_by_code.py", *args)
            record = hooklib.read_document(out) or {}      # t-2020: pretty-printed answer; a warning with a `{` in it is skipped
            path = record.get("record")
            if isinstance(path, str) and re.fullmatch(r"work/probes/(?:product/)?[^/\\]+\.json", path) and path not in records:
                records.append(path)
            if not code and record.get("verdict") == "intended_failure":
                proved += 1
            elif record.get("verdict") == "incomplete" and record.get("cause") == "judgment":
                # t-1968 N2 (R6, E2.11): no critic window follows the S6 close, so nobody judges this record; it is said as NOT
                # proved (FR-41), asks no question, and S6 still closes. The delivery reason is `check_delivery`'s (`PL.reached`)
                lines.append(f"{iid}: the probe failed at the mutated line with a text the factory cannot read; nobody judges it at "
                             "the S6 close, so the test is not proved again")
            elif code:
                lines.append(f"{iid}: not proved again (probe_by_code exit {code}): "
                             + cut(record.get("error") or (out.splitlines()[-1] if out else "") or "it printed nothing"))
            else:
                lines.append(f"{iid}: the probe gave `{record.get('verdict') or 'no verdict'}`, not `intended_failure`: "
                             + cut(record.get("words") or "no words"))
        seconds = time.monotonic() - started
        if tried:
            lines.insert(0, f"re-proved {proved} probes after the tests changed ({seconds:.0f} s)")
        return lines, proved, seconds, records

    def s6_reprobed_close(self, probes: dict, cases, *, no_stand: bool, unrun: list, strict: bool, reason: str, base: str) -> int:
        """Prove the live checks again (`s6_reprove`), THEN reduce (`finalize_task.py`), THEN close S6 by code (site
        `s6.reprobed`, the digest `base` plus the lines). 0 when closed; else the reducer's exit code (`strict`: a Refusal,
        the way the other closes of S6 refuse - the runner is no longer to come). The mark `s6_probe_after` is dropped.
        The receipt's evidence is the manifest, the jobs and each probe record this pass went through (HF3-6: the close
        names what it stands on)."""
        self.consumer_need_record("S6", "s6_reprobed_close")        # X7-6: BEFORE the proofs, so a refusal leaves nothing proved for nothing
        lines, _proved, _seconds, records = self.s6_reprove(probes, cases, no_stand=no_stand, unrun=unrun)
        for line in lines:
            print(f"S6: {line}")
        code, out = self.py("finalize_task.py", str(self.task_root))
        if code:
            tail = out.splitlines()[-1] if out else ""
            if strict:
                raise Refusal(f"S6 close after the live checks: finalize_task.py exit {code}: {tail}")
            print(f"S6: finalize_task.py exit {code}: {tail}")
            return code
        self.close_by_code("S6", "; ".join([reason] + lines), ["work/automation-manifest.json", "state/execution-jobs"] + records,
                           finalize=False, site="s6.reprobed", digest="; ".join([base] + lines))
        if self.state.pop("s6_probe_after", None) is not None:
            self.save_state()
        return 0

    def s6_reentry(self, cases, no_stand: bool) -> None:
        """`auto_done`, no manual half: the automation runner is back (the proofs go under a running S6 dispatch when
        there is one, else in the close context of S6, `s6_reprove`). When this driver launched it with `complete=False`
        (the mark `s6_probe_after`, set when stale live checks were owed) the close is owed HERE whatever the proofs came to -
        nobody else closes S6 now. Without the mark nothing is owed, and the close happens only for stale live checks while
        every run stands on the current bytes (`staleness.run` fresh everywhere: `auto_done` is not scoped to this life of S6, an
        `invalidate` leaves earlier dispatches accepted). With the mark and the runner accepted in this life, a run the
        row recorded no identity for (`unknown`) counts as standing, as the runner has just run it; a `stale` run never does."""
        owed = "s6_probe_after" in self.state
        changed = self.s6_changed(cases)
        probes = self.s6_probes(changed)
        if owed or probes:
            self.consumer_need_record("S6", "s6_reentry")      # X7-6: a close below needs the consumer's record (a no-op with no consumer)
        unrun = self.s6_unrun(changed, self.s6_accepted(self.state.get("s6_probe_after")))
        if not owed and (not probes or unrun):
            return
        self.s6_reprobed_close(probes, cases, no_stand=no_stand, unrun=unrun, strict=True, base="the automated tests ran on their current bytes",
                               reason="every automated test ran on its current bytes; the live checks of the tests that changed were proved again or left as they were")

    def s6_reprove_before_manual(self, auto_scope, no_stand: bool) -> None:
        """HF8-18 (N2): with a manual half to come, the live checks that went stale are proved again HERE - after the
        automation runner is accepted, before the first manual block - because nothing else would (the code close of S6
        belongs to the no-manual path, `s6_reentry`). Once per byte state: the mark `s6_reproved` is `{instance id:
        input_hash}` of the attempts, so a second life of S6 with other bytes is tried again, the same bytes are not
        (D-0018: an `already_probed` answer is the tool's); a mark of the old shape (a string) reads as "none yet". The
        mark's value is the byte state `proof_level.same_test` judges - the test file's `input_hash` AND the per-test
        `instance_content_sha`, which moves with a conftest or a helper the test reaches - so an edited fixture is tried
        again, though the test file is the same.
        Invariants: a probe never runs next to code with no run on its current bytes (`unrun`: a `stale` run always;
        an `unknown` one - no identity recorded - only when `here`: the runner of THIS life of S6 is accepted, the mark
        `s6_manual_runner` that `stage_S6` sets when the runner returns and this method drops on its way out, so a
        later life has none), and never while a role works (`stage_S6`'s `where` sends a running dispatch to
        `wait_existing_job` before this is reached - by reading, no test pins it; `s6_reprove` would take `--dispatch <running>`,
        not refuse it).
        This closes nothing: the manual block closes S6 as before, the proofs are in no close receipt. Every
        failure is a digest line (P1); an exception is printed and the manual block still comes (AR-28)."""
        runner = self.state.get("s6_manual_runner")
        try:
            changed = self.s6_changed(auto_scope)
            probes = self.s6_probes(changed)
            if not probes:
                return
            rows = self.s6_rows()
            marked = self.state.get("s6_reproved")
            marked = marked if isinstance(marked, dict) else {}
            keys = {i: self.s6_bytes_key(rows[i]) for i in probes if i in rows}
            todo = {i: replay for i, replay in probes.items() if not (keys.get(i) and marked.get(i) == keys[i])}
            if not todo:
                return
            unrun = self.s6_unrun(changed, self.s6_accepted(runner))
            lines, _proved, _seconds, _records = self.s6_reprove(todo, auto_scope, no_stand=no_stand, unrun=unrun)
            for line in lines:
                print(f"S6: {line}")
            if not no_stand and not unrun:
                self.state["s6_reproved"] = dict(marked, **{i: keys[i] for i in todo if keys.get(i)})
                self.save_state()
        except Exception as exc:
            print(f"S6: the live checks of the changed tests could not be proved again before the manual half "
                  f"({type(exc).__name__}); the manual half goes on")
        finally:
            if self.state.pop("s6_manual_runner", None) is not None:
                self.save_state()

    def s6_rows(self) -> dict:
        """`{instance id or alias: manifest row}` of the automation manifest (`proof_level._row_ids`, the one spelling reader)."""
        import contract as C
        import proof_level
        manifest = self.s6_manifest()
        rows = {}
        for entry in C.manifest_tests(manifest if isinstance(manifest, dict) else {}):
            for alias in proof_level._row_ids(entry):
                rows.setdefault(alias, entry)
        return rows

    def s6_bytes_key(self, entry) -> str:
        """The byte state of a manifest row's test as `proof_level.same_test` reads it: `<input_hash>:<instance_content_sha>`
        (the second part empty when no run measured one), "" when the test file cannot be read (then nothing is marked)."""
        import proof_level
        now = proof_level.instance_identity(entry, self.task_root)
        raw = str(now.get("input_hash") or "")
        return f"{raw}:{(now.get('instance_identity') or {}).get('instance_content_sha') or ''}" if raw else ""

    # --- the manual half of S6: prepare by code, windows of `MANUAL_WINDOW_CASES` (one case; a block's ceiling is five) (t-250 §1, C2, C4; t-261) -----------------------

    # TP1-15045 (cmp2): `run_manual_block` sent ALL manual cases in one dispatch while the controller refuses a manual
    # block of more than five (`validate_manual_runner_block`), and `manual_evidence.prepare` refused every case because no
    # obligation was executable. Now the DRIVER prepares each case before anything is dispatched: a case `prepare`
    # refuses is NOT dispatched (its reason, in words, stands in `work/evidence/manual/<case>/request.json` for the
    # report), the others go in blocks of at most MANUAL_BLOCK_MAX in plan-row order, ONE dispatch per entry (the loop
    # comes back for the next). What is already done is read from the controller (the accepted manual dispatches'
    # `manual_case_ids`), so a crash between blocks re-dispatches nothing.
    # t-329 (B-270 g): not a second literal - the controller's own `MANUAL_WINDOW_CASES` (SC2-38 item 3: one case per window;
    # the ceiling `MANUAL_BLOCK_CASES` is what `validate_manual_runner_block` refuses above, and `story_progress` counts the
    # windows left by the window size). The name stays: tests set it on an instance.
    MANUAL_BLOCK_MAX = MANUAL_WINDOW_CASES

    def manual_done(self) -> set:
        """The cases an ACCEPTED manual runner dispatch already carried (`manual_case_ids`)."""
        return manual_done_cases(self.controller_state())

    def manual_order(self, cases: list) -> list:
        """The cases in the plan's row order (then as given); as given when the plan or the cases cannot be read."""
        given = list(dict.fromkeys(str(case) for case in cases))
        try:
            import contract
            from coverage_contract import plan_rows
            position = {str(row.get("id")): i for i, row in enumerate(plan_rows(self.task_root)) if isinstance(row, dict)}
            index = contract.case_index(self.task_root)
            return sorted(given, key=lambda case: (position.get(str((index.get(case) or {}).get("plan_row") or ""),
                                                                len(position)), given.index(case)))
        except Exception:
            return given

    def manual_prepare(self, case: str) -> tuple:
        """([obligation ids], "", "") for a case the agent may check by hand, ([], the refusal in words, "") otherwise, and
        (ids, "", <reason>) for a case the FACTORY failed to prepare (F5(c): it is walked unprepared, never dropped).
        The body is `manual_evidence.prepare_for_block`, which `story_step.py start` calls too (FB-9, AR-15)."""
        import manual_evidence as ME
        return ME.prepare_for_block(self.task_root, case)

    def manual_plan(self, cases: list, skip=()) -> dict:
        """{"blocks": [[case, ...], ...], "refused": [(case, words), ...], "unprepared": [(case, reason), ...]} for the cases not
        yet done (and not in `skip`). Prepares each of them (see `manual_prepare`); the blocks are the prepared ones AND the
        unprepared ones (F5(c): the factory never stands - an unprepared case is walked, listed beside its block), plan-row
        order, at most MANUAL_BLOCK_MAX each (the window: 3), the cases of one account set together (`walk_lanes`: guests form one lane;
        a case whose request cannot be read is a lane of one). Four guest cases -> [3, 1]; with a size of 5: 6 -> [5, 1]; none
        prepared -> no block."""
        # t-1957 N5s: a case whose walk record the build refused once stands in an accepted lane and is walked once more (`walk_after`)
        again = {case for case, entry in ((getattr(self, "state", None) or {}).get("walk_retry") or {}).items()
                 if isinstance(entry, dict) and entry.get("open")}
        gone = (self.manual_done() - again) | {str(c) for c in skip}
        ready, refused, unprepared = [], [], []
        for case in [c for c in self.manual_order(cases) if c not in gone]:
            got = self.manual_prepare(case)
            why, walk = got[1], got[2]
            if why:
                refused.append((case, why))
            else:
                ready.append(case)
                if walk:
                    unprepared.append((case, walk))
        # t-1957 N5s (E5s.8, E5s.9): the lanes - one account set to a lane, plan-row order, at most MANUAL_BLOCK_MAX - by the one function
        # the door and the progress line use; a request that cannot be read leaves its case a lane of one
        return {"blocks": walk_lanes(ready, lane_keys(getattr(self, "task_root", None), ready), self.MANUAL_BLOCK_MAX),
                "refused": refused, "unprepared": unprepared}

    GATE_A_DRY_BLOCK = "gate A recorded dry"       # a name `references/block-names.json` holds (reader: `manual_gate_note`)

    def manual_gate_note(self) -> None:
        """One line when the plan has manual rows and NOT ONE of their obligations is executable: gate A was recorded
        dry (a dry run skips `apply_gate_answers`, the step that makes them so), or the plan was approved before that
        step existed. Said once per entry (FR-41, FR-57), and then - C1-6b, P22 - the person is ASKED (`gate_a_dry_person`:
        `reapprove` / `go on` / `stop`), unless their word already passes the block `gate A recorded dry` (`waiver.py --stage S6`):
        a passed question is not asked again, the line stays."""
        try:
            from coverage_contract import plan_rows
            rows = [r for r in plan_rows(self.task_root) if isinstance(r, dict) and r.get("disposition") == "manual-agent"]
            executable = [o for r in rows for o in r.get("coverage_obligations") or []
                          if isinstance(o, dict) and o.get("decision") == "manual-agent"]
        except Exception:
            return
        if rows and not executable:
            print(f"S6: gate A was recorded dry; the plan has {len(rows)} row(s) checked by an agent by hand and none of "
                  "their obligations says so, so no case can be checked by hand (a dry run skips the step that makes "
                  "them executable, and a plan approved before it keeps them as planned); until gate A is approved again "
                  "or your word passes it, the cases stand as not checked by hand")
            if not waiver.split_overridden([self.GATE_A_DRY_BLOCK], self.pipeline(), "S6")[1]:
                # remains: the dry-gate question is a seam question (priced, `offered`): reapprove has the site's executor, go on / stop the seam's, other words go to the seam
                raise self.gate_a_dry_person(rows)

    def gate_a_dry_person(self, rows: list) -> "Person":
        """The `s6.gate_a_dry` question (C1-6b, S7 of the inventory): the manual rows' cases cannot be checked, gate A having been
        recorded without the step that makes them checkable. `reapprove` is OFFERED only when its executor can run: this run does not
        itself record gates dry (`self.dry` - a `--dry-run` would skip the same step again), no dispatch runs (the `running` fact of
        the seam), the controller holds an approved gate A on the current source revision (what `semantic_reopen` requires) and the
        cases are named in the approved scope; a fact that cannot be read closes it (FR-59), and the lead says so in ONE line (FR-42).
        The cases the question names are kept in `state["gate_a_dry"]`: one answer covers exactly that set."""
        wanted = {str(row.get("id")) for row in rows}
        why, cases = "", []
        try:
            import contract
            state = self.controller_state()
            scope = {str(item) for item in state.get("scope") or []}
            named = sorted(case for case, meta in contract.case_index(self.task_root).items()
                           if str((meta or {}).get("plan_row")) in wanted)
            cases = [case for case in named if case in scope]
            approved = any(d.get("gate") == "A" and d.get("status") == "approved" and d.get("source_revision") == state.get("source_revision")
                           for d in (state.get("decisions") or {}).values())
            running = self.no_move_facts({}).get("running")
        except Exception:
            named, approved, running = [], False, None
            why = "the factory could not read the story's state"
        if not why:
            why = ("this run records gates dry, so asking gate A again would skip the same step" if self.dry
                   else "a role is still working, and gate A can be asked again when it has stopped" if running is True
                   else "the factory could not establish that no role is working" if running is None
                   else "there is no approved gate A to ask again" if not approved
                   else "the factory could not name these cases in the approved plan" if not cases else "")
        shown = cases or named
        lead = (f"{len(shown) or len(rows)} case(s) an agent checks by hand cannot be checked: gate A was recorded without the step that "
                "makes them checkable.\n" + "\n".join(self.case_lines(shown))
                + (f"\nApproving gate A again is not offered now: {why}." if why else "")
                + "\n\nWhat I need from you is one of these:")
        options = ([] if why else [{"answer": "reapprove", "token": "reapprove",
                                    "slots": {"stages": "the case review of S4, gate A and the manual half of S6"},
                                    "says": "approve gate A again so that these cases can be checked by hand; the test design is reviewed "
                                            "again, gate A is asked again, and then they are checked"}])
        options += [{"answer": "go on", "token": "go on",
                     "says": "go on without checking them by hand; the report carries them as not checked, in your words"}, self.STOP_OPTION]
        self.state["gate_a_dry"] = {"cases": cases}
        person = self.site_seam_person("gate_a_dry", self.closed_question("s6.gate_a_dry", lead, options), "S6", block=self.GATE_A_DRY_BLOCK,
                                       details="The plan rows checked by an agent by hand: " + ", ".join(sorted(wanted)))
        person.holds = tuple(cases)            # RN1-24: the cases the question names wait; none named (`cases` empty) = it holds everything
        return person

    def manual_request_paths(self, cases: list) -> list:
        import manual_evidence as ME
        return [ME.request_path(self.task_root, case).relative_to(self.task_root).as_posix() for case in cases]

    def manual_close(self, cases: list, refused: list) -> None:
        """No block is left to dispatch (every case is done, or none could be prepared): the manual half closes with
        no runner - the receipt is `code_only`, written over a `run-report.json` the reducer has just written (the same
        order as the freshness branch of `stage_S6`), then `stage_done`. The words say how many were checked and which
        were not. A reducer that fails is a refusal: nothing is closed over a report nobody could build."""
        self.consumer_need_record("S6", "manual_close")             # X7-6: the manual half closes by the consumer's record (a no-op with no consumer)
        gone = self.manual_done()
        done = [case for case in cases if case in gone]
        # RN1-24: the cases a deferred question holds are closed over as NOT checked, in the safe default `left_unchecked` (no new value of
        # `by`), with the question's number in the reason; the answer, asked before gate B, decides what happens to them next (`retry`
        # sends them back to S6, `prepare` then writes their request again)
        for case, n in self.deferred_waiting(cases):
            held_reason = f"not checked yet: it waits for your answer to question {n}, asked before gate B"
            self.refuse_case(None, case, held_reason, "answer the question about this check that comes before gate B", "left_unchecked")
            refused = list(refused) + [(case, held_reason)]
        reason = (f"the manual half of S6: {len(done)} case(s) checked by an agent by hand, {len(refused)} not checked"
                  + (": " + ", ".join(case for case, _why in refused) if refused else ""))
        code, out = self.py("finalize_task.py", str(self.task_root))
        if code:
            raise Refusal(f"S6 manual half: finalize_task.py exit {code}: " + (out.splitlines()[-1] if out else ""))
        self.close_by_code("S6", reason, ["work/run-report.json"] + self.manual_request_paths([case for case, _ in refused]),
                           finalize=False, site="s6.manual_close")

    # --- the stand's sign-in account, asked BEFORE a block with a screen case is dispatched (t-292) -----------------------

    # TP1-15045 (cmp2r rehearsal, 02.10): a manual block of screen cases was dispatched with no usable test account,
    # and every capture photographed the sign-in page. The material is read by the capture's own reader
    # (`manual_capture.read_login`), so the gate and the capture see the same file; the question comes before any
    # block is registered or launched, and the person's word passes it like every other block (FR-4).
    STAND_LOGIN_BLOCK = waiver.STAND_LOGIN_MISSING_BLOCK       # the one definition (t-722 N5)

    def manual_policy(self, case: str) -> str:
        """The evidence policy of a case `manual_prepare` has just prepared (`ui`, `api`, ...), read from its request;
        "" when the request is unreadable, holds `refused`, or names no policy (an unknown). A seam: the rig stubs it
        the way it stubs `manual_prepare`."""
        import manual_evidence as ME
        request = _read_json(ME.request_path(self.task_root, case))
        if not isinstance(request, dict) or isinstance(request.get("refused"), dict):
            return ""
        return str(request.get("evidence_policy") or "")

    STAND_LOGIN_KEYS = ("Where the factory looks for the account: environment.env_files (the files) or environment.env_file (the file), environment.user_key "
                        "(the key of the account's name, default AUTH_USERNAME) and environment.secret_keys[0] (the key "
                        "of its password, default AUTH_PASSWORD) in the project's qa-factory/config.json. A project whose "
                        "screens need no sign-in at all sets manual_capture.login.ui to null there.")

    def _cases_all_on_driver(self, cfg, cases) -> bool:
        """True only when every case of `cases` is planned `manual-agent` on a profile whose surface row has `hands: driver`
        (`gate_preflight.stand_profiles`, `surfaces.row_for_profile`). ERROR DIRECTION: a doubt is False (no cases, a case no
        profile claims, a profile with no such row, a broken table, any exception) - the old question is asked, a question too
        many and never one too few."""
        if not cases:
            return False
        try:
            import gate_preflight as GP
            import surfaces
            of_case = {c: pid for pid, entry in GP.stand_profiles(cfg, self.task_root, ("manual-agent",)).items()
                       for c in entry.get("cases") or []}
            hands: dict = {}
            for case in cases:
                pid = of_case.get(case)
                if not pid:
                    return False
                if pid not in hands:
                    row = surfaces.row_for_profile(cfg, pid)
                    hands[pid] = surfaces.is_device_row(row)
                if not hands[pid]:
                    return False
            return True
        except Exception:
            return False

    def stand_login_problem(self, cases=None) -> tuple:
        """("", "") when the stand's test account can be read - or the project says it needs none (`manual_capture.
        login.ui: null`); else (kind, details): `no_file` (the settings name no file), `missing_file` (the file they
        name is not there - or the settings file itself cannot be loaded: its own text is the details), `unreadable`
        (the file is there but cannot be read: a folder in its place, no permission), `missing_key` (it lacks the
        account's name or password). The capture's own
        loader and reader (`manual_capture.load_config`, `read_login`), so the gate and the capture read the same file
        and resolve `env_file` against the same root. ERROR DIRECTION: toward "missing" - a question too many, never
        "present" when the capture would fail on the file. Wrong but present values pass: the landing proof of the
        capture catches them."""
        import manual_capture as MC
        try:
            cfg, root = MC.load_config(self.task_root)
        except ValueError as exc:
            # t-308 F6: a settings file that is absent or broken was shown as "the settings name no file" - false
            return "missing_file", f"{exc}\n\n{self.STAND_LOGIN_KEYS}"
        if MC.login_declared_none(cfg, "ui"):
            return "", ""
        # EP1-41f (N-18): a block whose cases are ALL on a device stand signs in with no default web account, so only that block
        # is skipped; the accounts the cases name are still asked for below. POSITION: after `login_declared_none`, before the
        # default account is read.
        # PK0-5 (AR-19): the default account is read only when the ONE rule of gate A says the story needs it
        # (`gate_preflight.default_login_needed`; a doubt is "needed"). POSITION: after `login_declared_none` and the device clause, before
        # `read_login` - a story that needs no default login is never refused over keys nothing will use.
        import gate_preflight as GP
        import stand_gaps
        on_driver = self._cases_all_on_driver(cfg, cases)
        asked_default = []

        def read_default() -> tuple:
            """("", "") or the refusal; read at most once (also for a case whose request cannot be read: its capture signs in as default)."""
            if asked_default:
                return "", ""
            asked_default.append(True)
            try:
                login = MC.read_login(cfg, root)
            except MC.LoginMaterialMissing as exc:
                kind = {"file": "missing_file", "unreadable": "unreadable"}.get(exc.part, "missing_key")
                return kind, f"{exc}\n\n{self.STAND_LOGIN_KEYS}"
            except ValueError as exc:
                return "missing_key", f"{exc}\n\n{self.STAND_LOGIN_KEYS}"
            if login is None:
                return "no_file", ("the project's settings name no file for the stand's login (environment.env_file)"
                                   f"\n\n{self.STAND_LOGIN_KEYS}")
            return "", ""
        if not on_driver and GP.default_login_needed(self.task_root, cfg):
            problem = read_default()
            if problem[0]:
                return problem
        # HF5-3: the accounts the screen cases of the block name in their requests (`manual_evidence.request_actors`, the one
        # reader of the field). POSITION: after the default account, and `cases` are the screen cases only - the caller
        # returns before this when there is none, so an http-only block asks nothing (its capture refuses by key name).
        # A `stand_account` role is read as `read_login(..., actor=role)` reads it; an account named by one `env` key must
        # have that key set in the env file (the pair is the capture's `--as env:U/S`; here the one key is read twice).
        # A request that is absent or unreadable adds nothing of its own: its capture signs in as the default account, which the loop
        # reads (once) for it when the rule above did not. The details name the case and the account, never a value.
        import config_contract
        import manual_evidence as ME
        chosen = stand_gaps.stand_name(self.task_root)       # loop-invariant: the chosen stand, the entry of that name (or None)
        chosen_stand = next((e for e in cfg.get("environments") or [] if isinstance(e, dict) and str(e.get("name") or "") == chosen), None)
        for case in cases or []:
            actors, why = ME.request_actors(self.task_root, case)
            if why or not ME.request_path(self.task_root, case).is_file():
                print(f"S6: {case}: {why or 'its prepared request is not there'}; the stand's default account is checked "
                      "for it", file=sys.stderr)
                if not on_driver:
                    problem = read_default()
                    if problem[0]:
                        return problem
            for actor in actors:
                check = actor.get("check") if isinstance(actor.get("check"), dict) else {}
                kind, value = next(iter(check.items()), ("", ""))
                if kind not in ("stand_account", "env"):
                    continue
                # GW1-27: the role is what the gate reads (`gate_preflight.account_role`): the value is trimmed, and a spelling
                # differing in case, `_`, `-` or spaces is read as `resolve_actor` reads it. PK0-5 (S11 c): the stand is the CHOSEN one
                # (`stand_gaps.stand_name`, the entry of that name, found above the loop) - an account answered for `dev` is never read
                # on `stage`, and no other stand is searched; a role with no chosen stand is refused with the reason, never read on a
                # guessed one. The reserved forms (`default`, `env:...`, `created:...`) need no stand: they are not refused for its absence.
                value = str(value).strip() if kind == "stand_account" else value
                as_actor = str(value) if kind == "stand_account" else f"env:{value}/{value}"
                stand = chosen_stand
                if kind == "stand_account" and not config_contract.reserved_role(value) and stand is None:
                    return "missing_key", (f"{case}: the story has no chosen stand, so the account {actor.get('id')} ({value}) cannot "
                                           f"be read on it\n\n{self.STAND_LOGIN_KEYS}")
                if value == "default":
                    stand = None
                try:
                    MC.read_login(cfg, root, actor=as_actor, stand=stand, task_root=self.task_root)
                except ValueError as exc:      # LoginMaterialMissing is one, and so is every refusal of `resolve_actor`
                    return "missing_key", (f"{case}: the account {actor.get('id')} ({kind} {value}) cannot be read: {exc}"
                                           f"\n\n{self.STAND_LOGIN_KEYS}")
        return "", ""

    STAND_LOGIN_REASONS = {"no_file": "the project's settings name no file for it",
                           "missing_file": "the file the settings name for it is not there",
                           "unreadable": "the file the settings name for it could not be read",
                           "missing_key": "the file the settings name does not hold the account's name or its password"}

    def case_lines(self, cases: list) -> list:
        """One line per case for a question: its title and id; a case with no title by a link to its case file on the same line (the
        stand-login question and the dry-gate question name their cases the same way)."""
        import contract
        try:
            index = contract.case_index(self.task_root)
        except Exception:
            index = {}
        lines = []
        for case in cases:
            entry = index.get(case) if isinstance(index, dict) else None
            path = Path(str((entry or {}).get("path") or "")) if entry and (entry or {}).get("path") else None
            try:
                title = " ".join(contract.case_title(path).split()) if path else ""
            except Exception:
                title = ""
            if title:
                lines.append(f"- {title} ({case})")
            elif path:
                try:
                    shown = path.resolve().relative_to(self.task_root.resolve()).as_posix()
                except ValueError:
                    shown = path.name
                lines.append(f"- [{case}]({shown})")
            else:
                lines.append(f"- {case}")
        return lines

    def stand_login_question_text(self, cases: list, kind: str) -> str:
        """The question (references/human-questions.md): what was done, why it cannot go on, one question, three closed
        answers with their prices. Each case by its title and id (`case_lines`)."""
        lines = self.case_lines(cases)
        reason = self.STAND_LOGIN_REASONS.get(kind, self.STAND_LOGIN_REASONS["no_file"])
        # RN1-24: when the question is going to be set aside (`holds_can_wait`: the same test `deferrable` makes for this question) the
        # other checks do NOT wait for it, and the text says which road it is on; otherwise the live text is unchanged
        others = (f"the other checks go on; these cases wait for your answer: {', '.join(str(case) for case in cases)}"
                  if self.holds_can_wait(cases) else "the other checks by hand wait for this answer too")
        lead = (f"The requirements, the test plan and the test cases for {self.task} are done, and the checks an agent "
                f"makes by hand are next. {len(cases)} of them look at the product's screens:\n" + "\n".join(lines)
                + f"\nTo open those screens the agent signs in to the stand with the project's test account, and I "
                f"cannot find that account: {reason}. I have not started any of these checks: without the account they "
                f"would only photograph the sign-in page, and {others}.\n\n"
                "What I need from you is one of these:")
        # C1-6b: the options carry their three price lines (the data row of `s6.stand_login`); the tokens are unchanged
        return self.closed_question("s6.stand_login", lead, [
            {"answer": "retry", "token": "retry", "slots": {"what": "put the account where the settings point"},
             "says": "put the test account where the project's settings point (or point the settings at the file that holds it; if "
                     "these screens need no sign-in at all, say so in the settings); I look again"},
            {"answer": "by hand", "token": "by hand", "slots": {"what": "the screen checks named above"},
             "says": "you will check these screens yourself; I leave them out and the report says so, in your words"},
            {"answer": "go on", "token": "go on",
             "says": "leave them unchecked; the report carries them as not checked, in your words"}])

    def stand_login_gate(self, plan: dict) -> None:
        """Before ANY block of `plan` is dispatched: when a ready case opens the product's screens (policy `ui`; an
        unknown policy counts as ui, with one printed line - ERROR DIRECTION toward asking: one answer for the person,
        against a role session spent photographing the sign-in page) and the stand's test account cannot be read, the
        person is asked (a `Person`, kind `stand_login`) - unless their word already passes the block `stand login
        missing` (`waiver.py --stage S6`, read ONLY while the material is missing: once it is there, the cases are
        dispatched even though a pass exists). A pass skips the screen cases, in the person's words: they join
        `plan["refused"]` (and their request.json says so), the other blocks are re-chunked - no second `prepare`.

        POSITION (the invariant): after `manual_plan` (the policy is known from the request it wrote) and before the
        controller registers or the runner launches anything: no block holding a screen case exists while the account
        is missing and no word passes it. Nothing is asked when no screen case remains (http-only stories, cases
        done or refused), and `run_manual_block`'s C4 rule holds: a skipped case is in `refused`, so the last block
        goes not-complete and the next entry closes the manual half code-only, naming it."""
        ready = [case for block in plan["blocks"] for case in block]
        screens = []
        for case in ready:
            policy = self.manual_policy(case)
            if not policy:
                print(f"S6: {case}: its prepared request ({self.manual_request_paths([case])[0]}) could not be read "
                      "or names no policy, so the case counts as one that opens the product's screens")
            if policy in ("ui", ""):
                screens.append(case)
        if not screens:
            return
        kind, details = self.stand_login_problem(screens)
        if not kind:
            return
        _blocking, passed = waiver.split_overridden([self.STAND_LOGIN_BLOCK], self.pipeline(), "S6")
        if not passed:
            # A7 (C1-6b): a seam question - `retry` / `go on` are carried out by the seam's own executors, `by hand` by the same pass
            # plus the site's typed record (`_take_stand_login_answer`)
            # remains: the stand-login question is a seam question (priced, `offered`): every token has an executor, other words go to the seam
            person = self.site_seam_person("stand_login", self.stand_login_question_text(screens, kind), "S6",
                                           block=self.STAND_LOGIN_BLOCK, details=details)
            person.login_cases = list(screens)       # read by `ask()`, which sets the flag - and clears it for every other Person
            # RN1-24: the screen cases wait for the answer; the other ready cases do not (`Driver.run` may set the question aside)
            person.holds = tuple(screens)
            raise person
        said = " ".join(str(passed[0].get("decision") or "").split())
        reason = ("not checked by an agent: the stand's sign-in account is not set up for the factory; the person said: "
                  f"\"{said}\"")
        door = "put the stand's test account in the project's settings; the next run checks it by hand"
        # A6: the TYPED carrier of the choice, never a token read out of the words: `by hand` -> `person_checks` (the delivery check
        # restates the case as handed to the person), anything else - `go on`, a pass the conductor recorded from free words, a pass
        # with no record of ours - -> `left_unchecked` (the safe default: no claim that the person checks it)
        choice = self.state.get("login_choice") or {}
        by = ("person_checks" if choice.get("token") == "by hand" and choice.get("words") == said.replace(self.BOM, "").strip()
              else "left_unchecked")      # the record is bound to THE pass it was made for: its words are the pass's words
        for case in screens:
            self.refuse_case(plan, case, reason, door, by)
            print(f"S6: {case}: not checked by hand — {reason}")
        left = [case for case in ready if case not in set(screens)]
        plan["blocks"] = manual_blocks(left, self.MANUAL_BLOCK_MAX)

    def manual_lane_plan(self, cases: list) -> tuple:
        """`(plan, waiting)` for the manual cases of S6 at this entry (t-2147 C1: the plan half of the old `run_manual_block`, unchanged): the
        cases a deferred question holds, the dry-gate note, `manual_plan`, the stand-login gate, the lanes cut again, the cases whose walk
        record was refused twice named beside the refused ones, and the lanes whose account has no pair refused. Its lines and its order are
        the old road's; `plan["blocks"]` are the lanes."""
        # RN1-24: the cases a deferred question holds are not prepared, not asked about again and not dispatched; the dry-gate note
        # is not raised a second time while ITS question waits (E11: one open question per case; `deferrable` read the same record).
        waiting = self.deferred_waiting(cases)
        if not any(item.get("kind") == "gate_a_dry" for item in self.deferred_items()):
            self.manual_gate_note()
        plan = self.manual_plan(cases, skip=[case for case, _n in waiting])
        for case, why in plan["refused"]:
            print(f"S6: {case}: not checked by hand — {why}")
        for case, why in plan.get("unprepared") or []:
            print(f"S6: {case}: unprepared - {why}; the manual agent walks it without a prepared request and records no result")
        self.stand_login_gate(plan)      # t-292: the account for the screen cases, BEFORE any block is registered
        # t-1957 N5s: the gate re-chunks what a pass leaves by the plain split; cut the cases that are left into lanes again (the same
        # function), and name the cases whose walk record was refused twice (closed `left_unchecked`) beside the refused ones
        plan["blocks"] = walk_lanes([case for lane in plan["blocks"] for case in lane],
                                    lane_keys(self.task_root, [case for lane in plan["blocks"] for case in lane]), self.MANUAL_BLOCK_MAX)
        for case, entry in (self.state.get("walk_retry") or {}).items():
            if case in cases and isinstance(entry, dict) and entry.get("refused", 0) > 1 and case not in [c for c, _w in plan["refused"]]:
                plan["refused"].append((case, str(entry.get("reason") or "the record of its walk was refused twice")))
        self.walk_refuse_gaps(plan)     # TR1-4: a lane whose account has no pair is not walked, and does not stop the next lane
        # TR3-10d item 1 (D.5): the account and record assignment is for the PARALLEL road only - more than one lane and `manual.walkers`
        # not 1. INVARIANT: on the old road no pool is read and no state key is written; a key left by an earlier entry is cleared (its
        # reservations settled) so that a lane never runs under an assignment that is not this entry's. POSITION: after `walk_refuse_gaps`
        # (a lane that cannot walk costs no handle) and before any dispatch of this entry is registered.
        if self.s6_walkers_cap() != 1 and len(plan["blocks"]) >= 2:
            self.walk_assign_step(plan)
        else:
            self.walk_assign_clear()
        return plan, waiting

    def walk_assign_clear(self) -> None:
        """TR3-10d L4 (AR-25): the assignment of an EARLIER entry goes before a new one is made, or when this entry makes none. A reserved walk
        id that no controller dispatch took was never walked: its records are settled `free` (`walk_settle_unopened`; no walker touched the
        account or the record); the five `walk_*` assignment keys of the state are dropped. A walk that a dispatch took is left to `walk_before`
        / the verdict (`settle_unopened` never moves a walk that has a record). ERROR DIRECTION: when the controller's dispatches cannot be read
        nothing is settled and nothing is dropped (an unknown is never a free). Reads nothing when the state holds no key (the old road)."""
        if not ("walk_assign" in self.state or "walk_assign_cases" in self.state or "walk_entities" in self.state
                or "walk_ids" in self.state or "walk_alone" in self.state):
            return
        try:
            dispatches = (self.controller_state() or {}).get("dispatches")
            if not isinstance(dispatches, dict):
                print("note: S6: the controller record holds no dispatches; the held records of the lanes stay as they are", flush=True)
                return
            taken = {str(k) for k in dispatches} | {str(v.get("id")) for v in dispatches.values() if isinstance(v, dict)}
            running = ({str(k) for k, v in dispatches.items() if isinstance(v, dict) and v.get("status") == "running"}
                       | {str(v.get("id")) for v in dispatches.values() if isinstance(v, dict) and v.get("status") == "running"})
        except Exception as exc:       # noqa: BLE001 - P1/FR-59: unreadable stays as it is (held, never free), with one note
            print(f"note: S6: the controller record could not be read ({type(exc).__name__}); the held records of the lanes stay as they are",
                  flush=True)
            return
        for did in [str(i) for i in (self.state.get("walk_ids") or {}).values() if i]:
            if did not in taken:
                self.walk_settle_unopened(did, "free")
            elif did not in running:
                # TR3-10d N3 (AR-25): a dispatch registered but no longer running whose walk has no record is the crash between the
                # registration and `walk_before`; the lane may have run on the recorder, so `dirty` (never free). A walk with a record is
                # not moved (`settle_unopened`), a running dispatch is left alone.
                self.walk_settle_unopened(did, "dirty")
        self.state.pop("walk_assign", None)
        self.state.pop("walk_assign_cases", None)
        self.state.pop("walk_entities", None)
        self.state.pop("walk_ids", None)
        self.state.pop("walk_alone", None)
        self.save_state()

    def walk_assign_step(self, plan: dict) -> dict:
        """TR3-10d item 1 (AR-13, AR-15, AR-28; the parallel road only): which account each lane signs in as and which record of an exclusive kind
        it uses, decided ONCE per entry before any dispatch. Reads `walk_supply` (the one reader; its notes said once), the doubts, a pool per key
        part (`walk_pool.pool_of`), `assign_lanes`, and `assign_entities` (the `in_use` records are written there, under the ids reserved here).
        State (all keyed by the lane number as text, re-made at every entry): `walk_assign` {n: {part: handle}} - ONLY a lane whose EVERY part has
        a handle (L3: any other lane keeps today's key-based holds and actor); `walk_assign_cases` {first case: n} for every lane; `walk_entities`
        {n: {item: [entry]}}; `walk_ids` {n: reserved walk id} (L1: `run_manual_lane` takes it, so the id the claims store holds is the id the
        walk opens under); `walk_alone` [first case, ...] - the lanes that run alone in the serial first round (item 7; ERROR DIRECTION toward
        alone: a lane whose request carries `walk_global`; with no data words, a lane that needs an exclusive kind with no free instance or with no
        pool at all; a claims store that cannot be used). Never raises (P1): a failure is one note and the lanes keep today's holds. Returns
        the facts the way question will need: `{"short": [(part, lanes waiting, pool size)], "alone_kinds": [kind text], "supply": the supply,
        "may_change": whether the stand may be changed}`. TR3-10 D3b: at its end it RAISES the one question owed (`walk_supply_raise`), the only
        `Person` that leaves it; walkers 1 or one lane never reach it (D.5)."""
        import config_contract as CC
        import manual_capture as MC
        import manual_evidence as ME
        import walk_pool as WP
        T = self.task_root
        facts: dict = {"short": [], "alone_kinds": [], "supply": {}}
        try:
            self.walk_assign_clear()
            supply, notes = CC.walk_supply(self.config)
            facts["supply"] = supply
            for note in notes:
                self.say_once("walk_supply", note)
            lanes = [[str(c) for c in lane] for lane in plan.get("blocks") or ()]
            flat = [case for lane in lanes for case in lane]
            keys = lane_keys(T, flat) if flat else {}
            doubts = MC.account_doubts(T)
            try:
                cfg, _root = MC.load_config(T)
            except ValueError:
                cfg = {}                # no stand records at all: no pool, today's refusals
            stand = WP._stand_of(cfg)
            pools: dict = {}
            for lane in lanes:
                key = keys.get(lane[0]) if lane else None
                for part in (key.split("+") if isinstance(key, str) else []):
                    if part and part not in pools:
                        pools[part], more = WP.pool_of(T, cfg, lane[0], part, supply, doubts)
                        notes.extend(more)
            may_change = MC._stand_may_change(stand, MC.spec()["safe_to_break_no"])
            facts["may_change"] = may_change
            obtain, more = WP.obtain_roles_of(supply, MC._roles_of(stand))
            notes.extend(more)
            failed = self.state.get("obtain_failed") or {}
            obtain = [role for role in obtain if not failed.get(role)]
            if obtain and not may_change:
                self.say_once("walk_obtain_stand", "note: S6: you said a walker may make its own user, but your settings do not mark this "
                                                   "stand as one that may be changed; walkers use the accounts that exist")
            assignment, more = WP.assign_lanes(lanes, pools, obtain, may_change, keys)
            notes.extend(more)
            requests: dict = {}
            for case in flat:
                try:
                    requests[case] = _read_json(ME.request_path(T, case))
                except ValueError:
                    requests[case] = {}
            # L1: one walk id per lane that needs a record, taken from the numbers no dispatch has; `run_manual_lane` takes it back
            dispatches = (self.controller_state() or {}).get("dispatches")
            if not isinstance(dispatches, dict):
                # an early exit, not a raise caught below: the same note, the lanes keep today's holds; no question is owed on this path
                # (`short` and `alone_kinds` are still empty, so `walk_supply_raise` would return None)
                print("note: S6: the accounts and records of the lanes were not assigned (ValueError: the controller record holds no "
                      "dispatches); the lanes run as before", flush=True)
                return facts
            needs = WP._needs(lanes, requests)
            start = len([d for d in dispatches.values() if isinstance(d, dict) and d.get("stage") == "S6" and d.get("role") == "qa-runner"]) + 1
            reserved: dict = {}
            for n in needs:
                reserved[n] = self.walk_next_id(dispatches, start, reserved.values())
            data = supply["data"]
            entities, more = WP.assign_entities(lanes, requests, data["pools"], T, reserved, data["may"])
            notes.extend(more)
            # the records are written now: their ids and the lanes' numbers go into the state at once, so a failure below can never leave a
            # held record that no entry will settle (the next entry's `walk_assign_clear` reads `walk_ids`)
            self.state["walk_assign_cases"] = {lane[0]: n for n, lane in enumerate(lanes, 1) if lane}
            self.state["walk_ids"] = {str(n): reserved[n] for n, found in entities.items() if found.get("state") == "given" and n in reserved}
            self.save_state()
            for note in dict.fromkeys(notes):
                self.say_once("walk_pool", note if note.startswith("note:") else f"note: S6: {note}")
            by_handle: dict = {}
            for n, parts in assignment.items():
                for handle in dict.fromkeys(parts.values()):
                    by_handle.setdefault(handle, []).append(n)
            for handle, numbers in by_handle.items():
                if len(numbers) > 1:
                    pool = next((p for p in pools.values() if handle in p), [handle])
                    role = getattr(pool, "role", "") or handle
                    self.say_once("walk_shared:" + handle, f"S6: {len(numbers)} lanes wait for each other: the project's list holds {len(pool)} "
                                                           f"account(s) for {role}")
            short, more = WP.short_parts(assignment, pools, supply, self.s6_walkers_cap())
            facts["short"] = short
            for note in more:
                self.say_once("walk_pool", f"note: S6: {note}")
            assigned: dict = {}
            for n, parts in assignment.items():
                key = keys.get(lanes[n - 1][0])
                wanted = [p for p in key.split("+") if p] or [""]
                if all(p in parts for p in wanted):
                    assigned[str(n)] = {p: parts[p] for p in wanted}
            known = bool(data["known"])
            store_failed = any(note.startswith("records were not assigned") for note in notes)
            alone, kinds = [], []
            for n, lane in enumerate(lanes, 1):
                if not lane:
                    continue
                state = (entities.get(n) or {}).get("state")
                wanted = [(k, t) for item in (needs.get(n) or {}).values() for k, t in item]
                nopool = [t for k, t in wanted if k not in data["pools"]]
                gone = [t for k, t in wanted if k in data["pools"]] if state in ("wait", "alone") else []
                every = any(isinstance(requests.get(c), dict) and isinstance(requests[c].get("walk_global"), str)
                            and requests[c]["walk_global"].strip() for c in lane)
                if every or (n in needs and store_failed) or (not known and (nopool or gone)):
                    alone.append(lane[0])
                    if not every and not known:
                        kinds.extend(k for k in nopool + gone if k not in kinds)
            facts["alone_kinds"] = kinds
            self.state["walk_assign"] = assigned
            self.state["walk_entities"] = {str(n): found["entries"] for n, found in entities.items() if found.get("state") == "given"}
            self.state["walk_alone"] = alone
            self.save_state()
        except Exception as exc:        # noqa: BLE001 - P1: the assignment informs, it never stops S6; the lanes keep today's holds
            print(f"note: S6: the accounts and records of the lanes were not assigned ({type(exc).__name__}: {' '.join(str(exc).split())[:200]}); "
                  "the lanes run as before", flush=True)
        # TR3-10 D3b (spec items 9 and 12; D.2, D.3, D.11): the way question or the data-change question, ONE per entry. POSITION: here, at the
        # end of the assignment step, before any dispatch of this entry is registered - the question is set aside (`no_hold`, it holds no
        # case) and the next entry runs the lanes in turn. INVARIANT: a `Person` leaves this step only here; any other failure of the raise
        # block is one note and the lanes go on (P1: a question never stops S6).
        try:
            # remains: the way question is the person's intent, set aside (`no_hold`) and raised once per entry by design (D.2, D.3); not a state with no move
            person = self.walk_supply_raise(facts)
        except Person:
            raise
        except Exception as exc:        # noqa: BLE001 - P1/D.11: the raise informs, it never stops S6
            print(f"note: S6: the question about test accounts and records was not raised ({type(exc).__name__}: "
                  f"{' '.join(str(exc).split())[:200]}); the lanes go on in turn", flush=True)
            person = None
        if person is not None:
            raise person
        return facts

    def walk_asked(self, kind: str) -> bool:
        """Is the S6 question `kind` already owed or asked in this story (D.3)? A deferred item of that kind, or its `<kind>_asked` row id in
        the state (set by the question's builder, kept for the story)."""
        row = self.state.get("walk_supply_asked") if kind == "walk_supply" else self.state.get("data_change_asked")
        return any(item.get("kind") == kind for item in self.deferred_items()) or bool(row)

    def walk_supply_raise(self, facts: dict):
        """The ONE question this entry owes, or None (items 9 and 12). Reads only `walk_assign_step`'s facts: `walk_supply` first - the short
        parts of a pool while `supply.accounts.known` is False, or a lane made alone by a data shortage while `supply.data.known` is False; else
        `data_change` - a lane made alone for lack of a free record while `supply.data.may_known` is False. Each is skipped when its question
        is already deferred or asked in this story (`walk_asked`); an answered half is `known` in the supply and never reaches here. The other
        question waits for the next entry (D.3: two questions never ask the same thing)."""
        supply, short, kinds = facts.get("supply") or {}, facts.get("short") or [], [str(k) for k in facts.get("alone_kinds") or [] if str(k).strip()]
        accounts, data = supply.get("accounts") or {}, supply.get("data") or {}
        if ((short and not accounts.get("known")) or (kinds and not data.get("known"))) and not self.walk_asked("walk_supply"):
            # remains: the way question is the person's intent with its three closed answers (L5), not a state with no move; `_answer_walk_supply` executes them
            return self.walk_ask_once("walk_supply", ["/manual/accounts_way", "/manual/data_way"],
                                      "how this project gets more test accounts and which records walkers may share",
                                      str(self.walk_supply_text(short)), lambda row: self.walk_supply_person(row, short))
        if kinds and not data.get("may_known") and not self.walk_asked("data_change"):
            may_change = bool(facts.get("may_change", True))
            # remains: the data-change question is the person's permission with its closed answers, not a state with no move; `_answer_data_change` executes them
            return self.walk_ask_once("data_change", ["/manual/data_way/may"],
                                      "whether the factory may make and remove records on the stand for the walkers' data pools",
                                      str(self.data_change_text(kinds, may_change)), lambda row: self.data_change_person(row, kinds, may_change))
        return None

    def walk_ask_once(self, kind: str, field_refs: list, essence: str, asked: str, build) -> "Person | None":
        """The ONE body of "open the registry row, then build the question" for the S6 supply questions (AR-15). `project_decisions.py add`
        (scope project, owner `user`; an open row of the same refs is returned and reused, FR-7); the row's id goes to `build(row_id)`, which
        keeps it in the state (`<kind>_asked`) - the state is saved BEFORE the person is returned to be raised. An `add` that exits non-zero or
        prints no row is one note, said once, and None: no question, the lanes go on in turn, the next story tries again (D.11, FR-59)."""
        args = ["--root", str(self.project), "add", *[a for ref in field_refs for a in ("--field-ref", ref)],
                "--essence", essence, "--asked", asked, "--scope", "project", "--owner", "user"]
        code, out = self.py("project_decisions.py", *args)
        row = None
        if not code:
            try:
                row = json.loads(out)
            except ValueError:
                row = None
        row_id = str(row.get("id") or "") if isinstance(row, dict) else ""
        if not row_id:
            self.say_once(kind + "_add", "note: S6: the question about test accounts and records could not be written to the project's decision "
                                         "registry, so it is not asked now; the checks go on in turn and the next story tries again")
            return None
        person = build(row_id)
        self.save_state()
        return person

    def run_manual_block(self, cases: list) -> None:
        """qa-runner for the manual-agent cases, ONE block per entry: the dispatch is registered in-process (FB-9: `story_step start
        --execution-kind manual --scope <block>` registers the same fields) because the driver keeps its own role prompt lines.

        C4 (the 13797-run-3 class): only the LAST block closes the stage, and only when nothing was refused - the
        controller completes S6 over its derived scope by ACCEPTED dispatches (`_s6_completion_problems`), a case that
        was never dispatched is outside that cover, and a completion over it is refused. When refused cases exist, the
        last block goes `--not-complete` and the next entry (no block left) closes the manual half code-only, as the
        edge of this change says for "no case could be prepared".

        t-2147 C1: with `manual.walkers` 1, one lane, or a serial reason (`s6_serial_reason`) this is the old road, one lane per entry
        (`run_manual_lane(None, lane)`: no thread, no new state key, no flag on the request). Otherwise the lanes go side by side on the
        window scheduler (`run_s6_lanes`); the lanes that meet a running or stopped dispatch, or whose account cannot be read, run first
        at one lane at a time and the stage re-enters for the rest (the F6 road of `stage_S5`, one round)."""
        plan, waiting = self.manual_lane_plan(cases)
        if not plan["blocks"]:
            self.manual_close(cases, plan["refused"])
            return
        lanes = plan["blocks"]
        walkers = self.s6_walkers_cap()
        self._s6_view = {"plan": plan, "waiting": waiting, "cases": [case for lane in lanes for case in lane]}
        try:
            if walkers != 1 and len(lanes) >= 2:
                reason = self.s6_serial_reason()
                if reason:
                    self.say_once("s6-lanes", f"note: S6 lanes run one at a time: {reason}")
                if not reason or reason == self.S6_SETTLE_RUNNING:
                    try:
                        first = self.s6_settling_lanes(lanes)
                    except Exception:       # noqa: BLE001 - unreadable: the unknown stays serial (FR-59; the S5 twin does the same)
                        first = []
                        reason = reason or "the lanes that settle first cannot be read"
                    if first:
                        return self.run_s6_lanes(plan, 1, first)       # the stage re-enters for the rest
                    if not reason:
                        return self.run_s6_lanes(plan, min(walkers, len(lanes)))
            self.run_manual_lane(None, lanes[0])
        finally:
            self._s6_view = None

    S6_SETTLE_RUNNING = "dispatches of S6 are running or stopped at entry; they settle first and the rest goes side by side after"

    def s6_serial_reason(self) -> str:
        """"" when the S6 lanes may run side by side, else the one reason they run one at a time (t-2147 C1 item 7; it tells, it never stops).
        ERROR DIRECTION: it may say serial needlessly on doubt, and must never let two lanes run where a row below holds. The project's own
        word (`manual.walkers: 1`) is not this function's: that is the old road itself. Reads the entry's plan through `_s6_view`."""
        import config_contract
        import dispatch_identity
        view = getattr(self, "_s6_view", None) or {}
        host_reason = self.host_window_reason()
        if host_reason:
            return host_reason
        try:
            mode = ((config_contract.effective_config(self.config).get("execution") or {}).get("parallel") or {}).get("mode")
        except Exception:       # noqa: BLE001
            mode = None
        if mode == "serial":
            return "the project asks for serial execution (`execution.parallel.mode: serial`), so one walker uses the stand at a time"
        if getattr(self, "_s6_cap_one", False):
            return "the model service limited one lane earlier in this run"
        try:
            ctl = self.controller_state()
            rows = dispatch_identity.records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
        except Exception:       # noqa: BLE001
            return "the state of the S6 dispatches cannot be read"
        if any(r.get("stage") == "S6" and r.get("status") in ("running", "blocked", "paused") for r in rows):
            return self.S6_SETTLE_RUNNING
        if view.get("waiting"):
            return "a question about a check, asked before gate B, holds a case of the plan"
        try:
            self.s6_open_lanes(())
        except Exception:       # noqa: BLE001
            return "the state or the plan of the lanes cannot be read"
        return ""

    def s6_settling_lanes(self, lanes: list) -> list:
        """The lanes among `lanes` that run FIRST at one at a time (t-2147 C1 items 2b and 6): those whose cases meet a running, blocked or
        paused S6 dispatch at entry, then those whose account cannot be read from the request. Empty when a dispatch names no case (nothing
        is then known to settle). Raises with the readers (the caller treats that as nothing to settle)."""
        import dispatch_identity
        ctl = self.controller_state()
        rows = dispatch_identity.records(ctl.get("dispatches") if isinstance(ctl, dict) else None)
        scopes = [{str(c) for c in r.get("scope") or [] if c} for r in rows
                  if r.get("stage") == "S6" and r.get("status") in ("running", "blocked", "paused")]
        if any(not s for s in scopes):
            return []
        named = [lane for lane in lanes if any({str(c) for c in lane} & s for s in scopes)]
        unreadable = [lane for lane in lanes if lane not in named and self.s6_lane_account(lane) is None]
        # TR3-10d L2 (item 7): a lane the assignment marked ALONE joins the serial first round. INVARIANT: an alone lane never runs beside
        # another lane (the holds are intersection-only, so they cannot say "conflicts with everything")
        alone = {str(c) for c in self.state.get("walk_alone") or ()}
        loners = [lane for lane in lanes if lane not in named and lane not in unreadable and lane and str(lane[0]) in alone]
        return named + unreadable + loners

    def s6_lane_account(self, lane) -> "str | None":
        """The account key of a lane (its first case, `lane_keys`, the one reader): a string (`""` = guest) or None when it cannot be read.
        ONE spelling of unreadable for the S6 lanes (t-2239 F3)."""
        cases = [str(c) for c in lane or ()]
        if not cases:
            return None
        key = lane_keys(self.task_root, cases).get(cases[0])
        return key if isinstance(key, str) else None

    def s6_lane_holds(self, cases) -> set:
        """What a lane holds while its session runs (t-2147 C1 item 3): its cases and ONE `account:<part>` per part of its account key (the
        key joins parts with `+`; lanes whose part sets meet hold a common string, so they run in turn). A guest key (`""`) holds
        `account:guest`; a key that cannot be read holds `account:?<first case>`, which no other lane holds."""
        cases = [str(c) for c in cases or ()]
        if not cases:
            return set()
        key = self.s6_lane_account(cases)
        data: set = set()
        facts = self.walk_lane_facts(cases)
        if key is None:
            accounts = {"account:?" + cases[0]}
        elif facts["handles"]:
            # TR3-10d item 2/6: one hold per ASSIGNED handle (a guest lane's own `guest#<n>`, an obtain lane's own user): lanes whose handle
            # sets meet run in turn, lanes with distinct handles side by side; and one `data:<kind>:<instance>` per record given to the lane
            accounts = {"account:" + handle for handle in facts["handles"].values()}
            import walk_session as WS
            data = {f"data:{WS.fold_kind(entry['kind'])}:{entry['instance']}" for found in facts["entries"].values() for entry in found
                    if isinstance(entry, dict) and entry.get("how") == "existing"}
        else:
            accounts = {"account:" + part for part in key.split("+") if part} or {"account:guest"}
        return {"case:" + case for case in cases} | accounts | data

    def s6_chain_kind(self) -> "ChainKind":
        """What the scheduler's console and gate call an S6 chain (t-2147 C1 item 2): a lane (`[L<n>]`), holding a case or an account."""
        return ChainKind("S6", "lane", "a case or an account", lambda cases: self.s6_lane_holds(cases), tag="L")

    def s6_open_lanes(self, excluding=()) -> list:
        """The cases of this entry's S6 manual plan that are not accepted yet, other than those of the lane `excluding` (t-2147 C1 item 5;
        `manual_done_cases` is the one reader of the accepted ones, AR-13). Read fresh. RAISES when the plan of the entry or the controller's
        dispatches cannot be read (FR-59): the caller treats that as open and never as a close."""
        view = getattr(self, "_s6_view", None)
        if not isinstance(view, dict) or not isinstance(view.get("cases"), list):
            raise ValueError("the manual plan of this entry is not known")
        ctl = self.controller_state()
        if not isinstance(ctl, dict) or not isinstance(ctl.get("dispatches"), dict):
            raise ValueError("the controller record holds no dispatches")
        own = {str(c) for c in (excluding or ()) if c}
        done = manual_done_cases(ctl)
        return [case for case in view["cases"] if case not in done and case not in own]

    def s6_seam(self, records: list, cap: int) -> None:
        """The seam after the drain (t-2147 C1 item 8; AR-17): see `run_chains`. A model-service `limit` in one lane, with more than one lane
        allowed, is not a stop: the others finished and booked, and this run goes on at one lane at a time, said once. Any other kind stops."""
        pick = self.chain_pick(records, self.s6_chain_kind(), seam_rank)
        if pick is None:
            return
        exc = pick.exception
        if isinstance(exc, InfraStop) and exc.kind == "limit" and cap > 1 and not getattr(self, "_s6_cap_one", False):
            self._s6_cap_one = True
            print("note: the model service limited a lane; the others finished and are booked, and S6 goes on one lane at a time "
                  "for the rest of this run", flush=True)
            return
        self.adopt_chain(pick)
        raise exc

    def run_s6_lanes(self, plan: dict, cap: int, lanes=None) -> None:
        """The parallel road of the manual half of S6 (t-2147 C1 item 2): one chain per lane of `lanes` (default: every lane of the plan),
        `cap` at a time, on the generic scheduler. ONE lane is the old body (no thread, C.2). A lane does not start while a live lane holds
        one of its cases or its account (`chain_launchable`)."""
        lanes = list(plan["blocks"] if lanes is None else lanes)
        if len(lanes) == 1:
            return self.run_manual_lane(None, lanes[0])
        number = {tuple(lane): i + 1 for i, lane in enumerate(plan["blocks"])}
        items = [(number[tuple(lane)], list(lane), lane) for lane in lanes]
        self.run_chains(items, self.chain_launchable, self.run_manual_lane, max(1, min(int(cap), len(items))),
                        kind=self.s6_chain_kind(), seam=self.s6_seam)

    def run_manual_lane(self, record, lane: list) -> None:
        """One lane's dispatch, walk and role (the dispatch half of the old `run_manual_block`; t-2147 C1 item 4). `record` is the lane's
        chain record on the parallel road and None on the old road. The entry's plan comes through `_s6_view`. Differences of the parallel
        road only: the request carries `walk_lane` and `walk_actor`; `complete` is a callable read at the finish, under `_book`; a lane that
        ends before `run_role` closed its walk closes it here."""
        import acceptance
        self.boundary = "S6"
        self.stop_if_drained()      # C.7: a drained lane registers nothing (a no-op off a chain)
        view = getattr(self, "_s6_view", None) or {}
        plan, waiting = view["plan"], view["waiting"]
        parallel = record is not None
        block = lane
        if parallel:
            complete = None         # read at the finish (below)
            print(f"S6: manual block of {len(block)} case(s): {', '.join(block)}")
        else:
            complete = len(plan["blocks"]) == 1 and not plan["refused"] and not waiting      # a held case is outside the cover, as a refused one is
            if acceptance.consumer_of("S6"):
                # X7-6: the LAST block stops awaiting the consumer's acceptance (a refused or held case is then closed by `manual_close`, whose
                # site finds the record); an earlier block is not complete, as today.
                complete = self.consumer_awaits("S6", True) if len(plan["blocks"]) == 1 else False
            print(f"S6: manual block of {len(block)} case(s)" + (f", {len(plan['blocks']) - 1} more block(s) after it"
                                                                  if len(plan["blocks"]) > 1 else "")
                  + f": {', '.join(block)}")
        from controller import Controller
        import event_store
        # A lifecycle command, like every CLI main: it waits for an in-flight writer instead of
        # failing at once. Read at call time, so a test can shorten it.
        controller = Controller(self.task_root, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS)
        # t-2147 C1 (C.9, POSITIONAL): the count that names the id, the registration below and the walk record of `walk_before` follow one
        # another in ONE booked step - a chain holds `_book` from its start and gives it up only around a role's `claude` (`unbooked`), so
        # no other lane counts or registers between them. INVARIANT: two lanes never take one dispatch id, and the walk record is in place
        # before the role starts.
        state = controller.state()
        prior = [d for d in state.get("dispatches", {}).values() if d.get("stage") == "S6" and d.get("role") == "qa-runner"]
        # TR3-10d L1: the id `assign_entities` wrote into the claims store is the id this walk opens under; a lane with no reservation takes
        # the first number that no dispatch has and no other lane reserved (without any reservation this is `len(prior) + 1`, as before)
        facts = self.walk_lane_facts(block)
        reserved = {str(i) for i in (self.state.get("walk_ids") or {}).values() if i}
        if facts["id"] and facts["id"] not in state.get("dispatches", {}):
            dispatch_id = facts["id"]
        else:
            dispatch_id = self.walk_next_id(state.get("dispatches", {}), len(prior) + 1, reserved)
        assigned = facts["handles"] or None
        # t-289 (live S6 rehearsal, cmp2r): a story in `plan_contract_mode: new` has `prepare` itself demand the
        # `execution_kind` of a qa-runner packet and run `validate_manual_runner_block` over the block, so BOTH go in
        # with the options (they were added to the request only after `prepare`, which died with a ValueError and a
        # traceback). One try covers prepare and apply: whatever the controller refuses is the refusal below with its
        # own words (FR-1, P1) - the driver never dies on it. The fields stay on the request too, for a story in the
        # legacy mode, whose `prepare` copies neither.
        try:
            packet = controller.prepare({"stage": "S6", "role": "qa-runner", "id": dispatch_id, "scope": block,
                                         "execution_kind": "manual", "manual_case_ids": list(block)})
            request = dict(packet["dispatch_request"], execution_kind="manual", manual_case_ids=list(block),
                           purpose="manual")
            if parallel:
                # AR-22: `walk_lane` and `walk_actor` are read by `controller._lane_beside_running` (the admission of a lane beside a running
                # one); the actor is the lane's account key as a string (`""` = guest), a key that cannot be read is `?<case>` (never equal)
                # F3: an unreadable key puts neither on the request (the controller then admits nothing beside a running lane, FR-59)
                key = self.s6_lane_account(block)
                if isinstance(key, str):
                    # TR3-10d item 2: with an assignment the actor is the `+`-joined sorted handles (a guest lane's `guest#<n>`); the
                    # controller seam compares whole strings and the driver's holds keep the overlap of handle SETS unreachable
                    request.update(walk_lane=True, walk_actor="+".join(sorted(set(assigned.values()))) if assigned else key)
            controller.apply("dispatch", request)
        except Exception as exc:
            raise Refusal(f"S6 manual block dispatch refused: {type(exc).__name__}: {exc}")
        # G3 (C1-7b): the running record is written BEFORE the dispatch; a non-zero exit is a `Refusal` (the factory's own) and the
        # role is not started over a stage the record does not show as running (the guard and the dashboard read it). The refusal's
        # retry runs THIS function (B-4 ii, the G1 pattern; fix round F-2): a successful retry CONTINUES the rest of the step - the
        # role, with the manual-block instructions. The dispatch registered above stays `running` in the controller, so a retry that
        # reran only the record would leave it to `where` -> `wait_existing_job` -> `_act_wait_existing_job`, which starts the role
        # WITHOUT these lines (the execution kind, the prepared request paths, `role_lines`) and with `completion_for` instead of this
        # block's `complete`. INVARIANT: the registered dispatch is never left for that path without the instructions. A conductor's
        # `continue` (no retry) keeps the `where` road - the 13797-run-3 path, which the driver can run because it knows the record.
        # t-1957 N5s (E5s.4): the walk session is opened AFTER the dispatch is registered and BEFORE the role starts (the brief is written
        # with the walk record in place); a lane whose session did not open runs on today's road below, brief lines and all
        # TR3-10d N7: an ASSIGNED lane whose walk failed to open (`walking` False) falls back to the old road, which signs in with the CASE's
        # own account key, not the assigned handle. That is safe only because the recorder takes the stand lease EXCLUSIVE
        # (`manual_capture._hold_stand`, mode default) and so never runs beside a walk; a shared lease for the recorder would put two
        # lanes in one account - change it together with this site.
        walk = self.walk_before(block, dispatch_id, assigned) if assigned else self.walk_before(block, dispatch_id)
        walking = walk["walking"]
        if parallel:
            def run_complete(digest) -> object:
                """C.6, read at the finish under `_book` (the S6 twin of `s5_last_fn`): True only when this lane leaves no case of the entry's
                plan open, no refusal or held case stands and no walk record is waiting for a second walk; an unreadable state is open (FR-59)."""
                try:
                    base = ((not self.walk_pending(block) if walking else True)
                            and not self.walk_pending(view.get("cases") or block) and not self.s6_open_lanes(excluding=block))
                except Exception:       # noqa: BLE001 - FR-59: an unknown is never a close
                    base = False
                if acceptance.consumer_of("S6"):
                    # X7-6 (AR-25): the last lane awaits the consumer whatever is refused or held; `manual_close` closes those later, and its
                    # site finds the accept record
                    return self.consumer_awaits("S6", base)
                return base and not plan["refused"] and not waiting
        else:
            run_complete = (lambda _digest, base=complete: False if self.walk_pending(block) else base) if walking else complete

        def record_then_role() -> None:
            self.record_running("S6", "qa-runner", dispatch_id, retry=record_then_role)
            if walking:
                # the walker has the commands of its session in its brief; the driver closes it and builds the records (`walk_after`),
                # so no `finalize_task.py` line - unless no run report exists and none could be made (E5s.3)
                extra = [f"Execution kind: manual — walk the items of walk session {dispatch_id} (the `Walk:` line of your brief) with the "
                         "commands of your brief; the factory closes the session and builds the case records when you end."
                         + (f" Your last command: `finalize_task.py {self.task_root}` (no run report exists yet)."
                            if walk["report_last"] else "")]
                if assigned:
                    # TR3-10d item 4 (D.10): an ASSIGNED parallel lane only (walkers 1, one lane, a part with no handle: no new line, the
                    # prompt is as before). The sentences are the ones of `walk-charter.md`; the person's data words go whole, unless they look
                    # like a secret (an unreadable pattern list masks them too: FR-59, an unknown is never shown)
                    if any(str(h).startswith("obtain:") for h in assigned.values()):
                        extra.append("Before your first item, make your own user on the app's sign-up page with `fill-new-account` steps, then "
                                     "sign in with `fill-account <selector> created:<name> user|secret`. If that step is refused because the "
                                     "sign-up 'was not seen to land' but you saw the app accept it (a success message on the same page), say "
                                     "`account created:<name> confirmed \"<what you saw>\"` and sign in again. If the sign-up did not succeed, "
                                     "say `account created:<name> unconfirmed \"<what you saw>\"` and end without walking the items.")
                    extra.append("Before you change a record other walkers could also use, claim it: `walk_session.py claim --kind <what it is> "
                                 "--instance <its id>` (`--all` when your check reads the whole list); a claim held by another walker waits a "
                                 "little, then tells you what to do.")
                    import walk_pool as WP
                    extra.extend(WP.entity_lines(facts["entries"]))
                    try:
                        import config_contract as CC
                        import guard_secrets
                        import manual_capture as MC
                        data = CC.walk_supply(self.config)[0]["data"]
                        words = str(data.get("words") or "")
                        if data.get("known") and words.strip():
                            try:
                                cfg = MC.load_config(self.task_root)[0]
                            except ValueError:
                                cfg = {}
                            try:
                                hit = MC.secret_pattern_hit(words, {"secret_content_patterns": guard_secrets._patterns(
                                    cfg, "secret_content_patterns", list(guard_secrets.DEFAULT_SECRET_CONTENT_PATTERNS))}) is not None
                            except ValueError:
                                hit = True
                            extra.append("How this project handles shared records, in the person's words: \""
                                         + ("(not shown: they look like a secret)" if hit else words) + "\"")
                    except Exception:       # noqa: BLE001 - P1: a line the lane cannot have is no stop; the lane walks without it
                        pass
            else:
                extra = (["Execution kind: manual — execute the approved manual-agent cases in this block, "
                          "record each observation as manual evidence, then `finalize_task.py <task root>`.",
                          "Prepared requests, one per case (read the one of each case; never rebuild it): "
                          + ", ".join(self.manual_request_paths(block))]
                         + [f"{case}: unprepared - {why}; walk it yourself with the recorder (manual_capture.py) or the "
                            "browser and record every doubtful place; a seed the recorder cannot do by API is done through the "
                            "screens, and a capture the factory refuses for its own gap halts nothing; close the case with "
                            f"`manual_evidence.py unprepared --task-root {self.task_root} --case {case} "
                            "--observations-file <file>` (add `--not-walked \"<why>\"` when nothing was walked with the "
                            "recorder); record no pass or fail"
                            for case, why in plan.get("unprepared") or [] if case in block])
            self.run_role("S6", "qa-runner", scope=block, complete=run_complete, extra=extra + self.role_lines("S6", "qa-runner"),
                          rework={"id": dispatch_id, "scope": block, "reason": "manual block"})     # `run_role` owns the walk hook (F4)
        if not parallel:
            record_then_role()
            return
        try:
            record_then_role()
        except BaseException:       # noqa: BLE001 - C.3: a lane that ends before `run_role` closed its walk closes it here (idempotent, never raises)
            if walking:
                self.walk_after(block, dispatch_id, {})
            raise

    def file_passed_over(self, stage: str, receipt) -> None:
        """TR1-9 B4 (AR-27): the work a code close passed over (`stages[stage].passed_over`, written by the controller's `code_only`
        receipt: `returned, never accepted`, `abandoned`, `stopped, never accepted`) is a FINDING, one per dispatch, idempotent by
        (task, stage, dispatch). Position: right after the receipt, before the stage record, so a refused record cannot lose the name;
        the report reads the same names from the stage entry (`report_facts._passed_over_gap`). An unreadable state files nothing here
        and the stage entry still carries the names."""
        state = self.controller_state()
        stages = state.get("stages") if isinstance(state, dict) else None
        entry = stages.get(stage) if isinstance(stages, dict) else None
        rows = state.get("dispatches") if isinstance(state, dict) and isinstance(state.get("dispatches"), dict) else {}
        named = entry.get("passed_over") if isinstance(entry, dict) else None
        for item in named if isinstance(named, list) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            ident = str(item["id"])
            who = str((rows.get(ident) or {}).get("role") or "a role") if isinstance(rows.get(ident), dict) else "a role"
            self.owe_row("project_decisions.py", "--root", str(self.project), "add-finding",
                         "--essence", f"{stage} was closed by code over the work of {who} ({ident}): {item.get('label') or 'never accepted'}"[:500],
                         "--scope", "local-calibration", "--witness", f"close receipt {receipt}",
                         "--idempotency-key", f"close-passed-over:{self.task}:{stage}:{ident}",
                         what="the finding about work a code close passed over", stage=stage)
