#!/usr/bin/env python3
"""TR3-10 D (t-2283): the three questions of S6 about accounts and data - `walk_supply` (the way), `data_change` (what the factory may do with
records on the stand) and `walk_account` (the data of an account the project does not have) - their builders, their answer executors, their
`take_answer` branches and the `deferrable` clause. NO raise site is tested here: the raises are another worker's (TR3-10 D3b).

Every case builds a bare `Driver` (`Driver.__new__` + fakes, as test_driver_chain.py does); the one case that proves the write survives the
story's config give-back runs the real `project_decisions.py` in a throwaway project."""
import inspect
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402
import human_text  # noqa: E402

SHORT = [("stand_account:user", 2, 1)]       # a PART of a lane key, as `walk_pool.short_parts` gives it (not the bare role)
TASK = "QA-9"


class Stop(Exception):
    """What a fake `unread` / `held_question` raises or returns: the case reads what the seam was handed."""


class Rig:
    """A bare driver with a throwaway project: `py` records its calls (or runs the real script with `real=True`), `unread` records the
    conductor hand-over, `answer_row` / `owe_row` record instead of writing."""

    def __init__(self, real: bool = False, config: dict | None = None, scope=("TC-1", "TC-2")):
        self.root = temp_dir("qa-factory-walk-supply-")
        self.task_root = self.root / "qa-factory" / "artifacts" / TASK
        (self.task_root / "state").mkdir(parents=True)
        (self.root / "qa-factory" / "config.json").write_text(json.dumps(config if config is not None else {"manual": {}}, indent=2), encoding="utf-8")
        d = SR.Driver.__new__(SR.Driver)
        d.project, d.task, d.task_root, d.state_dir = self.root, TASK, self.task_root, self.task_root / "state"
        d.scripts, d.env, d.dry, d.state, d.boundary, d._price_notes = SCRIPTS, dict(os.environ), True, {}, "S6:walk:answer", None
        d._answer = {"text": "", "rel": None}
        self.calls, self.unreads, self.rows, self.refused = [], [], [], []
        self.exit_code, self.out = 0, ""
        d.file_defect = lambda ref, notes: None
        d.controller_state = lambda: {"scope": list(scope)}
        d.case_lines = lambda cases: [f"- Title of {case} ({case})" for case in cases]
        d.answer_row = lambda prefix, words, *, what, extra=(): self.rows.append((prefix, words))
        d.owe_row = lambda *a, **k: None
        d.refuse_case = lambda plan, case, reason, door, by, by_first=False: self.refused.append((case, by, reason, door)) or True
        d.unread = self.unread
        d.held_question = lambda lead, details=None: Stop(lead)
        if real:
            real_py = SR.Driver.py
            d.py = lambda script, *a, **k: (self.calls.append((script, a)), real_py(d, script, *a, **k))[1]
        else:
            d.py = lambda script, *a, **k: (self.calls.append((script, a)), (self.exit_code, self.out))[1]
        self.driver = d

    def unread(self, kind, stage, dispatch, text, words="", block="", *, doors=None, lead="", again=None):
        self.unreads.append({"kind": kind, "stage": stage, "dispatch": dispatch, "text": text, "words": words, "doors": tuple(doors or ())})
        return "continue"

    def answer(self, words: str) -> None:
        """Set the answer the way `take_answer` does (raw bytes in `_answer`, the words file written on first use)."""
        self.driver._answer = {"text": words, "rel": None}

    def values(self, index: int = -1) -> dict:
        args = self.calls[index][1]
        return json.loads(args[args.index("--field-values") + 1])

    def done(self) -> None:
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


def read_config(rig: Rig) -> dict:
    return json.loads((rig.root / "qa-factory" / "config.json").read_text(encoding="utf-8"))


def text_of(person, extra: str = "") -> str:
    return person.text + human_text.TAIL + extra


# --- step 1: the way question --------------------------------------------------------------------------------------------------

def question_holds_no_case_deferred():
    rig = Rig()
    try:
        person = rig.driver.walk_supply_person("DD-1", SHORT)
        check_eq("the way question holds no case and carries the flag", (person.kind, person.stage, person.holds, person.no_hold),
                 ("walk_supply", "S6", (), True))
        check_eq("L5: it carries no `offered` (the seam's questions alone do)", person.offered, ())
        check("it is deferrable: it waits and holds no case", rig.driver.deferrable(person) is True)
        check_eq("the row id and the short roles are kept for the executor", (rig.driver.state["walk_supply_asked"],
                 rig.driver.state["walk_supply_roles"]), ("DD-1", ["stand_account:user"]))
    finally:
        rig.done()


def gate_and_other_empty_holds_still_asked():
    rig = Rig()
    try:
        plain = rig.driver.walk_supply_person("DD-1", SHORT)
        del plain.no_hold
        check("D.1: a walk_supply Person WITHOUT the flag is asked at once", rig.driver.deferrable(plain) is False)
        for kind in ("gate_A", "gate_B", "repair_limit", "stand_login", "conductor", "halt"):
            other = SR.Person(kind, "text", "S6")
            other.no_hold = True
            check(f"D.1: a `{kind}` Person with the flag set by mistake is asked at once", rig.driver.deferrable(other) is False)
        gave_up = SR.Person("conductor", "text", "S6", code=SR.EXIT_GAVE_UP)
        gave_up.no_hold = True
        check("D.1: the conductor's stop (exit 4) with the flag is asked at once", rig.driver.deferrable(gave_up) is False)
        with_cases = SR.Person("stand_login", "text", "S6")
        with_cases.holds = ("TC-1",)
        check("a question that names cases still goes through the case test (scope has TC-2)", rig.driver.deferrable(with_cases) is True)
        data = rig.driver.walk_supply_person("DD-1", [])
        check("the flag passes with the scope unreadable too (it holds nothing to wait for)",
              (setattr(rig.driver, "controller_state", lambda: 1 / 0), rig.driver.deferrable(data))[1] is True)
    finally:
        rig.done()


def token_app_makes_them_writes_both_keys():
    rig = Rig(config={"manual": {"accounts_way": {"words": "old", "more_accounts": {"user": ["env:A/B"]}}, "data_way": {"words": "old", "pools": {"x": 1}}}})
    try:
        rig.driver.walk_supply_person("DD-4", [("stand_account:user", 2, 1), ("stand_account:admin", 1, 1)])
        rig.answer("The app makes them.")
        rig.driver._answer_walk_supply("The app makes them.", "question text", "S6", "")
        script, args = rig.calls[0]
        check_eq("the one command is project_decisions.py resolve on the row", (script, args[2], args[args.index("--id") + 1]),
                 ("project_decisions.py", "resolve", "DD-4"))
        check_eq("the resolution ref names the story and S6", args[args.index("--resolution-ref") + 1], f"{TASK} S6")
        words_file = Path(args[args.index("--words-file") + 1])
        check_eq("the words file is the answer's, as given", words_file.read_text(encoding="utf-8"), "The app makes them.")
        values = rig.values()
        check_eq("both pointers are written", sorted(values), ["/manual/accounts_way", "/manual/data_way"])
        accounts, data = values["/manual/accounts_way"], values["/manual/data_way"]
        check_eq("the roles of the short parts are recorded as the sign-up roles", accounts["self_sign_up"], {"roles": ["user", "admin"]})
        check_in("the words are the option's sentence and the answer, whole", 'The person answered: "The app makes them."', accounts["words"])
        check_in("the sentence names the sign-up page", "sign-up page", accounts["words"])
        check_eq("the data way gets the same words", data["words"], accounts["words"])
        check_eq("merge on write: the hand-added more_accounts survives", accounts["more_accounts"], {"user": ["env:A/B"]})
        check_eq("merge on write: the data pools survive", data["pools"], {"x": 1})
        check_eq("the answer is on record once", len(rig.rows), 1)
        check_eq("the registry row stays named for the story (never asked twice)", rig.driver.state["walk_supply_asked"], "DD-4")
    finally:
        rig.done()


def sign_up_roles_round_trip_through_obtain_roles_of():
    """D3b-2 item 2 (finding 1 of t-2293): the value `the app makes them` writes is read back by `walk_pool.obtain_roles_of` as the ROLE names
    - not the lane-key PART names the question stored. A part no existing reader reduces to a role is left out and named."""
    import contextlib
    import io
    import config_contract as CC
    import walk_pool as WP
    stand = {"name": "local", "credentials_by_role": {"user": ".env: QA_U / QA_P - a user", "admin": ".env: AD_U / AD_P - the admin"}}
    rig = Rig(config={"manual": {}, "environments": [stand]})
    try:
        parts = [("stand_account:user", 2, 1), ("env:AD_U", 1, 1), ("stand_account:default", 1, 1), ("custom:thing", 1, 1), ("env:NOPE_U", 1, 1),
                 ("stand_account:user", 3, 1)]
        rig.driver.walk_supply_person("DD-4", parts)
        rig.answer("the app makes them")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rig.driver._answer_walk_supply("the app makes them", "q", "S6", "")
        written = rig.values()["/manual/accounts_way"]
        check_eq("the executor writes ROLE names, in order, once each: the role after `stand_account:`, `default`, the role of an `env:` login key",
                 written["self_sign_up"]["roles"], ["user", "admin", "default"])
        supply, notes = CC.walk_supply({"manual": {"accounts_way": written}})
        roles, why = WP.obtain_roles_of(supply, stand["credentials_by_role"])
        check_eq("ROUND TRIP: `obtain_roles_of` returns every role the executor wrote", (roles, why), (["user", "admin", "default"], []))
        check_eq("the reader has no note on the value", notes, [])
        check_in("a part no reader reduces is NAMED in the console, never guessed", "custom:thing", out.getvalue())
        check_in("and so is the `env:` key the stand does not know", "env:NOPE_U", out.getvalue())
        check_not_in("the parts that were read are not named as left out", "stand_account:user", out.getvalue().split("not on the list of roles")[-1])
        before = WP.obtain_roles_of({"accounts": {"self_sign_up_roles": ["stand_account:user"]}}, stand["credentials_by_role"])
        check_eq("control: the PART spelling the question stored is NOT a role `obtain_roles_of` reads (the defect this item closed)", before[0], [])
    finally:
        rig.done()
    none = Rig(config={"manual": {}, "environments": [stand]})
    try:
        none.driver.walk_supply_person("DD-4", [("custom:thing", 1, 1)])
        none.answer("the app makes them")
        with contextlib.redirect_stdout(io.StringIO()):
            none.driver._answer_walk_supply("the app makes them", "q", "S6", "")
        check_eq("no part reducible: an empty role list is written (the reader reads it as nothing mapped, no guess)",
                 none.values()["/manual/accounts_way"]["self_sign_up"], {"roles": []})
    finally:
        none.done()


def token_one_at_a_time():
    rig = Rig()
    try:
        rig.driver.walk_supply_person("DD-2", SHORT)
        rig.answer("one at a time")
        rig.driver._answer_walk_supply("one at a time", "q", "S6", "")
        values = rig.values()
        check_eq("only the two `words` keys are written", values["/manual/accounts_way"].keys() | values["/manual/data_way"].keys(), {"words"})
        check_in("the words carry the sentence", "use only the accounts already recorded", values["/manual/accounts_way"]["words"])
        check_not_in("no sign-up is recorded", "self_sign_up", json.dumps(values))
    finally:
        rig.done()


def token_i_will_add(capsys=None):
    import contextlib
    import io
    rig = Rig()
    try:
        rig.driver.walk_supply_person("DD-2", SHORT)
        rig.answer("I will add accounts")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rig.driver._answer_walk_supply("I will add accounts", "q", "S6", "")
        values = rig.values()
        check_eq("the same two `words` keys as `one at a time`", values["/manual/accounts_way"].keys() | values["/manual/data_way"].keys(), {"words"})
        check_in("the words carry its own sentence", "adds more accounts", values["/manual/accounts_way"]["words"])
        check_in("one console line says the checks run in turn until the accounts are recorded",
                 "S6: you said you will add accounts; until they are in the project's settings the checks that share an account run one after another",
                 buffer.getvalue())
    finally:
        rig.done()


def free_words_go_to_conductor_once():
    rig = Rig()
    try:
        rig.driver.walk_supply_person("DD-7", SHORT)
        words = "we have two more test users, keys QA_USER2_LOGIN and QA_USER2_PASS"
        rig.answer(words)
        rig.driver._answer_walk_supply(words, "the question text", "S6", "")
        check_eq("one hand-over, no recording command", (len(rig.unreads), rig.calls), (1, []))
        got = rig.unreads[0]
        check_eq("the kind, the stage and the words whole", (got["kind"], got["stage"], got["words"]), ("walk_supply", "S6", words))
        check_eq("the three tokens are the doors", got["doors"], ("the app makes them", "one at a time", "I will add accounts"))
        check_in("the conductor is told the registry row", "DD-7", got["text"])
        check_in("and gets the question's own text", "the question text", got["text"])
        check_eq("nothing was recorded as the answer", rig.rows, [])
    finally:
        rig.done()


def test_words_kept_whole():
    rig = Rig()
    try:
        rig.driver.walk_supply_person("DD-7", SHORT)
        words = "line one\r\nline \"two\" with a password hunter2 in it\r\n\r\n  line three  \n"
        rig.answer(words)
        rig.driver._answer_walk_supply(words, "q", "S6", "")
        check_eq("the conductor gets the words byte for byte", rig.unreads[0]["words"], words)
        check_eq("and the words file holds them whole too", (rig.task_root / rig.driver.answer_file()).read_bytes().decode("utf-8"), words)
        check_eq("code recorded nothing of them", rig.calls, [])
    finally:
        rig.done()


def resolve_failure_holds_question():
    rig = Rig()
    try:
        rig.driver.walk_supply_person("DD-3", SHORT)
        rig.driver.state["asked"] = {"kind": "walk_supply", "stage": "S6", "dispatch": ""}
        rig.exit_code, rig.out = 2, "unknown decision DD-3"
        rig.answer("one at a time")
        err = None
        try:
            rig.driver._answer_walk_supply("one at a time", "q", "S6", "")
        except SR.Refusal as exc:
            err = exc
        check("a failed resolve is a Refusal", err is not None)
        check_in("it names the row and the exit", "DD-3", err.text if err else "")
        check_in("it names the exit", "exit 2", err.text if err else "")
        check_eq("the question stays asked (nothing cleared)", rig.driver.state["asked"]["kind"], "walk_supply")
        check_eq("nothing was recorded as the answer", rig.rows, [])
        check_eq("the registry row of the story is still named", rig.driver.state["walk_supply_asked"], "DD-3")
    finally:
        rig.done()


def real_resolve(token: str, config: dict, words: str | None = None):
    """Run the executor over the REAL project_decisions.py in a throwaway project; `(rig, receipt)`."""
    import project_decisions as PD
    rig = Rig(real=True, config=config)
    row = PD.upsert(rig.root, field_refs=["/manual/accounts_way", "/manual/data_way"], essence="how this project gets more test accounts",
                    asked="the question text", scope="project", owner="user")
    rig.driver.walk_supply_person(row["id"], SHORT)
    rig.answer(words or token)
    rig.driver._answer_walk_supply(words or token, "q", "S6", "")
    receipt = rig.root / "qa-factory" / "state" / "decision-transactions" / f"{row['id']}.json"
    return rig, row["id"], json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}


def answer_survives_give_back():
    import config_contract as C
    rig, row, receipt = real_resolve("the app makes them", {"manual": {"accounts_way": {"words": "not known"}}})
    try:
        check_eq("the receipt is complete", receipt.get("status"), "complete")
        check("it carries the config as it was before and the time of the write", isinstance(receipt.get("before"), dict) and bool(receipt.get("recorded_at")))
        writes = C.recorded_writes(rig.root, "2000-01-01T00:00:00+00:00")
        check_eq("`recorded_writes` names the answer, so the story's revert keeps it", [w["ref"] for w in writes], [row])
        config = read_config(rig)
        check_eq("the config holds the answer's sign-up roles", config["manual"]["accounts_way"]["self_sign_up"], {"roles": ["user"]})
        check_in("and the words", "The person answered", config["manual"]["data_way"]["words"])
    finally:
        rig.done()


def answer_keeps_existing_more_accounts():
    rig, _row, _receipt = real_resolve("one at a time", {"manual": {"accounts_way": {"words": "not known", "more_accounts": {"user": ["env:A/B"]},
                                                         "limit_by_role": {"user": 2}}, "data_way": {"pools": {"order": {"existing": ["1"]}}}}})
    try:
        config = read_config(rig)["manual"]
        check_eq("the hand-added more_accounts is still in the file", config["accounts_way"]["more_accounts"], {"user": ["env:A/B"]})
        check_eq("so is the limit", config["accounts_way"]["limit_by_role"], {"user": 2})
        check_eq("and the data pools", config["data_way"]["pools"], {"order": {"existing": ["1"]}})
        check_in("while the words are the answer's", "The person answered", config["accounts_way"]["words"])
    finally:
        rig.done()


def test_never_reads_words():
    """AR-2: the three tokens are the closed set; words that merely contain or look like one are the conductor's."""
    rig = Rig()
    try:
        rig.driver.walk_supply_person("DD-1", SHORT)
        for words in ("the app makes them, but only for the admin", "one at a time please", "yes", "no", "1", "a", "the app makes them one at a time",
                      "I won't add accounts", "ONE AT A TIME and then the app makes them"):
            rig.answer(words)
            rig.driver._answer_walk_supply(words, "q", "S6", "")
        check_eq("every one of them went to the conductor, whole, once each", [u["words"] for u in rig.unreads], [
            "the app makes them, but only for the admin", "one at a time please", "yes", "no", "1", "a", "the app makes them one at a time",
            "I won't add accounts", "ONE AT A TIME and then the app makes them"])
        check_eq("and no command ran", rig.calls, [])
        rig.answer("   ")
        rig.driver._answer_walk_supply("   ", "q", "S6", "")
        check_eq("empty words go to the conductor once, whole, as well", (len(rig.unreads), rig.unreads[-1]["words"]), (10, "   "))
        rig.answer("  `One At A Time`.  ")
        rig.driver._answer_walk_supply("  `One At A Time`.  ", "q", "S6", "")
        check_eq("only the normalisation of a token (case, quotes, one full stop) is read as the token", len(rig.calls), 1)
        source = inspect.getsource(SR.Driver._answer_walk_supply)
        check("the executor holds no regular expression and no `in words` search", "re." not in source and " in words" not in source)
    finally:
        rig.done()


def walk_supply_text_passes_and_names_no_key_path():
    rig = Rig()
    try:
        for short in (SHORT, [("default", 1, 1), ("admin", 3, 2)], []):
            person = rig.driver.walk_supply_person("DD-1", short)
            check_eq(f"the way question text obeys human-questions.md ({len(short)} part(s))",
                     human_text.problems(text_of(person), offered=list(person.priced)), [])
            check_eq("it prices the three tokens", sorted(person.priced), sorted(["the app makes them", "one at a time", "I will add accounts"]))
            for needle in ("/manual", "accounts_way", "data_way", "config.json", "project_decisions", "DD-1", "walk_supply", "S6-"):
                check_not_in(f"no `{needle}` in what the person reads", needle, person.text)
            check("no option is marked recommended", "recommended" not in person.text.lower())
        check_in("the stand's main account is named in words", "the stand's main account", rig.driver.walk_supply_text([("default", 1, 1)]))
        check_in("D.4: it says this story's checks already ran in turn", "already ran, only slower", rig.driver.walk_supply_text(SHORT))
    finally:
        rig.done()


def take_answer_branches_before_generic_offered():
    source = inspect.getsource(SR.Driver.take_answer)
    generic = source.index('elif asked.get("offered") and not seam_gate_words:')
    for kind in KINDS_WITH_BRANCH:
        at = source.find(f'elif kind == "{kind}":')
        check(f"item 14: the `{kind}` branch exists and sits before the generic `offered` branch", 0 < at < generic)


KINDS_WITH_BRANCH = ["walk_supply", "data_change"]


# --- step 2: the data-change question ------------------------------------------------------------------------------------------

DC_TOKENS = ["only use what exists", "may create, never delete", "may create and delete"]


def data_change_deferrable_holds_no_case():
    rig = Rig()
    try:
        person = rig.driver.data_change_person("DD-5", ["order"])
        check_eq("the data question holds no case and carries the flag", (person.kind, person.stage, person.holds, person.no_hold),
                 ("data_change", "S6", (), True))
        check_eq("it carries no `offered`", person.offered, ())
        check("it is deferrable", rig.driver.deferrable(person) is True)
        check_eq("the row id is kept for the executor", rig.driver.state["data_change_asked"], "DD-5")
        plain = rig.driver.data_change_person("DD-5", [])
        del plain.no_hold
        check("D.1: without the flag it is asked at once", rig.driver.deferrable(plain) is False)
    finally:
        rig.done()


def data_change_tokens_match_the_reader():
    import config_contract as C
    check_eq("the tokens are the sentences `config_contract` reads back, in option order", list(SR.Driver.DATA_CHANGE_SAYS), DC_TOKENS)
    check_eq("and the reader's set", set(C.DATA_MAY_OPTIONS), set(DC_TOKENS))


def data_change_token_writes_the_value():
    for token in DC_TOKENS:
        rig = Rig()
        try:
            rig.driver.data_change_person("DD-6", ["order"])
            said = f"  `{token.title()}`. "
            rig.answer(said)
            rig.driver._answer_data_change(said, "q", "S6", "")
            script, args = rig.calls[0]
            check_eq(f"`{token}`: one resolve on the row", (script, args[2], args[args.index("--id") + 1]), ("project_decisions.py", "resolve", "DD-6"))
            check_eq(f"`{token}`: the one pointer gets the sentence, a plain string, no merge", rig.values(), {"/manual/data_way/may": token})
            check_eq("the resolution ref names the story and S6", args[args.index("--resolution-ref") + 1], f"{TASK} S6")
            check_eq("the answer is on record once", len(rig.rows), 1)
            check_eq("nothing went to the conductor", rig.unreads, [])
        finally:
            rig.done()


def data_change_free_words_to_conductor_once():
    rig = Rig()
    try:
        rig.driver.data_change_person("DD-7", ["order"])
        for words in ("yes, create them but delete only the orders", "", "   ", "my password is hunter2\r\nand more\r\n\r\n", "may create"):
            rig.answer(words)
            rig.driver._answer_data_change(words, "the question text", "S6", "")
        check_eq("one hand-over per answer, whole, no command", ([u["words"] for u in rig.unreads], rig.calls), (
            ["yes, create them but delete only the orders", "", "   ", "my password is hunter2\r\nand more\r\n\r\n", "may create"], []))
        got = rig.unreads[0]
        check_eq("kind, stage and the three doors", (got["kind"], got["stage"], got["doors"]), ("data_change", "S6", tuple(DC_TOKENS)))
        check_in("the conductor is told the registry row", "DD-7", got["text"])
        check_in("and the question's own text", "the question text", got["text"])
        check_eq("nothing recorded as an answer", rig.rows, [])
        source = inspect.getsource(SR.Driver._answer_data_change)
        check("the executor holds no regular expression and no `in words` search", "re." not in source and " in words" not in source)
    finally:
        rig.done()


def data_change_resolve_failure_holds_question():
    rig = Rig()
    try:
        rig.driver.data_change_person("DD-8", ["order"])
        rig.driver.state["asked"] = {"kind": "data_change", "stage": "S6", "dispatch": ""}
        rig.exit_code, rig.out = 3, "unknown decision DD-8"
        rig.answer("may create and delete")
        err = None
        try:
            rig.driver._answer_data_change("may create and delete", "q", "S6", "")
        except SR.Refusal as exc:
            err = exc
        check("a failed resolve is a Refusal", err is not None)
        check_in("it names the row", "DD-8", err.text if err else "")
        check_in("and the exit", "exit 3", err.text if err else "")
        check_eq("the question stays asked", rig.driver.state["asked"]["kind"], "data_change")
        check_eq("nothing recorded as an answer", rig.rows, [])
    finally:
        rig.done()


def data_change_missing_state_key_is_a_refusal():
    rig = Rig()
    try:
        err = None
        try:
            rig.driver._answer_data_change("may create and delete", "q", "S6", "")
        except SR.Refusal as exc:
            err = exc
        check("no `data_change_asked`: a Refusal, not a crash", err is not None)
        check_in("it says what is missing", "data_change_asked", err.text if err else "")
        check_eq("no command ran, nothing went to the conductor", (rig.calls, rig.unreads), ([], []))
    finally:
        rig.done()


def data_change_text_passes_and_names_no_key_path():
    rig = Rig()
    try:
        for kinds in (["order"], ["order", "user", "invoice"], []):
            person = rig.driver.data_change_person("DD-1", kinds)
            check_eq(f"the data question obeys human-questions.md ({len(kinds)} kind(s))",
                     human_text.problems(text_of(person), offered=list(person.priced)), [])
            check_eq("it prices the three tokens", sorted(person.priced), sorted(DC_TOKENS))
            for needle in ("/manual", "accounts_way", "data_way", "config.json", "project_decisions", "DD-1", "data_change", "S6-", "safe_to_break"):
                check_not_in(f"no `{needle}` in what the person reads", needle, person.text)
            check("no option is marked recommended", "recommended" not in person.text.lower())
        text = rig.driver.data_change_text(["order", "user"])
        check_in("the kinds are named in the story's words", "an order and a user", text)
        check_in("a kind with a leading consonant", "a customer", rig.driver.data_change_text(["customer"]))
        check_in("empty kinds: a record", "change a record that", rig.driver.data_change_text([]))
        check_in("the stand dependence", "applies to the stand your settings name", text)
        check_in("D.4: checks already ran one after another", "those checks ran one after another", text)
        check_in("D.4: nothing redone", "already ran, only slower", text)
        check_not_in("a stand that may be changed gets no warning", "do not mark this stand", text)
    finally:
        rig.done()


def data_change_stand_not_safe_to_break_says_so():
    rig = Rig()
    try:
        person = rig.driver.data_change_person("DD-1", ["order"], may_change=False)
        check_in("the text says in human words that the stand is not marked", "Your settings do not mark this stand as one that may be changed", person.text)
        check_in("and that the default stays", "only uses what exists", person.text)
        check_eq("still passes the text rules", human_text.problems(text_of(person), offered=list(person.priced)), [])
        check_not_in("the mark is not named as a key", "safe_to_break", person.text)
        check_eq("the answer is still the person's: all three options are offered", sorted(person.priced), sorted(DC_TOKENS))
    finally:
        rig.done()


def data_change_real_resolve_writes_the_pointer():
    import project_decisions as PD
    rig = Rig(real=True, config={"manual": {"data_way": {"words": "old", "pools": {"x": 1}}}})
    try:
        row = PD.upsert(rig.root, field_refs=["/manual/data_way/may"], essence="may the factory make records", asked="q", scope="project", owner="user")
        rig.driver.data_change_person(row["id"], ["order"])
        rig.answer("may create, never delete")
        rig.driver._answer_data_change("may create, never delete", "q", "S6", "")
        data = read_config(rig)["manual"]["data_way"]
        check_eq("the may value is the sentence", data.get("may"), "may create, never delete")
        check_eq("the siblings survive", (data.get("words"), data.get("pools")), ("old", {"x": 1}))
    finally:
        rig.done()


# --- TR3-10 D3b (t-2293): the raise site inside `walk_assign_step` (spec items 9 and 12; D.2, D.3, D.5, D.11) -----------------------------------
# The lanes' own scaffolding (`make`, `project`, `enter`, the world with its controller) is test_walk_lanes_parallel's; `py` is the one thing added.

import contextlib  # noqa: E402
import io  # noqa: E402
from unittest import mock  # noqa: E402

import test_walk_lanes_parallel as LP  # noqa: E402

INVOICE = [{"kind": "Invoice", "exclusive": True, "changes": "sends one"}]
ROW = json.dumps({"id": "DD-7", "status": "open"})


def wire(d, root, real: bool = False, code: int = 0, out: str = ROW):
    """The bare lanes driver gets what the raise needs: a project, `py` (recorded; real with `real=True`), `scripts`, `env`."""
    d.project, d.scripts, d.env, d._price_notes, d.calls = root, SCRIPTS, dict(os.environ), None, []
    if real:
        real_py = SR.Driver.py
        d.py = lambda script, *a, **k: (d.calls.append((script, a)), real_py(d, script, *a, **k))[1]
    else:
        d.py = lambda script, *a, **k: (d.calls.append((script, a)), (code, out))[1]
    return d


def short_rig(accounts=None, data=None, **wiring):
    """Two lanes of ONE account with a pool of one: a short part (`user`), no data need."""
    cases = ["TC-1", "TC-2"]
    d = LP.make(cases, {c: LP.USER for c in cases}, config=LP.supply_config(accounts=accounts, data=data))
    task = LP.project(d)
    return wire(d, task.parent.parent.parent, **wiring), cases, [LP.pools_patch({LP.USER: (["user"], "user")})]


def data_rig(accounts=None, data=None, safe=True, **wiring):
    """Two lanes of two accounts; lane 1 needs an exclusive kind (`Invoice`) the project has no pool for: a data shortage, no short part."""
    cases = ["TC-1", "TC-2"]
    d = LP.make(cases, {"TC-1": LP.USER, "TC-2": LP.ADMIN}, config=LP.supply_config(accounts=accounts, data=data))
    task = LP.project(d, safe=safe)
    LP.put_request(d, "TC-1", walk_data=INVOICE)
    return wire(d, task.parent.parent.parent, **wiring), cases, []


def step(d, patches=()):
    """`walk_assign_step` over the two single-case lanes: (the Person it raised or None, its console)."""
    out, got = io.StringIO(), None
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        stack.enter_context(contextlib.redirect_stdout(out))
        try:
            d.walk_assign_step(LP.plan_of(["TC-1"], ["TC-2"]))
        except SR.Person as person:
            got = person
    return got, out.getvalue()


def add_args(call) -> dict:
    args = list(call[1])
    return {"refs": [args[i + 1] for i, a in enumerate(args) if a == "--field-ref"], "owner": args[args.index("--owner") + 1],
            "scope": args[args.index("--scope") + 1], "essence": args[args.index("--essence") + 1], "cmd": args[2]}


def short_parts_raise_once_per_story():
    d, _cases, patches = short_rig()
    person, _out = step(d, patches)
    check("a short part with the way unknown raises the question", person is not None and person.kind == "walk_supply", repr(person))
    check_eq("it is the set-aside kind: stage S6, no case held, no_hold, no `offered`", (person.stage, person.holds, person.no_hold, person.offered),
             ("S6", (), True, ()))
    check_eq("ONE `add` through project_decisions.py", [c[0] for c in d.calls], ["project_decisions.py"])
    one = add_args(d.calls[0])
    check_eq("the add names both pointers, scope project, owner user", (one["cmd"], one["refs"], one["scope"], one["owner"]),
             ("add", ["/manual/accounts_way", "/manual/data_way"], "project", "user"))
    check_eq("the row id and the short parts are in the state (the part's own spelling is `walk_supply_person`'s, see the report)",
             (d.state["walk_supply_asked"], len(d.state["walk_supply_roles"])), ("DD-7", 1))
    check_in("the question text is the way question's", "How should walkers get their own accounts and records", person.text)
    second, _out = step(d, patches)
    check("the same story, the state kept: no second raise and no second add", second is None and len(d.calls) == 1, repr((second, d.calls)))
    d.state.pop("walk_supply_asked")
    d.deferred_items = lambda: [{"kind": "walk_supply", "n": 1}]
    third, _out = step(d, patches)
    check("a deferred item of the kind: no raise (D.2, the second entry)", third is None and len(d.calls) == 1, repr((third, d.calls)))


def data_shortage_raises_the_one_question():
    d, _cases, patches = data_rig()
    person, _out = step(d, patches)
    check("an exclusive kind with no pool and no words: the way question", person is not None and person.kind == "walk_supply", repr(person))
    check_eq("it asks about the data pointer too, once", ([c[0] for c in d.calls], add_args(d.calls[0])["refs"]),
             (["project_decisions.py"], ["/manual/accounts_way", "/manual/data_way"]))
    check_in("the data shortage text speaks of records", "work on the same records", person.text)
    check_eq("ONE question per entry: no data-change row was opened beside it", d.state.get("data_change_asked"), None)
    quiet, _cases, patches = short_rig(accounts={"words": "x"}, data={"words": "y"})
    nothing, _out = step(quiet, patches)
    check_eq("empty short and no alone kind: no question, no call", (nothing, quiet.calls), (None, []))


def known_way_never_asks():
    for label, rig in (("short, both halves known", short_rig(accounts={"words": "one at a time"}, data={"words": "one at a time"})),
                       ("data shortage, both halves known", data_rig(accounts={"words": "one at a time"}, data={"words": "one at a time"}))):
        d, _cases, patches = rig
        person, _out = step(d, patches)
        check_eq(f"{label}: never asked, no registry call", (person, d.calls), (None, []))
    d, _cases, patches = short_rig()
    person, _out = step(d, patches)
    check("control: the same rig with the way unknown does ask", person is not None and person.kind == "walk_supply", repr(person))


def open_row_reused_no_second_row():
    import project_decisions as PD
    d, _cases, patches = short_rig(real=True)
    first, _out = step(d, patches)
    for key in ("walk_supply_asked", "walk_supply_roles", "noted"):
        d.state.pop(key, None)              # a new story: nothing kept in the state, the registry row is still open
    second, _out = step(d, patches)
    rows = [r for r in PD.parse_rows((d.project / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8")) if r.get("id", "").startswith("DD-")]
    check("both stories raised the question", first is not None and second is not None, repr((first, second)))
    check_eq("the open row is reused: ONE row, the same id", (len(rows), d.state["walk_supply_asked"]), (1, rows[0]["id"]))
    check_eq("the row names the two pointers", sorted(rows[0]["field_refs"].split(",")), ["/manual/accounts_way", "/manual/data_way"])


def raise_before_any_dispatch():
    d, cases, patches = short_rig()
    err, _said = LP.enter(d, cases, patches)
    check("the entry stops at the question: a `walk_supply` Person", isinstance(err, SR.Person) and err.kind == "walk_supply", repr(err))
    check_eq("D.2: no dispatch of this entry is registered and the question holds no case", (LP.registered(d), err.holds), ([], ()))
    check_eq("the lanes are not touched either", d.world.done_cases(), set())
    d.deferred_items = lambda: [{"kind": "walk_supply", "n": 1}]
    err, _said = LP.enter(d, cases, patches)
    check_eq("the second entry (the question set aside) runs the lanes", (err, d.world.done_cases()), (None, set(cases)))
    check("and registers them", len(LP.registered(d)) == 2, repr(LP.registered(d)))


def add_failure_lanes_go_on():
    for label, rig in (("exit 1", short_rig(code=1, out="boom")), ("no JSON", short_rig(code=0, out="registered")),
                       ("JSON with no id", short_rig(code=0, out="{}"))):
        d, cases, patches = rig
        err, said = LP.enter(d, cases, patches)
        check_eq(f"D.11 {label}: no question, the lanes go on in turn", (err, d.world.done_cases(), len(LP.registered(d))), (None, set(cases), 2))
        check_eq(f"{label}: ONE console note", said.count("could not be written to the project's decision registry"), 1)
        check_not_in(f"{label}: the note names no script of ours", "project_decisions", said)
        check_eq(f"{label}: nothing is kept in the state, so the next story tries again", d.state.get("walk_supply_asked"), None)
    d, _cases, patches = data_rig(code=1, out="boom")
    d.state["walk_supply_asked"] = "DD-1"
    person, _out = step(d, patches)
    check_eq("a failed data_change add: no question either", (person, d.state.get("data_change_asked")), (None, None))
    crash = short_rig()[0]
    crash.walk_supply_text = lambda short: 1 / 0
    person, out = step(crash, [LP.pools_patch({LP.USER: (["user"], "user")})])
    check("any other crash of the raise block is a note and no stop", person is None and "was not raised (ZeroDivisionError" in out, out)


def not_changeable_stand_records_no_obtain():
    # The lanes' side of D.8 (`assign_lanes` gives no obtain on a stand not marked safe_to_break) is not pinned in test_walk_lanes_parallel.py
    # (its obtain cases run on a stand that may be changed); pinned here: the recorded `the app makes them` answer on such a stand makes no
    # obtain handle, says why, and the answered way is not asked again.
    cases = ["TC-1", "TC-2"]
    d = LP.make(cases, {c: LP.USER for c in cases}, config=LP.supply_config(accounts=LP.OBTAIN_WAY, data={"words": "x"}))
    task = LP.project(d, safe=False)
    wire(d, task.parent.parent.parent)
    person, out = step(d, [LP.pools_patch({LP.USER: (["user"], "user")})])
    check_eq("the answered way is never asked again", (person, d.calls), (None, []))
    check_eq("no lane got an obtain handle", [h for parts in d.state["walk_assign"].values() for h in parts.values()], ["user", "user"])
    check_in("one line names why", "do not mark this stand as one that may be changed", out)


def data_change_asked_on_need_only():
    d, _cases, patches = data_rig()
    d.state["walk_supply_asked"] = "DD-1"           # the way question was asked earlier in this story: the data question may follow
    person, _out = step(d, patches)
    check("an exclusive kind with no free record, may unknown, the way asked: the data question", person is not None and person.kind == "data_change",
          repr(person))
    one = add_args(d.calls[0])
    check_eq("the add names the may pointer only, owner user", (one["refs"], one["owner"], one["scope"]), (["/manual/data_way/may"], "user", "project"))
    check_eq("the row is kept", d.state["data_change_asked"], "DD-7")
    check_eq("it holds no case and is set aside like the way question", (person.holds, person.no_hold, person.stage), ((), True, "S6"))
    check_in("it names the kind in the story's words", "an Invoice", person.text)
    check_not_in("a stand that may be changed gets no warning", "do not mark this stand", person.text)
    no_need, _cases, patches = short_rig()
    no_need.state["walk_supply_asked"] = "DD-1"
    other, _out = step(no_need, patches)
    check_eq("a story with a short part but no data need never asks it", (other, no_need.calls), (None, []))
    unsafe, _cases, patches = data_rig(safe=False)
    unsafe.state["walk_supply_asked"] = "DD-1"
    warned, _out = step(unsafe, patches)
    check_in("a stand not marked safe_to_break: the text says so", "do not mark this stand as one that may be changed", warned.text)
    for kinds in ([], [" "]):
        d.state.pop("data_change_asked", None)
        calls = len(d.calls)
        check_eq(f"kinds {kinds!r}: not raised", (d.walk_supply_raise({"supply": {"accounts": {}, "data": {"known": True}}, "short": [],
                                                                      "alone_kinds": kinds}), len(d.calls)), (None, calls))


def data_change_answered_never_reasked():
    d, _cases, patches = data_rig(data={"may": "may create, never delete"})
    d.state["walk_supply_asked"] = "DD-1"
    person, _out = step(d, patches)
    check_eq("`may_known`: never asked, no registry call", (person, d.calls), (None, []))
    d, _cases, patches = data_rig()
    d.state["walk_supply_asked"] = "DD-1"
    person, _out = step(d, patches)
    check("control: the same rig with no answer asks", person is not None and person.kind == "data_change", repr(person))
    again, _out = step(d, patches)
    check_eq("once per story: `data_change_asked` kept, no second raise or add", (again, len(d.calls)), (None, 1))
    d.state.pop("data_change_asked")
    d.deferred_items = lambda: [{"kind": "data_change", "n": 2}]
    third, _out = step(d, patches)
    check_eq("a deferred `data_change` item: no raise", (third, len(d.calls)), (None, 1))


def data_change_default_before_answer_existing_only():
    d, _cases, patches = data_rig()
    d.state["walk_supply_asked"] = "DD-1"
    person, _out = step(d, patches)
    check("the question is raised", person is not None and person.kind == "data_change", repr(person))
    check_eq("before the answer the default is `existing only`: no `create:` instance was assigned",
             "create" in json.dumps(d.state.get("walk_entities") or {}), False)
    check_eq("the lane that needs the kind with no free record is alone, as under `only use what exists`", d.state["walk_alone"], ["TC-1"])


def data_change_open_row_reused():
    import project_decisions as PD
    d, _cases, patches = data_rig(real=True)
    d.state["walk_supply_asked"] = "DD-1"
    first, _out = step(d, patches)
    for key in ("data_change_asked", "noted"):
        d.state.pop(key, None)
    second, _out = step(d, patches)
    rows = [r for r in PD.parse_rows((d.project / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8")) if r.get("id", "").startswith("DD-")]
    check("both stories raised the data question", first is not None and second is not None, repr((first, second)))
    check_eq("ONE row for the may pointer, the same id both times", (len(rows), rows[0]["field_refs"], d.state["data_change_asked"]),
             (1, "/manual/data_way/may", rows[0]["id"]))


def charter_and_prompt_carry_the_same_obtain_sentence():
    """D3b-2 item 3: the sentence an obtain lane's prompt carries is in the charter word for word (one source of the words, AR-15)."""
    sentence = ("make your own user on the app's sign-up page with `fill-new-account` steps, then sign in with "
                "`fill-account <selector> created:<name> user|secret`")
    _d, lines = LP.obtain_pair()
    prompt = " ".join(" ".join(lines["TC-2"]).split())
    charter = " ".join((SCRIPTS.parent / "references" / "walk-charter.md").read_text(encoding="utf-8").split())
    check_in("the obtain lane's prompt carries the sentence", sentence, prompt)
    check_in("the charter carries the SAME sentence", sentence, charter)
    check_not_in("control: the lane that signs in with a pool account is not told to sign up", "fill-new-account", " ".join(" ".join(lines["TC-1"]).split()))


def walkers_one_runs_none_of_it():
    d, cases, _patches = short_rig()
    d.config = {"manual": {"walkers": 1}}
    d.run_chains = mock.Mock(side_effect=AssertionError("old road"))
    err, _said = LP.enter(d, cases)
    check_eq("D.5: walkers 1 - no question, no registry call, no state key", (err, d.calls, d.state.get("walk_supply_asked")), (None, [], None))


def crashed_reservation_settled_dirty():
    """N3 (AR-25): a reserved id whose dispatch is registered but no longer running, with no walk record (the crash between the registration
    and `walk_before`), is settled `dirty` at the next entry; a running dispatch's rows stay held; an unreadable controller frees nothing."""
    d = LP.make(["TC-1", "TC-2"], {"TC-1": LP.USER, "TC-2": LP.ADMIN})
    task = LP.project(d)
    row = {"kind": "book", "instance": "b1", "walk": "S6-qa-runner-7", "item": "TC-9", "state": "in_use", "at": "2026-11-10T10:00:00"}
    LP.WS.update_claims(task, lambda rows: ([*rows, row], None))
    d.world.dispatches["S6-qa-runner-7"] = {"id": "S6-qa-runner-7", "stage": "S6", "role": "qa-runner", "status": "stopped", "scope": ["TC-1"]}
    d.state = {"walk_ids": {"1": "S6-qa-runner-7"}}
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_assign_clear()
    check_eq("a dispatch that is no longer running and has no walk record: its held rows are `dirty`, never free",
             [r["state"] for r in LP.WS.claims_of(task)[0] if r["walk"] == "S6-qa-runner-7"], ["dirty"])
    check("and the assignment keys are dropped", "walk_ids" not in d.state, repr(d.state))
    d.world.dispatches["S6-qa-runner-8"] = {"id": "S6-qa-runner-8", "stage": "S6", "role": "qa-runner", "status": "running", "scope": ["TC-1"]}
    LP.WS.update_claims(task, lambda rows: ([*rows, {**row, "walk": "S6-qa-runner-8"}], None))
    d.state = {"walk_ids": {"1": "S6-qa-runner-8"}}
    with contextlib.redirect_stdout(io.StringIO()):
        d.walk_assign_clear()
    check_eq("a RUNNING dispatch's rows stay held",
             [r["state"] for r in LP.WS.claims_of(task)[0] if r["walk"] == "S6-qa-runner-8"], ["in_use"])
    d.world.dispatches["S6-qa-runner-8"]["status"] = "stopped"
    d.controller_state = lambda: (_ for _ in ()).throw(OSError("controller.json cannot be read"))
    d.state = {"walk_ids": {"1": "S6-qa-runner-8"}}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        d.walk_assign_clear()
    check_eq("an unreadable controller record: rows stay held and one note says so",
             ([r["state"] for r in LP.WS.claims_of(task)[0] if r["walk"] == "S6-qa-runner-8"], "could not be read" in out.getvalue()),
             (["in_use"], True))


def main():
    question_holds_no_case_deferred()
    gate_and_other_empty_holds_still_asked()
    token_app_makes_them_writes_both_keys()
    sign_up_roles_round_trip_through_obtain_roles_of()
    token_one_at_a_time()
    token_i_will_add()
    free_words_go_to_conductor_once()
    test_words_kept_whole()
    resolve_failure_holds_question()
    answer_survives_give_back()
    answer_keeps_existing_more_accounts()
    test_never_reads_words()
    walk_supply_text_passes_and_names_no_key_path()
    take_answer_branches_before_generic_offered()
    data_change_deferrable_holds_no_case()
    data_change_tokens_match_the_reader()
    data_change_token_writes_the_value()
    data_change_free_words_to_conductor_once()
    data_change_resolve_failure_holds_question()
    data_change_missing_state_key_is_a_refusal()
    data_change_text_passes_and_names_no_key_path()
    data_change_stand_not_safe_to_break_says_so()
    data_change_real_resolve_writes_the_pointer()
    try:
        for fn in (short_parts_raise_once_per_story, data_shortage_raises_the_one_question, known_way_never_asks, open_row_reused_no_second_row,
                   raise_before_any_dispatch, add_failure_lanes_go_on, not_changeable_stand_records_no_obtain, data_change_asked_on_need_only,
                   data_change_answered_never_reasked, data_change_default_before_answer_existing_only, data_change_open_row_reused,
                   walkers_one_runs_none_of_it, charter_and_prompt_carry_the_same_obtain_sentence, crashed_reservation_settled_dirty):
            fn()
    finally:
        SR.lane_keys = LP.SHOWN["lane_keys"]         # test_walk_lanes_parallel swapped it at import
    finish("test_walk_supply")


if __name__ == "__main__":
    main()
