#!/usr/bin/env python3
"""RN1-9 Part B1: the question's class on the driver road and on the waiver road (spec t-722 §2 B1, §3 E-1..E-10, E-20).

Driver: `no_move.validate_options` refuses a QUESTION without a class of the question classes (`person_owned.py`) or without `checked`
(`ClassRefused`, an `ArgsRefused`), AFTER every shape rule; `Driver.no_move` tells the conductor once, then falls to the priced fallback
with ONE defect; `pass_to_person` (legacy `s1_review`) has the same exit as an empty question. Waiver: `--why-person <id>` is checked
BEFORE any `pipeline.json` read or write. A lint over a token and a record - never a reading of a person's or a role's wording (FR-12 n/a).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import driver_for, jsonl, seam_option, seed  # noqa: E402

import no_move as NM  # noqa: E402
import person_owned as PO  # noqa: E402
import story_run  # noqa: E402

OPEN = ["rework_stage", "person_does", "stop_here"]
FACTS = {"rework_stages": ["S4", "S5"], "rework_roles": {"S4": ["qa-case-designer"], "S5": ["qa-automator", "qa-code-critic"]},
         "scope": ["TC-1", "TC-2"], "causes": ["test_defect", "mechanical"]}
ARGS = {"stage": "S5", "role": "qa-automator", "cases": ["TC-1"], "cause": "test_defect"}
CLASSED = {"why_person": "access", "checked": "the probe record"}


def norm(text: str) -> str:
    return text.strip().lower()


def verdict(options=None, action="ask_person", question="Which one? `retry` or `stop`?", **extra) -> dict:
    options = options if options is not None else [seam_option("retry", "person_does"), seam_option("stop", "stop_here")]
    return dict({"action": action, "did": "looked", "question": question, "options": options}, **extra)


def validate(v, chosen=False, move=""):
    """`("ok", rows)`, `("class", rule)`, `("args", rule)` or `("malformed", rule)` - which road the verdict took."""
    try:
        rows, rule = NM.validate_options(v, OPEN, NM.data(), norm, {}, facts=FACTS, chosen=chosen, chosen_move=move)
    except NM.ClassRefused as refused:
        return "class", refused.rule
    except NM.ArgsRefused as refused:
        return "args", refused.rule
    return ("ok", rows) if rows else ("malformed", rule)


def rework(**args):
    return dict(seam_option("rework", "rework_stage"), args=args)


def a_to_e_validate_options() -> None:
    check("m6: ClassRefused is a subclass of ArgsRefused (`_verdict_rule` gives it again=True)", issubclass(NM.ClassRefused, NM.ArgsRefused))
    kind, rule = validate(verdict())
    check_eq("(a) two options, no why_person -> ClassRefused", kind, "class")
    check_in("(a) ...the sentence names the missing key and the conductor's door", "`why_person` is absent", rule)
    for bad in (None, "", "   ", 7, ["access"], {"id": "access"}):
        check(f"E-1 why_person {bad!r} -> ClassRefused", validate(verdict(why_person=bad, checked="x"))[0] == "class")
    check_eq("(b) why_person access + checked -> the rows", validate(verdict(**CLASSED))[0], "ok")
    check_eq("E-2 ' Access ' is accepted as access", validate(verdict(why_person=" Access ", checked="x"))[0], "ok")
    for bad in ("access, money", chr(0x430) + "ccess", "access_"):
        check(f"E-2b {bad!r} -> ClassRefused", validate(verdict(why_person=bad, checked="x"))[0] == "class")
    for bad in ("", "  \n", None, 3):
        check(f"E-2c checked {bad!r} -> ClassRefused", validate(verdict(why_person="access", checked=bad))[0] == "class")
    check_eq("E-2c any non-empty `checked` passes", validate(verdict(why_person="access", checked="x"))[0], "ok")
    kind, rule = validate(verdict(why_person="nope", checked="x"))
    check_eq("(c) `nope` -> ClassRefused", kind, "class")
    check_in("(c) ...naming the file", "references/" + PO.FILE_NAME, rule)
    check_in("(c) ...and the ids", "`money`", rule)
    check_eq("(d) `stop` without a class -> ClassRefused (E-10)", validate(verdict(action="stop"))[0], "class")
    check_eq("(d) `stop` with a class -> the rows", validate(verdict(action="stop", **CLASSED))[0], "ok")
    check_eq("(e) a lone chosen rework option, no class -> the rows (E-7)",
             validate(verdict([rework(**ARGS)], question="Which one?"), chosen=True, move="rework_stage")[0], "ok")
    # (f) bad args AND no class: ONE refusal carrying both
    kind, rule = validate(verdict([rework(**dict(ARGS, role="nobody")), seam_option("retry", "person_does")], question="Which one?"))
    check_eq("(f) bad args and no class -> ONE ClassRefused", kind, "class")
    check("(f) ...carrying the args rule and the class rule", "did no accepted work" in rule and "`why_person` is absent" in rule, rule)
    kind, rule = validate(verdict([rework(**dict(ARGS, role="nobody")), seam_option("retry", "person_does")], question="Which one?", **CLASSED))
    check_eq("(f) bad args WITH a class -> ArgsRefused as before", kind, "args")
    # (g) m7: a malformed verdict keeps its OWN refusal, reached first
    kind, rule = validate(verdict([seam_option("retry", "person_does")]))
    check_eq("(g) one option, not a chosen rework, no class -> its own rule (fewer than two)", kind, "malformed")
    check_in("(g) ...byte-unchanged", "options: fewer than two, or not a list of objects", rule)
    check_not_in("(g) ...and no class sentence", "why_person", rule)
    kind, rule = validate(verdict(question=""))
    check_eq("(g) an empty question and no class -> the question's own rule", (kind, rule), ("malformed", "the question is empty"))
    check_eq("(g) the action `continue` keeps its own rule", validate(verdict(action="continue"))[0], "malformed")
    # E-3: an unreadable class file never withholds the question (FR-59)
    real = PO.load

    def broken(path=None):
        raise PO.PersonOwnedUnreadable("test: unreadable")
    try:
        PO.load = broken
        check_eq("E-3 unreadable class file: the verdict without a class passes", validate(verdict())[0], "ok")
    finally:
        PO.load = real


def rig(answers):
    """A driver whose conductor is a stub: `answers` are the verdicts it gives in turn (the last one repeats)."""
    root, task_root, env = seed("QA-9")
    driver = driver_for(root, env, "QA-9")
    driver.calls, driver.defects = [], []
    queue = list(answers)

    def conductor(text, *, words="", files=None, words_file=None):
        count = driver.conductor_calls.get(driver.boundary, 0)
        if count >= story_run.CONDUCTOR_CALLS_PER_BOUNDARY:
            raise story_run.ConductorSpent(count, text)
        driver.calls.append(text)
        driver.conductor_calls[driver.boundary] = count + 1
        return queue.pop(0) if len(queue) > 1 else queue[0]
    driver.conductor = conductor
    real_py = driver.py
    driver.py = lambda script, *a, **k: (driver.defects.append(a), (0, ""))[1] if script == "log_append.py" and "defect_found" in a else real_py(script, *a, **k)
    driver.no_move_facts = lambda state: dict(FACTS, dispatch_status="running", session=True, running=False, closed=False, attempts=0,
                                              stand_authorized=True, live_exclusions=True, gate="", gate_decided=None)
    return root, task_root, driver


def raised(driver, state):
    try:
        return driver.no_move(state), None
    except story_run.Person as person:
        return None, person


STATE = {"why": "refusal", "kind": "conductor", "stage": "S5", "dispatch": "", "text": "the factory's words"}


def h_the_driver_road() -> None:
    root, task_root, driver = rig([verdict(), verdict(**CLASSED)])
    try:
        driver.boundary = "S5:S5-qa-automator-1"
        _, person = raised(driver, STATE)
        check_eq("(h) first answer without a class, second with: ONE re-call (two calls)", len(driver.calls), 2)
        check_in("(h) ...the second prompt carries the refusal and the door", "Your options were refused", driver.calls[1])
        check_in("(h) ...with `checked` named in it", "`checked` naming what you read", driver.calls[1])
        check_eq("(h) the Person carries the class, the reading and the source",
                 (person.why_person, person.checked, person.source), ("access", "the probe record", "conductor"))
        check_eq("(h) ...no defect (a refusal answered in one re-call is not one)", len(driver.defects), 0)
        driver.ask(person)
        rows = jsonl(driver.state_dir / "driver-questions.jsonl")
        check_eq("(h) the driver-questions row carries source / why_person / checked / class_check",
                 (rows[-1]["source"], rows[-1]["why_person"], rows[-1]["checked"], rows[-1]["class_check"]),
                 ("conductor", "access", "the probe record", "ok"))
    finally:
        harness.cleanup(root)
    root, task_root, driver = rig([verdict()])
    try:
        driver.boundary = "S5:S5-qa-automator-1"
        _, person = raised(driver, STATE)
        check_eq("(i) no class twice: two calls, then the priced fallback Person", (len(driver.calls), list(person.offered)), (2, ["retry", "go on", "stop"]))
        check_eq("(i) ...and exactly ONE defect_found (E-6)", len(driver.defects), 1)
        check_eq("(i) ...the fallback Person has no class and the source `fallback`", (person.why_person, person.source), ("", "fallback"))
        driver.ask(person)
        row = jsonl(driver.state_dir / "driver-questions.jsonl")[-1]
        check_eq("(i) ...its row says so (counted unclassified)", (row["source"], row["why_person"]), ("fallback", None))
    finally:
        harness.cleanup(root)
    # the legacy road: `pass_to_person` without a class is the same exit as an empty question
    root, task_root, driver = rig([verdict()])
    try:
        driver.boundary = "S1:S1-qa-scout-1"
        driver.py = lambda script, *a, **k: (driver.defects.append(a), (0, ""))[1] if script == "log_append.py" else (0, "")
        try:
            driver.pass_to_person({"action": "ask_person", "question": "Which stand?"}, "s1_review", "S1", "S1-qa-scout-1")
            made = None
        except story_run.Person as person:
            made = person
        check_eq("(i) pass_to_person without a class: no Person", made, None)
        check_eq("(i) ...one defect naming the class rule", (len(driver.defects), "person-owned" in " ".join(driver.defects[0])), (1, True))
        try:
            driver.pass_to_person({"action": "ask_person", "question": "Which stand?", **CLASSED}, "s1_review", "S1", "S1-qa-scout-1")
            made = None
        except story_run.Person as person:
            made = person
        check("(i) pass_to_person WITH a class: the Person, in the conductor's words",
              made is not None and made.text == "Which stand?" and (made.why_person, made.source) == ("access", "conductor"))
    finally:
        harness.cleanup(root)
    # E-20: a Person raised by code carries no class and is counted, never refused
    plain = story_run.Person("refusal", "text")
    check_eq("E-20 a code-raised Person: no class, source `code`", (plain.why_person, plain.checked, plain.source), ("", "", "code"))
    check_eq("E-20 the code route of a known ask_person row is its class", PO.code_route("story_budget"), "money")
    root, task_root, driver = rig([verdict()])
    try:
        check_eq("delivery: the class is recorded when the verdict names one",
                 (lambda p: (p.source, p.why_person))(driver.delivery_person("said", why_person=" Money ")), ("delivery", "money"))
        check_eq("delivery: a non-class is recorded as none, never refused",
                 (lambda p: (p.source, p.why_person))(driver.delivery_person("said", why_person="nope")), ("delivery", ""))
    finally:
        harness.cleanup(root)


# --- the waiver road ------------------------------------------------------------------------------------------------------------------
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def waiver_project():
    root = harness.temp_project("qa-waiver-class-")
    task_root = root / "qa-factory" / "artifacts" / "QA-1"
    task_root.mkdir(parents=True)
    pipeline = task_root / "pipeline.json"
    pipeline.write_text(json.dumps({"task": "QA-1", "gates": {"A": {"decision": "approved"}}}), encoding="utf-8")
    return root, pipeline


def waiver(root, *args):
    import os
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return harness.run_script("waiver.py", "--task", "QA-1", *args, cwd=root, env=env)


def w_the_waiver_road() -> None:
    root, pipeline = waiver_project()
    try:
        remark = ("--remark", "--stage", "S5", "--text")
        done = waiver(root, *remark, "no class here")
        check_eq("waiver: no flag -> exit 0", done.returncode, 0)
        check_in("waiver: ...the `not classified` line", "not classified: this word answers no class", done.stdout)
        check_in("waiver: ...naming the door", "--why-person <id>", done.stdout)
        check_not_in("waiver: ...and NO key written", "why_person", pipeline.read_text(encoding="utf-8"))
        done = waiver(root, *remark, "the stand is theirs", "--why-person", "access")
        check_eq("waiver: --why-person access -> exit 0, no `not classified` line", (done.returncode, "not classified" in done.stdout), (0, False))
        kept = json.loads(pipeline.read_text(encoding="utf-8"))["remarks"]
        check_eq("waiver: ...the key is written on that word only", [r.get("why_person") for r in kept], [None, "access"])
        waiver(root, *remark, "another word", "--why-person", " Access ")
        check_eq("waiver: ' Access ' is recorded as access", json.loads(pipeline.read_text(encoding="utf-8"))["remarks"][-1]["why_person"], "access")
        done = waiver(root, "--gate", "A", "--requirement", "R-1", "--decision", "accepted", "--why-person", "risk")
        check_eq("waiver: a gate waiver carries the class", (done.returncode, json.loads(pipeline.read_text(encoding="utf-8"))["gate_waivers"][0].get("why_person")),
                 (0, "risk"))
        # a revoke OVERWRITES the class of the entry it revokes (named behaviour, B1 deviation 4)
        pipeline.write_text(json.dumps({"task": "QA-1", "stage_overrides": [
            {"stage": "S1", "match": "video", "decision": "go on", "at": "t", "by": "human", "why_person": "access"}]}), encoding="utf-8")
        done = waiver(root, "--revoke", "--stage", "S1", "--block", "video", "--decision", "attached now", "--why-person", "money")
        entry = json.loads(pipeline.read_text(encoding="utf-8"))["stage_overrides"][0]
        check_eq("waiver: a revoke overwrites the earlier class on that entry", (done.returncode, entry.get("why_person"), "revoked_at" in entry),
                 (0, "money", True))
        pipeline.write_text(json.dumps({"task": "QA-1", "gates": {"A": {"decision": "approved"}}, "remarks": kept}), encoding="utf-8")
        # refusals: exit 2, stderr names the door, pipeline.json byte-identical (m8: the check runs BEFORE the write)
        before = sha(pipeline)
        for label, extra in (("nope", ["--why-person", "nope"]), ("empty", ["--why-person", ""]), ("two ids", ["--why-person", "access, money"])):
            done = waiver(root, *remark, "refused word", *extra)
            check_eq(f"waiver: --why-person {label} -> exit 2", done.returncode, 2)
            check_in("waiver: ...stderr names `--why-person <id>` (m9b)", "--why-person <id>", done.stderr)
            check_eq("waiver: ...pipeline.json unchanged (sha256)", sha(pipeline), before)
        done = waiver(root, "--why-person", "nope", "--stage", "S5", "--block", "x", "--decision", "word")
        check_eq("waiver: a refused class on the stage form -> exit 2, pipeline.json unchanged", (done.returncode, sha(pipeline)), (2, before))
        check_not_in("waiver: ...the sentence tells to use the flag, not to set a JSON key", "`why_person` set to", done.stderr)
        for label, extra in (("--list", ["--list"]), ("--carry-from", ["--carry-from", "QA-0"]), ("--selftest", ["--selftest"])):
            done = waiver(root, *extra, "--why-person", "access")
            check_eq(f"waiver: --why-person with {label} -> exit 2", done.returncode, 2)
            check_in("waiver: ...says it goes with a recording form", "goes with a recording form", done.stderr)
            check_eq("waiver: ...pipeline.json unchanged", sha(pipeline), before)
        done = waiver(root, "--why-person", "access")
        check_eq("waiver: --why-person alone (no recording form) -> exit 2", done.returncode, 2)
    finally:
        harness.cleanup(root)


def k1_the_class_travels() -> None:
    """B-1: every driver-road `waiver.py` recording call carries `*self.waiver_road(...)` (`--by driver`, plus `--why-person <id>` when the
    asked question named a class); the class survives `ask()` and `held_question`; `m-1`: the delivery prompt asks for `why_person`."""
    import re
    source = harness.driver_text()

    def bare_lines(text):
        """(recording call sites, the lines of those that do not carry `waiver_road(` before the next call or 900 characters)."""
        starts = [m.start() for m in re.finditer(r'self\.py\("waiver\.py"', text)]
        found, lines = [], []
        for i, at in enumerate(starts):
            window = text[at:min(starts[i + 1] if i + 1 < len(starts) else len(text), at + 900)]
            if '"--list"' in window[:80]:
                continue
            found.append(at)
            if "waiver_road(" not in window:
                lines.append(text.count("\n", 0, at) + 1)
        return found, lines
    recording, bare = [], []
    for path, text in harness.driver_sources():
        found, lines = bare_lines(text)
        recording += found
        bare += [f"{path.name}:{n}" for n in lines]
    check_eq("K1 positive control: the seven recording call sites", len(recording), 7)
    check_eq("K1 every recording call carries `waiver_road` (the lines that do not)", bare, [])
    check_eq("K1 negative control: one call site with the flag dropped is named (mutation of a copy)",
             len(bare_lines(source.replace("*self.waiver_road())", "", 1))[1]), 1)
    root, task_root, driver = rig([verdict()])
    try:
        check_eq("K1 no asked question: only the road mark", driver.waiver_road(), ("--by", "driver"))
        driver.state["asked"] = {"kind": "conductor", "why_person": " Money "}
        check_eq("K1 the asked class rides on the word", driver.waiver_road(), ("--by", "driver", "--why-person", "money"))
        check_eq("K1 a take-back carries the road mark alone", driver.waiver_road(False), ("--by", "driver"))
        driver.state["asked"] = {"kind": "conductor", "why_person": "nope"}
        check_eq("K1 a non-class is never passed on (it would be refused)", driver.waiver_road(), ("--by", "driver"))
        driver.boundary = "S5:S5-qa-automator-1"
        _, person = raised(driver, STATE)          # the stub conductor answers without a class twice: the fallback Person
        driver.ask(story_run.Person("conductor", "Which one?", "S5"))
        check_eq("K1 a question with no class stores none", driver.state["asked"].get("why_person"), None)
        classed = story_run.Person("conductor", "Which one?", "S5")
        classed.why_person = "risk"
        driver.ask(classed)
        check_eq("K1 ask() keeps the class in `asked`", driver.state["asked"].get("why_person"), "risk")
        check_eq("K1 ...so the word the answer records carries it", driver.waiver_road(), ("--by", "driver", "--why-person", "risk"))
        check_eq("K1 held_question gives the same question the same class", driver.held_question("lead").why_person, "risk")
    finally:
        harness.cleanup(root)
    at = source.find('{\\"action\\": \\"continue|ask_person|stop\\", \\"did\\": \\"<what went out')
    check("m-1 the delivery prompt's JSON line asks for `why_person`", at > 0 and "why_person" in source[at:at + 400], str(at))


def m5_carry_from_is_one_form() -> None:
    root, pipeline = waiver_project()
    try:
        done = waiver(root, "--carry-from", "QA-0", "--why-person", "access")
        check_eq("m-5 --carry-from with --why-person -> exit 2", done.returncode, 2)
        check_in("m-5 ...refused by the ONE check that names it (a recording form)", "goes with a recording form", done.stderr)
        check_not_in("m-5 ...not by the dead `mixed` entry", "does not combine", done.stderr)
    finally:
        harness.cleanup(root)


def main() -> None:
    for scenario in (a_to_e_validate_options, h_the_driver_road, k1_the_class_travels, w_the_waiver_road, m5_carry_from_is_one_form):
        scenario()
    harness.finish("person_owned_paths")


if __name__ == "__main__":
    main()
