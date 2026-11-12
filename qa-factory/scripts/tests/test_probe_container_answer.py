"""EP1-24 F3 (FR-8, FR-9): the which-container card keeps its promise.

The card lists the running containers; each one it can take by name is a closed answer (`<check id>: <name>`). Choosing it makes the
driver run the existing write command (`runtime_probe.py --suggest --write --container <name>`) once; a word off the list does not;
a chosen container records no waiver; a refused write leaves the gate open. Run: python -B scripts/tests/test_probe_container_answer.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish  # noqa: E402

import gate_preflight  # noqa: E402
import story_run as SR  # noqa: E402

PROFILE = "api"


def card(candidates: list):
    """The finding `_probe_which_container` writes for these candidates (the stand and the checkout are stubbed)."""
    root = Path(tempfile.mkdtemp(prefix="qa-probe-answer-"))
    reh = gate_preflight.Rehearsal(root, "A")
    reh._probe_which_container("s5_runtime_probe", PROFILE, "localhost", candidates, "localhost", "repo")
    return root, reh.findings[0]


def driver_for(root: Path, finding: dict):
    """A Driver that has only what `take_stand_gap_answers` touches; `run_argv` (the WRITE) and `py` are spies, and
    `gate_preflight.run_probe` (the read-only CHECK, the one function that starts the probe) answers `drv.verdict`."""
    drv = object.__new__(SR.Driver)
    drv.task_root, drv.dry, drv.task, drv.project = root, False, "T-1", root
    drv.config, drv.env, drv.words_file = {}, {}, "w.txt"
    drv.ran, drv.py_calls, drv.exit_code, drv.checked, drv.order = [], [], 0, [], []
    drv.verdict = {"record": {"result": "matched"}}

    def run_probe(argv, cwd, timeout):
        drv.checked.append(list(argv))
        drv.order.append("check")
        return drv.verdict
    gate_preflight.run_probe = run_probe
    shown = f"- [{finding['id']}] {finding['message']}"
    drv.state = {"shown_doors": {"A": {finding["id"]: finding["waives"]}}}
    drv.rehearse = lambda gate: {"findings": [finding]}
    drv.shown_packet = lambda kind: shown
    drv.carry_environment_properties = lambda *a, **k: None
    drv.revoke_environment_properties = lambda gate, revokes: []

    def run_argv(argv):
        drv.ran.append(list(argv))
        drv.order.append("write")
        return drv.exit_code, "refused: no such container" if drv.exit_code else "ok"
    drv.run_argv = run_argv
    drv.py = lambda *a, **k: (drv.py_calls.append(a) or (0, ""))
    return drv, shown


def answer(drv, shown, finding, text):
    return drv.take_stand_gap_answers("gate_A", f"{finding['id']}: {text}", shown, "S5", "")


def test_the_card_offers_what_it_can_take_by_name() -> None:
    root, f = card(["c1", "c2"])
    try:
        check_eq("two names are offered", f["container_answers"], ["c1", "c2"])
        check_eq("each has its own write command", sorted(f["answer_argvs"]), ["c1", "c2"])
        argv = f["answer_argvs"]["c2"]
        check("the name is ONE argv element after --container, the write form",
              argv[argv.index("--container") + 1] == "c2" and "--suggest" in argv and "--write" in argv and "c1" not in argv, argv)
        probe = f["answer_probes"]["c2"]
        check("each has its read-only check, portable, the name one element, and no write flag",
              sorted(f["answer_probes"]) == ["c1", "c2"] and probe[0] == "{python}" and probe[probe.index("--container") + 1] == "c2"
              and "--no-evidence" in probe and "--suggest" not in probe and "--write" not in probe, probe)
        check_in("the fix names the closed answer, under the finding's id", f["id"] + ": <name>", f["fix"])
        check_eq("the card still passes by the person's word", f["waives"][0]["block"], f"runtime probe: {PROFILE}")
    finally:
        cleanup(root)


def test_adversarial_names_are_not_offered() -> None:
    bad = ["a b", "x;y", "-rf", "", "z" * 300, "$(id)", "accept", "run", "a\nb"]
    root, f = card(["c1", *bad])
    try:
        check_eq("only the plain name is offered", f["container_answers"], ["c1"])
        check_in("the rest is the conductor's, and the card says so", "I cannot take these by name: a b, x;y, -rf", f["fix"])
    finally:
        cleanup(root)
    root, f = card([f"c{i}" for i in range(7)])
    try:
        check_eq("AT the limit (5) names are offered, BEYOND it the rest is the conductor's", f["container_answers"], [f"c{i}" for i in range(5)])
        check_in("and the card NAMES the two it cannot take", "c5, c6", f["fix"])
    finally:
        cleanup(root)
    root, f = card(["c0", "a b", "c1", "c2", "c3", "c4", "c5"])
    try:
        check_eq("a filtered name in the middle is skipped, the next plain one takes its place",
                 f["container_answers"], ["c0", "c1", "c2", "c3", "c4"])
        check_in("the card names the filtered one and the one past the limit", "a b, c5", f["fix"])
    finally:
        cleanup(root)
    root, f = card(["z" * 200, "z" * 201])
    try:
        check_eq("200 characters is AT the limit, 201 is beyond it", f["container_answers"], ["z" * 200])
    finally:
        cleanup(root)
    root, f = card(["-rf", "a b"])
    try:
        check("nothing to offer: no closed answer fields, plain wording that names the container in words",
              "container_answers" not in f and "answer_probes" not in f and "name the container in your own words" in f["fix"]
              and "name it" not in f["fix"], f)
    finally:
        cleanup(root)


def test_the_whole_road() -> None:
    root, f = card(["c1", "c2"])
    try:
        drv, shown = driver_for(root, f)
        out = answer(drv, shown, f, "c2")
        check_eq("the check ran first, then the write command ONCE", drv.order, ["check", "write"])
        check("the check is the chosen container's, not the other", any(a == "c2" for a in drv.checked[0]) and "c1" not in drv.checked[0], drv.checked)
        argv = drv.ran[0]
        check("with the chosen name as one element, and not the other", argv[argv.index("--container") + 1] == "c2" and "c1" not in argv, argv)
        check_eq("it is NOT a stand-gap record (own list)", out["recorded"], [])
        check_eq("it is listed as a checked and registered container", [p["name"] for p in out["probed"]], ["c2"])
        check_eq("and the line is not unread", out["unread"], [])
        check_eq("NO waiver was recorded: nothing was passed", drv.py_calls, [])
        check_in("the conductor is told which container was checked and registered", "`c2` for profile `api` (the check said `matched`)", out["note"])
        check_not_in("and the note does not call it a stand-gap line the driver recorded", "Stand-gap lines of this answer", out["note"])
        # a word off the list
        for text in ("c3", "c2 please", "C2", "c2?", "the second one", "accept"):
            drv2, shown2 = driver_for(root, f)
            out2 = answer(drv2, shown2, f, text)
            check_eq(f"`{text}` runs nothing", drv2.ran, [])
            check_eq(f"`{text}` records no probe", out2.get("recorded", []), [])
        drv3, shown3 = driver_for(root, f)
        out3 = answer(drv3, shown3, f, "c3")
        check_eq("an unlisted name is unread: it goes to the conductor", out3["unread"], [f"{f['id']}: c3"])
    finally:
        cleanup(root)


def test_a_name_with_commands_but_not_offered_is_not_read() -> None:
    """t-427 (canon part A, survivor 4): the commands are looked up first; the offered list is still the second lock. A finding whose
    `answer_probes` / `answer_argvs` hold a name its own `container_answers` does not offer (a damaged or stale record), and one whose
    `container_answers` is no list (a string would match a name by substring), takes no line."""
    root, f = card(["c1", "c2"])
    try:
        stray = dict(f, answer_probes=dict(f["answer_probes"], c3=list(f["answer_probes"]["c2"])),
                     answer_argvs=dict(f["answer_argvs"], c3=list(f["answer_argvs"]["c2"])))
        drv, shown = driver_for(root, stray)
        out = answer(drv, shown, stray, "c3")
        check_eq("a name with both commands but off the offered list runs nothing", (drv.checked, drv.ran), ([], []))
        check_eq("and is unread: it goes to the conductor", (out["unread"], out.get("probed", [])), ([f"{f['id']}: c3"], []))
        drv_ok, shown_ok = driver_for(root, stray)
        out_ok = answer(drv_ok, shown_ok, stray, "c2")
        check_eq("control: an offered name of the same record still runs", [p["name"] for p in out_ok["probed"]], ["c2"])
        as_text = dict(f, container_answers="c1 c2")
        drv_t, shown_t = driver_for(root, as_text)
        out_t = answer(drv_t, shown_t, as_text, "c2")
        check_eq("an offered list that is no list is no list of names: nothing runs, the line is unread",
                 (drv_t.ran, out_t["unread"]), ([], [f"{f['id']}: c2"]))
    finally:
        cleanup(root)


def test_a_refusal_keeps_the_gate_open() -> None:
    root, f = card(["c1", "c2"])
    try:
        drv, shown = driver_for(root, f)
        drv.exit_code = 1
        out = answer(drv, shown, f, "c1")
        check_eq("the check matched, the write ran once and is not retried", drv.order, ["check", "write"])
        check_eq("nothing is recorded as done", (out["recorded"], out["probed"]), ([], []))
        check_eq("the line is unread, so the gate is not recorded by code over it", out["unread"], [f"{f['id']}: c1"])
        check_in("the refusal's own text reaches the note", "refused: no such container", out["note"])
        check_in("and the note says the check matched but the write was refused", "the check matched, but registering it was refused", out["note"])
        check_eq("no waiver was recorded", drv.py_calls, [])
    finally:
        cleanup(root)


def test_exit_0_with_a_non_matched_verdict_is_not_recorded() -> None:
    """F-1: the write of `--suggest --write` exits 0 on every verdict, so the verdict of the READ-ONLY check decides."""
    root, f = card(["c1", "c2"])
    try:
        ways = {"mismatched": {"record": {"result": "mismatched"}}, "unknown": {"record": {"result": "unknown", "error": "no revision"}},
                "not_applicable": {"record": {"result": "not_applicable"}}, "a foreign word": {"record": {"result": "MATCHED"}},
                "no verdict": {"record": {"result": " "}}, "timed out": {"timed_out": True}, "not JSON": {"unreadable": "not json"}}
        for label, verdict in ways.items():
            drv, shown = driver_for(root, f)
            drv.verdict = verdict
            out = answer(drv, shown, f, "c2")
            check_eq(f"{label}: the write never ran (nothing registered, the container stays answerable)", drv.order, ["check"])
            check_eq(f"{label}: not recorded and not probed", (out["recorded"], out["probed"]), ([], []))
            check_eq(f"{label}: the line stays unread, so the gate is not recorded over it", out["unread"], [f"{f['id']}: c2"])
            check_in(f"{label}: the note says nothing was registered", "nothing was registered", out["note"])
            check_not_in(f"{label}: and never says the probe is registered", "already checked and registered", out["note"])
        drv, shown = driver_for(root, f)
        drv.verdict = {"record": {"result": "mismatched"}}
        check_in("a mismatch is named in words with its verdict", "said `mismatched` (it runs other code than this story's)",
                 answer(drv, shown, f, "c2")["note"])
        drv.verdict = {"record": {"result": "matched"}}
        drv.order.clear()
        again = answer(drv, shown, f, "c1")
        check_eq("another name is still answerable after a refused one", (drv.order, [p["name"] for p in again["probed"]]), (["check", "write"], ["c1"]))
    finally:
        cleanup(root)


def test_two_lines_for_one_card_the_last_counts_and_is_said() -> None:
    import contextlib
    import io
    root, f = card(["c1", "c2"])
    try:
        drv, shown = driver_for(root, f)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = drv.take_stand_gap_answers("gate_A", f"{f['id']}: c1\n{f['id']}: c2", shown, "S5", "")
        check_eq("only the last line runs", [p["name"] for p in out["probed"]], ["c2"])
        check("the write carries c2 and not c1", drv.ran and drv.ran[0][drv.ran[0].index("--container") + 1] == "c2" and len(drv.ran) == 1, drv.ran)
        check_in("and the answer says the last line counts", "was answered more than once; the last line counts", buf.getvalue())
    finally:
        cleanup(root)


def test_the_sibling_cards_say_it_in_plain_words_and_the_conductor_has_a_row() -> None:
    import json
    root = Path(tempfile.mkdtemp(prefix="qa-probe-sib-"))
    try:
        reh = gate_preflight.Rehearsal(root, "A")
        reh.project_root = root
        reh._probe_refused("s5_runtime_probe", PROFILE, "no checkout is named")
        fake = type("RP", (), {"__file__": __file__, "suggest": staticmethod(lambda *a: (None, None)), "APP_ROOT": "/app"})
        reh._probe_no_container("s5_runtime_probe", PROFILE, fake, "localhost", "repo")
        for f in reh.findings:
            check_in("the card names the container in the person's own words", "name the container", f["fix"])
            check_not_in("and no longer says 'name it'", "name it", f["fix"])
        check_in("the no-container card says docker names none", "docker names no running container", reh.findings[1]["message"])
    finally:
        cleanup(root)
    rows = json.loads((Path(gate_preflight.__file__).resolve().parents[1] / "references" / "conductor-actions.json").read_text(encoding="utf-8"))["actions"]
    row = [r for r in rows if "names the container that serves a profile's tests" in r["says"]]
    check_eq("the conductor has ONE row for a named container", len(row), 1)
    check("it checks read-only first and writes only on `matched`", "--no-evidence" in row[0]["run"] and "ONLY when it is `matched`" in row[0]["run"], row)


def test_a_changed_card_is_not_read() -> None:
    root, f = card(["c1", "c2"])
    try:
        drv, shown = driver_for(root, f)
        drv.state["shown_doors"] = {"A": {}}
        out = answer(drv, shown, f, "c1")
        check_eq("a card the person was not shown runs nothing", drv.ran, [])
        check_eq("and goes to the conductor", out["unread"], [f"{f['id']}: c1"])
    finally:
        cleanup(root)


def test_a_story_without_such_a_finding() -> None:
    root, f = card(["c1", "c2"])
    try:
        drv, shown = driver_for(root, f)
        drv.rehearse = lambda gate: {"findings": []}
        out = answer(drv, shown, f, "c1")
        check_eq("an answer for a card this story does not have runs nothing", drv.ran, [])
        check_eq("and records nothing", out.get("recorded", []), [])
    finally:
        cleanup(root)


if __name__ == "__main__":
    test_the_card_offers_what_it_can_take_by_name()
    test_adversarial_names_are_not_offered()
    test_the_whole_road()
    test_a_name_with_commands_but_not_offered_is_not_read()
    test_a_refusal_keeps_the_gate_open()
    test_exit_0_with_a_non_matched_verdict_is_not_recorded()
    test_two_lines_for_one_card_the_last_counts_and_is_said()
    test_the_sibling_cards_say_it_in_plain_words_and_the_conductor_has_a_row()
    test_a_changed_card_is_not_read()
    test_a_story_without_such_a_finding()
    finish("test_probe_container_answer")
