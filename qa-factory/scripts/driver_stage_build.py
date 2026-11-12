"""driver_stage_build.py - Driver members homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import json
import re
import subprocess
import sys
import human_text
import waiver
from driver_core import Person
from driver_dialog import ANSWER_BLOCK_RE, QUESTION_HEAD_RE
from driver_conductor import MOVES_RULE, OWN_TOKEN_RULE


class DriverStageBuild:
    # --- the stand: asked ONCE, before anything runs on it (t-017 D2: B-005, owner D-0014) ----------

    #
    # S0 used to halt the whole story on a stand that did not answer - a stop, and a person's word,
    # for a story that had read no stand yet - and a project with no stand at all sailed to S5 and
    # stopped there in a phase file's prose. Now S0 only records the fact (`environment_pending`,
    # the name kept), and the ONE place that asks is `stand_check`, at the entry of the two stages
    # that put something on a stand. A person's word passes S5 and S6 together: it is recorded for
    # the stage that asked and read for both, so the second stage never asks again.
    STAND_STAGES = ("S5", "S6")

    STAND_STEPS = {"S5": "writing the automated tests and running them",
                   "automation": "running the automated tests",
                   "manual": "carrying out the manual checks",
                   "both": "running the automated tests and carrying out the manual checks"}

    def stand_question_text(self, stage: str, environment: str, names: list, kind: str = "") -> str:
        """The question (references/human-questions.md): what was done, why the stand cannot be
        derived, one question, the closed answers. Nothing in it is the probe's own vocabulary -
        that goes in the details file. `kind` is what the stage is about to do on the stand
        (S6: automation, manual, or both) - a manual-only S6 must not say "automated tests"."""
        task = self.task
        step = self.STAND_STEPS["S5" if stage == "S5" else (kind if kind in self.STAND_STEPS else "automation")]
        head = (f"The requirements, the test plan and the test cases for {task} are done. The next "
                f"step is {step}, and for that I need a stand I can trust. I could not confirm one: ")
        if environment:
            head += (f"the stand `{environment}` did not answer when I checked it just now. ")
        elif names:
            head += "no stand has been chosen for this story yet. "
        else:
            head += "this project records no stand, so there is nothing to run them on yet. "
        head += ("I have not run anything on a stand and I have not switched to another one on my "
                 "own: which stand the tests may touch is your decision.")
        options = []
        if environment:
            options.append({"answer": "retry", "token": "retry", "slots": {"what": f"bring `{environment}` up, or fix what stops it answering"},
                            "says": f"bring `{environment}` up, or fix what stops it answering; I check it again"})
        elif not names:
            # t-363 B3 (the Lead's second site of the class): the plugin's command is something to TYPE, so it stands in
            # the answer block (human-questions.md rule 5), never in the body; the body names it as "the onboarding step
            # named below". ONE shape with the other sites (t-373 F7): `stand_check` passes it as `Person.answer_note`
            # (`stand_answer_note`), which `ask()` renders in the one `---/Answer:` block.
            options.append({"answer": "retry", "token": "retry", "slots": {"what": "record a stand with the onboarding step named below"},
                            "says": "record a stand with the onboarding step named below; I ask again with the stands that are then recorded"})
        others = [name for name in names if name != environment]
        if others:
            options.append({"answer": "stand name",
                            "says": ("answer with the name of another configured stand: " if environment
                                     else "answer with the name of the stand to use: ")
                                    + ", ".join(f"`{name}`" for name in others) + "; I check that one"})
        options.append({"answer": "go on", "token": "go on",
                        "says": "go on without a stand" + ("; the tests are still written, but none is run on a stand" if stage == "S5" else "")
                                + ", and the story carries a line saying it was your decision"})
        # C1-6b (S6, A7): the priced section replaces the lettered list; the site's own words stay in `says`, the three price lines are
        # the data row of `s6.stand_confirm`
        return self.closed_question("s6.stand_confirm", head + "\n\nWhat I need from you is one of these:", options)

    def stand_check(self, stage: str, kind: str = "") -> None:
        """Before S5/S6 puts anything on a stand: is one confirmed for this story?
        (`kind`: what S6 is about to run - automation, manual or both - for the question's words.)

        Returns at once for a confirmed stand (a name, and `environment_pending` false) - a stand
        confirmed at S0 is NOT probed again (owner decision F4). Otherwise: a person's word that
        passes the block `stand not confirmed` (recorded on S5 or S6 - one word covers both) lets
        the stage go on without one; else, when a name is recorded, the stand is probed and a
        probe that exits 0 confirms it; else the person is asked. A legacy story whose pipeline
        says `environment: null, environment_pending: false` is asked too - that pair was what the
        old S0 wrote for a project with no stand.

        INVARIANT (why this stands where it does): it is called only by a stage that has something
        to run - after S5's two refusals and S6's "nothing to execute" close - and before its first
        role, so no S5/S6 role starts on an unconfirmed stand that no word has passed, and a
        stage with nothing to run never asks. A dispatch registered but never launched
        (`relaunch`, and `wait_existing_job` on one the driver never started) STARTS a role, so it
        comes through here too; a dispatch already begun and resumed with the person's words
        (`resume_checkpoint`, `resolve_return`, `wait_existing_job` with a saved answer) does not
        and is not gated.

        The flag `stand_question` is set in ONE place, `ask()`, from the Person this raises: the
        answer branch of `take_answer` takes only the answer to THIS question, never the answer
        to another question of the same stage (`environment_job` asks kind `environment` at S5 too)."""
        pipeline = self.pipeline()
        environment = str(pipeline.get("environment") or "")
        if self.state.pop("stand_question", None):      # set again below only when a question is raised
            self.save_state()                           # so a stale one can never claim another question's answer
        if environment and not pipeline.get("environment_pending"):
            return
        block = (f"{waiver.STAND_NOT_CONFIRMED_BLOCK}: " + (f"stand `{environment}` is not confirmed as usable"
                                                            if environment else "no stand is confirmed for this story"))
        for owner in self.STAND_STAGES:
            _blocking, passed = waiver.split_overridden([block], pipeline, owner)
            if passed:
                print(f"{stage}: {block} - passed by the person's word "
                      f"\"{self.s0_quote(passed[0].get('decision'))}\"; going on without a confirmed stand")
                return
        details = "no stand is recorded for this story (environment: none)"
        if environment:
            code, out = self.py("env_probe.py", "--env", environment, "--task", self.task)
            if code == 0:
                self.py("stage_done.py", "--task", self.task, "--set", "environment_pending=false", check=True)
                print(f"{stage}: stand `{environment}` answered the check; it is confirmed")
                return
            details = out or "the probe printed nothing"
        # A7 (C1-6b): a seam question - `retry` / `go on` carry the seam's own moves (`person_does`, `go_on_as_is` + the block), so
        # `take_seam_answer` executes them; the stand's NAME is the site's own door (`_take_stand_answer`)
        # remains: the stand question is a seam question (priced, `offered`): retry / go on run the seam's executors, the name has its own, other words go to the seam
        person = self.site_seam_person("environment", self.stand_question_text(stage, environment, self.stand_names(), kind), stage,
                                       block=waiver.STAND_NOT_CONFIRMED_BLOCK, details=details,
                                       answer_note=human_text.onboarding_note(environment, self.stand_names()))
        person.stand_stage = stage       # read by `ask()`, which sets the flag - and clears it for every other Person
        raise person

    # --- the BUILD the stand runs: asked once the stand itself is confirmed (t-300 N1b) -----------------------------

    #
    # `stand_check` settles WHICH stand; `build_check` settles whether that stand runs the build THIS story is about. It
    # follows `stand_check` at the same four sites (the two stage entries, a never-launched dispatch, a relaunch), so it
    # runs only for a stage that has something to run, before its first role. The ladder that READS the stand is the
    # probe's (runtime_probe.py, through the project's registered probe argv, as a rehearsal: `--no-evidence`, and
    # `--task-root` so the story's own word is the one read); the driver reads the FIELDS of its record, never a sentence
    # (FR-12). A question is raised only when the record says so (`asks_person`, or a proven `mismatched`) - the ladder
    # always runs first (FR-50) - and the five variants of its text, the closed answers and the executor commands are
    # DATA (references/build-identity-methods.json, FR-13).
    BUILD_DISPOSITIONS = {"automation": ("automate",), "manual": ("manual-agent",), "both": ("automate", "manual-agent"),
                          "": ("automate", "manual-agent")}

    BUILD_ANSWER_STUB = "\n---\nAnswer: write your words to a file and run\n  python story_run.py --task T --answer <file>\n"

    BUILD_FRAGMENT_RULES = ("filler", "too_short", "no_how_to_answer")      # whole-question rules a one-line status never meets

    BUILD_SHA = re.compile(r"[0-9a-f]{40}")

    @staticmethod
    def build_join(value) -> str:
        return "\n".join(str(item) for item in value) if isinstance(value, list) else str(value)

    def build_fit(self, template: str, slots: dict, plain: dict, whole: bool) -> str:
        """The template with its slots filled - and, when what was filled in breaks a rule of references/human-questions.md
        (a quoted command or a file name with a flag or a script name in it, a docker message), the same text with the
        `plain` words in those places instead (FR-6: the details go to the details file). `whole`: a question, so the
        answer block is under it when it is checked; a status line is checked for the shape rules only."""
        import human_text

        def broken(text: str) -> list:
            found = human_text.problems(text + self.BUILD_ANSWER_STUB if whole else text)
            return [p for p in found if whole or p["rule"] not in self.BUILD_FRAGMENT_RULES]
        text = template.format(**slots)
        if broken(text):
            text = template.format(**dict(slots, **plain))
        return text

    def build_profiles(self, stage: str, kind: str, cases) -> list:
        """The profiles of what this stage is about to run, in the project's profile order: S5 asks about the cases of the
        WINDOW it is entering (an e2e-ui question never blocks an api-only window), S6 about the dispatch's own kind (and
        scope); `cases` None means the whole stage. Never `all`: a kind the driver does not know reads as both halves, but a
        scope that is empty names nothing (INVARIANT: a question about a profile this dispatch does not run is a question
        nobody can use)."""
        import gate_preflight
        wanted = ("automate",) if stage == "S5" else self.BUILD_DISPOSITIONS.get(kind, self.BUILD_DISPOSITIONS[""])
        found = gate_preflight.stand_profiles(self.config, self.task_root, wanted)
        keep = None if cases is None else {str(case) for case in cases}
        order = list(dict.fromkeys(str(p.get("profile_id")) for p in self.config.get("profiles") or [] if isinstance(p, dict)))
        return [name for name in order if name in found and (keep is None or keep & {str(c) for c in found[name].get("cases") or []})]

    def build_run_probe(self, profile: str, derive: bool = False, stand: str = "") -> tuple:
        """(record, why, said): the project's registered probe for this profile, run as a rehearsal (`runtime_probe.rehearsal_argv`:
        `--task-root` and `--no-evidence`, the factory's own script only - a project's own script is never handed a flag it
        does not know, AE16). `why` is a key of `question.lines` when there is no record: no probe is registered, or it did
        not finish, could not start, failed, or printed no JSON object (FR-3: the factory's, never a question). `derive`
        (EP1-28, S6 manual only): with no registered probe, the default one over the profile's checkout
        (`execution_request.stand_probe_spec`); `said` is then why there is none (three causes: no checkout, two repositories,
        two stands), else ""."""
        import execution_request
        from runtime_probe import rehearsal_argv
        if derive:
            spec, said = execution_request.stand_probe_spec(self.config, profile, stand)
        else:
            spec, said = execution_request.registered_probe(self.config, profile), ""
        if spec is None:
            return None, "no_probe", said
        try:
            done = subprocess.run(rehearsal_argv(spec["argv"], self.task_root), cwd=str(self.project / spec["cwd"]), env=self.env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=spec["timeout_s"])
        except subprocess.TimeoutExpired:
            return None, "why_timeout", ""
        except OSError:
            return None, "why_start", ""
        if done.returncode != 0:
            return None, "why_failed", ""
        try:
            record = json.loads(done.stdout)
        except ValueError:
            return None, "why_no_json", ""
        return (record, "", "") if isinstance(record, dict) else (None, "why_no_json", "")

    def build_check(self, stage: str, kind: str = "", cases=None) -> None:
        """After `stand_check`: does the confirmed stand run the build this story is about? One rehearsal per profile of what
        is about to run; a verdict that needs nobody is ONE printed line; a verdict that needs the person is a `Person`
        (kind `stand_identity`) - ONE per call, the first profile that needs it (the next is asked at the next entry).

        INVARIANT (why it stands where it does): it runs only after a stand is confirmed or passed by a person's word, and
        before the first role; a stand passed by word (no stand name, or `environment_pending` still true) has nothing to
        read, so it returns at once; a stage with nothing to run never reaches it; a dispatch already begun and resumed
        with the person's words is not gated. The flag `build_question` is set in ONE place, `ask()`, from the Person this
        raises, and is gone for every other question (t-037). ERROR DIRECTION: a doubt is a line, never a question and
        never a silent pass - the run path still refuses a build nobody could prove."""
        if self.state.pop("build_question", None):      # set again below only when a question is raised
            self.save_state()
        pipeline = self.pipeline()
        stand = str(pipeline.get("environment") or "")
        if not stand or pipeline.get("environment_pending"):
            return
        import stand_identity as SI
        lines = SI.data()["question"]["lines"]      # every console line of this check is data (FR-13); the raw error text goes to stderr
        try:
            profiles = self.build_profiles(stage, kind, cases)
        except Exception as exc:      # a doubt about WHICH profiles is a line (the run path decides), never a stop
            print(f"story_run: build check, profiles: {type(exc).__name__}: {' '.join(str(exc).split())[:300]}", file=sys.stderr)
            print(lines["check_broke_profiles"].format(stage=stage, stand=stand))
            return
        if not profiles:
            print(lines["no_profiles"].format(stage=stage))
            return
        import surfaces
        for profile in profiles:
            try:
                # EP1-41c: the stand is the PROFILE's own (surfaces.stand_of_profile, the one reader). A project that names no
                # `surface` gets `stand` back unchanged (the web road); a profile with no stand of its own is a line and no
                # question - nobody is asked about a build that no stand of this project runs. The question's `environment`
                # is then the profile's stand, so the word lands on the key the probe reads (`task_confirmation`).
                stand_p = surfaces.stand_of_profile(self.config, profile, stand)
                if not stand_p:
                    print(lines["no_profile_stand"].format(stage=stage, stand=stand, profile=profile))
                    continue
                # F-1: only the manual half of S6 derives a probe nobody registered; S5 and automation keep the line
                # `no_probe` (the S5 door writes the entry, EP1-24)
                record, why, said = self.build_run_probe(profile, derive=stage == "S6" and kind != "automation", stand=stand_p)
                line, person = self.build_outcome(stage, kind, stand_p, profile, record, why, said)
            except Exception as exc:      # the check itself broke: said, and the run goes on (the run path still decides)
                print(f"story_run: build check, {profile}: {type(exc).__name__}: {' '.join(str(exc).split())[:300]}", file=sys.stderr)
                print(lines["check_broke"].format(stage=stage, stand=stand, profile=profile))
                continue
            if line:
                print(line)
            if person is not None:
                raise person

    def build_method_words(self, q: dict, row, name: str) -> str:
        """The words for the way a build was read: the registry row's own when it is the row's method (a `command` names its
        line), else the data's for the method (FR-13)."""
        import stand_identity as SI
        if not name:
            return q["method_unknown"]
        return SI.method_words(row if isinstance(row, dict) and row.get("method") == name else {"method": name})

    @staticmethod
    def build_names(files, q: dict) -> str:
        """File names for a line of the build question: the first `limits.files_shown` in code spans, the rest counted
        (`files_more`). The ONE spelling for the mismatch question, the not-compared line and the accepted-files line."""
        names = [str(n) for n in files or []]
        cap = int(q["limits"]["files_shown"])
        return ", ".join(f"`{n}`" for n in names[:cap]) + (" " + q["files_more"].format(more=len(names) - cap)
                                                           if len(names) > cap else "")

    def build_outcome(self, stage: str, kind: str, stand: str, profile: str, record, why: str, said: str = "") -> tuple:
        """(line, person) for one profile's probe record, chosen by FIELDS: `result`, `asks_person`, `differing_files`,
        `deployed_source_revision`, `not_shipped_files` (a `matched` that did not compare some files), `accepted_files` and
        the confirmation's `kind` (a person's `test as is`). Exactly one of the two is set."""
        import stand_identity as SI
        q = SI.data()["question"]
        row = SI.state(self.project)["in_force"].get((stand, profile))
        base = {"stage": stage, "stand": stand, "profile": profile, "method": "", "date": "", "error": "", "why": ""}

        def line(key: str, **slots) -> str:
            return self.build_fit(q["lines"][key], dict(base, **slots), q["plain_line"], whole=False)
        if record is None:
            if why == "no_probe":
                # EP1-28: when the default probe could not be worked out, the line says why (the three causes of `None`)
                # a person reads the refusal's plain half (no flag in it, FR-6); the whole of it is the role's
                return (line("no_probe_said", why=str(getattr(said, "plain", said))) if said else line("no_probe")), None
            return line("probe_failed", why=q["lines"][why]), None
        result = record.get("result")
        prov = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
        if result in ("matched", "person_confirmed", "not_applicable"):
            import profile_contract
            if not profile_contract.acceptable_provenance(record, profile_contract.ACCEPTS, rehearsal=True):
                return line("probe_unrecognised"), None
            if result == "not_applicable":
                return line("not_applicable"), None
            if result == "person_confirmed":
                at = str((record.get("person_confirmation") or {}).get("at") or "")[:10] or q["no_date"]
                if (record.get("person_confirmation") or {}).get("kind") == "content_accepted":
                    # FB-8: ONE line for this kind, in place of the two base lines (no sentence claims an image binding that
                    # did not happen, and none says the build was confirmed: the person accepted the files as they are)
                    names = self.build_names(record.get("accepted_files"), q)
                    return line("person_content", date=at, files=names), None
                no_image = str(record.get("observed_runtime_identity") or "").startswith("person-confirmed:")
                return line("person_confirmed_no_image" if no_image else "person_confirmed", date=at), None
            name = str(prov.get("identity_kind") or ("sources" if prov.get("source_linkage") == "verified_content" else ""))
            not_shipped = record.get("not_shipped_files")
            if isinstance(not_shipped, list) and not_shipped:
                # FB-8: a build input the container does not hold was not compared - never shown as a plain verified build
                return line("matched_not_shipped", method=self.build_method_words(q, row, name),
                            files=self.build_names(not_shipped, q)), None
            return line("matched", method=self.build_method_words(q, row, name)), None
        if result == "unknown":
            asks = record.get("asks_person")
            if asks in ("how", "confirm"):
                # EP1-28: `how` on a record that names no container is the stand nobody runs in one (a host process): the
                # question is "is that commit there", not "how do I read the image" - chosen by the FIELD (FR-12)
                no_container = asks == "how" and not str(record.get("container") or "").strip()
                # EP1-41e: `how` on a DEVICE stand (the field `device_stand`, set by the probe) is "is this build the one", chosen
                # BEFORE the container test: a device has no container, so the `no_container` words would not fit it
                device = asks == "how" and record.get("device_stand") is True
                return "", self.build_person(stage, kind, stand, profile, record, row,
                                             "confirm" if asks == "confirm" else "device_build" if device
                                             else "no_container" if no_container else "how")
            if row and row.get("method") == "person_confirms":
                # docker did not answer on a stand the person checks themselves: nothing to ask (their word is already
                # there, FR-7) and nothing to read - said as a status, never a question
                return line("docker_down_confirms", date=str(row.get("recorded_at") or "")[:10] or q["no_date"],
                            method=SI.method_words(row)), None
            return line("unread", error=str(record.get("error") or q["no_error"])), None
        if result == "mismatched":
            sources = bool(record.get("differing_files")) or prov.get("deployed_source_revision") == "content_mismatch"
            return "", self.build_person(stage, kind, stand, profile, record, row, "mismatched_sources" if sources else "mismatched")
        return line("probe_unrecognised"), None

    def build_person(self, stage: str, kind: str, stand: str, profile: str, record: dict, row, variant: str) -> Person:
        """The question for one profile: the variant's text with its slots filled from the record's FIELDS, the prefixes the
        record asks for on top (`registry_error`, `registry_method_failed`, `voided`: FR-7 - the text moves when the
        situation moved), the factory's own words in the details file, and the packet `ask()` turns into the flag."""
        import stand_identity as SI
        q = SI.data()["question"]
        prov = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}

        def sha(value) -> str:
            return value if isinstance(value, str) and self.BUILD_SHA.fullmatch(value) else ""
        expected = sha(record.get("expected_source_revision"))
        deployed = sha(prov.get("deployed_source_revision")) or sha(record.get("build_sha"))
        identity = str(record.get("observed_runtime_identity") or "")
        image = identity if re.fullmatch(r"image:sha256:[0-9a-f]{64}", identity) else ""
        if not image:
            # FB-8: a content mismatch names no build, but the probe read the image that held the bytes: the word binds to it
            seen = str(record.get("observed_image") or "")
            image = seen if re.fullmatch(r"image:sha256:[0-9a-f]{64}", seen) else ""
        voided = record.get("voided") if isinstance(record.get("voided"), dict) else {}
        failed = str(record.get("registry_method_failed") or "")
        files = [str(name) for name in record.get("differing_files") or []]
        names = self.build_names(files, q)
        docker = ""
        if variant == "no_container":
            # EP1-28 (H-7): what docker runs on this machine, so the person can say the application is in one of them. No
            # line when docker is absent, silent or runs nothing (never an error); at most `limits.containers_shown`
            # names, the rest counted. `deployed` stays the person's word; a name they give is checked by the conductor's
            # move before anything is recorded.
            try:
                import runtime_probe
                running = [str(name) for name, _image in runtime_probe.containers()]
            except Exception:
                running = []
            if running:
                cap = int(q["limits"]["containers_shown"])
                shown = ", ".join(f"`{n}`" for n in running[:cap]) + (" " + q["files_more"].format(more=len(running) - cap)
                                                                     if len(running) > cap else "")
                docker = "\n" + q["no_container_docker_line"].format(containers=shown) + "\n"
        tried = [str(t.get("outcome")) for t in record.get("tried") or [] if isinstance(t, dict) and t.get("outcome")]
        more = record.get("tried_more") if isinstance(record.get("tried_more"), int) else 0
        tried_words = ("; ".join(tried) + (f"; {q['tried_more'].format(more=more)}" if more else "")) if tried else q["no_tried"]
        repo = SI.repo_for(self.config, profile)
        name = str(prov.get("identity_kind") or "")
        slots = {"task": self.task, "step": self.STAND_STEPS["S5" if stage == "S5" else (kind if kind in self.STAND_STEPS else "automation")],
                 "stand": stand, "profile": profile, "code": q["code"]["named" if repo else "unnamed"].format(repo=repo),
                 "short": expected[:12], "tried": tried_words, "registry": SI.registry_rel(), "deployed_short": deployed[:12],
                 "method": self.build_method_words(q, row, name), "files": names, "count": len(files), "what": str(voided.get("what") or ""),
                 "docker": docker,
                 "why": failed, "error": str(record.get("error") or ""),
                 "date": (str(row.get("recorded_at") or "")[:10] if row else "") or str(voided.get("earlier_at") or "")[:10] or q["no_date"],
                 "failed_date": (str(row.get("recorded_at") or "")[:10] if row else "") or q["no_date"],
                 "failed_method": SI.method_words(row) if row else q["plain"]["failed_method"],
                 "voided_date": str(voided.get("earlier_at") or "")[:10] or q["no_date"]}
        prefixes = []
        if record.get("registry_error"):
            prefixes.append(q["prefixes"]["registry_error"])
        if failed and row:
            prefixes.append(q["prefixes"]["method_failed"])
        if voided.get("what"):
            prefixes.append(q["prefixes"]["voided"])
        spec = q["variants"][variant]
        plain = {key: value.format(count=len(files)) for key, value in q["plain"].items()}
        if variant == "device_build":
            # EP1-41e: what the device holds, and what voids the word - both in words of the variant's own data. A promise is made
            # only about what the code can see: with the file hashed, a different build voids the word; with the hash unread, only
            # a different version does (the record's `limitation`); with no build read at all, nothing ties the word to a build.
            seen = str(record.get("observed_device_build") or "")
            kind_of = "voids_unseen" if not seen else "voids_version" if record.get("limitation") else "voids_build"
            slots.update({"device_build": spec["device_has"].format(line=seen) if seen else spec["device_unread"],
                          "device_voids": spec[kind_of]})
            plain["device_build"] = spec["device_unread"]
        template = " ".join(prefixes) + ("\n\n" if prefixes else "") + self.build_join(spec["text"])
        text = self.build_fit(template, slots, plain, whole=True)
        details = [f"stand `{stand}`, {profile} tests - what the check said: {record.get('error') or 'nothing'}"]
        details += [f"tried - {t.get('method')}: {t.get('outcome')}" for t in record.get("tried") or [] if isinstance(t, dict)]
        details += [f"{label}: {record[field]}" for label, field in (("remedy", "remedy"), ("the record of ways", "registry_error"),
                                                                       ("the way you gave", "registry_method_failed")) if record.get(field)]
        if files:
            details.append("files that differ: " + ", ".join(files))
        person = Person("stand_identity", text, stage, details="\n".join(details))
        person.build_question = {"stage": stage, "kind": kind, "environment": stand, "profile": profile, "variant": variant,
                                 "revision": expected, "image": image, "deployed": deployed, "method_words": slots["method"],
                                 "differing_files": files, "content": str(record.get("content_identity") or ""),
                                 "checkout": str(record.get("checkout") or ""),
                                 "answers": list(spec["answers"]), "text": text, "reasked": False}
        return person

    @staticmethod
    def build_expand(argv: list, slots: dict) -> list:
        """An executor template with its slots filled. A `?--flag` followed by its value is dropped when the value is empty
        (no image digest was read; `label` with no name)."""
        out, index = [], 0
        while index < len(argv):
            token = str(argv[index])
            if token.startswith("?"):
                value = str(argv[index + 1]).format(**slots) if index + 1 < len(argv) else ""
                if value.strip():
                    out += [token[1:], value]
                index += 2
                continue
            out.append(token.format(**slots))
            index += 1
        return out

    def build_commit_of(self, pending: dict, name: str) -> str:
        """The full commit of THIS story's checkout that `name` (7 to 40 hex characters) stands for, or '' when it is not a
        commit of it (git says so, git cannot be run, or the packet names no checkout). ERROR DIRECTION: toward ''."""
        checkout = str(pending.get("checkout") or "")
        if not checkout:
            return ""
        try:
            done = subprocess.run(["git", "-C", str(self.project / checkout), "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}"],
                                  capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        found = done.stdout.strip()
        return found if done.returncode == 0 and self.BUILD_SHA.fullmatch(found) else ""

    def build_answer_slots(self, pending: dict, words: str, arg: str) -> dict:
        return {"task": self.task, "stand": str(pending.get("environment") or ""), "profile": str(pending.get("profile") or ""),
                "revision": str(pending.get("revision") or ""), "deployed": str(pending.get("deployed") or ""),
                "image": str(pending.get("image") or ""), "content": str(pending.get("content") or ""), "words": words,
                "arg": arg}

    def take_build_answer(self, words: str, qtext: str, stage: str, dispatch: str) -> None:
        """The answer to `build_check`'s question - and only to it (`ask()` sets the flag from that Person alone).

        CLOSED forms, read by code (`build_read_answer`, the forms are `answers.forms` of the data file): the driver runs the
        form's executor commands ITSELF (FR-48) - the person is never shown a script name, a flag or an exit code (FR-6) -
        and records the person's words whole in the journal (FR-8). Anything it does not read as a form - prose, another
        language, a form this question did not offer, an answer for a stand the config no longer has - goes to the conductor
        with the key and the table of forms and their commands (the rule of gate B's stand-gap answers), never silently
        dropped. A form with its value missing, or a commit the answer is not about, is asked again naming what is wrong
        (FR-1): the commit once, then the conductor. `stop` is held: the words are journaled, the question stays open
        (nothing is passed), the story stops. A second recording answer for one stand and profile in one story: the last
        counts, the log says so, and the record quotes the earlier line. An executor that fails: the question comes back
        changed, naming that nothing was recorded, the factory's words in the details file."""
        import contract as C
        import stand_identity as SI
        pending = self.state.pop("build_question", None) or {}
        stand, profile = str(pending.get("environment") or ""), str(pending.get("profile") or "")
        data = SI.data()
        q, forms = data["question"], data["answers"]["forms"]
        offered = [name for name in pending.get("answers") or [] if name in forms]
        said = words.replace(self.BOM, "").strip()
        base = str(pending.get("text") or QUESTION_HEAD_RE.sub("", ANSWER_BLOCK_RE.sub("", qtext), count=1)).strip()
        where = f"stand build at {stage} ({stand}, {profile} tests)"

        def journal(what: str = "") -> None:
            self.answer_row(f"{where}{f' ({what})' if what else ''}: ", said, what="your answer about the stand build")

        def again(text: str, details: str = "", **keep) -> None:
            person = Person("stand_identity", text + "\n\n" + base, stage, dispatch, details=details)
            person.build_question = dict(pending, **keep)
            raise person

        def conductor(why: str) -> None:
            journal("not read as one of the answers, sent to the conductor")
            slots = dict(self.build_answer_slots(pending, '"<their words, verbatim>"', "<their value>"))
            commands = []
            for name in offered:
                spec = forms[name]
                runs = ["python " + str(self.scripts / "stand_identity.py") + " " + " ".join(self.build_expand(argv, slots))
                        for argv in spec.get("runs") or []]
                if spec.get("hold"):
                    commands.append(f"- `{name}`: run nothing; the story stops here. Answer `ask_person` with a question that says it "
                                    "is stopped and that the answers above still go on.")
                elif not runs:
                    commands.append(f"- `{name}`: run nothing; the stand is checked again when the stage starts.")
                else:
                    commands.append(f"- `{name}`" + ("" if spec.get("arg") == "none" else " <value>") + ":\n  " + "\n  ".join(runs))
            self.unread(
                "stand_identity", stage, dispatch,
                f"The person answered the driver's question about which build stand `{stand}` runs (the {profile} tests of story "
                f"{self.task}, at {stage}), and their words are below. The driver reads only the closed answers of that question "
                f"and these words were not read as one of them ({why}), so nothing was recorded.\n"
                f"The key: stand `{stand}`, test profile `{profile}`, story {self.task}. The project's record of how each stand's "
                f"build is read: {SI.registry_rel()}.\n"
                "If their words mean one of the answers below, record it with exactly those command lines and nothing else, the "
                "person's words verbatim in --words:\n" + "\n".join(commands) + "\n"
                + MOVES_RULE + " " + OWN_TOKEN_RULE + "\n\n## The question\n" + qtext[:6000], words=words)
        read = self.build_read_answer(said, offered, forms)
        missing = SI.in_config(self.config, stand, profile) if stand and profile else "the question names no stand or test profile"
        if not read["form"] or missing:
            return conductor(missing or read["why"])
        form, arg = read["form"], str(read.get("arg") or "")
        spec = forms[form]
        if spec.get("arg") == "required" and not arg:
            journal("a value is missing, asked again")
            again(q["reasks"]["missing_arg"].format(form=form, needs=spec.get("needs", ""), example=spec.get("example", form)))
        if spec.get("arg") == "commit" and arg:
            full = self.build_commit_of(pending, arg)
            wanted = str(pending.get("revision") or "") if form == "deployed" else str(pending.get("deployed") or "")
            problem = "not_a_commit" if not full else ("" if full == wanted else
                                                       ("wrong_story_commit" if form == "deployed" else "wrong_deployed_commit"))
            if problem and pending.get("reasked"):
                return conductor(f"it named the commit {arg}, which is not the commit this answer is about, a second time")
            if problem:
                journal("the commit it names is not the one asked about, asked again")
                again(q["reasks"][problem].format(sha=arg, short=str(pending.get("revision") or "")[:12], stand=stand,
                                                  deployed_short=str(pending.get("deployed") or "")[:12]), reasked=True)
        lines = q["lines"]
        shown = {"stage": stage, "stand": stand, "profile": profile, "said": self.s0_quote(said)}     # the slots of the console lines
        if spec.get("hold"):
            journal("stop; owner: environment")
            print(lines["answer_stop"].format(**shown))
            again(q["held"]["stop"].format(stand=stand))
        key = f"{stand}|{profile}"
        recorded = self.state.setdefault("stand_identity_answers", {})
        earlier = recorded.get(key) if spec.get("runs") else None
        line = said
        if earlier:
            print(lines["answer_repeated"].format(**shown))
            line = said + C.replaces_tail([earlier])
        slots = self.build_answer_slots(pending, line, arg)
        done = 0
        for argv in spec.get("runs") or []:
            code, out = self.py("stand_identity.py", *self.build_expand(argv, slots))
            if code:
                if done:
                    # t-366 F2: an earlier step of this answer IS written (`always confirm`: the person's decision for the
                    # stand), so the question must not say "nothing was recorded" (FR-10): it says what is written and what
                    # is not, and offers what is still open. The factory's own words go to the details file only.
                    recorded[key] = shown["said"]
                    journal("partly recorded, asked again")
                    print(lines["answer_partly"].format(**shown))
                    partly = q["partly_recorded"]
                    text = self.build_fit(self.build_join(partly["text"]), {"stand": stand, "profile": profile}, {}, whole=True)
                    person = Person("stand_identity", text, stage, dispatch, details=out)
                    person.build_question = dict(pending, variant="partly_recorded", answers=list(partly["answers"]), text=text,
                                                 reasked=False)
                    raise person
                journal("not recorded, asked again")
                print(lines["answer_not_recorded"].format(**shown))
                again(q["reasks"]["not_recorded"], details=out)
            done += 1
        if spec.get("runs"):
            recorded[key] = shown["said"]
        journal()
        print(lines["answer_recorded" if spec.get("runs") else "answer_retry"].format(**shown))
