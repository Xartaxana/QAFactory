"""HF1-9 (GW1-13): a stand integration known since onboarding is named BEFORE gate A.

TP1-12586: onboarding recorded `environment.integrations[jira-integration]` (keys JIRA_URL, JIRA_TOKEN, JIRA_PROJECT_KEY,
`required_by: ["api: Jira datasources and tools"]`) and the env file had none of them; the gate A brief never said "Jira" and the
person learned of it in S5, only because they had asked to be told. These tests pin the cure on a fixture of that shape (the cmp2
story of `test_gate_preflight.py` - imported, never copied): the integration is named in "After your approval" with its keys and
the file, tied to the cases by EQUALITY of `required_by` with the story's own ids (a card per case), asked once for the whole
story when it cannot be tied, and never silent (AR-23, AR-28). Values are never read into a text (the sentinel below).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import contract as C  # noqa: E402
import gate_brief  # noqa: E402
import gate_preflight  # noqa: E402
import stand_gaps  # noqa: E402
import test_gate_preflight as T  # noqa: E402  (the cmp2 story and its helpers)

JIRA = ["JIRA_URL", "JIRA_TOKEN", "JIRA_PROJECT_KEY"]
PROSE = "api: Jira datasources and tools"      # the 12586 `required_by`, verbatim
SENTINEL = "sentinel-value-9f3c2a"              # the value of a key that IS set: it must appear in no text
TC1 = T.cmp2_case_id(1)
ENV_FILE = "testproject1_test_harness/.env"


def integration(**fields) -> dict:
    return dict({"name": "jira-integration", "keys": JIRA + ["JIRA_USER"], "owner": "not named by the team",
                 "required_by": [PROSE]}, **fields)


def required(**fields) -> dict:
    """The 12586 row, called `required` by the project: HF8-11 keeps the question for it (prose alone became a line), so the
    pins of the question's text and limits stand on this row (changed from the bare prose row, HF8-11)."""
    return integration(applicability="required", **fields)


def story(prefix: str, integrations=None, config=None, one_case: bool = False, env_extra=(), **kw) -> Path:
    """The cmp2 story with the 12586 integration row (keys absent from the env file; JIRA_USER is set, to the sentinel).
    `one_case`: only TC1 on the api profile (plan row TS-10, automate)."""
    def edit(cfg):
        cfg["environment"]["integrations"] = integrations if integrations is not None else [integration()]
        if config:
            config(cfg)
    lines = kw.pop("env_lines", None) or (["AUTH_USERNAME=admin@example.invalid", "AUTH_PASSWORD=not-printed-1"]
                                          + [f"{key}=x" for key in T.CMP2_EXTRA_KEYS] + ["JIRA_USER=" + SENTINEL]
                                          + list(env_extra))
    if one_case:
        kw.update(base=False, extra=[(1, "TS-10", [])])
    return T.cmp2_story(prefix, config=edit, env_lines=lines, **kw)


def creds(root: Path, steps=("s5_credentials",)) -> dict:
    return T.cmp2_run(root, steps=steps)


def for_brief(result: dict) -> dict:
    return dict(result, gate="A", next_stage="S5", can_proceed=not result["findings"], by_class={})


def task_of(root: Path) -> Path:
    return root / "qa-factory" / "artifacts" / T.CMP2_TICKET


def questions(result: dict) -> list:
    return T.by_check(result, "s5_integrations")


def every_text(result: dict) -> str:
    return json.dumps([result["findings"], result["info"], result["stand_gaps"]])


# --- R0: the 12586 shape on the tree before the fix -----------------------------------------------------------------

def test_r0_the_12586_shape_is_named_in_the_brief_whatever_stood_ahead_of_it() -> None:
    """R0 reproduced two of the five suspects (H1: the finding sat behind the brief's 5-row cut; H2: nine missing login keys
    ahead of the Jira keys hid them behind `missing[:8]` and the integration's name was never said). Both are pinned here."""
    root = story("qa-int-r0-", integrations=[required()])
    try:
        result = creds(root)
        found = questions(result)
        check_eq("the 12586 row alone: one story-level question", len(found), 1)
        rows = [f for f in for_brief(result)["findings"]]
        # H1: five findings stood ahead of it in check order
        ahead = [{"id": f"x-{n}", "check": "s5_toolchain", "class": gate_preflight.FACTORY_DEFECT,
                  "message": f"defect {n}", "fix": ""} for n in range(5)]
        lines = gate_preflight.brief_lines(dict(for_brief(result), findings=ahead + rows))
        check_in("H1: the integration is among the five shown rows although five findings were produced before it",
                 "jira-integration", lines[0])
        check_in("H1: and the overflow line counts the row that gave way", "+1 more", lines[-1])
        # H2: nine login keys missing ahead of the Jira keys
        keys = [f"EXTRA_{n}" for n in range(9)]
    finally:
        cleanup(root)
    root = story("qa-int-r0-h2-", integrations=[required()], config=lambda cfg: cfg["environment"].__setitem__("extra_keys", keys))
    try:
        result = creds(root)
        env = T.by_check(result, "s5_environment")
        check_in("H2: the login question says it is cut (8 named, 1 more)", "and 1 more", env[0]["message"])
        check_not_in("H2: the integration's keys are not in the login question", "JIRA_URL", env[0]["message"])
        check_in("H2 (OH3-8: access in the message, the keys in the first move): the integration is its own question",
                 "jira-integration", questions(result)[0]["message"])
        check_in("H2: and its first move has the keys", "JIRA_URL", questions(result)[0]["fix"])
    finally:
        cleanup(root)


# --- K1 / K10: the 12586 shape (prose `required_by`) ----------------------------------------------------------------

def test_k1_the_brief_names_the_integration_its_keys_and_the_file_with_the_answers() -> None:
    root = story("qa-int-k1-", integrations=[required()])
    try:
        result = creds(root)
        found = questions(result)
        check_eq("K1: one finding, the person's, check s5_integrations", [(f["check"], f["class"]) for f in found],
                 [("s5_integrations", gate_preflight.PERSON_DECIDES)])
        check_eq("K1: its door is the waiver `integration missing: jira-integration` at S5",
                 found[0]["waives"], [{"block": "integration missing: jira-integration", "stage": "S5", "option": "accept"}])
        check_eq("K1: no s5_environment finding repeats the keys (all login keys are set)", T.by_check(result, "s5_environment"), [])
        text = "\n".join(gate_brief._after_approval({"rehearsal": for_brief(result)}))
        for needle in ["jira-integration"] + JIRA + [ENV_FILE, "\"" + PROSE + "\"", "how to answer", "yourself",
                                                         "tell the conductor", "reported as not run", "s5_integrations-1: accept"]:   # OH3-8: was "not run on this stand" - the fix has 400 characters
            check_in(f"K1: the brief block says {needle!r}", needle, text)
        check_not_in("K1: the key that is set is not asked", "JIRA_USER", text)
        check_not_in("K1: no value anywhere in the brief block", SENTINEL, text)
        check_not_in("K1: `change` is never offered on a secret", "change", text.replace("tell the conductor", ""))
        check_eq("K1: the sentinel is in no finding, note or row", SENTINEL in every_text(result), False)
        # the owner's rule, for the person's words (K10)
        import human_text
        for label, part in (("message", found[0]["message"]), ("fix", found[0]["fix"])):
            check_eq(f"K10: the {label} breaks no rule of human-questions.md",
                     [p["rule"] for p in human_text.problems(part, kind="report")], [])
    finally:
        cleanup(root)


# --- K2 / section 7: tied to a case ------------------------------------------------------------------------------------

def tied_story(prefix: str = "qa-int-k2-", **kw) -> Path:
    return story(prefix, integrations=[integration(required_by=["api"])], one_case=True, **kw)


def test_k2_an_integration_tied_to_a_case_is_one_card_with_three_answers_and_never_change() -> None:
    root = tied_story()
    try:
        result = creds(root)
        check_eq("K2: exactly one stand-gap row", len(result["stand_gaps"]), 1)
        row = result["stand_gaps"][0]
        check_eq("K2: its id and case", (row["id"], row["case"], row["pc_id"]), ("INT-jira-integration", TC1, "INT-jira-integration"))
        check_eq("K2: it offers myself / run / accept as options, never apply", row["remedy"]["offers"], ["theirs", "handed", "accept"])
        check_eq("K2: the remedy passes the contract", C.remedy_errors(row["remedy"]), [])
        check_eq("K2: the owner is said as not recorded by the project", row["owner"], "not recorded by the project")
        check_eq("K2: the check is the first missing key, so `accept always` has a key",
                 row["check"], {"env": "JIRA_URL"})
        gaps = stand_gaps.collect(task_of(root), "A", rehearsal=result)
        card = "\n".join(gate_brief.stand_gap_card_lines(task_of(root), gaps))
        for needle in [TC1, *JIRA, "`myself`", "`run`", "`accept`", ENV_FILE, "the automated run (S5)"]:
            check_in(f"K2: the card says {needle!r}", needle, card)
        check_not_in("K2: the card never offers `change`", "`change`", card)
        check_not_in("K2: the card does not ask for JIRA_USER (it is set)", "JIRA_USER", card)
        check_eq("K2: no value of any key is in any text", SENTINEL in every_text(result) + card, False)
        pointer = questions(result)
        check_eq("K2: one pointer finding, the card's door, option any",
                 [(f["class"], f["waives"][0]["block"], f["waives"][0]["option"]) for f in pointer],
                 [(gate_preflight.PERSON_DECIDES, "stand gap: INT-jira-integration", "any")])
        check_in("K2: the pointer names the case and the integration in its first 200 characters",
                 TC1, pointer[0]["message"][:200])
        check_in("K2: the pointer says the integration inside the brief's cut", "jira-integration", pointer[0]["message"][:200])
        # OH3-8 (was: "keys in first 200"): the pointer speaks of access; the keys are the card's fix line
        check_not_in("K2 (OH3-8): and no key in the pointer", "JIRA_URL", pointer[0]["message"])
        # the adversarial battery of the answer line (section 7), through the one reader
        def read(words: str) -> dict:
            return gate_brief.read_stand_gap_answers(words, gaps)
        for word, option in (("myself", "theirs"), ("accept", "accept"), ("run", "handed")):
            got = read(f"{TC1}: {word}")["read"]
            check_eq(f"S7: `{word}` is read as {option}", [r["option"] for r in got], [option])
        got = read(f"{TC1}: change")
        check_eq("S7: `change` is not recorded, and the refusal names the words that apply",
                 (got["read"], "myself" in got["unread"][0]["why"] and "accept" in got["unread"][0]["why"]), ([], True))
        for label, words in (("empty", ""), ("no word", f"{TC1}:"), ("a foreign id", "TC-999: accept"),
                             ("a word of another language", f"{TC1}: " + "".join(map(chr, (0x43F, 0x440, 0x438, 0x43D, 0x44F, 0x442, 0x44C)))), ("emoji", f"{TC1}: accept \U0001F680"),
                             ("NUL", f"{TC1}: accept\x00"), ("a 10 KB line", f"{TC1}: " + "accept " * 1500)):
            check_eq(f"S7: {label} records nothing", read(words)["read"], [])
        check_eq("S7: case and spacing are forgiven, as on every card",
                 [r["option"] for r in read(f"{TC1} : ACCEPT")["read"]], ["accept"])
    finally:
        cleanup(root)


# --- K3 / K9: the ties are equality only -------------------------------------------------------------------------------

def test_k3_a_tie_is_equality_of_ids_never_a_reading_of_words() -> None:
    def kinds(required_by, prefix="qa-int-k3-", mutate=None, **kw) -> tuple:
        root = story(prefix, integrations=[integration(required_by=required_by)], **kw)
        try:
            if mutate:
                mutate(root)
            result = creds(root)
            return len(questions(result)), len(result["stand_gaps"]), [row["message"] for row in result["info"]]
        finally:
            cleanup(root)

    check_eq("K3 (HF8-11, was a question: one story-level question, no card): prose holding a profile id ties nothing, "
             "and is now a line of the brief, not a question", kinds(["api: Jira"])[:2], (0, 0))
    check_eq("K3 (HF8-11, was a question): a row id of another story ties nothing and is a line, not a question",
             kinds(["TS-99"])[:2], (0, 0))
    check_eq("K3: a plan row id of this story ties its case", kinds(["TS-10"], one_case=True)[:2], (1, 1))
    check_eq("K3: a profile id ties the cases that run on it (four api cases)", kinds(["api"])[:2], (4, 4))
    check_eq("K3: a case area ties the cases of that area (the 18 cmp2 cases hold six automate ones)",
             kinds(["workflow-visual-diff"])[:2], (6, 6))

    def plan_edit(change):
        def apply(root):
            path = task_of(root) / "work" / "test-plan.json"
            plan = json.loads(path.read_text(encoding="utf-8"))
            change(plan)
            path.write_text(json.dumps(plan), encoding="utf-8")
        return apply

    def add_profile(cfg):
        cfg["profiles"].append(dict(cfg["profiles"][0], profile_id="mobile", capabilities=["mobile"]))
    mobile = {"config": add_profile}
    asked, rows, notes = kinds(["mobile"], **mobile)
    check_eq("E6: a profile of the project that no case of this story runs on, every case keyed: not asked", (asked, rows), (0, 0))
    check_in("E6: and the INFO says so", "needed by mobile, which no case of this story runs on", notes)
    unkeyed = plan_edit(lambda plan: plan["rows"][0].update(disposition="automate", level="contract"))
    check_eq("E6: one automate case whose profile code cannot tell keeps the question",
             kinds(["mobile"], mutate=unkeyed, **mobile)[:2], (1, 0))
    check_eq("E6: a profile id mixed with prose keeps the question", kinds(["mobile", "the mobile app"], **mobile)[:2], (1, 0))
    check_eq("K3: an unreadable plan is asked at story level",
             kinds(["api"], mutate=lambda root: (task_of(root) / "work" / "test-plan.json").write_text("{not json", encoding="utf-8"))[:2],
             (1, 0))
    check_eq("K9: a case whose `preconditions` cannot be read: asked at story level, for every in-scope integration",
             kinds(["api"], extra=[(1, "TS-1", '[{"id": "PC-1", "kind": "toggle"}]')])[:2], (1, 0))

    # t-075 (the mutation pass survivors t062-m2 / m2b): the tie is the WHOLE id as written, in both directions of a substring
    check_eq("K3 equality (HF8-11, was asked at story level): a row id INSIDE a prose entry ties nothing - a line, no card",
             kinds(["TS-10 is the area that needs it"], one_case=True)[:2], (0, 0))
    check_eq("K3 equality (HF8-11, was asked): an entry that is a fragment of a row id (`TS-1` in `TS-10`) ties nothing",
             kinds(["TS-1"], one_case=True)[:2], (0, 0))
    check_eq("K3 equality (HF8-11, was asked): the id in another case (`ts-10` for `TS-10`) ties nothing - ids are compared as written",
             kinds(["ts-10"], one_case=True)[:2], (0, 0))
    check_eq("K3 equality: the id as written, with the blanks around it dropped, ties its case",
             kinds(["  TS-10 "], one_case=True)[:2], (1, 1))
    check_eq("K3 equality: and the same id inside a list of other entries still ties",
             kinds(["TS-99", "TS-10"], one_case=True)[:2], (1, 1))


# --- K4: one statement of each fact, and the limit that says it is cut ------------------------------------------------

def test_k4_the_login_question_keeps_login_keys_and_says_when_its_list_is_cut() -> None:
    for count, cut in ((8, False), (9, True)):
        names = [f"EXTRA_{n}" for n in range(count)]
        root = story(f"qa-int-k4-{count}-", config=lambda cfg, names=names: cfg["environment"].__setitem__("extra_keys", names),
                     integrations=[])
        try:
            message = T.by_check(creds(root), "s5_environment")[0]["message"]
            check_eq(f"L1: {count} missing login keys, all {min(count, 8)} named", all(n in message for n in names[:8]), True)
            check_eq(f"L1: {count} missing: {'cut, and it says so' if cut else 'no suffix'}", "and 1 more" in message, cut)
        finally:
            cleanup(root)

    def both(cfg):
        cfg["environment"]["secret_keys"] = ["AUTH_PASSWORD", "JIRA_TOKEN"]
    root = story("qa-int-k4-login-", config=both, env_extra=[], integrations=[integration(required_by=["api"])],
                 env_lines=["AUTH_USERNAME=a", "AUTH_PASSWORD=b"] + [f"{k}=x" for k in T.CMP2_EXTRA_KEYS])
    try:
        result = creds(root)
        check_in("FR-10: a key that is also a login key stays in the login question", "JIRA_TOKEN",
                 T.by_check(result, "s5_environment")[0]["message"])
        check_not_in("and is not on the integration's card or question", "JIRA_TOKEN", json.dumps(result["stand_gaps"]))
        check_in("while the integration's other keys are", "JIRA_URL", json.dumps(result["stand_gaps"]))
    finally:
        cleanup(root)


# --- K5: the answer has a recorder and a reader -------------------------------------------------------------------------

def answer(root: Path, gap: str, decision: str, at: str = "2026-10-05T11:00:00+00:00", **extra) -> None:
    path = task_of(root) / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8"))
    pipeline.setdefault("stage_overrides", []).append(dict(
        {"stage": "S5", "match": f"stand gap: {gap}", "decision": decision, "at": at, "by": "human"}, **extra))
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def test_k5_an_answer_is_read_by_the_rehearsal_gate_b_and_the_delivery_check() -> None:
    root = tied_story("qa-int-k5-")
    try:
        check_eq("before any word: the pointer is there", len(questions(creds(root))), 1)
        answer(root, "INT-jira-integration", "accept - the Jira tests run on the team's stand")
        again = creds(root)
        check_eq("AR-24: the rehearsal drops the pointer of an accepted gap (the recorder is the driver's `stand gap:` line)",
                 questions(again), [])
        check_eq("...and the card is still built, so it shows the answer", len(again["stand_gaps"]), 1)
        # what the driver writes when every gap of the case is accepted at gate A (B-361): the carry under the case key
        answer(root, TC1, "accept - carried", declared=["INT-jira-integration"])
        gate_b_gap = [{"id": TC1, "case_id": TC1, "gate": "B", "stage": "S9"}]
        answers, had = stand_gaps.gate_b_answers(task_of(root), gate_b_gap)
        check_eq("AR-24: gate B reads the answer under the case, does not ask again",
                 (answers.get(TC1, {}).get("option"), answers.get(TC1, {}).get("gate"), answers.get(TC1, {}).get("change"), had),
                 ("accept", "A", "", True))
        pipeline = json.loads((task_of(root) / "pipeline.json").read_text(encoding="utf-8"))
        decisions, changed = stand_gaps.delivery_decisions(task_of(root), pipeline)
        check_eq("AR-24: the delivery check reads it as decided", (decisions.get(TC1, {}).get("option"), changed), ("accept", {}))
        # `myself` and keys still missing: the case is asked again at gate B, with its own text (E15)
        path = task_of(root) / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = []
        path.write_text(json.dumps(pipeline), encoding="utf-8")
        answer(root, "INT-jira-integration", "theirs - I will put the keys there")
        answer(root, TC1, "theirs - carried", declared=[])
        answers, _ = stand_gaps.gate_b_answers(task_of(root), gate_b_gap)
        check_eq("E15: a `myself` is not an acceptance, so the carry says it does not cover the case",
                 ("accept" != answers[TC1]["option"], bool(answers[TC1]["change"])), (True, True))
        check_eq("FR-7: any recorded word (here `myself`) closes the pointer, and the card stays to show it",
                 (len(questions(creds(root))), len(creds(root)["stand_gaps"])), (0, 1))
    finally:
        cleanup(root)


# --- K6 / K7 / K8: absent, empty, set, alternatives ---------------------------------------------------------------------

def test_k6_k7_an_absent_record_is_silent_and_a_clean_one_is_declared() -> None:
    for label, junk in (("absent", None), ("[]", []), ("junk", ["x", 3, {"keys": "A"}, {"name": "n", "keys": [None, ""]}])):
        root = story("qa-int-k6-", integrations=[] if junk is None else junk)
        try:
            result = creds(root)
            check_eq(f"K6/E1/E2: {label}: no finding, no card, no INFO of this check",
                     (result["findings"], result["stand_gaps"], [i for i in result["info"] if i["check"] == "s5_integrations"]),
                     ([], [], []))
        finally:
            cleanup(root)
    root = story("qa-int-k7-", integrations=[integration(applicability="not_required", required_by=["api"])])
    try:
        result = creds(root)
        check_eq("K7/E14: recorded, none needed: one INFO line, never silence",
                 [i["message"] for i in result["info"] if i["check"] == "s5_integrations"],
                 ["integrations: none of the 1 recorded has keys missing for this story"])
    finally:
        cleanup(root)


def test_k8_present_keys_are_not_asked_and_never_called_verified() -> None:
    env = [f"{k}=set-{n}" for n, k in enumerate(JIRA)]
    root = story("qa-int-k8-", env_extra=env)
    try:
        result = creds(root)
        check_eq("K8/E8: every key set: nothing is asked", (result["findings"], result["stand_gaps"]), ([], []))
        said = [i["message"] for i in result["info"] if i["check"] == "s5_integrations"]
        check_eq("K8: one INFO line", len(said), 1)
        check_in("K8: it says access is not proved", "is not proved", said[0])
        check_not_in("K8: and never 'verified' or 'ok'", "verified", said[0].lower() + " ")
        lines = gate_preflight.brief_lines(for_brief(result))
        check_in("F-3: the brief carries the same unknown as one report line", "is not proved", "\n".join(lines))
        check_in("F-3: the line is not a question (the rehearsal can proceed)", "can start: yes", lines[0])
    finally:
        cleanup(root)

    alt = integration(keys=["A_ONE", "A_TWO", "B_ONE", "B_TWO"], required_by=["api"],
                      credential_alternatives=[["A_ONE", "A_TWO"], ["B_ONE", "B_TWO"]])
    for label, extra, missing in (("an alternative satisfied", ["B_ONE=1", "B_TWO=1"], None),
                                  ("none satisfied, the nearest named", ["A_ONE=1"], ["A_TWO"]),
                                  ("none satisfied and nothing set: the first of equal routes", [], ["A_ONE", "A_TWO"])):
        root = story("qa-int-k8-alt-", integrations=[alt], one_case=True, env_extra=extra)
        try:
            result = creds(root)
            if missing is None:
                check_eq(f"FR-50: {label}: nothing is asked", (result["findings"], result["stand_gaps"]), ([], []))
            else:
                check_eq(f"FR-50: {label}", result["stand_gaps"][0]["remedy"]["change"].split(" (")[0], "set " + ", ".join(missing))
        finally:
            cleanup(root)
    for label, junk in (("an empty list", []), ("an empty alternative", [[]]), ("a non-list alternative", ["A_ONE"])):
        root = story("qa-int-k8-junk-", integrations=[dict(alt, credential_alternatives=junk)], one_case=True)
        try:
            check_eq(f"AR-28: {label} is no alternative: every key is wanted",
                     result_keys(creds(root)), ["A_ONE", "A_TWO", "B_ONE", "B_TWO"])
        finally:
            cleanup(root)


def result_keys(result: dict) -> list:
    return result["stand_gaps"][0]["remedy"]["change"].split(" (")[0].replace("set ", "").split(", ")


# --- K11: identities ----------------------------------------------------------------------------------------------------

def test_k11_gap_ids_are_per_integration_and_per_case_and_never_hold_a_separator() -> None:
    check_eq("E18: a name with `:`, `/`, `@` and spaces", gate_preflight.integration_gap_ids(["jira: prod/eu@x y"]), ["INT-jira--prod-eu-x-y"])
    check_eq("E18: two names that slug alike get -2, -3 in config order",
             gate_preflight.integration_gap_ids(["a:b", "a-b", "a b"]), ["INT-a-b", "INT-a-b-2", "INT-a-b-3"])
    check_eq("E18: a twin never takes a name another integration already holds",
             gate_preflight.integration_gap_ids(["a", "a", "a-2"]), ["INT-a", "INT-a-2", "INT-a-2-2"])
    two = [integration(name="jira", required_by=["api"], keys=["J_ONE"]),
           integration(name="aws: store", required_by=["api"], keys=["AWS_ONE"])]
    root = story("qa-int-k11-", integrations=two, one_case=True)
    try:
        rows = creds(root)["stand_gaps"]
        check_eq("E10: a case that needs two integrations has two rows, one gap each",
                 sorted(r["id"] for r in rows), ["INT-aws--store", "INT-jira"])
        check_eq("E10: ...and both have the one case", {r["case"] for r in rows}, {TC1})
    finally:
        cleanup(root)
    root = story("qa-int-k11-shared-", integrations=[integration(name="jira", required_by=["TS-10", "TS-12"], keys=["J_ONE"])])
    try:
        rows = creds(root)["stand_gaps"]
        check_eq("E11: one integration on two cases: the ids are qualified by the case, so no answer passes the other",
                 sorted(r["id"] for r in rows), sorted(f"INT-jira@{T.cmp2_case_id(n)}" for n in (10, 12)))
    finally:
        cleanup(root)


# --- K12: the position keeps the split with the precondition cards ---------------------------------------------------------

def test_k12_the_order_of_the_two_steps_changes_nothing_a_person_reads() -> None:
    def shown(order) -> tuple:
        root = story("qa-int-k12-", integrations=[integration(required_by=["api"], keys=["TC014_READONLY_USER_TOKEN", "J_ONE"])])
        try:
            result = T.cmp2_run(root, steps=order)
            return (sorted(f["message"] for f in result["findings"]), sorted(r["id"] for r in result["stand_gaps"]))
        finally:
            cleanup(root)
    forward = shown(("s5_credentials", "case_preconditions"))
    check_eq("K12: credentials then preconditions, or the reverse: the same findings and the same gaps",
             forward, shown(("case_preconditions", "s5_credentials")))
    check_in("K12: a key a case names itself stays the precondition card's (FR-10)", "TC014_READONLY_USER_TOKEN", json.dumps(forward[0]))
    check_not_in("K12: ...and is not on the integration's card", "TC014_READONLY_USER_TOKEN",
                 json.dumps([m for m in forward[0] if "jira-integration" in m]))


# --- K13: limits, at and beyond ---------------------------------------------------------------------------------------------

def test_k13_the_limits_say_they_cut_and_never_hide_an_integration() -> None:
    cut = gate_preflight.BRIEF_CUT

    def row(check: str, message: str) -> dict:
        return {"id": f"{check}-1", "check": check, "class": gate_preflight.PERSON_DECIDES, "message": message, "fix": ""}
    def lines_of(message: str) -> list:
        return gate_preflight.brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
                                           "findings": [row("s5_integrations", message)]})
    check_eq("L2: 200 characters are not cut", "…" in lines_of("x" * cut)[0], False)
    check_eq("L2: 201 are cut, with the mark and the line that says so", ("…" in lines_of("x" * (cut + 1))[0],
                                                                         "marks a line cut" in lines_of("x" * (cut + 1))[-1]), (True, True))
    prose = "the Jira datasources and the tools that create them " * 8
    root = story("qa-int-k13-", integrations=[required(required_by=[prose])])
    try:
        found = questions(creds(root))[0]["message"]
        check_eq("L2 (OH3-8, was: and the keys): a very long prose is clipped INSIDE its quotes, and the name stays in the first 200",
                 ["…" in found[:cut], "jira-integration" in found[:cut]], [True, True])
    finally:
        cleanup(root)
    many = [f"JIRA_K{n:02d}" for n in range(36)]
    for count, more in ((6, False), (7, True), (36, True)):
        root = story("qa-int-k13-l5-", integrations=[required(keys=many[:count], required_by=["the project's words"])])
        try:
            found = questions(creds(root))[0]
            fix = found["fix"]
            # OH3-8 (was: "All the keys:" after the message): the first move names at most LIST_LIMIT, then how many are left
            check_eq(f"L5: {count} keys: {'6 named, the rest counted, and the conductor has the list' if more else 'all named'}",
                     (f"and {count - 6} more" in fix, "the conductor has the full list" in fix), (more, more))
            check_eq(f"L5: {count} keys: the fix is not cut by the brief (the name of the last move survives)",
                     "tell the conductor" in gate_preflight.brief_lines(for_brief(creds(root)))[1], True)
            check_eq(f"L5: {count} keys: no name is cut in the middle", [k in fix for k in many[:min(count, 6)]], [True] * min(count, 6))
        finally:
            cleanup(root)
    # L5 on the REAL names (F-1): the 14 rows of a real project's config, keys longest first (the worst order), all unset. The
    # fix of every question stays whole inside the 400 characters the brief shows, so the last move survives.
    fixture = json.loads((Path(__file__).resolve().parent / "fixtures" / "config-projection" / "config-ff4fc62e.json")
                         .read_text(encoding="utf-8"))
    real = [required(name=r["name"], keys=sorted(r["keys"], key=lambda k: (-len(k), k)), required_by=["the project's words"])
            for r in fixture["environment"]["integrations"]]
    root = story("qa-int-k13-real-", integrations=real)
    try:
        found = questions(creds(root))
        check_eq("L5 real: 14 rows, 14 questions", len(found), 14)
        shown = [gate_preflight.brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
                                             "findings": [q]})[1] for q in found]
        check_eq("L5 real: every fix is within 2 x BRIEF_CUT and keeps 'tell the conductor' uncut",
                 [(len(q["fix"]) <= 2 * cut, "tell the conductor" in line and "…" not in line) for q, line in zip(found, shown)],
                 [(True, True)] * 14)
        check_eq("L5 real: the names are still there: the first key of every row, longest first",
                 [real[n]["keys"][0] in found[n]["fix"] for n in range(14)], [True] * 14)
    finally:
        cleanup(root)
    # L5 AT and BEYOND the limit, on the function that builds the moves: a `where` of every length, long names
    waiver = "or accept the gap with the word `accept` and the block name of the integration, nothing is recorded else"
    long_keys = [f"SANDBOX_ELASTICSEARCH_API_KEY_{n}" for n in range(10)]
    lengths = {where_len: gate_preflight.access_fix(long_keys, "p" * where_len, waiver) for where_len in range(0, 701)}
    check_eq("L5 beyond: a `where` of 0..700 characters: never longer than 2 x BRIEF_CUT, the last move always there",
             [n for n, fix in lengths.items() if len(fix) > 2 * cut or not fix.endswith("tell the conductor")], [])
    exact = [n for n, fix in lengths.items() if len(fix) == 2 * cut]
    check_eq("L5 at: some `where` makes the fix exactly 400 characters, and 400 is not cut", bool(exact) and "…" not in lengths[exact[0]], True)
    check_eq("L5 beyond: a `where` that cannot fit is clipped at its FRONT (the file name survives)",
             lengths[700].split(" in ")[1].split(", never")[0][0], "…")
    check_in("L5: names that do not fit are counted, and the full list is the conductor's", "more; the conductor has the full list",
             lengths[300])
    # L3: the integration is shown whatever the checks produced ahead of it
    ahead = [row("s5_toolchain", f"defect {n}") for n in range(5)]
    shown = gate_preflight.brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
                                        "findings": ahead + [row("s5_integrations", "the integration question")]})
    check_eq("L3: six rows, the integration produced last: it is first of the five shown, the overflow counts one",
             (shown[0].endswith("the integration question"), "+1 more" in shown[-1], len(shown)), (True, True, 6))
    five = gate_preflight.brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
                                       "findings": ahead[:4] + [row("s5_integrations", "the integration question")]})
    check_eq("L3: five rows, all shown, no overflow", ("+" in five[-1], len(five)), (False, 5))
    # L4: a fourth card is one line, never dropped
    root = story("qa-int-k13-l4-", integrations=[integration(required_by=["api"])])
    try:
        result = creds(root)
        gaps = stand_gaps.collect(task_of(root), "A", rehearsal=result)
        text = "\n".join(gate_brief.stand_gap_card_lines(task_of(root), gaps))
        check_eq("L4: four cases, four gaps; the fourth is in the packet as a line", (len(gaps), all(r["case"] in text for r in result["stand_gaps"])),
                 (4, True))
        check_eq("L4: three in full, one as a short line", text.count("Stand gap:"), 3)
    finally:
        cleanup(root)


def test_the_new_texts_obey_the_owners_rule_and_the_old_door_still_works() -> None:
    """K10 for the card pointer and the INFO lines; the old `s5_environment` waiver (a recorded word against the old text)
    neither passes the new question (a different block, FR-7: new text, asked once) nor is it needed by it (§4.T)."""
    import human_text
    root = tied_story("qa-int-k10-")
    try:
        result = creds(root)
        for text in [f["message"] + " " + f["fix"] for f in result["findings"]] + [i["message"] for i in result["info"]]:
            check_eq(f"K10: {text[:50]!r} breaks no script/flag/exit-code rule", T._owner_rule_offences(text), [])
        broken = {p["rule"] for p in human_text.problems(result["findings"][0]["message"], kind="report")}
        check_eq("K10: the pointer breaks the same rules the older card pointers break (a case id first named by its gap)",
                 broken - {"unexplained_id"}, set())
    finally:
        cleanup(root)
    root = story("qa-int-k10-old-", integrations=[required()])
    try:
        answer(root, "x", "accept")      # a stand-gap word for another gap
        path = task_of(root) / "pipeline.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{"stage": "S5", "match": "S5 needs keys it does not have for jira-integration",
                                        "decision": "accept - old text", "by": "human"}]
        path.write_text(json.dumps(pipeline), encoding="utf-8")
        check_eq("§4.T: a word recorded against the OLD text does not pass the new question", len(questions(creds(root))), 1)
    finally:
        cleanup(root)


# --- HF8-11 / OH3-8: alternatives, the line instead of the wall, the text of the question --------------------------------

CLOUD = ["JIRA_CLOUD_URL", "JIRA_CLOUD_TOKEN"]
SERVER = ["JIRA_URL", "JIRA_TOKEN"]


def alternatives(**fields) -> dict:
    """The 12586 service with its two ways in: a cloud set and a server set (W-3). `keys` is their union (the contract)."""
    return integration(keys=CLOUD + SERVER, credential_alternatives=[CLOUD, SERVER], **fields)


def plan_edit(root: Path, change) -> None:
    path = task_of(root) / "work" / "test-plan.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    change(plan)
    path.write_text(json.dumps(plan), encoding="utf-8")


def shape(specs, prefix: str = "qa-int-hf8-", mutate=None, **kw) -> tuple:
    """(questions, stand-gap rows, the result, the brief lines) of the cmp2 story with these integration rows."""
    root = story(prefix, integrations=specs, **kw)
    try:
        if mutate:
            mutate(root)
        result = creds(root)
        return len(questions(result)), len(result["stand_gaps"]), result, gate_preflight.brief_lines(for_brief(result))
    finally:
        cleanup(root)


def untied_names(result: dict) -> list:
    return [i["integration"] for i in result["info"] if i.get("untied")]


def collective(lines: list) -> list:
    return [line for line in lines if line.startswith("- Stand access not set")]


def test_hf8_11_a1_an_alternative_that_is_set_asks_nothing_and_the_nearest_is_named() -> None:
    asked, rows, result, lines = shape([alternatives()], env_extra=["JIRA_URL=1", "JIRA_TOKEN=1"])
    check_eq("K-A1: the server set is whole: no finding, no gap", (result["findings"], result["stand_gaps"]), ([], []))
    check_in("K-A1: the INFO says access is not proved", "is not proved", json.dumps(result["info"]))
    asked, rows, result, lines = shape([alternatives()], env_extra=["JIRA_URL=1"])
    said = [i["message"] for i in result["info"] if i.get("untied")]
    check_eq("K-A1: one JIRA_TOKEN missing in the server set: no question, no card, one INFO line", (asked, rows, len(said)), (0, 0, 1))
    check_in("K-A1: the line names the NEAREST set (the server one)", "JIRA_TOKEN", said[0])
    check_not_in("K-A1: not the cloud set", "JIRA_CLOUD_URL", said[0])


def test_hf8_11_a2_prose_alone_is_one_line_of_the_brief_not_a_question() -> None:
    asked, rows, result, lines = shape([integration()])
    check_eq("K-A2: no question, no card, no finding", (asked, rows, result["findings"]), (0, 0, []))
    text = "\n".join(lines)
    check_not_in("K-A2: and not 'nothing else stands' beside a gap (M6)", "nothing else stands", text)
    check_eq("K-A2: the brief opens with the gap", lines[0], "- S5 can start: yes, with the gap below.")
    line = collective(lines)
    check_eq("K-A2: ONE collective line, with the name", (len(line), "jira-integration" in line[0]), (1, True))
    check_in("K-A2 (C1): it says the factory could not match", "could not match", line[0])
    check_not_in("K-A2 (C1): and not 'no case'", "no case", line[0])
    for word in ("JIRA_URL", "key", "env"):
        check_not_in(f"K-A2: the line has no {word!r}", word, line[0])
    check_eq("K-A2: `info` keeps the name as data", untied_names(result), ["jira-integration"])
    check_in("K-A2: and the whole fact (with the names) is in the note for --text", "JIRA_URL",
             [i["message"] for i in result["info"] if i.get("untied")][0])


def test_hf8_11_a3_every_unknown_stays_a_question() -> None:
    mobile = lambda cfg: cfg["profiles"].append(dict(cfg["profiles"][0], profile_id="mobile", capabilities=["mobile"]))
    unkeyed = lambda root: plan_edit(root, lambda plan: plan["rows"][0].update(disposition="automate", level="contract"))

    def obligation(root):
        plan_edit(root, lambda plan: [r.update(coverage_obligations=[{"obligation_id": "OB-1"}]) for r in plan["rows"]
                                      if r["id"] == "TS-1"])
    unreadable_plan = lambda root: (task_of(root) / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
    bad_case = [(1, "TS-1", '[{"id": "PC-1", "kind": "toggle"}]')]
    branches = {
        "an unreadable case": dict(specs=[integration()], extra=bad_case),
        "an unreadable plan": dict(specs=[integration()], mutate=unreadable_plan),
        "required, nothing recorded": dict(specs=[required(required_by=[])]),
        "required with prose": dict(specs=[required()]),
        "a row of this story with no automate case": dict(specs=[integration(required_by=["TS-1"])]),
        "an obligation of this story with no automate case": dict(specs=[integration(required_by=["OB-1"])], mutate=obligation),
        "a profile of the project, an automate case without a profile (E6)": dict(
            specs=[integration(required_by=["mobile"])], mutate=unkeyed, config=mobile),
        "that profile mixed with prose (E6)": dict(
            specs=[integration(required_by=["mobile", "the mobile app"])], mutate=unkeyed, config=mobile),
    }
    for label, kw in branches.items():
        asked, rows, result, lines = shape(**kw)
        check_eq(f"K-A3: {label}: one question, no line", (asked, untied_names(result)), (1, []))


def test_hf8_11_a4_a_foreign_id_or_prose_with_a_profile_name_is_a_line() -> None:
    for label, entries in (("an id of another story", ["TS-99"]), ("prose that holds a profile id", ["api: Jira"])):
        asked, rows, result, lines = shape([integration(required_by=entries)])
        check_eq(f"K-A4: {label}: a line and no question", (asked, rows, untied_names(result)), (0, 0, ["jira-integration"]))


def test_hf8_11_a5_an_integration_tied_by_equality_is_still_cards() -> None:
    asked, rows, result, lines = shape([integration(required_by=["api"])])
    check_eq("K-A5: the profile id ties the four api cases: four cards", (asked, rows), (4, 4))
    check_eq("K-A5: and no collective line", (collective(lines), untied_names(result)), ([], []))


def test_hf8_11_a6_the_collective_line_names_six_and_counts_the_rest() -> None:
    def many(count: int) -> list:
        return [integration(name=f"svc-{n}", keys=[f"SVC{n}_ONE"], required_by=["the team's own words"]) for n in range(count)]
    asked, rows, result, lines = shape(many(6))
    line = collective(lines)[0]
    check_eq("K-A6: six: all six named, no 'more'", ([f"svc-{n}" in line for n in range(6)], "more" in line.split(". ")[0]),
             ([True] * 6, False))
    asked, rows, result, lines = shape(many(7))
    line = collective(lines)[0]
    check_eq("K-A6: seven: six named and 'and 1 more'", ("svc-5" in line, "svc-6" in line, "and 1 more" in line), (True, False, True))
    check_eq("K-A6: `info` keeps all seven", len(untied_names(result)), 7)


def test_hf8_11_a7_the_new_lines_break_no_rule_and_carry_no_value() -> None:
    import human_text
    asked, rows, result, lines = shape([integration()])
    check_eq("K-A7: the collective line breaks no rule of human-questions.md",
             [p["rule"] for p in human_text.problems(collective(lines)[0].lstrip("- "), kind="report")], [])
    check_eq("K-A7: no value in any text", SENTINEL in every_text(result) + "\n".join(lines), False)


def test_hf8_11_a8_a_key_a_case_names_is_not_asked_inside_an_alternative_either() -> None:
    named = integration(keys=["TC014_READONLY_USER_TOKEN", "B_ONE"], required_by=["api"],
                        credential_alternatives=[["TC014_READONLY_USER_TOKEN"], ["B_ONE"]])
    asked, rows, result, lines = shape([named])
    check_eq("K-A8: the nearest set is the case's own key: the case asks, the integration does not", (asked, rows), (0, 0))
    asked, rows, result, lines = shape([named], extra=[(1, "TS-1", '[{"id": "PC-1", "kind": "toggle"}]')])
    check_eq("K-A8: with a case that cannot be read the key stays wanted (a question)", asked, 1)
    check_in("K-A8: and it is named", "TC014_READONLY_USER_TOKEN", questions(result)[0]["fix"])
    # F-5 (P6): ONE set that holds the case's own key AND another: the case asks its key, the integration the other
    both = integration(keys=["TC014_READONLY_USER_TOKEN", "X_ONE"], required_by=["api"],
                       credential_alternatives=[["TC014_READONLY_USER_TOKEN", "X_ONE"]])
    asked, rows, result, lines = shape([both])
    changes = [row["remedy"]["change"] for row in result["stand_gaps"]]
    check_eq("K-A8 (M6): the partly-named set: every card asks X_ONE and never the case's own key",
             (bool(changes), all("set X_ONE " in c and "TC014_READONLY_USER_TOKEN" not in c for c in changes)), (True, True))


def test_hf8_11_a9_a_row_with_named_sets_and_no_keys_does_not_vanish() -> None:
    named = integration(keys=[], required_by=["api"], credential_alternatives=[["A_ONE", "A_TWO"], ["B_ONE"]])
    asked, rows, result, lines = shape([named], one_case=True)
    check_eq("K-A9: empty `keys`, two sets: one card, the nearest set", (rows, result_keys(result)), (1, ["B_ONE"]))


def test_hf8_11_a10_a_row_that_only_says_where_the_code_reads_it() -> None:
    def bare(**fields) -> dict:
        row = integration(**fields)
        row.pop("required_by")
        return row
    where = ["tests/ado/test_x.py:12"]
    asked, rows, result, lines = shape([bare(read_at=where)])
    check_eq("K-A10: read_at, keys not set: no question, in the collective line", (asked, untied_names(result)), (0, ["jira-integration"]))
    check_eq("K-A10: and the brief has the line", len(collective(lines)), 1)
    check_not_in("K-A10 (F-2): beside the gap, not 'none has keys missing'", "none of the", json.dumps(result["info"]))
    check_in("K-A10 (F-3): the line is true of a row that records no words at all", "does not say who needs them", collective(lines)[0])
    check_not_in("K-A10 (F-3): and does not say the project describes it in its own words", "own words", collective(lines)[0])
    asked, rows, result, lines = shape([bare()])
    check_eq("K-A10: no read_at: as before - a note of the old check, no line", (untied_names(result), collective(lines)), ([], []))
    check_in("K-A10: the old note", "not asked", json.dumps(result["info"]))
    asked, rows, result, lines = shape([bare(read_at=where)], env_extra=[f"{k}=1" for k in JIRA])
    check_eq("K-A10: keys set: neither the line nor a question; the old note stays", (untied_names(result), asked), ([], 0))
    check_in("K-A10: the old note when the keys are set", "not asked", json.dumps(result["info"]))


def test_oh3_8_the_texts_say_access_and_name_the_keys_only_in_the_first_move() -> None:
    import human_text
    row = required(owner="the platform team")
    root = story("qa-int-oh38-", integrations=[row])
    try:
        found = questions(creds(root))[0]
        for label, text in (("message", found["message"]),):
            for word in ("key", "env"):
                check_not_in(f"K-B6: the {label} has no {word!r}", word, text.lower())
        check_in("K-B6: the first move names the keys and the file", ENV_FILE, found["fix"])
        check_in("K-B6: with an owner recorded, who gives the access is said", "the platform team", found["message"])
        for label, part in (("message", found["message"]), ("fix", found["fix"])):
            check_eq(f"K-B6: the {label} breaks no rule of human-questions.md",
                     [p["rule"] for p in human_text.problems(part, kind="report")], [])
    finally:
        cleanup(root)
    root = story("qa-int-oh38-none-", integrations=[required()])
    try:
        check_not_in("K-B6: no owner recorded: no 'Who gives'", "Who gives", questions(creds(root))[0]["message"])
    finally:
        cleanup(root)
    root = tied_story("qa-int-oh38-card-")
    try:
        result = creds(root)
        row = result["stand_gaps"][0]
        for field in ("what", "detail"):
            for word in ("key", "env"):
                check_not_in(f"K-B6: the card's {field} has no {word!r}", word, row[field].lower())
        check_not_in("K-B6: the card pointer has no 'key'", "key", questions(result)[0]["message"].lower())
    finally:
        cleanup(root)


# --- GW1-16: a case declares its integration -----------------------------------------------------------------------------

TC2, TC3 = T.cmp2_case_id(2), T.cmp2_case_id(3)
ROLE_REMEDY = {"kind": "credential", "where": "the-role-wrote-this-file", "change": "the role wrote this change"}
BOTH = ("case_preconditions", "s5_credentials")


def declaring(name: str = "jira-integration", partitions=("P-x",), **fields) -> list:
    """The `preconditions` of a case that goes through an integration, as the designer now writes it (G-1: the NAME, not a key)."""
    return [dict(T._pc("PC-1", "service", "access to the Jira datasources", list(partitions), "x", {"integration": name}), **fields)]


def declared(prefix: str, specs, name: str = "jira-integration", others=(), **kw) -> Path:
    """TC-001 on the api profile (plan row TS-10) declares `name`; `others` are more cases `(n, row, items)`."""
    return story(prefix, integrations=specs, base=False, extra=[(1, "TS-10", declaring(name))] + list(others), **kw)


def declared_run(prefix: str, specs, **kw) -> tuple:
    """(the result of case_preconditions + s5_credentials, the brief lines) of the story where TC-001 declares `name`."""
    root = declared(prefix, specs, **kw)
    try:
        result = creds(root, steps=BOTH)
        return result, gate_preflight.brief_lines(for_brief(result))
    finally:
        cleanup(root)


def gate_findings(result: dict) -> list:
    return T.by_check(result, "case_preconditions")


def test_gw1_16_k16_1_the_12586_shape_a_declared_integration_is_one_card_of_the_case() -> None:
    result, lines = declared_run("qa-int-gw16-k1-", [integration()])
    gaps = result["stand_gaps"]
    check_eq("K16.1: ONE card, the declaring case's own, with its partitions and the kind the designer wrote",
             [(g["id"], g["case"], g["partitions"], g["kind"]) for g in gaps], [("PC-1", TC1, ["P-x"], "service")])
    check_in("K16.1: the fix names the keys of the nearest set", "JIRA_URL", gaps[0]["remedy"]["change"])
    check_eq("K16.1: no story-level question and no collective line of the project's prose",
             (questions(result), untied_names(result), collective(lines)), ([], [], []))
    check_eq("K16.1: the integration says who declared it, as data", [i["message"] for i in result["info"] if i.get("declared")],
             [f"jira-integration: declared by {TC1}, whose own cards ask for the access"])
    check_eq("K16.1: no value in any text", SENTINEL in every_text(result), False)


def test_gw1_16_k16_2_k16_3_alternatives_are_the_routes_reader() -> None:
    result, lines = declared_run("qa-int-gw16-k2-", [alternatives()], env_extra=["JIRA_URL=1", "JIRA_TOKEN=1"])
    check_eq("K16.2: the server set is whole: no finding, no card", (result["findings"], result["stand_gaps"]), ([], []))
    result, lines = declared_run("qa-int-gw16-k3-", [alternatives()], env_extra=["JIRA_URL=1"])
    change = result["stand_gaps"][0]["remedy"]["change"]
    check_in("K16.3: the nearest set is named", "JIRA_TOKEN", change)
    check_not_in("K16.3: not the union of the sets", "JIRA_CLOUD_URL", change)


def test_gw1_16_k16_4_the_empty_outcomes_are_named() -> None:
    result, lines = declared_run("qa-int-gw16-k4a-", [])
    found = gate_findings(result)
    check_eq("K16.4: no integration recorded at all: ONE finding of the factory (the designer's line to rewrite), no question",
             ([f["class"] for f in found], result["stand_gaps"], questions(result)), ([gate_preflight.FACTORY_FIXABLE], [], []))
    check_in("K16.4: it names the case and the name", TC1, found[0]["message"])
    check_in("K16.4: and the name", "jira-integration", found[0]["message"])
    check_in("K16.4: and says the project records none", "records none", found[0]["message"])
    check_in("K16.4: with the designer as the door", "case designer rewrites", found[0]["fix"])
    for label, spec in (("a row with no keys", integration(keys=[])), ("a row marked not needed", integration(applicability="not_required"))):
        result, lines = declared_run("qa-int-gw16-k4b-", [spec])
        found = gate_findings(result)
        check_eq(f"K16.4: {label}: a QUESTION to the person (they know the stand), no card, no finding of the factory",
                 ([f["class"] for f in found], result["stand_gaps"]), ([gate_preflight.PERSON_DECIDES], []))
        check_in(f"K16.4: {label}: it names the case", TC1, found[0]["message"])


def test_gw1_16_k16_5_a_name_is_equality_and_every_unknown_stays_a_question() -> None:
    for label, name in (("another case", "Jira-Integration"), ("a space inside", "jira integration"), ("a suffix", "jira-integration-2")):
        root = declared("qa-int-gw16-k5-", [integration()], name=name)
        try:
            result = creds(root, steps=BOTH)
        finally:
            cleanup(root)
        found = gate_findings(result)
        check_eq(f"K16.5: {label}: a finding of the factory naming the recorded name, no card, no question to the person",
                 ([f["class"] for f in found], "jira-integration" in found[0]["message"], result["stand_gaps"]),
                 ([gate_preflight.FACTORY_FIXABLE], True, []))
    # the declaration beside a case whose `preconditions` cannot be read: the unknown is asked (the neighbour may need the service)
    root = declared("qa-int-gw16-k5u-", [integration()], others=[(2, "TS-12", '[{"id": "PC-1", "kind": "toggle"}]')])
    try:
        result = creds(root, steps=BOTH)
    finally:
        cleanup(root)
    check_eq("K16.5: an unreadable neighbour: the story question stays", (len(questions(result)), untied_names(result)), (1, []))
    # `gate_rehearsal.skip_preconditions`: no card will be made, so nothing is taken away
    skip = lambda cfg: cfg["gate_rehearsal"].update(skip_preconditions=True)
    root = declared("qa-int-gw16-k5s-", [integration()], config=skip)
    try:
        result = creds(root, steps=BOTH)
    finally:
        cleanup(root)
    check_eq("K16.5: skip_preconditions: the line stays, no card, no silence", (untied_names(result), result["stand_gaps"]),
             (["jira-integration"], []))


def test_gw1_16_k16_6_equality_and_a_declaration_make_one_card_per_case() -> None:
    others = [(2, "TS-12", []), (3, "TS-14", [])]
    root = declared("qa-int-gw16-k6-", [integration(required_by=["api"])], others=others)
    try:
        result = creds(root, steps=BOTH)
    finally:
        cleanup(root)
    gaps = result["stand_gaps"]
    check_eq("K16.6: TC-1 has its PC card and no INT card; TC-2 and TC-3 have the INT cards",
             sorted((g["case"], g["id"].split("@")[0]) for g in gaps),
             sorted([(TC1, "PC-1"), (TC2, "INT-jira-integration"), (TC3, "INT-jira-integration")]))


def test_gw1_16_k16_7_the_form_is_a_name() -> None:
    def errors(check) -> list:
        return gate_preflight.parse_preconditions([{"id": "PC-1", "kind": "service", "what": "x", "check": check}])[1]
    for bad in ("", "   ", ["a"], "a\nb", 7):
        found = errors({"integration": bad})
        check_eq(f"K16.7: {bad!r} is refused, naming the field", [("check.integration" in e) for e in found], [True])
    check_eq("K16.7: a name is accepted", errors({"integration": "jira-integration"}), [])
    check_in("K16.7: the form says the form", '"integration"', gate_preflight.PRECONDITION_FORM)
    check_in("K16.7: the list of checks holds it", "integration", gate_preflight.PRECONDITION_CHECKS)


def test_gw1_16_k16_8_the_role_never_writes_the_fix_of_this_check() -> None:
    root = story("qa-int-gw16-k8-", integrations=[integration()], base=False, extra=[(1, "TS-10", declaring(remedy=ROLE_REMEDY))])
    try:
        result = creds(root, steps=BOTH)
        card = result["stand_gaps"][0]["remedy"]
        check_eq("K16.8: unmet: the card carries the code's remedy, not the role's", (card["where"], card["change"].startswith("set JIRA_")),
                 (ENV_FILE, True))
        check_not_in("K16.8: and nothing the role wrote", "the role wrote", json.dumps(result["stand_gaps"]))
        # the parsed items are never changed (two rehearsals in a row see equal items), whatever the state
        import copy
        r = gate_preflight.Rehearsal(task_of(root), "A")
        ctx = r._precondition_ctx({})
        items = gate_preflight.parse_preconditions([dict(declaring(remedy=ROLE_REMEDY)[0], check={"integration": "jira-integration"})])[0]
        before = copy.deepcopy(items)
        first = r._sort_items(items, ctx, "TC")
        second = r._sort_items(items, ctx, "TC")
        check_eq("K16.8: parse_preconditions' result is not mutated and the second sort equals the first", (items == before, first == second),
                 (True, True))
    finally:
        cleanup(root)
    root = story("qa-int-gw16-k8u-", integrations=[integration(applicability="not_required")], base=False,
                 extra=[(1, "TS-10", declaring(remedy=ROLE_REMEDY))])
    try:
        result = creds(root, steps=BOTH)
        check_eq("K16.8: uncheckable: the valid remedy of the role makes NO card", result["stand_gaps"], [])
        r = gate_preflight.Rehearsal(task_of(root), "A")
        items = gate_preflight.parse_preconditions([dict(declaring(remedy=ROLE_REMEDY)[0], check={"integration": "jira-integration"})])[0]
        opened = r._sort_items(items, r._precondition_ctx({}), "TC")[0]
        check_eq("K16.8: the open item carries no remedy, the parsed one still does", ("remedy" in opened[0][0], "remedy" in items[0]),
                 (False, True))
    finally:
        cleanup(root)
    root = story("qa-int-gw16-k8b-", integrations=[integration()], base=False,
                 extra=[(1, "TS-10", declaring(remedy={"kind": "nothing"}))])
    try:
        found = gate_findings(creds(root, steps=BOTH))
        check_eq("K16.8: a wrong remedy is the ordinary refusal of the form", [("cannot be read" in f["message"]) for f in found], [True])
    finally:
        cleanup(root)


def test_gw1_16_k16_9_another_naming_is_a_card_not_a_crash() -> None:
    row = integration(name="stripe-keys", keys=["STRIPE_API_KEY"], required_by=["payments team"])
    root = story("qa-int-gw16-k9-", integrations=[row], base=False, extra=[(1, "TS-4", declaring("stripe-keys"))])
    try:
        result = creds(root, steps=BOTH)
    finally:
        cleanup(root)
    check_eq("K16.9: one card, its fix names the key", [g["id"] for g in result["stand_gaps"]], ["PC-1"])
    check_in("K16.9: the key of THIS project", "STRIPE_API_KEY", result["stand_gaps"][0]["remedy"]["change"])
    check_eq("K16.9: no collective line of the project's prose", untied_names(result), [])


def test_gw1_16_k16_12_the_details_are_said_in_words_with_no_key() -> None:
    import human_text
    root = story("qa-int-gw16-k12-", integrations=[integration()], base=False, extra=[(1, "TS-10", declaring())])
    try:
        r = gate_preflight.Rehearsal(task_of(root), "A")
        ctx = r._precondition_ctx({})
        seen = [r._integration_state("jira-integration", ctx), r._integration_state("nowhere", ctx)]
        for config, name in (({"keys": []}, "jira-integration"), ({"applicability": "not_required"}, "jira-integration")):
            r.config["environment"]["integrations"] = [integration(**config)]
            seen.append(r._integration_state(name, ctx))
        details = [s[1] for s in seen]
        check_eq("K16.12: the four states", [s[0] for s in seen], ["unmet", "uncheckable", "uncheckable", "uncheckable"])
        for detail in details:
            check_eq(f"K16.12: {detail!r} breaks no rule of human-questions.md",
                     [p["rule"] for p in human_text.problems(detail, kind="report")], [])
            for word in ("JIRA_", "env", "key "):
                check_not_in(f"K16.12: {detail!r} has no {word!r}", word, detail)
    finally:
        cleanup(root)


def test_gw1_16_k16_14_twins_of_a_name_are_all_read() -> None:
    def twins(first: dict, second: dict, env_extra=()) -> tuple:
        root = story("qa-int-gw16-k14-", integrations=[first, second], base=False, extra=[(1, "TS-10", declaring())], env_extra=env_extra)
        try:
            r = gate_preflight.Rehearsal(task_of(root), "A")
            ctx = r._precondition_ctx({})
            asked = r._integration_keys(r.config["environment"], ctx["values"], [])[0]
            return r._integration_state("jira-integration", ctx), [a["declared_by"] for a in asked]
        finally:
            cleanup(root)
    first = integration(keys=["A_ONE"])
    second = integration(keys=["B_ONE"])
    state, declared_by = twins(dict(first, applicability="not_required"), second)
    check_eq("K16.14: the first twin is not needed here: the second decides (unmet), not a false uncheckable", state[0], "unmet")
    state, declared_by = twins(first, second, env_extra=["A_ONE=1"])
    check_eq("K16.14: the first is met, the second is not: not met, by the second's keys, and BOTH rows are declared",
             (state[0], state[2], declared_by), ("unmet", ["B_ONE"], [[TC1], [TC1]]))
    state, declared_by = twins(first, second, env_extra=["A_ONE=1", "B_ONE=1"])
    check_eq("K16.14: met only when every row is", state[0], "met")


def test_gw1_16_k16_15_a_case_number_two_areas_hold_is_not_taken_out() -> None:
    def ties(two_areas: bool) -> list:
        root = declared("qa-int-gw16-k15-", [integration(required_by=["api"])], others=[(2, "TS-12", [])])
        try:
            if two_areas:
                # the same case number in another area: `case_index` keys both `<area>/TC-NNN` and the bare id says neither
                tests = task_of(root) / "work" / "test-cases"
                source = next((tests / "workflow-visual-diff").glob("*_TC_002.md"))
                text = source.read_text(encoding="utf-8").replace("area: workflow-visual-diff", "area: other-area")
                (tests / "other-area").mkdir()
                (tests / "other-area" / source.name.replace("_TC_002", "_TC_001")).write_text(
                    text.replace("_TC_002", "_TC_001"), encoding="utf-8")
            T.use_project(root)
            r = gate_preflight.Rehearsal(task_of(root), "A")
            return r._integration_ties(r.config["environment"]["integrations"][0], [TC1])[0]
        finally:
            cleanup(root)
    check_eq("K16.15: control: one area holds TC-1, the declaring case is taken out", TC1 in ties(False), False)
    check_eq("K16.15: two areas hold TC-1: it stays in the INT cards", TC1 in ties(True), True)


def test_r0107_f2_a_declaration_never_removes_a_question_on_an_unread_reading() -> None:
    """F-2 (AR-28, FR-59): "no cases left" after taking out the declaring cases is a fact only when the cases were READ. The two
    unread reasons of `_integration_cases` keep the story question, as GW1-15's reader says None for them."""
    row = integration(applicability="required", required_by=["TS-10"])
    root = declared("qa-int-r0107-f2-", [row])
    try:
        plan = task_of(root) / "work" / "test-plan.json"
        control = creds(root, steps=BOTH)
        check_eq("F-2 control: the plan is read and TC-001 declares it: no story question", len(questions(control)), 0)
        plan.write_text("{not json", encoding="utf-8")
        result = creds(root, steps=BOTH)
        check_eq("F-2: an unreadable plan with a declaring case: the story question stays", len(questions(result)), 1)
    finally:
        cleanup(root)
    for why in gate_preflight.INTEGRATION_UNREAD_WHY:
        root = declared("qa-int-r0107-f2b-", [row])
        try:
            T.use_project(root)
            r = gate_preflight.Rehearsal(task_of(root), "A")
            r._integration_cases = lambda spec, _why=why: ([], False, _why)
            item = {"readable": True, "declared_by": [TC1], "spec": row}
            check_eq(f"F-2: {why!r}: untied, never declared", r._integration_decision(item)[0], "untied")
        finally:
            cleanup(root)


def test_r0107_f3_no_sentence_says_none_when_a_row_is_declared_or_the_declarations_were_not_read() -> None:
    """F-3 (FR-41, AR-23). (a) A `read_at` row a case declares: the note is the integrations' check, so "none of the N recorded
    has keys missing" is not said beside it, and a row whose keys are set does not claim a card. (b) With
    `skip_preconditions` the collective line does not say that no case declares what was not looked at."""
    def bare(**fields) -> dict:
        row = integration(read_at=["tests/ado/test_x.py:12"], **fields)
        row.pop("required_by")
        return row
    for label, extra in (("keys unset", []), ("keys set", [f"{k}=1" for k in JIRA])):
        root = declared("qa-int-r0107-f3a-", [bare()], env_extra=extra)
        try:
            result = creds(root, steps=BOTH)
        finally:
            cleanup(root)
        text = json.dumps(result["info"])
        check_not_in(f"F-3a: {label}: not 'none of the 1 recorded has keys missing'", "none of the", text)
        notes = [i for i in result["info"] if i.get("declared")]
        check_eq(f"F-3a: {label}: the declaration is said under the integrations' check", [i["check"] for i in notes], ["s5_integrations"])
        if extra:
            check_not_in("F-3a: keys set: no claim that a card asks", "asks for it itself", text)
    skip = lambda cfg: cfg["gate_rehearsal"].update(skip_preconditions=True)
    result, lines = declared_run("qa-int-r0107-f3b-", [integration()], config=skip)
    check_eq("F-3b: skip_preconditions: the collective line is there", len(collective(lines)), 1)
    check_not_in("F-3b: and does not claim that no case declares it", "None of this story's cases declares", collective(lines)[0])
    check_in("F-3b: it says what was not looked at", "did not look at", collective(lines)[0])
    # the control (the clause stays when the declarations were read) is K31.1


# --- GW1-31: gate A without a wall ------------------------------------------------------------------------------------------

REAL_NAMES = ["auth", "aws", "azure", "confluence", "github", "gitlab", "jira", "keycloak", "oauth", "other", "preview",
              "sandbox", "sonar", "xwiki"]        # the 14 of run 12586, gate A item 8 (the finding of 28.10.2026)


def services(names, **fields) -> list:
    """One row per name, keys of its own, each tied to the api profile by equality (cards) unless `fields` say otherwise."""
    return [integration(name=f"{n}-integration", keys=[f"{n.upper()}_KEY"], **fields) for n in names]


def mine(lines: list) -> list:
    """The grouped rows of integrations in the brief."""
    return [line for line in lines if line.startswith("- [your call] ") and ": the stand has no access set;" in line]


def test_gw1_31_k31_1_the_12586_wall_is_one_line() -> None:
    asked, rows, result, lines = shape(services(REAL_NAMES, required_by=["api: its own words"]), prefix="qa-int-gw31-k1-")
    check_eq("K31.1: 14 integrations by prose, none declared: no question, no card, no `[your call]` of an integration",
            (asked, rows, mine(lines)), (0, 0, []))
    line = collective(lines)
    check_eq("K31.1: ONE collective line", len(line), 1)
    check_eq("K31.1: six names and `and 8 more`", ([f"{n}-integration" in line[0] for n in REAL_NAMES[:6]],
                                                   f"{REAL_NAMES[6]}-integration" in line[0].split(". ")[0], "and 8 more" in line[0]),
            ([True] * 6, False, True))
    check_in("K31.1: it says what the factory knows (no case declares) and what it could not do", "None of this story's cases declares", line[0])
    check_in("K31.1: and that it could not match", "could not match", line[0])
    check_eq("K31.1: the brief opens with the gap", lines[0], "- S5 can start: yes, with the gap below.")


def group_story(count: int, prefix: str, **kw) -> tuple:
    """(the result, the brief lines, the text of 'After your approval') of `count` integrations tied to the api cases by equality."""
    root = story(prefix, integrations=services([f"svc{n}" for n in range(count)], required_by=["api"]), **kw)
    try:
        result = creds(root)
        return result, gate_preflight.brief_lines(for_brief(result)), "\n".join(gate_brief._after_approval({"rehearsal": for_brief(result)}))
    finally:
        cleanup(root)


def test_gw1_31_k31_2_one_integration_with_cases_is_one_line_and_cards_stay_one_per_gap() -> None:
    result, lines, text = group_story(1, "qa-int-gw31-k2-")
    found = questions(result)
    check_eq("K31.2: four cases tied by equality: four findings, four gaps with their own ids", (len(found), len({g["id"] for g in result["stand_gaps"]})), (4, 4))
    row = mine(lines)
    check_eq("K31.2: ONE line for the integration", len(row), 1)
    cases = [f["integration_case"] for f in found]
    check_eq("K31.2: it names every case the cards are about", [c in row[0] for c in cases], [True] * 4)
    check_in("K31.2: and says the cards below ask", "the cards below ask what to do", row[0])
    check_eq("K31.2: the findings are not merged: one door each", [len(f["waives"]) for f in found], [1] * 4)
    check_eq("K31.2: `_needs_words_line` names every id", [f"[{f['id']}]" in text for f in found], [True] * 4)


def test_gw1_31_k31_3_the_limit_counts_lines_and_an_integration_comes_before_the_rest() -> None:
    result, lines, text = group_story(7, "qa-int-gw31-k3-")
    check_eq("K31.3: seven integrations at limit 5: five lines and `+2 more`", (len(mine(lines)), "- (+2 more" in lines[-1]), (5, True))
    ahead = [{"id": f"x-{n}", "check": "s5_toolchain", "class": gate_preflight.FACTORY_DEFECT, "message": f"defect {n}", "fix": ""}
             for n in range(2)]
    shown = gate_preflight.brief_lines(dict(for_brief(result), findings=ahead + result["findings"]))
    check_eq("K31.3: other rows after them: the five shown are integrations, the rest are counted",
             (len(mine(shown)), "+4 more" in shown[-1], any("defect" in line for line in shown)), (5, True, False))


def test_gw1_31_k31_4_two_integrations_of_one_case_are_two_lines() -> None:
    root = story("qa-int-gw31-k4-", integrations=services(["a", "b"], required_by=["api"]), one_case=True)
    try:
        lines = gate_preflight.brief_lines(for_brief(creds(root)))
    finally:
        cleanup(root)
    row = mine(lines)
    check_eq("K31.4: one line per integration, each names the case", [(("a-integration" in r) or ("b-integration" in r), TC1 in r) for r in row],
             [(True, True)] * 2)
    check_eq("K31.4: not merged", len(row), 2)


def test_gw1_31_k31_5_k31_6_empty_and_over_the_limit_say_so() -> None:
    asked, rows, result, lines = shape([integration()], env_extra=[f"{k}=1" for k in JIRA])
    check_eq("K31.5: nothing asked: no row of an integration, no `gap below`", (mine(lines), "gap below" in "\n".join(lines)), ([], False))
    finding = lambda case: {"id": "s5_integrations-1", "check": "case_preconditions", "class": gate_preflight.PERSON_DECIDES,
                            "message": "m", "fix": "", "integration": "svc", "integration_case": case}
    grouped = gate_preflight._group_by_integration([finding(f"TC-{n}") for n in range(1, 8)])
    check_eq("K31.6: seven cases: ONE row, six named and `and 1 more`", (len(grouped), "TC-6 and 1 more" in grouped[0]["message"],
                                                                      "TC-7" in grouped[0]["message"]), (1, True, False))
    check_eq("K31.5: a finding with no case, or no integration, is left as it is (E17)",
             gate_preflight._group_by_integration([dict(finding(""), integration_case=""), {"id": "z", "check": "c", "class": "x"}]),
             [dict(finding(""), integration_case=""), {"id": "z", "check": "c", "class": "x"}])
    base = {"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {}}
    short = gate_preflight.brief_lines(dict(base, findings=[dict(finding(f"TC-{n}"), integration="n" * 60) for n in range(1, 7)]))
    check_eq("K31.6: a name of 60 characters and six cases fit the cut", (len(short[0]) - len("- [your call] ") <= gate_preflight.BRIEF_CUT,
                                                                       "…" in short[0], any("marks a line cut" in l for l in short)), (True, False, False))
    long = gate_preflight.brief_lines(dict(base, findings=[dict(finding(f"TC-{n}"), integration="n" * 120) for n in range(1, 7)]))
    check_eq("K31.6: a longer name is cut with `…` and the cut says so", ("…" in long[0], any("marks a line cut" in l for l in long)), (True, True))


def test_gw1_31_k31_7_the_unmatched_integrations_are_the_collective_lines_names() -> None:
    def answer(specs, prefix="qa-int-gw31-k7-", mutate=None, **kw) -> tuple:
        root = story(prefix, integrations=specs, **kw)
        real = gate_preflight.http_get
        gate_preflight.http_get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a socket was opened"))
        try:
            if mutate:
                mutate(root)
            T.use_project(root)
            result = creds(root)
            return gate_preflight.unmatched_integrations(task_of(root)), collective(gate_preflight.brief_lines(for_brief(result)))
        finally:
            gate_preflight.http_get = real
            cleanup(root)
    got, line = answer(services(["a", "b"], required_by=["words of the team"]))
    check_eq("K31.7: prose: the names, readable", got, {"names": ["a-integration", "b-integration"], "readable": True})
    check_eq("K31.7: the same names the collective line says", [n in line[0] for n in got["names"]], [True, True])
    got, line = answer([required()])
    check_eq("K31.7: `required` is a question, not a name", (got, line), ({"names": [], "readable": True}, []))
    got, line = answer([integration(required_by=["api"])])
    check_eq("K31.7: tied by equality: no name", got, {"names": [], "readable": True})
    got, line = answer([integration()], extra=[(1, "TS-1", '[{"id": "PC-1", "kind": "toggle"}]')])
    check_eq("K31.7: an unreadable case: not known, never an empty `none`", got, {"names": [], "readable": False})
    unreadable_plan = lambda root: (task_of(root) / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
    got, line = answer([integration()], mutate=unreadable_plan)
    check_eq("K31.7: an unreadable plan: not known", (got["names"], got["readable"]), ([], False))
    root = story("qa-int-gw31-k7-e18-")
    try:
        (task_of(root) / "pipeline.json").unlink()
        T.use_project(root)
        check_eq("K31.7 (E18): no pipeline.json: not known", gate_preflight.unmatched_integrations(task_of(root)), {"names": [], "readable": False})
        check_eq("K31.7: a path that is nothing at all: not known", gate_preflight.unmatched_integrations(root / "nowhere"),
                 {"names": [], "readable": False})
    finally:
        cleanup(root)
    # M31.4: a reading that RAISES inside the body (not the early return of `_has_story`) is not known, never `readable`
    root = story("qa-int-gw31-k7-raise-")
    real_keys = gate_preflight.Rehearsal._integration_keys
    gate_preflight.Rehearsal._integration_keys = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        T.use_project(root)
        check_eq("K31.7 (M31.4): a reading that raises: not known", gate_preflight.unmatched_integrations(task_of(root)),
                 {"names": [], "readable": False})
    finally:
        gate_preflight.Rehearsal._integration_keys = real_keys
        cleanup(root)


def test_gw1_31_k31_9_the_new_lines_break_no_rule_and_name_no_key() -> None:
    import human_text
    result, lines, text = group_story(1, "qa-int-gw31-k9-")
    asked, rows, plain, plain_lines = shape([integration()], prefix="qa-int-gw31-k9b-")
    for label, line in (("group", mine(lines)[0]), ("collective", collective(plain_lines)[0])):
        check_eq(f"K31.9: the {label} line breaks no rule of human-questions.md",
                 [p["rule"] for p in human_text.problems(line.lstrip("- "), kind="report")], [])
        for word in ("key", "env"):
            check_not_in(f"K31.9: the {label} line has no {word!r}", word, line.lower())


if __name__ == "__main__":
    test_r0_the_12586_shape_is_named_in_the_brief_whatever_stood_ahead_of_it()
    test_k1_the_brief_names_the_integration_its_keys_and_the_file_with_the_answers()
    test_k2_an_integration_tied_to_a_case_is_one_card_with_three_answers_and_never_change()
    test_k3_a_tie_is_equality_of_ids_never_a_reading_of_words()
    test_k4_the_login_question_keeps_login_keys_and_says_when_its_list_is_cut()
    test_k5_an_answer_is_read_by_the_rehearsal_gate_b_and_the_delivery_check()
    test_k6_k7_an_absent_record_is_silent_and_a_clean_one_is_declared()
    test_k8_present_keys_are_not_asked_and_never_called_verified()
    test_k11_gap_ids_are_per_integration_and_per_case_and_never_hold_a_separator()
    test_k12_the_order_of_the_two_steps_changes_nothing_a_person_reads()
    test_k13_the_limits_say_they_cut_and_never_hide_an_integration()
    test_the_new_texts_obey_the_owners_rule_and_the_old_door_still_works()
    test_hf8_11_a1_an_alternative_that_is_set_asks_nothing_and_the_nearest_is_named()
    test_hf8_11_a2_prose_alone_is_one_line_of_the_brief_not_a_question()
    test_hf8_11_a3_every_unknown_stays_a_question()
    test_hf8_11_a4_a_foreign_id_or_prose_with_a_profile_name_is_a_line()
    test_hf8_11_a5_an_integration_tied_by_equality_is_still_cards()
    test_hf8_11_a6_the_collective_line_names_six_and_counts_the_rest()
    test_hf8_11_a7_the_new_lines_break_no_rule_and_carry_no_value()
    test_hf8_11_a8_a_key_a_case_names_is_not_asked_inside_an_alternative_either()
    test_hf8_11_a9_a_row_with_named_sets_and_no_keys_does_not_vanish()
    test_hf8_11_a10_a_row_that_only_says_where_the_code_reads_it()
    test_oh3_8_the_texts_say_access_and_name_the_keys_only_in_the_first_move()
    test_gw1_16_k16_1_the_12586_shape_a_declared_integration_is_one_card_of_the_case()
    test_gw1_16_k16_2_k16_3_alternatives_are_the_routes_reader()
    test_gw1_16_k16_4_the_empty_outcomes_are_named()
    test_gw1_16_k16_5_a_name_is_equality_and_every_unknown_stays_a_question()
    test_gw1_16_k16_6_equality_and_a_declaration_make_one_card_per_case()
    test_gw1_16_k16_7_the_form_is_a_name()
    test_gw1_16_k16_8_the_role_never_writes_the_fix_of_this_check()
    test_gw1_16_k16_9_another_naming_is_a_card_not_a_crash()
    test_gw1_16_k16_12_the_details_are_said_in_words_with_no_key()
    test_gw1_16_k16_14_twins_of_a_name_are_all_read()
    test_gw1_16_k16_15_a_case_number_two_areas_hold_is_not_taken_out()
    test_r0107_f2_a_declaration_never_removes_a_question_on_an_unread_reading()
    test_r0107_f3_no_sentence_says_none_when_a_row_is_declared_or_the_declarations_were_not_read()
    test_gw1_31_k31_1_the_12586_wall_is_one_line()
    test_gw1_31_k31_2_one_integration_with_cases_is_one_line_and_cards_stay_one_per_gap()
    test_gw1_31_k31_3_the_limit_counts_lines_and_an_integration_comes_before_the_rest()
    test_gw1_31_k31_4_two_integrations_of_one_case_are_two_lines()
    test_gw1_31_k31_5_k31_6_empty_and_over_the_limit_say_so()
    test_gw1_31_k31_7_the_unmatched_integrations_are_the_collective_lines_names()
    test_gw1_31_k31_9_the_new_lines_break_no_rule_and_name_no_key()
    finish("gate rehearsal: integrations")
