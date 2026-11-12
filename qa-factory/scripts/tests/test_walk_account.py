#!/usr/bin/env python3
"""TR3-10 D3a step 3 (t-2291): the `walk_account` question of S6 - the data of ONE account the project does not have: its text, its Person,
its answer executor (`_answer_walk_account`), its `take_answer` branch and the constant `WALK_ACCOUNT_TRIGGERS`. NO raise site is tested
here (`walk_refuse_gaps` and the assignment are another step's).

The rig is `test_walk_supply.Rig` (a bare `Driver` with fakes, imported, not copied): `refuse_case` records `(case, by, reason, door)`,
`unread` records the conductor hand-over, `held_question` returns a `Stop` carrying the lead."""
import contextlib
import inspect
import io
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_run as SR  # noqa: E402
import human_text  # noqa: E402
from test_walk_supply import Rig, Stop, text_of  # noqa: E402

CASES = ["TC-1", "TC-2"]
LINES = ["- Title of TC-1 (TC-1)", "- Title of TC-2 (TC-2)"]
SECRET = "hunter2-Pa55w0rd"


def person_for(rig: Rig, row: str = "DD-5", role: str = "admin", cases=None):
    return rig.driver.walk_account_person(row, role, list(cases or CASES), LINES)


def walk_account_holds_tied_cases_deferrable():
    rig = Rig(scope=("TC-1", "TC-2", "TC-3"))
    try:
        person = person_for(rig)
        check_eq("kind, stage, holds", (person.kind, person.stage, person.holds), ("walk_account", "S6", ("TC-1", "TC-2")))
        check("no `no_hold` flag: it defers through the existing case test", not getattr(person, "no_hold", False))
        check_eq("L5: no `offered`", person.offered, ())
        check("deferrable: the scope has a case outside `holds`", rig.driver.deferrable(person) is True)
        check_eq("the state row: role and tied cases under the row id", rig.driver.state["walk_account_asked"],
                 {"DD-5": {"role": "admin", "cases": ["TC-1", "TC-2"]}})
        everything = Rig(scope=("TC-1", "TC-2"))
        try:
            check("the tied cases are the whole scope: nothing to go on with, asked at once (the rule's own error direction)",
                  everything.driver.deferrable(person_for(everything)) is False)
        finally:
            everything.done()
        check_eq("one question per role: a second role is a second row, the first stays", sorted(
            (person_for(rig, "DD-6", "user", ["TC-3"]), rig.driver.state["walk_account_asked"])[1]), ["DD-5", "DD-6"])
    finally:
        rig.done()


def walk_account_by_hand_and_go_on_refuse_case():
    for token, by in (("by hand", "person_checks"), ("go on", "left_unchecked")):
        rig = Rig()
        try:
            person_for(rig)
            rig.answer(token)
            rig.driver._answer_walk_account(token, "q", "S6", "")
            check_eq(f"`{token}`: every tied case is refused, in order, with `{by}`", [(c, b) for c, b, _r, _d in rig.refused],
                     [("TC-1", by), ("TC-2", by)])
            check_in("the reason names the role", "admin account", rig.refused[0][2])
            check_eq("no conductor hand-over and no command", (rig.unreads, rig.calls), ([], []))
            check_eq("the question's row is dropped from the state", rig.driver.state["walk_account_asked"], {})
            check_eq("the answer is on record as the token", [w for _p, w in rig.rows], [token])
        finally:
            rig.done()
    rig = Rig()
    try:
        person_for(rig)
        for form in ("  `By Hand`.  ", "GO ON"):
            person_for(rig)
            rig.driver._answer_walk_account(form, "q", "S6", "")
        check_eq("the normalisation of a token (case, quotes, one full stop) is the whole reading", [b for _c, b, _r, _d in rig.refused],
                 ["person_checks", "person_checks", "left_unchecked", "left_unchecked"])
    finally:
        rig.done()


def walk_account_keys_missing_asked_once_then_go_on():
    rig = Rig()
    try:
        person_for(rig)
        err = None
        try:
            rig.driver._answer_walk_account("added", "q", "S6", "")
        except Stop as exc:
            err = exc
        check("the first bare `added` brings the question back (a held question)", err is not None)
        check_in("with the truthful reason (D3b-2: the person named no key, the probe found none is another text)",
                 "You said the account is added, but did not name the two keys", str(err))
        check_not_in("and not the probe's text", "are not in the environment file", str(err))
        check_eq("nothing was refused, nothing handed to the conductor", (rig.refused, rig.unreads), ([], []))
        check_eq("the counter is per role", rig.driver.state["walk_account_again"], {"admin": 1})
        rig.driver._answer_walk_account("`Added`.", "q", "S6", "")
        check_eq("the second bare `added` is `go on`: every tied case `left_unchecked`", [(c, b) for c, b, _r, _d in rig.refused],
                 [("TC-1", "left_unchecked"), ("TC-2", "left_unchecked")])
        check_in("and the reason says no key was named", "did not name its two keys", rig.refused[0][2])
        check_not_in("and does not claim keys were looked for", "environment file", rig.refused[0][2])
        check_eq("the counter and the row are gone", (rig.driver.state["walk_account_again"], rig.driver.state["walk_account_asked"]), ({}, {}))
        check_eq("the conductor was never called", rig.unreads, [])
        other = Rig()
        try:
            person_for(other)
            other.driver.state["walk_account_again"] = {"user": 1}
            try:
                other.driver._answer_walk_account("added", "q", "S6", "")
            except Stop:
                pass
            check_eq("another role's earlier re-ask does not spend this role's one", other.driver.state["walk_account_again"], {"user": 1, "admin": 1})
        finally:
            other.done()
    finally:
        rig.done()


def walk_account_both_triggers_one_constant():
    check_eq("the constant holds the two triggers, in the spec's order", SR.WALK_ACCOUNT_TRIGGERS, ("no_pair", "short_distinct"))
    source = harness.driver_text()
    check_eq("one definition in the driver", source.count("\nWALK_ACCOUNT_TRIGGERS = "), 1)
    for name in ("walk_account_text", "walk_account_person", "_answer_walk_account"):
        body = inspect.getsource(getattr(SR.Driver, name))
        check_not_in(f"`{name}` names neither trigger (the raise sites read the constant)", "no_pair", body)
        check_not_in(f"`{name}` names neither trigger (short)", "short_distinct", body)


def walk_account_free_words_to_conductor_once():
    rig = Rig()
    try:
        person_for(rig, row="DD-7")
        words = f"added: QA_ADMIN_LOGIN and QA_ADMIN_PASS (the password is {SECRET})"
        rig.answer(words)
        rig.driver._answer_walk_account(words, "the question text", "S6", "")
        check_eq("one hand-over, no command, no refusal", (len(rig.unreads), rig.calls, rig.refused, rig.rows), (1, [], [], []))
        got = rig.unreads[0]
        check_eq("the kind, the stage and the words whole", (got["kind"], got["stage"], got["words"]), ("walk_account", "S6", words))
        check_eq("the three tokens are the doors", got["doors"], ("added", "by hand", "go on"))
        check_in("the conductor is told the registry row", "DD-7", got["text"])
        check_in("and the role", "`admin`", got["text"])
        check_in("and the cases", "TC-1, TC-2", got["text"])
        check_in("and gets the question's own text", "the question text", got["text"])
        check_not_in("D.10: the words (a password may stand in them) are not copied into the text code built", SECRET, got["text"])
        check_eq("the row stays: the conductor may ask again", list(rig.driver.state["walk_account_asked"]), ["DD-7"])
        for words in ("added, keys A and B", "yes", "no", "by hand please", "go on and add it", "  ", ""):
            rig.driver._answer_walk_account(words, "q", "S6", "")
        check_eq("every other word goes to the conductor, whole, once each; no case was touched", (len(rig.unreads), rig.refused), (8, []))
    finally:
        rig.done()


def walk_account_text_passes_and_names_no_key_path():
    rig = Rig()
    try:
        for cases, lines in ((CASES, LINES), (["TC-1"], LINES[:1])):
            person = rig.driver.walk_account_person("DD-1", "admin", cases, lines)
            check_eq(f"the text obeys human-questions.md ({len(cases)} case(s))", human_text.problems(text_of(person), offered=list(person.priced)), [])
            check_eq("it prices the three tokens, in order", list(person.priced), ["added", "by hand", "go on"])
            check_in("the case titles are in the body", LINES[0], person.text)
            check_in("the role as the stand lists it", "admin account", person.text)
            check_in("the spec's sentence: nothing else waits", "Nothing else waits for it", person.text)
            check_in("the spec's sentence: where the login and password go",
                     "Put the account's login and password in your project's environment file (never in this chat) and tell me the names of "
                     "the two keys", person.text)
            for needle in ("/manual", "accounts_way", "more_accounts", "data_way", "config.json", "project_decisions", "stand-account", "DD-1",
                           "walk_account", "S6-", ".json", "qa-factory/"):
                check_not_in(f"no `{needle}` in what the person reads", needle, person.text)
            check("no option is marked recommended", "recommended" not in person.text.lower())
        main = rig.driver.walk_account_text("default", ["TC-1"], LINES[:1])
        check_in("the stand's main account is named in words", "a main account", main)
        check_not_in("the word `default` is not shown", "default", main)
    finally:
        rig.done()


def take_answer_branch_before_generic_offered():
    source = inspect.getsource(SR.Driver.take_answer)
    generic = source.index('elif asked.get("offered") and not seam_gate_words:')
    at = source.find('elif kind == "walk_account":')
    check("item 14: the `walk_account` branch exists and sits before the generic `offered` branch", 0 < at < generic)
    check("and right after the `walk_supply` branch", source.find('elif kind == "walk_supply":') < at < source.find('elif kind == "open_work":'))


def walk_account_edges_refuse_and_say_what_is_missing():
    rig = Rig()
    try:
        def refused(call, *needles):
            try:
                call()
            except SR.Refusal as exc:
                for needle in needles:
                    check_in(f"the Refusal says `{needle}`", needle, exc.text)
                return True
            return False

        check("an empty `cases` list is a Refusal that names the role", refused(
            lambda: rig.driver.walk_account_person("DD-1", "admin", [], LINES), "no case is tied", "admin"))
        check("cases of blanks are the same", refused(lambda: rig.driver.walk_account_person("DD-1", "admin", ["", "  "], LINES), "no case is tied"))
        for role in ("site admin", "admin" + chr(0xE9), chr(0x430) + "dmin", "", " admin", "adm\tin"):      # built from code points: FR-30
            check(f"the role {role!r} is a Refusal that says why", refused(
                lambda role=role: rig.driver.walk_account_person("DD-1", role, CASES, LINES), "cannot be named as an account key"))
        check("no registry row is a Refusal", refused(lambda: rig.driver.walk_account_person("", "admin", CASES, LINES), "registry row"))
        check_eq("none of them left a state row behind", rig.driver.state.get("walk_account_asked"), None)
        check("a missing state row at answer time is a Refusal that says what is missing", refused(
            lambda: rig.driver._answer_walk_account("go on", "q", "S6", ""), "walk_account_asked", "missing"))
        rig.driver.state["walk_account_asked"] = "not a dict"
        check("an unreadable state row is the same Refusal", refused(lambda: rig.driver._answer_walk_account("by hand", "q", "S6", ""), "missing"))
        rig.driver.state["walk_account_asked"] = {"DD-1": {"role": "admin"}, "DD-2": {"cases": ["TC-1"]}}
        check("a row without its cases or its role is not a row", refused(lambda: rig.driver._answer_walk_account("go on", "q", "S6", ""), "missing"))
        check_eq("in none of these a case was touched or the conductor called", (rig.refused, rig.unreads), ([], []))
        rig.driver.state["walk_account_asked"] = {}
        person_for(rig, "DD-1", "admin", ["TC-1"])
        person_for(rig, "DD-2", "user", ["TC-2"])
        check("two open questions and no way to tell which was answered: a Refusal, never a guess", refused(
            lambda: rig.driver._answer_walk_account("go on", "q", "S6", ""), "2 account questions"))
        check_eq("still nothing touched", rig.refused, [])
        rig.driver.state["deferred"] = [{"n": 4, "kind": "walk_account", "stage": "S6", "dispatch": "", "holds": ["TC-2"]}]
        rig.driver.state["asked"] = {"kind": "walk_account", "stage": "S6", "dispatch": "", "deferred_n": 4}
        rig.driver._answer_walk_account("by hand", "q", "S6", "")
        check_eq("a deferred answer picks the entry whose cases are the item's `holds`", [(c, b) for c, b, _r, _d in rig.refused],
                 [("TC-2", "person_checks")])
        check_eq("and only that row is dropped", list(rig.driver.state["walk_account_asked"]), ["DD-1"])
    finally:
        rig.done()


def walk_account_words_that_look_like_a_password_are_never_echoed():
    for token in ("by hand", "go on"):
        rig = Rig()
        try:
            person_for(rig)
            rig.driver._answer_walk_account(token, "q", "S6", "")
            built = " ".join([r for _c, _b, r, _d in rig.refused] + [d for _c, _b, _r, d in rig.refused] + [w for _p, w in rig.rows])
            check_not_in(f"`{token}`: nothing built here carries a password", SECRET, built)
        finally:
            rig.done()
    rig = Rig()
    try:
        person_for(rig)
        try:
            rig.driver._answer_walk_account("added", "q", "S6", "")
        except Stop as exc:
            check_not_in("the re-ask lead carries no words of the person", SECRET, str(exc))
        rig.driver._answer_walk_account("added", f"q {SECRET}", "S6", "")
        check_not_in("the second `added` goes `go on`; its reason carries no password", SECRET, rig.refused[0][2])
        source = inspect.getsource(SR.Driver._answer_walk_account)
        check("the executor holds no regular expression and no `in words` search", "re." not in source and " in words" not in source)
    finally:
        rig.done()


# --- TR3-10 D3b-2 (t-2313): the raise site - `walk_refuse_gaps`, trigger (i) `no_pair` -------------------------------------------------

ROW = json.dumps({"id": "DD-7", "status": "open"})
STAND = {"name": "local", "credentials_by_role": {"admin": ".env: A_USER / A_PASS"}}
CONFIG = {"manual": {}, "environments": [STAND]}
USER = "stand_account:user"


def gaps(keys, config=None, real=False, ok=True, **state):
    """A rig whose lanes (`{case: key}`, one lane per case) cannot walk: `walk_account_gap` is a fixed reason, `lane_keys` reads `keys`,
    `owe_row` records the finding, the registry `add` answers a row (`ok`) or fails. `real=True` runs the real project_decisions.py."""
    rig = Rig(real=real, config=CONFIG if config is None else config)
    d = rig.driver
    rig.out, rig.exit_code = (ROW, 0) if ok else ("boom", 1)
    rig.keys, rig.findings, rig.deferred = keys, [], []
    d.save_state = lambda: None
    d.walk_account_gap = lambda lane: f"the account of {lane[0]} ({keys.get(lane[0])}) is not one a machine can sign in as"
    d.owe_row = lambda *a, **k: rig.findings.append(a)
    d.defer_question = lambda person: rig.deferred.append(person)
    d.state.update(state)
    return rig


def run_gaps(rig, lanes):
    """`walk_refuse_gaps` over `lanes`: `(plan, the Person it raised or None, the console)`."""
    plan = {"blocks": [list(lane) for lane in lanes], "refused": []}
    out, raised = io.StringIO(), None
    with mock.patch.object(SR, "lane_keys", lambda root, lane: {case: rig.keys.get(case) for case in lane}), contextlib.redirect_stdout(out):
        try:
            rig.driver.walk_refuse_gaps(plan)
        except SR.Person as person:
            raised = person
    return plan, raised, out.getvalue()


def add_calls(rig):
    return [call for call in rig.calls if call[0] == "project_decisions.py" and call[1][2] == "add"]


def walk_account_asked_for_unrecorded_role():
    rig = gaps({"TC-1": USER, "TC-2": USER})
    plan, person, out = run_gaps(rig, [["TC-1"], ["TC-2"]])
    check("a role the stand records no pair for raises the account question", person is not None and person.kind == "walk_account", repr(person))
    check_eq("it holds the tied cases of BOTH lanes (one question per role) and is no set-aside kind", (person.stage, person.holds, person.offered),
             ("S6", ("TC-1", "TC-2"), ()))
    check_eq("ONE registry add, for the role's pointer, scope project, owner user", len(add_calls(rig)), 1)
    args = list(add_calls(rig)[0][1])
    check_eq("the field ref is the pointer `stand-account` writes", args[args.index("--field-ref") + 1], "/environments/0/credentials_by_role/user")
    check_eq("scope and owner", (args[args.index("--scope") + 1], args[args.index("--owner") + 1]), ("project", "user"))
    check_eq("the state row and the once-per-story record", (rig.driver.state["walk_account_asked"], rig.driver.state["walk_account_roles"]),
             ({"DD-7": {"role": "user", "cases": ["TC-1", "TC-2"]}}, {"user": "DD-7"}))
    check_eq("the lanes left the plan (as today)", plan["blocks"], [])
    check_in("the text names the role in words", "user account", person.text)
    for case in ("TC-1", "TC-2"):
        check_in(f"{case} is named", case, person.text)


def no_pair_role_asks_walk_account_not_silent_left_unchecked():
    asked = gaps({"TC-1": USER})
    plan, person, out = run_gaps(asked, [["TC-1"]])
    silent = gaps({"TC-1": USER})
    with mock.patch.object(SR, "WALK_ACCOUNT_TRIGGERS", ("short_distinct",)):
        plan_s, person_s, out_s = run_gaps(silent, [["TC-1"]])
    check("control: without the `no_pair` trigger nothing is asked and nothing is written to the registry",
          person_s is None and add_calls(silent) == [] and "walk_account_asked" not in silent.driver.state, repr((person_s, silent.calls)))
    check("and with it the question comes", person is not None and person.kind == "walk_account", repr(person))
    check_eq("INVARIANT: before any answer the cases are closed `left_unchecked` exactly as today (same reason, same door)", asked.refused, silent.refused)
    check_eq("the case is `left_unchecked`", [(c, b) for c, b, _r, _d in asked.refused], [("TC-1", "left_unchecked")])
    def bare(rig):
        return [tuple(str(part).replace(str(rig.root), "<root>") for part in call) for call in rig.findings]
    check_eq("the finding is unchanged: the same one call (the two throwaway projects aside)", bare(asked), bare(silent))
    check_eq("and it is one", len(asked.findings), 1)
    check_eq("the console says the same line", out.splitlines()[0], out_s.splitlines()[0])
    check_in("and the line is the old `not walked`", "S6: TC-1: not walked: ", out)
    check_eq("the plan is the same", (plan["blocks"], plan_s["blocks"]), ([], []))
    for label, key in (("a guest", ""), ("an env: key", "env:QA_U/QA_P"), ("a two-account key", USER + "+stand_account:other"),
                       ("the reserved role default", "stand_account:default"), ("an unreadable key", None)):
        other = gaps({"TC-1": key})
        _plan, who, _out = run_gaps(other, [["TC-1"]])
        check_eq(f"{label}: no role is named, so no question and no add (today's close)", (who, add_calls(other), len(other.refused)), (None, [], 1))
    paired = gaps({"TC-1": "stand_account:admin"})
    _plan, who, _out = run_gaps(paired, [["TC-1"]])
    check_eq("a role the stand records WITH a pair is not `no pair` (the gap is something else): closed, not asked", (who, add_calls(paired), len(paired.refused)),
             (None, [], 1))


def walk_account_open_row_reused():
    import project_decisions as PD
    rig = gaps({"TC-1": USER}, real=True)
    rig.out = ""
    first = run_gaps(rig, [["TC-1"]])[1]
    for key in ("walk_account_asked", "walk_account_roles", "noted"):
        rig.driver.state.pop(key, None)          # a new story: nothing kept in the state, the registry row is still open
    second = run_gaps(rig, [["TC-1"]])[1]
    rows = [r for r in PD.parse_rows((rig.root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8")) if r.get("id", "").startswith("DD-")]
    check("both stories raised the question", first is not None and second is not None, repr((first, second)))
    check_eq("the open row is reused: ONE row, the same id both times", (len(rows), list(rig.driver.state["walk_account_asked"])), (1, [rows[0]["id"]]))
    check_eq("the row names the role's pointer", rows[0]["field_refs"], "/environments/0/credentials_by_role/user")
    again = run_gaps(rig, [["TC-1"]])[1]
    check_eq("the same story, the state kept: the role is asked ONCE (no second raise, no second add)", (again, len(add_calls(rig))), (None, 2))


def walk_account_added_records_and_probes():
    # up to the point the conductor's words are handed over: the probe of a newly added account is gate A's (D8). The pointer is the one
    # `stand-account` writes, so the conductor's own recording reuses THIS open row and resolves it (never a second row).
    import project_decisions as PD
    rig = gaps({"TC-1": USER, "TC-2": USER}, real=True)
    rig.out = ""
    person = run_gaps(rig, [["TC-1"], ["TC-2"]])[1]
    row = list(rig.driver.state["walk_account_asked"])[0]
    words = "added: QA_USER_LOGIN and QA_USER_PASS (never the password)"
    rig.driver._answer_walk_account(words, person.text, "S6", "")
    check_eq("the words go whole to the conductor, once", [(u["kind"], u["words"]) for u in rig.unreads], [("walk_account", words)])
    for needle in (row, "`user`", "TC-1, TC-2"):
        check_in(f"the hand-over names {needle}", needle, rig.unreads[0]["text"])
    done = PD.record_stand_account(rig.root, stand="", role="user", user_key="QA_USER_LOGIN", secret_key="QA_USER_PASS", words=words)
    rows = [r for r in PD.parse_rows((rig.root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8")) if r.get("id", "").startswith("DD-")]
    check_eq("the conductor's `stand-account` resolves the SAME row: still one row, and it is the question's", (len(rows), rows[0]["id"], done.get("decision")),
             (1, row, row))
    check_eq("the account is on the stand now", json.loads((rig.root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
             ["environments"][0]["credentials_by_role"]["user"], "QA_USER_LOGIN / QA_USER_PASS")
    check_eq("nothing was refused by the answer itself (the cases rejoin through the conductor's road)", len(rig.refused), 2)


def walk_account_one_live_row_per_role():
    rig = Rig()
    try:
        person_for(rig, "DD-5", "admin", ["TC-1"])
        person_for(rig, "DD-6", "user", ["TC-3"])
        person_for(rig, "DD-9", "admin", ["TC-2"])
        check_eq("a later row of a role replaces the stale one; another role's row stays", rig.driver.state["walk_account_asked"],
                 {"DD-6": {"role": "user", "cases": ["TC-3"]}, "DD-9": {"role": "admin", "cases": ["TC-2"]}})
        check_eq("the once-per-story record is per role", rig.driver.state["walk_account_roles"], {"admin": "DD-9", "user": "DD-6"})
        rig.driver._answer_walk_account("go on", "q", "S6", "")
    except SR.Refusal as exc:
        check_in("with two roles open an answer is still never a guess (D3a): the Refusal says so", "2 account questions", exc.text)
        check_eq("and nothing was refused", rig.refused, [])
    else:
        check("the answer met two rows of two roles and must be a Refusal", False)
    finally:
        rig.done()
    rig = Rig()
    try:
        person_for(rig, "DD-5", "admin", ["TC-1"])
        person_for(rig, "DD-9", "admin", ["TC-2"])
        rig.driver._answer_walk_account("by hand", "q", "S6", "")
        check_eq("the later answer meets ONE row: its own case only", [(c, b) for c, b, _r, _d in rig.refused], [("TC-2", "person_checks")])
    finally:
        rig.done()


def walk_account_edges_at_the_raise_site():
    failing = gaps({"TC-1": USER}, ok=False)
    plan, person, out = run_gaps(failing, [["TC-1"]])
    check_eq("D.11 add fails: no question, the case is closed, ONE note naming no script", (person, len(failing.refused), out.count("could not be written")),
             (None, 1, 1))
    check_not_in("the note names no script of ours", "project_decisions", out)
    check_eq("nothing is kept in the state, so the next story tries again", failing.driver.state.get("walk_account_asked"), None)
    for label, role in (("a space", "site admin"), ("a non-ASCII letter", "adm" + chr(0xE9) + "n")):
        rig = gaps({"TC-1": "stand_account:" + role})
        plan, person, out = run_gaps(rig, [["TC-1"]])
        check_eq(f"a role with {label}: the builder's Refusal is a note, the close stands, no question", (person, len(rig.refused)), (None, 1))
        check_in("the note says what happened", "was not raised", out)
        check("no row is left in the state", not rig.driver.state.get("walk_account_asked"), repr(rig.driver.state.get("walk_account_asked")))
        check_eq(f"a role with {label}: NO registry `add` was made (no open row for an unaskable role)", add_calls(rig), [])
    for label, state in (("asked in this story (an open row)", {"walk_account_asked": {"DD-1": {"role": "user", "cases": ["TC-9"]}}}),
                         ("asked in this story and answered", {"walk_account_roles": {"user": "DD-1"}}),
                         ("held by a deferred `walk_account` item", {"deferred": [{"n": 1, "kind": "walk_account", "holds": ["TC-1"]}]})):
        rig = gaps({"TC-1": USER}, **state)
        _plan, person, _out = run_gaps(rig, [["TC-1"]])
        check_eq(f"role {label}: not asked again, the cases close as today", (person, add_calls(rig), len(rig.refused)), (None, [], 1))
    rig = gaps({"TC-1": USER}, config={"manual": {}})
    _plan, person, out = run_gaps(rig, [["TC-1"]])
    check_eq("a project with no stand row: no question (nothing names the stand), one note, the close stands", (person, add_calls(rig), len(rig.refused)),
             (None, [], 1))
    check_in("the note says so", "was not raised", out)
    rig = gaps({"TC-1": USER, "TC-2": "stand_account:viewer"})
    ids = iter(["DD-1", "DD-2"])
    rig.driver.py = lambda script, *a, **k: (rig.calls.append((script, a)), (0, json.dumps({"id": next(ids)})))[1]
    _plan, person, _out = run_gaps(rig, [["TC-1"], ["TC-2"]])
    check_eq("two roles: one question each - the first is set aside, the last is raised", ([p.holds for p in rig.deferred], person.holds),
             ([("TC-1",)], ("TC-2",)))
    check_eq("both rows are kept (one per role)", sorted(rig.driver.state["walk_account_asked"]), ["DD-1", "DD-2"])
    check_eq("every case of both is closed", [c for c, _b, _r, _d in rig.refused], ["TC-1", "TC-2"])


def no_pair_question_applies_at_walkers_one():
    # D.5: the one place of Part D that ALSO applies at `walkers` 1 (and with one lane). The frozen walkers-1 story (`test_story_run_s6_w1_frozen.py`)
    # walks four GUEST cases, which never reach this site, so its pins need no change; pinned here instead: the raise does not read `walkers`, and
    # `manual_lane_plan` calls the site before the parallel-road condition.
    rig = gaps({"TC-1": USER})
    rig.driver.config = {"manual": {"walkers": 1}}
    plan, person, _out = run_gaps(rig, [["TC-1"]])
    check_eq("walkers 1: the question is raised and the case closed, as at any walkers", (person is not None and person.kind, len(rig.refused)),
             ("walk_account", 1))
    source = inspect.getsource(SR.Driver.manual_lane_plan)
    check("`walk_refuse_gaps` runs before the `walkers` test of `manual_lane_plan`", 0 < source.index("self.walk_refuse_gaps(plan)") < source.index("self.s6_walkers_cap() != 1"))
    check_not_in("and nothing of the raise reads the walkers cap", "s6_walkers_cap", inspect.getsource(SR.Driver.walk_account_raise)
                 + inspect.getsource(SR.Driver.walk_gap_role) + inspect.getsource(SR.Driver.walk_refuse_gaps))


def main():
    no_pair_question_applies_at_walkers_one()
    walk_account_holds_tied_cases_deferrable()
    walk_account_by_hand_and_go_on_refuse_case()
    walk_account_keys_missing_asked_once_then_go_on()
    walk_account_both_triggers_one_constant()
    walk_account_free_words_to_conductor_once()
    walk_account_text_passes_and_names_no_key_path()
    take_answer_branch_before_generic_offered()
    walk_account_edges_refuse_and_say_what_is_missing()
    walk_account_words_that_look_like_a_password_are_never_echoed()
    walk_account_asked_for_unrecorded_role()
    no_pair_role_asks_walk_account_not_silent_left_unchecked()
    walk_account_open_row_reused()
    walk_account_added_records_and_probes()
    walk_account_one_live_row_per_role()
    walk_account_edges_at_the_raise_site()
    finish("test_walk_account")


if __name__ == "__main__":
    main()
