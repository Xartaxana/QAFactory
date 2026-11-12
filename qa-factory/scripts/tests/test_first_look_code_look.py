#!/usr/bin/env python3
"""t-2277 FL-6: the hold after the first look (`first_look_stop`) - the packet it prints, the code look of a bare relaunch
(`Driver.first_look_code_look`), the closed question `first_look.same_code` and its three answers.

Fast: the methods are called on a bare `Driver` (no loop, no `claude`, no network). The files (register, manifest, pipeline, the record of
the first look) are real, in a scratch folder; `git ls-remote` (`subprocess.run`), `arrival_record` and the controller are recorders. The
manifest entries have the shape the factory WRITES (critic t-2528 B1: a bare merge request number beside `branch`, `commit`, `source_sha`),
not a link. One test per name of the FL-6 list that is about the code look; the arrival ROAD (S1, S2, then S3; the position invariant; the
stopped line) is `test_story_run_arrival.py` (slow, CI). Run: `python -B test_first_look_code_look.py`.
"""
import contextlib
import io
import json
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import first_look as FL  # noqa: E402
import grounding_table as GT  # noqa: E402
import story_run as SR  # noqa: E402

STAND = "dev"
A, B, C = "a" * 40, "b" * 40, "c" * 40
MR, MR_UI = "refs/merge-requests/4214/head", "refs/merge-requests/1881/head"
BRANCH = "refs/heads/feature/x"
HOLD = {"cause": "first_look_stop", "held_from": "S3", "since": "2026-11-10T10:00:00+00:00"}
ACTION = {"action": "awaiting_implementation", "cause": "first_look_stop", "held_from": "S3"}
ROWS = {"R-1": "confirms", "R-2": "missing", "R-3": "unreachable", "R-4": "missing"}
NOT_LISTED = None       # a `live` value: the remote answers cleanly and lists no such ref


def entry(repo="product", mr="4214", sha=A, **more):
    """An implementation entry as the factory writes it (sizing-15045: `mr` a bare number, `branch`, `commit`, `source_sha`)."""
    return {"repo_id": repo, "source_sha": sha, "mr": mr, "branch": "feature/x", "commit": sha, **more}


class Rig:
    """A story held after the first look: register, manifest, the record of the look, the hold, and a bare driver with recorders."""

    def __init__(self, tmp, entries=None, recorded=None, launch=None, rows=ROWS):
        self.root = Path(tmp)
        self.task = self.root / "QA-1"
        (self.task / "work").mkdir(parents=True)
        (self.task / "state").mkdir()
        table = "".join(f"| {r} | The stand shows {r}. | task |\n" for r in ROWS)
        (self.task / "work" / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n" + table, encoding="utf-8")
        self.set_entries(entries if entries is not None else [entry()])
        heads = recorded if recorded is not None else {e.get("repo_id"): e.get("source_sha") for e in self.entries}
        _text, reg = FL.current_keys(self.task)
        GT.write_yaml(FL._record_path(self.task), {
            "walked_at": "2026-11-10T09:00:00+00:00", "walk": "S3-qa-runner-1", "stand": STAND, "stand_build": "not_established",
            "source_head": heads, "register_hash": reg, "gaps": [],
            "rows": [{"req": r, "status": s, "why": f"the stand said {s} for {r}",
                      **({"blocked_by": "product", "evidence": ["captures/a.png"], "quote": "no such page"} if s == "unreachable" else
                         {"blocked_by": "product"} if s == "missing" else {})} for r, s in rows.items()]})
        self.set_pipeline({"ticket": "QA-1", "environment": STAND, "awaiting": HOLD})
        self.live, self.asked, self.arrived, self.sent = {}, [], [], []
        d = SR.Driver.__new__(SR.Driver)
        d.task_root, d.task, d.project, d.config = self.task, "QA-1", self.root, {}
        d.state_dir, d.env = self.task / "state", {}
        d.state, d.boundary, d._price_notes, d.answer_kind = {"launch": launch if launch is not None else {"mr": "4214"}}, "", None, ""
        d._answer = None
        d.file_defect = lambda *a, **k: None
        d.save_state = lambda: None
        d.pipeline = lambda: json.loads((self.task / "pipeline.json").read_text(encoding="utf-8"))
        d.controller_state = lambda: {"revision": 3, "dispatches": {}}
        d.controller = lambda op, *args, input_data=None: self.sent.append((op, args, input_data)) or {}
        d.continue_command = lambda drop_absent=(): "python story_run.py --task QA-1"
        d.arrival_record = lambda: self.arrived.append(json.loads(json.dumps(d.state["launch"].get("arrival"))))
        d.answer_row = lambda *a, **k: None
        d.answer_file = lambda: "state/words/answer.txt"
        d.unread = lambda *a, **k: self.asked.append(("unread", a))
        d.held_question = lambda *a, **k: SR.Person("x", "held", "S3")
        d.repo_of_project = lambda project, why=None: (project, str(self.root / "checkout" / project))
        self.d = d

    def set_entries(self, entries):
        self.entries = entries
        (self.task / "work" / "context-manifest.json").write_text(json.dumps({"implementations": entries}), encoding="utf-8")

    def set_pipeline(self, pipeline):
        (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    def run(self, argv, **kw):
        """The fake `subprocess.run`: `live[ref]` is a sha (listed), `NOT_LISTED`, an Exception (raised) or `("fail", stderr)`."""
        ref = argv[-1]
        self.asked.append(("ls", argv[2], ref, kw.get("timeout")))
        got = self.live.get(ref)
        if isinstance(got, Exception):
            raise got
        if isinstance(got, tuple):
            return types.SimpleNamespace(stdout="", stderr=got[1], returncode=128)
        return types.SimpleNamespace(stdout=f"{got}\t{ref}\n" if got else "", stderr="", returncode=0)

    def look(self):
        """`first_look_code_look` with the remote faked: `(returned | None, raised Person | None, printed text)`."""
        real, out, back, raised = SR.subprocess.run, io.StringIO(), None, None
        SR.subprocess.run = self.run
        try:
            with contextlib.redirect_stdout(out):
                try:
                    back = SR.Driver.first_look_code_look(self.d, ACTION)
                except SR.Person as person:
                    raised = person
        finally:
            SR.subprocess.run = real
        return back, raised, out.getvalue()

    def asks(self):
        return [c[2] for c in self.asked if c[0] == "ls"]


def test_first_look_stop_packet_not_s5_packet():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                SR.Driver._act_await_implementation(r.d, {"action": "await_implementation", "cause": "first_look_stop", "held_from": "S3"})
        except SR.Stop as stop:
            code = stop.code
        text = out.getvalue()
        check_in("first_look_stop_packet_not_s5_packet: the report is the first look's", "# First look report for QA-1", text)
        check_not_in("first_look_stop_packet_not_s5_packet: not the S5 interim report", "Interim report", text)
        check_in("first_look_stop_packet_not_s5_packet: the count", "1 of 4 requirements (25.0%)", text)
        check_in("first_look_stop_packet_not_s5_packet: the unreachable one with its cited capture", "evidence: captures/a.png", text)
        check_in("first_look_stop_packet_not_s5_packet: the head and the day", "product: aaaaaaa", text)
        check_in("first_look_stop_packet_not_s5_packet: ... the stop day", "stopped on 2026-11-10", text)
        check_in("first_look_stop_packet_not_s5_packet: the restart command", "python story_run.py --task QA-1 --branch", text)
        check_eq("first_look_stop_packet_not_s5_packet: the run ends with exit 0", code, SR.EXIT_DONE)
        check_eq("first_look_stop_packet_not_s5_packet: the await record carries the cause and the stage it holds from",
                 [(op, i.get("cause"), i.get("held_from")) for op, _a, i in r.sent], [("await", "first_look_stop", "S3")])
        s5 = io.StringIO()
        try:
            with contextlib.redirect_stdout(s5):
                SR.Driver._act_await_implementation(r.d, {"action": "await_implementation", "cause": "s5_absent_side", "held_from": "S6"})
        except SR.Stop:
            pass
        check_in("first_look_stop_packet_not_s5_packet: control - another cause still prints the S5 packet", "# Interim report for QA-1", s5.getvalue())


def test_bare_relaunch_head_moved_arrives():
    """B1: the manifest shapes the factory writes - a bare number, `!42`, a link - all read the head of the merge request from the remote."""
    for shape, ref in (("4214", MR), ("!42", "refs/merge-requests/42/head"), ("https://git.example/g/product/-/merge_requests/7?x=1", "refs/merge-requests/7/head"),
                       # t-2548 F3: ONE reader (`vcs_evidence.mr_iid`, the base slice's too) - the shapes the base slice's own reader used to refuse
                       ("https://git.example/g/product/-/merge_requests/9/diffs", "refs/merge-requests/9/head"),
                       ("http://git.example/g/product/-/merge_requests/9", "refs/merge-requests/9/head"),
                       ("https://git.example/g/product/merge_requests/9", "refs/merge-requests/9/head"), ("007", "refs/merge-requests/7/head")):
        with tempfile.TemporaryDirectory() as tmp:
            r = Rig(tmp, entries=[entry(mr=shape)], launch={"mr": shape})
            r.live = {ref: B}
            back, raised, said = r.look()
            check(f"bare_relaunch_head_moved_arrives[{shape}]: the code look says it arrived and asks nothing", back is True and raised is None, (back, raised))
            check_eq(f"bare_relaunch_head_moved_arrives[{shape}]: the arrival is recorded with the EARLIER source", r.arrived, [{"source": {"mr": shape}, "side": {}}])
            check_in(f"bare_relaunch_head_moved_arrives[{shape}]: one line says why", "the code changed since the first look (product)", said)
            check_eq(f"bare_relaunch_head_moved_arrives[{shape}]: the merge request ref was asked first, in the repository's checkout, with the timeout",
                     r.asked[0], ("ls", str(Path(tmp) / "checkout" / "product"), ref, 10))


def test_bare_relaunch_head_same_asks_same_code():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A}
        back, raised, _ = r.look()
        check("bare_relaunch_head_same_asks_same_code: the question is raised, nothing arrives", raised is not None and back is None and not r.arrived)
        check_eq("bare_relaunch_head_same_asks_same_code: kind and stage", (raised.kind, raised.stage), ("first_look_same_code", "S3"))
        text = str(raised.text)
        check_in("bare_relaunch_head_same_asks_same_code: the stop day and the counts", "stopped this story on 2026-11-10", text)
        for word in ("confirms 1", "contradicts 0", "missing 2", "unreachable 1"):
            check_in(f"bare_relaunch_head_same_asks_same_code: the count by status ({word})", word, text)
        check_in("bare_relaunch_head_same_asks_same_code: the head by repository", "product aaaaaaa", text)
        check_not_in("bare_relaunch_head_same_asks_same_code: no unknown line when all are equal", "could not find out", text)
        for token in ("wait", "source", "continue"):
            check_in(f"bare_relaunch_head_same_asks_same_code: `{token}` is a priced option", f"`{token}`", text)
        check_in("bare_relaunch_head_same_asks_same_code: `continue` says delivery is not ready", "the story:", text)
        check_eq("bare_relaunch_head_same_asks_same_code: no technical details", raised.details, "")


def test_mr_head_falls_back_to_the_entrys_branch():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: NOT_LISTED, BRANCH: B}
        back, raised, _ = r.look()
        check("mr_head_falls_back_to_the_entrys_branch: a merge request the remote does not list reads its branch: moved, arrives", back is True and raised is None)
        check_eq("mr_head_falls_back_to_the_entrys_branch: the merge request first, then the branch", r.asks(), [MR, BRANCH])
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A, BRANCH: B}
        back, raised, _ = r.look()
        check("mr_head_falls_back_to_the_entrys_branch: control - a merge request that answers is not second-guessed by the branch",
              back is None and raised is not None and r.asks() == [MR])


def test_bare_relaunch_head_unknown_asks_with_unknown_line():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: OSError("network down"), BRANCH: OSError("network down")}
        back, raised, _ = r.look()
        text = str(raised.text)
        check("bare_relaunch_head_unknown_asks_with_unknown_line: an unknown head is never `moved`: the question, no arrival",
              raised is not None and back is None and not r.arrived)
        check_in("bare_relaunch_head_unknown_asks_with_unknown_line: one line for the repository, in plain words",
                 "I could not find out whether the code in product has changed: the remote did not give the current commit of its merge request.", text)
        for raw in ("OSError", "Error:", "fatal", "network down", "source_sha"):
            check_not_in(f"bare_relaunch_head_unknown_asks_with_unknown_line: the body carries no raw text ({raw})", raw, text)
        check_in("bare_relaunch_head_unknown_asks_with_unknown_line: the raw reason is in the details", "git could not be run (OSError)", raised.details)
        r.live = {MR: ("fail", "fatal: could not read from remote repository"), BRANCH: NOT_LISTED}
        _b, raised2, _ = r.look()
        check_not_in("bare_relaunch_head_unknown_asks_with_unknown_line: git's refusal is not in the body", "fatal", str(raised2.text))
        check_in("bare_relaunch_head_unknown_asks_with_unknown_line: ... it is in the details", "fatal: could not read from remote repository", raised2.details)


def test_unreadable_or_absent_link_is_unknown_not_same():
    """Edges: a merge request with no number to read -> the branch if there is one, else an unknown line; no merge request and no branch and
    no commit -> an unknown line; a merge request or branch is NEVER settled by the entry's `commit` (what was seen cannot say it is unchanged)."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry(mr="see the ticket", branch="")], launch={})
        back, raised, _ = r.look()
        check("unreadable_or_absent_link_is_unknown_not_same: a link with no number and no branch asks, never arrives or reads 'same'",
              back is None and raised is not None and not r.arrived and r.asks() == [])
        check_in("unreadable_or_absent_link_is_unknown_not_same: the line says the link cannot be read",
                 "the link to its merge request is not one this machine can read", str(raised.text))
        check_not_in("unreadable_or_absent_link_is_unknown_not_same: ... and not that the code is unchanged", "has not changed since", str(raised.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry(mr="see the ticket")], launch={})
        r.live = {BRANCH: B}
        back, _raised, _ = r.look()
        check("unreadable_or_absent_link_is_unknown_not_same: a link with no number goes to the branch", back is True and r.asks() == [BRANCH])
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[{"repo_id": "product", "source_sha": A}], launch={})
        back, raised, _ = r.look()
        check("unreadable_or_absent_link_is_unknown_not_same: no merge request, branch or commit: the question with a line",
              back is None and raised is not None and "names no merge request, branch or commit" in str(raised.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[{"repo_id": "product", "source_sha": A, "commit": A}], launch={})
        back, raised, _ = r.look()
        check("unreadable_or_absent_link_is_unknown_not_same: an entry that names only a commit is itself - same, the question without a line",
              back is None and raised is not None and "could not find out" not in str(raised.text) and r.asks() == [])


def test_recorded_head_unmeasured_asks_not_arrives():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry(sha=None)], recorded={"product": "unmeasured: no source_sha for repo product"})
        r.live = {MR: B}
        back, raised, _ = r.look()
        text = str(raised.text)
        check("recorded_head_unmeasured_asks_not_arrives: a recorded `unmeasured` head asks, though the live one is a commit",
              raised is not None and back is None and not r.arrived)
        check_in("recorded_head_unmeasured_asks_not_arrives: the line names the repository and says what was recorded, in words",
                 "the code in product has changed: the first look did not record which commit it saw", text)
        check_in("recorded_head_unmeasured_asks_not_arrives: the heads list says no commit was recorded", "product no commit recorded", text)
        for raw in ("unmeasured", "source_sha"):
            check_not_in(f"recorded_head_unmeasured_asks_not_arrives: no stored text or field name in the body ({raw})", raw, text)
        check_in("recorded_head_unmeasured_asks_not_arrives: the stored value is in the details", "unmeasured: no source_sha", raised.details)
        packet = __import__("interim_packet").first_look_packet(r.task, "cmd")
        check_not_in("recorded_head_unmeasured_asks_not_arrives: nor in the packet", "source_sha", packet)


def two_repos(tmp, live):
    r = Rig(tmp, entries=[entry("product", "4214"), entry("ui", "1881")])
    r.live = live
    return r


def test_multi_repo_one_moved_arrives():
    with tempfile.TemporaryDirectory() as tmp:
        r = two_repos(tmp, {MR: A, MR_UI: B})
        back, raised, said = r.look()
        check("multi_repo_one_moved_arrives: one of two moved - it arrives", back is True and raised is None and len(r.arrived) == 1)
        check_in("multi_repo_one_moved_arrives: the line names the repository that moved", "(ui)", said)
    with tempfile.TemporaryDirectory() as tmp:
        r = two_repos(tmp, {MR: OSError("down"), MR_UI: B})
        back, raised, _ = r.look()
        check("multi_repo_one_moved_arrives: one moved and one unknown - still an arrival (a moved head is a fact)", back is True and raised is None)


def test_multi_repo_compares_each_named_repo():
    with tempfile.TemporaryDirectory() as tmp:
        r = two_repos(tmp, {MR: A, MR_UI: A})
        _b, raised, _ = r.look()
        check_eq("multi_repo_compares_each_named_repo: the remote is asked for EVERY repository's request", sorted(r.asks()), sorted([MR, MR_UI]))
        check_in("multi_repo_compares_each_named_repo: the question lists both with their heads", "product aaaaaaa; ui aaaaaaa", str(raised.text))
        check_not_in("multi_repo_compares_each_named_repo: all equal - no unknown line", "could not find out", str(raised.text))


def test_multi_repo_unknown_lists_each_repo():
    with tempfile.TemporaryDirectory() as tmp:
        r = two_repos(tmp, {MR: OSError("a"), MR_UI: OSError("b")})
        back, raised, _ = r.look()
        text = str(raised.text)
        check("multi_repo_unknown_lists_each_repo: two unknown heads ask, nothing arrives", back is None and raised is not None and not r.arrived)
        check("multi_repo_unknown_lists_each_repo: one line per repository",
              "code in product has changed" in text and "code in ui has changed" in text and text.count("I could not find out") == 2, text)
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry()], recorded={"product": A, "ui": A})
        r.live = {MR: A}
        _b, raised, _ = r.look()
        check_in("multi_repo_unknown_lists_each_repo: a recorded repository the story no longer names is a line, not a move",
                 "the code in ui has changed: the story's record of the code no longer names this repository", str(raised.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry()])
        (r.task / "work" / "context-manifest.json").write_text("{broken", encoding="utf-8")
        _b, raised, _ = r.look()
        check_in("multi_repo_unknown_lists_each_repo: a manifest that does not read says so, not that the repository is no longer named",
                 "the story's record of the code is empty or cannot be read", str(raised.text))
        check_not_in("multi_repo_unknown_lists_each_repo: ... (the wrong reason)", "no longer names", str(raised.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry()])
        FL._record_path(r.task).write_text("not: [valid", encoding="utf-8")
        _b, raised, _ = r.look()
        check("multi_repo_unknown_lists_each_repo: a record that cannot be read: a line in words, no path, no parser text",
              raised is not None and "the record of the first look cannot be read" in str(raised.text)
              and "first-look.yaml" not in str(raised.text) and "yaml" not in str(raised.text).lower(), str(raised.text))


def test_new_implementation_entry_arrives():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry()])
        r.set_entries([entry(), entry("ui", "1881", sha=C)])
        r.live = {MR: A}
        back, raised, said = r.look()
        check("new_implementation_entry_arrives: an entry the record does not hold arrives, whatever the others say", back is True and raised is None)
        check_in("new_implementation_entry_arrives: the line names it", "(ui)", said)
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[entry()], recorded={})
        r.live = {MR: A}
        back, _raised, _ = r.look()
        check("new_implementation_entry_arrives: a record that held no implementation and a manifest that has one", back is True)


def test_branch_head_is_asked_of_the_repositorys_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp, entries=[{"repo_id": "product", "source_sha": A, "branch": "feature/x"}], launch={"branch": "feature/x"})
        asked = []

        def run(argv, **kw):
            asked.append((argv, kw.get("timeout")))
            return type("Done", (), {"stdout": f"{B}\trefs/heads/feature/x\n{C}\trefs/heads/other/feature/x\n", "stderr": "", "returncode": 0})()
        real, SR.subprocess.run, back = SR.subprocess.run, run, None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                back = SR.Driver.first_look_code_look(r.d, ACTION)
        finally:
            SR.subprocess.run = real
        check("branch_head_is_asked_of_the_repositorys_checkout: the branch's own row counts, the moved head arrives", back is True)
        check_eq("branch_head_is_asked_of_the_repositorys_checkout: `git -C <checkout> ls-remote origin refs/heads/<branch>`, with the timeout",
                 asked, [(["git", "-C", str(Path(tmp) / "checkout" / "product"), "ls-remote", "origin", "refs/heads/feature/x"], 10)])
        r.d.repo_of_project = lambda project, why=None: None
        back2, raised2, _ = r.look()
        check("branch_head_is_asked_of_the_repositorys_checkout: no checkout - the question with the reason, never a move",
              back2 is None and "no checkout of it is set up on this machine" in str(raised2.text))


def test_ls_remote_head_is_the_one_ask():
    """F2: the one helper the three sites use: a clean answer, only the ref's own row, a refusal's own first line, `missing`, timeout, no git."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {"refs/heads/x": B}
        real, SR.subprocess.run = SR.subprocess.run, r.run
        try:
            got = [r.d.ls_remote_head("c", "refs/heads/x"), r.d.ls_remote_head("c", "refs/heads/y", "gone"),
                   r.d.ls_remote_head("c", "refs/heads/z"), r.d.ls_remote_head("c", "refs/heads/w", "gone")]
            r.live["refs/heads/z"] = ("fail", "fatal: no remote\nmore")
            got[2] = r.d.ls_remote_head("c", "refs/heads/z")
            r.live["refs/heads/w"] = SR.subprocess.TimeoutExpired("git", 10)
            got[3] = r.d.ls_remote_head("c", "refs/heads/w")
        finally:
            SR.subprocess.run = real
        check_eq("ls_remote_head_is_the_one_ask: listed, missing (own words), refused (git's first line), timeout",
                 got, [(B, ""), ("", "gone"), ("", "fatal: no remote"), ("", "the remote did not answer within 10 seconds")])


def answered(r, token, at="2026-11-10T12:00:00"):
    path = r.task / "state" / "driver-answers.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": at, "kind": "first_look_same_code", "stage": "S3", "dispatch": "", "token": token}) + "\n")


def hold_answer(r, words):
    """Make the answer being taken (`take_answer` does it): the held answer dict `record_answer_row` writes the row from."""
    r.d._answer = {"text": words, "rel": None, "kind": "first_look_same_code", "stage": "S3", "dispatch": "", "question_sha": "q", "words": words}


def test_same_code_wait_reprints_and_holds():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A}
        taken = SR.Driver._same_code_answer(r.d, "wait\nnot yet, the build is old", "", "S3")
        check("same_code_wait_reprints_and_holds: the token is taken", taken is True)
        check_eq("same_code_wait_reprints_and_holds: nothing is sent to the controller - the hold stands", r.sent, [])
        answered(r, "wait")
        r.d.answer_kind = "first_look_same_code"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                SR.Driver._act_await_implementation(r.d, ACTION)
            code = None
        except SR.Stop as stop:
            code = stop.code
        check_eq("same_code_wait_reprints_and_holds: the run ends with exit 0 over the packet, the question is not asked again", code, SR.EXIT_DONE)
        check_in("same_code_wait_reprints_and_holds: the packet is printed again", "# First look report for QA-1", out.getvalue())
        check_eq("same_code_wait_reprints_and_holds: the remote is not asked on the answer run", r.asks(), [])
        other = SR.Driver._same_code_answer(r.d, "the build will be there tomorrow", "q", "S3")
        check("same_code_wait_reprints_and_holds: other words are not read by code (the conductor, once)", other is False and r.asked[-1][0] == "unread")


def test_same_code_after_wait_carries_date_line():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A}
        answered(r, "wait")
        _b, raised, _ = r.look()
        check_in("same_code_after_wait_carries_date_line: the second question names the day of the wait and that the code did not change",
                 "On 2026-11-10 you chose to wait; the code has not changed since.", str(raised.text))
        r.live = {MR: OSError("down"), BRANCH: OSError("down")}
        _b, raised_unknown, _ = r.look()
        check_in("same_code_after_wait_carries_date_line: with an unknown head the line does not claim the code is unchanged",
                 "On 2026-11-10 you chose to wait.", str(raised_unknown.text))
        check_not_in("same_code_after_wait_carries_date_line: ... (no false claim)", "has not changed since", str(raised_unknown.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A}
        (r.task / "state" / "driver-answers.jsonl").write_text("{broken\n" + json.dumps({"kind": "first_look_same_code", "token": "wait"}) + "\n",
                                                               encoding="utf-8")
        _b, raised, _ = r.look()
        check_not_in("same_code_after_wait_carries_date_line: a carrier that does not read gives the question without the line",
                     "you chose to wait", str(raised.text))
        check("same_code_after_wait_carries_date_line: ... and it is still a question", raised.kind == "first_look_same_code")


def test_two_line_answers_keep_their_token_and_their_words():
    """F1: the executor's token is the FIRST line, the row carries it, and the rest of the answer is the person's words kept whole."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        words = "source\nthe code is on feature-x"
        hold_answer(r, words)
        check("two_line_answers_keep_their_token_and_their_words: `source` + a second line is taken", SR.Driver._same_code_answer(r.d, words, "", "S3") is True)
        rows = [json.loads(line) for line in (r.task / "state" / "driver-answers.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("two_line_answers_keep_their_token_and_their_words: the row's token is the first line, its words the whole answer",
                 [(row["token"], row["words"]) for row in rows], [("source", words)])
        r.d.answer_kind = "first_look_same_code"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                SR.Driver.first_look_code_look(r.d, ACTION)
            code = None
        except SR.Stop as stop:
            code = stop.code
        check_eq("two_line_answers_keep_their_token_and_their_words: the `source` executor ran: exit 0", code, SR.EXIT_DONE)
        check_in("two_line_answers_keep_their_token_and_their_words: ... it printed the restart command", "--branch <the branch with the code>", out.getvalue())
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A}
        words = "wait\nthe build is old"
        hold_answer(r, words)
        SR.Driver._same_code_answer(r.d, words, "", "S3")
        _b, raised, _ = r.look()
        check_in("two_line_answers_keep_their_token_and_their_words: `wait` + a note: the next question still has the date line",
                 "you chose to wait; the code has not changed since.", str(raised.text))
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.d.answer_file = types.MethodType(SR.Driver.answer_file, r.d)
        r.d.words_file = types.MethodType(SR.Driver.words_file, r.d)
        words = "continue\nthe stand is old,\nthe feature is on the next build"
        hold_answer(r, words)
        SR.Driver._same_code_answer(r.d, words, "", "S3")
        args = r.sent[0][1]
        file = Path(args[args.index("--words-file") + 1])
        check_eq("two_line_answers_keep_their_token_and_their_words: a two-line `continue` keeps its words whole in the words file",
                 file.read_text(encoding="utf-8"), words)


def test_same_code_source_prints_command():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        check("same_code_source_prints_command: the token is taken", SR.Driver._same_code_answer(r.d, "source", "", "S3") is True)
        check_eq("same_code_source_prints_command: nothing is sent to the controller", r.sent, [])
        answered(r, "source")
        r.d.answer_kind = "first_look_same_code"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                SR.Driver.first_look_code_look(r.d, ACTION)
            code = None
        except SR.Stop as stop:
            code = stop.code
        check_eq("same_code_source_prints_command: exit 0", code, SR.EXIT_DONE)
        check_in("same_code_source_prints_command: the restart command with where the code is", "python story_run.py --task QA-1 --branch <the branch with the code>", out.getvalue())
        check_in("same_code_source_prints_command: ... and the other two flags", "--mr <link>", out.getvalue())


def test_same_code_continue_uses_first_look_continue_operation_with_current_keys():
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        check("same_code_continue_uses_first_look_continue_operation_with_current_keys: the token is taken",
              SR.Driver._same_code_answer(r.d, "continue\nthe stand is old, go on", "", "S3") is True)
        heads, reg = FL.current_keys(r.task)
        expected = [("first_look_continue", ("--words-file", str(r.task / "state/words/answer.txt"), "--source-head", heads, "--register-hash", reg))]
        check_eq("same_code_continue_uses_first_look_continue_operation_with_current_keys: the SAME operation as `first_look.dead`, the keys of now",
                 [(op, args) for op, args, _i in r.sent], expected)
        check_eq("same_code_continue_uses_first_look_continue_operation_with_current_keys: the register hash is 64 hex", len(reg), 64)
        r.sent.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            SR.Driver._first_look_answer(r.d, "continue\nthe stand is old, go on", "", "S3")
        check_eq("same_code_continue_uses_first_look_continue_operation_with_current_keys: F4 - `first_look.dead`'s `continue` is the one method: the same call",
                 [(op, args) for op, args, _i in r.sent], expected)
        r.d.answer_file = lambda: ""
        r.sent.clear()
        try:
            SR.Driver._same_code_answer(r.d, "continue", "", "S3")
            held = None
        except SR.Person as person:
            held = person
        check("same_code_continue_uses_first_look_continue_operation_with_current_keys: no words file - the held question, nothing sent",
              held is not None and r.sent == [])


def test_stop_after_dead_question_does_not_ask_again():
    """The `stop` of `first_look.dead` is taken in this process and the loop's next `where` answers `awaiting_implementation`: it ends with the
    packet (exit 0) and never asks `first_look.same_code` over the answer just given (FL-5's executor + FL-6's reader meeting)."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.live = {MR: A}
        r.d.answer_kind = "first_look_dead"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                SR.Driver._act_await_implementation(r.d, ACTION)
            code = None
        except SR.Stop as stop:
            code = stop.code
        check_eq("stop_after_dead_question_does_not_ask_again: exit 0 with the first look's packet, no question, no remote call",
                 (code, r.asks(), "# First look report" in out.getvalue()), (SR.EXIT_DONE, [], True))


def test_packet_stop_day_is_never_invented():
    """N2: a hold with no `since` prints "an earlier day", not today's date."""
    with tempfile.TemporaryDirectory() as tmp:
        r = Rig(tmp)
        r.set_pipeline({"ticket": "QA-1", "environment": STAND, "awaiting": {"cause": "first_look_stop", "held_from": "S3"}})
        text = __import__("interim_packet").first_look_packet(r.task, "cmd")
        check_in("packet_stop_day_is_never_invented: the day is 'an earlier day'", "stopped on an earlier day after the first look", text)
        r.live = {MR: A}
        _b, raised, _ = r.look()
        check_in("packet_stop_day_is_never_invented: the question says the same", "stopped this story on an earlier day", str(raised.text))


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    return finish("test_first_look_code_look")


if __name__ == "__main__":
    sys.exit(main())
