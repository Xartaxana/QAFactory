"""FB-10: a receipt speaks for ONE test function; adding another test to the file changes nothing of it, and a
live check that went stale in a later window has a door (TP1-14857, 0.10.2).

The two-window fixture: a temp project whose `tests/test_pair.py` holds six tests, a conftest, a story with the
author's `--mine` job (so every `instance_contracts` is what `instance_shas` measures), manifest rows and a live
receipt per proven test built the way `probe_by_code._receipt_core` shapes it. "Window 2" is an edit of the file.

Identity v2 (execution_fingerprint._test_gaps) forgives exactly one difference, an ADDED top-level test function
with the gap before it; every other module-level change stales every sibling (axis 7: the allowed error is
"different"). The words after a level follow the `same_test` answer (R8). The scope door is `reprobe_admitted`.
Nothing here launches pytest or a model.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import check_delivery as CD  # noqa: E402
import execution_fingerprint as EF  # noqa: E402
import execution_request as ER  # noqa: E402
import ledger as LG  # noqa: E402
import probe_debt as DEBT  # noqa: E402
import proof_level as PL  # noqa: E402
import test_window_record as WT  # noqa: E402
import window_record as WR  # noqa: E402
from acceptance import _bound_to, run_freshness_of  # noqa: E402
from test_probe_binding import Fixture, row, write  # noqa: E402

WT.SHAS.setdefault("TC-1", "0" * 64)   # `live_body` reads its default raw sha here; every receipt below passes its own
FILE = "tests/test_pair.py"
CRITIC = "S5-qa-code-critic-1"
SCOPE = ("TC-1", "TC-2", "TC-3", "TC-4", "TC-5")
PAIR = "import pytest\n\nLIMIT = 3\n\n\n" + "".join(
    f"def {name}():\n    assert LIMIT == 3\n\n\n" for name in (
        "test_one", "test_two", "test_three", "test_four", "test_five", "test_six"))
PAIR = PAIR.rstrip("\n") + "\n"
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef db():\n    return 1\n"
PROVEN = ("test_one", "test_two", "test_five")
NEW_TEST = "\n\ndef test_seven():\n    assert 7 == 7\n"
SCOPE_TEXT = ("TC-1 is outside its scope: dispatch S5-qa-code-critic-1 was given TC-9. A dispatch runs only the "
              "cases it was given; nothing is wrong with your test. Hand the case back in your digest — the "
              "orchestrator dispatches it, or records the person's word for it (waiver.py, stage S5, block "
              "\"outside its scope\").")


def live_ref(iid: str) -> str:
    return f"work/sensitivity-receipts/{iid}-live-0123456789abcdef.json"


class Pair:
    """The project of window 1: rows, the author's job, and a live receipt for each of PROVEN."""

    def __init__(self, text: str = PAIR, receipts=PROVEN):
        rows = [row("test_one", "TC-1", FILE, sensitivity_proof_required=True),
                row("test_two", "TC-2", FILE, sensitivity_proof_required=True),
                row("test_three", "TC-3", FILE, sensitivity_proof_required=True),
                row("test_four", "TC-4", FILE),
                row("test_five", "TC-5", FILE, sensitivity_proof_required=True),
                row("test_six", "TC-5", FILE, sensitivity_proof_required=True)]
        self.fix = Fixture({FILE: text, "tests/conftest.py": CONFTEST}, rows, scope=SCOPE)
        self.root, self.task = self.fix.root, self.fix.task
        self.fix.job(list(SCOPE))
        for iid in receipts:
            self.receipt(iid)
        self.records()

    def manifest(self) -> dict:
        return json.loads((self.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))

    def entry(self, iid: str) -> dict:
        return next(t for t in self.manifest()["tests"] if t["instance_id"] == iid)

    def receipt(self, iid: str) -> None:
        now = PL.instance_identity(self.entry(iid), self.task, self.root)
        write(self.task / live_ref(iid), WT.live_body(
            instance_id=iid, case_version="cv_1", test_content_hash=now["input_hash"],
            test_code_sha=now["test_code_sha"], instance_identity=now["instance_identity"]))
        manifest = self.manifest()
        for test in manifest["tests"]:
            if test["instance_id"] == iid:
                path = self.task / live_ref(iid)
                test["sensitivity_proof"] = {"receipt_ref": {
                    "path": live_ref(iid), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}}
        write(self.task / "work" / "automation-manifest.json", manifest)

    def records(self) -> None:
        for iid in ("test_one", "test_two"):
            write(PL.probe_record_path(self.task, iid), {
                "schema_version": 1, "instance_id": iid, "case": "TC-1", "test_node": f"{FILE}::{iid}",
                "verdict": "intended_failure", "mutation": "invert", "mutation_detail": {"line": 2},
                "test_file_sha256": "0" * 64, "recorded_at": "2026-10-27T10:00:00+00:00",
                "publish": {"published": True}})

    def set_text(self, text: str) -> None:
        use_project(self.root)
        write(self.root / FILE, text)
        PL._reset()

    def how(self, iid: str) -> str:
        use_project(self.root)
        now = PL.instance_identity(self.entry(iid), self.task, self.root)
        receipt = json.loads((self.task / live_ref(iid)).read_text(encoding="utf-8"))
        return PL.same_test(now, PL.proof_identity(receipt))

    def reached(self, iid: str) -> dict:
        use_project(self.root)
        return PL.reached(self.entry(iid), self.manifest(), self.task)

    def readers(self, iid: str) -> tuple:
        """The four readers of "is this receipt current", each as a boolean."""
        use_project(self.root)
        entry, manifest = self.entry(iid), self.manifest()
        debt = DEBT.find(self.task, manifest, self.root)
        return (CD._sensitivity_state(entry, manifest, self.task)[0] == [],
                LG.proof_shown(entry, manifest, self.task)[0] == "live",
                PL.probe_freshness(entry, manifest, self.task)["state"] == "fresh",
                not [i for i in debt["items"] if i["instance_id"] == iid])

    def dispatch(self, role: str, scope=("TC-9",)) -> str:
        """The story's only dispatch: `role` scoped to `scope`."""
        did = CRITIC if role == "qa-code-critic" else "S5-qa-automator-2"
        state = {"schema_version": "2", "revision": "1", "source_revision": self.fix.provenance["expected_source_revision"],
                 "dispatches": {did: {"id": did, "stage": "S5", "role": role, "status": "running",
                                      "scope": list(scope), "budget": {"requests": 50}}}}
        write(self.task / "state" / "controller.json", state)
        return did

    def close(self) -> None:
        self.fix.close()


def probe(pair: Pair, cases, did: str, **over):
    """`build_mine_request` as the red probe of the critic asks it: (request, notes) or the refusal text."""
    args = dict(cfg=pair.fix.cfg, task="BIND-1", dispatch_id=did, purpose="red_probe", again=True, reason="probe",
                probe=lambda spec: pair.fix.provenance, cwd=str(pair.root))
    args.update(over)
    use_project(pair.root)
    PL._reset()
    try:
        request, notes, _reuse, _verified = ER.build_mine_request(pair.root, cases, **args)
        return request, notes, ""
    except ER.MineRefusal as exc:
        return None, [], str(exc)


# --- K-L1 / K-L2: the code sha is byte-equal to the one before identity v2 ----------------------------------------

FIXTURES = {
    "plain": "import pytest\n\nLIMIT = 3\n\n\ndef test_one():\n    assert LIMIT\n\n\ndef test_two():\n    assert 1\n",
    "crlf": "import pytest\r\n\r\nLIMIT = 3\r\n\r\n\r\ndef test_one():\r\n    assert LIMIT\r\n\r\n\r\ndef test_two():\r\n    assert 1\r\n",
    "no_final_newline": "import pytest\n\nLIMIT = 3\n\n\ndef test_one():\n    assert LIMIT\n\n\ndef test_two():\n    assert 1",
    "module_string": 'import pytest\n\nDOC = """first\n\nsecond\n\n\nthird"""\n\n\ndef test_one():\n    assert DOC\n\n\n# about two\n\ndef test_two():\n    assert 1\n',
    "comments": "# header\nimport pytest\n\n# about LIMIT\nLIMIT = 3  # trailing\n\n\n# about one\n@pytest.mark.skipif(False, reason='x')\ndef test_one():\n    # inside\n    assert LIMIT\n\n\n# about two\n\ndef test_two():\n    assert 1\n\n# tail\n",
    "test_class": "LIMIT = 3\n\n\ndef test_one():\n    assert LIMIT\n\n\nclass TestGroup:\n\n    def test_in(self):\n        assert 1\n",
}
# BEFORE the edit (HEAD 67f4c5b5), `function_sha(<file>, "test_one", (), [])["code_sha"]`, produced by running the old
# `execution_fingerprint.py` (git show HEAD:...) over exactly these bytes: scratchpad kl1/before_old_full.py.
CODE_BEFORE = {
    "plain": "91f0d6736233a083b148283a71fff948ba5a02057f467ce3d45cfdeb277c9ad5",
    "crlf": "0d9ecde48ab42676713db671340e4315e72b741d92aba2ffcc29a46a3eea65a2",
    "no_final_newline": "a865b0cafce395634b3ba7cf608aa55bfb2ece2c9aec6a9ff2cdaffda22deb90",
    "module_string": "c2e748b7f504d82ae0e725403fe2c58ac7807443f04eb167471b9b931b648f7a",
    "comments": "d38a388571a762341e92e5e12d0ddf4c3e2774af787234f6d56b01731b095129",
    "test_class": "a36fb685b437eec81f1a5e44de02056aaa02cd802aad58de8f488ef2c1f6c064",
}
CONTENT_BEFORE_PLAIN = "b9ad832e3c09808422d0fccfff7cf172372567e943af813ea88e69119eae9397"


def code_sha_equal_to_today():
    folder = Path(tempfile.mkdtemp(prefix="qa-receipts-fn-"))
    try:
        for name, text in FIXTURES.items():
            path = folder / (name + ".py")
            path.write_bytes(text.encode("utf-8"))
            got = EF.function_sha(path, "test_one", (), [])
            check_eq(f"K-L1 {name}: the v2 code sha equals the value before the rule change", got["code_sha"],
                     CODE_BEFORE[name])
        plain = EF.function_sha(folder / "plain.py", "test_one", (), [])
        check("K-L2 control: the raw content sha MOVED (blank lines outside spans are cut)",
              plain["sha"] != CONTENT_BEFORE_PLAIN)
        # a carrier recorded under 0.10.2 (old content sha, same code sha) over unchanged bytes
        now = {"instance_content_sha": plain["sha"], "instance_code_sha": plain["code_sha"], "job_id": "j"}
        old = {"instance_content_sha": CONTENT_BEFORE_PLAIN, "instance_code_sha": CODE_BEFORE["plain"], "job_id": "j"}
        item = {"instance_id": "t", "input_hash": "a" * 64, "test_code_sha": "c" * 64, "instance_identity": now,
                "run_identity": {"instance_content_sha": old["instance_content_sha"],
                                 "instance_code_sha": old["instance_code_sha"]}}
        review = {"verdict": "approved", "input_hash": "b" * 64, "test_code_sha": "d" * 64, "instance_identity": old}
        check_eq("K-L2 same_test: a 0.10.2 identity over unchanged bytes is the same test by code",
                 PL.same_test(PL.proof_identity(item), PL.proof_identity(review)), "instance_code")
        check_eq("K-L2 acceptance._bound_to: a 0.10.2 review block stays bound", _bound_to(item, review, {}, None), True)
        check_eq("K-L2 acceptance.run_freshness_of: a 0.10.2 run row stays fresh", run_freshness_of(item)[0], "fresh")
        check_eq("K-L2 reached words: the receipt holds with the code-unchanged words",
                 PL.held_words(PL.same_test(PL.proof_identity(item), PL.proof_identity(review))),
                 PL.code_unchanged_words())
    finally:
        cleanup(folder)


# --- K-A: the append, the battery, the unparseable file ----------------------------------------------------------

def append_alone_is_exact():
    pair = Pair()
    try:
        check_eq("control: the receipts stand on the bytes they measured",
                 [(pair.how(i), pair.reached(i)["level"]) for i in PROVEN], [("instance", "live")] * 3)
        for name, extra in (
                ("K-A1 a test appended alone", NEW_TEST),
                ("K-A1 appended with a comment block directly above it (E2)", "\n\n# about seven\n# and more\ndef test_seven():\n    assert 7\n"),
                ("K-A1 appended with decorators, async (E1)", "\n\n@pytest.mark.skip\nasync def test_seven():\n    assert 7\n")):
            pair.set_text(PAIR + extra)
            for iid in PROVEN:
                got = pair.reached(iid)
                check_eq(f"{name}: {iid} is the same test, shown with no suffix", (pair.how(iid), got["words"]),
                         ("instance", PL.words("live")))
        # K-A5 a Test class appended: the code is equal, the comment above it is part of the skeleton (E3)
        pair.set_text(PAIR + "\n\n# the group\nclass TestGroup:\n    def test_in(self):\n        assert 1\n")
        for iid in PROVEN:
            check_eq(f"K-A5 a Test class appended: {iid} keeps its code, and the words say so",
                     (pair.how(iid), pair.reached(iid)["words"]),
                     ("instance_code", f"{PL.words('live')} ({PL.code_unchanged_words()})"))
        # a comment-only change after an addition: the label must not lie
        pair.set_text((PAIR + NEW_TEST).replace("def test_one():\n", "def test_one():\n    # a note\n"))
        check_eq("K-W a comment in test_one after an addition: its words are the code-unchanged ones, test_two's are none",
                 (pair.how("test_one"), pair.reached("test_one")["words"], pair.how("test_two"), pair.reached("test_two")["words"]),
                 ("instance_code", f"{PL.words('live')} ({PL.code_unchanged_words()})", "instance", PL.words("live")))
    finally:
        pair.close()


MEMBERS = {
    "a plugin fixture override (tmp_path_factory)": "import pytest\n\n\n@pytest.fixture\ndef tmp_path_factory():\n    raise RuntimeError('x')\n",
    "b class with a body statement": "import os\n\n\nclass Helper:\n    TOKEN = os.environ['X']\n",
    "c class with a base and a metaclass": "class Base:\n    pass\n\n\nclass P(Base, metaclass=type):\n    pass\n",
    "d default evaluated at import": "def helper(x=load()):\n    return x\n",
    "d annotation evaluated at import": "def helper(x: resolve()):\n    return x\n",
    "e subscript that can raise": "import os\n\nX = os.environ['MISSING']\n",
    "e name that can raise": "X = NOT_DEFINED\n",
    "f second name from an import": "from x import y2\n",
    "f stdlib import": "import os\n",
    "g nose setup": "def setup():\n    pass\n",
    "h fixture reached by a computed string": "import pytest\n\n\n@pytest.fixture\ndef db_a():\n    return 1\n",
    "pytestmark": "import pytest\n\npytestmark = pytest.mark.skip\n",
    "autouse fixture": "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef boot():\n    return 1\n",
    "assign with a call": "RESULT = compute()\n",
    "constant only another test reads": "OTHER = 5\n",
}


def module_change_with_an_append_stales_both():
    pair = Pair()
    try:
        for member, snippet in MEMBERS.items():
            pair.set_text(PAIR + "\n\n" + snippet + NEW_TEST.replace("7 == 7", "OTHER == 5" if "OTHER" in snippet else "7 == 7"))
            for iid in ("test_one", "test_two"):
                check_eq(f"K-A2 [{member}] appended with a new test: {iid} is stale (both shas moved)",
                         (pair.how(iid), pair.reached(iid)["level"]), ("", None))
    finally:
        pair.close()


def unparseable_file_goes_stale_on_append():
    bad = PAIR.replace("def test_one():\n    assert LIMIT == 3\n", "def test_one():\n    assert LIMIT ==\n")
    pair = Pair(text=bad, receipts=("test_one",))
    try:
        check_eq("K-A3 AT the boundary (equal bytes) the level is shown",
                 (pair.how("test_one"), pair.reached("test_one")["level"]), ("instance", "live"))
        pair.set_text(bad + NEW_TEST)
        check_eq("K-A3 BEYOND it (one test appended) the file is the identity: stale",
                 (pair.how("test_one"), pair.reached("test_one")["level"]), ("", None))
    finally:
        pair.close()


def editing_the_function_goes_stale():
    pair = Pair()
    try:
        pair.set_text(PAIR.replace("def test_one():\n    assert LIMIT == 3", "def test_one():\n    assert LIMIT >= 3"))
        check_eq("K-A4 the body of test_one edited: test_one stale, test_two the same test",
                 (pair.how("test_one"), pair.how("test_two")), ("", "instance"))
        pair.set_text(PAIR + "\n\ndef test_one():\n    assert 0\n")
        check_eq("K-A4 test_one defined twice (E4): test_one stale, test_two untouched",
                 (pair.how("test_one"), pair.how("test_two")), ("", "instance"))
    finally:
        pair.close()


def one_predicate_everywhere():
    """K-P1: delivery, the ledger, the S6 freshness and the probe debt answer alike, whatever the edit."""
    pair = Pair()
    try:
        edits = {
            "control": PAIR,
            "appended alone": PAIR + NEW_TEST,
            "comment above": PAIR + "\n\n# note\ndef test_seven():\n    assert 7\n",
            "Test class": PAIR + "\n\n# group\nclass TestGroup:\n    def test_in(self):\n        assert 1\n",
            "body edited": PAIR.replace("def test_one():\n    assert LIMIT == 3", "def test_one():\n    assert LIMIT >= 3"),
            "redefinition": PAIR + "\n\ndef test_one():\n    assert 0\n",
            "module change": PAIR.replace("LIMIT = 3", "LIMIT = 4"),
        }
        expect = {"body edited": {"test_one": False, "test_two": True}, "redefinition": {"test_one": False, "test_two": True},
                  "module change": {"test_one": False, "test_two": False}}
        for name, text in edits.items():
            pair.set_text(text)
            for iid in ("test_one", "test_two"):
                got = pair.readers(iid)
                want = expect.get(name, {}).get(iid, True)
                check_eq(f"K-P1 [{name}] {iid}: the four readers agree ({got}) and say current={want}",
                         (len(set(got)) == 1, got[0]), (True, want))
    finally:
        pair.close()


# --- K-W: the label follows the same_test answer ------------------------------------------------------------------

def the_words_follow_the_answer():
    check_eq("K-W1 instance and raw: no words", [PL.held_words("instance"), PL.held_words("raw"), PL.held_words("")],
             ["", "", ""])
    check_eq("K-W2 instance_code: the code-unchanged words", PL.held_words("instance_code"), PL.code_unchanged_words())
    check_eq("K-W3 file_code: the comment-only words (the whole file's code is equal)", PL.held_words("file_code"),
             PL.comment_only_words())
    ident = {"instance_content_sha": "n1", "instance_code_sha": "k", "job_id": "j"}
    other = dict(ident, instance_content_sha="n0")
    cases = {"instance": (ident, ident, None), "instance_code": (ident, other, None), "file_code": ({}, {}, "same")}
    for how, (now_id, bound_id, code) in cases.items():
        item = {"instance_id": "t", "outcome": "green", "input_hash": "a" * 64, "test_code_sha": "c" * 64,
                "instance_identity": now_id}
        proof = {"verdict": "approved", "input_hash": "a" * 64 if how == "instance" else "b" * 64,
                 "test_code_sha": "c" * 64, "instance_identity": bound_id}
        info: list = []
        WR._comment_only({"instances": [item | {"review": proof}]}, info)
        want = [] if how == "instance" else [f"t: the review holds; {PL.held_words(how)}"]
        check_eq(f"K-W window_record._comment_only [{how}]: the info line uses the same choice", info, want)


# --- K-D: the door ------------------------------------------------------------------------------------------------

def the_door_for_a_stale_check():
    pair = Pair()
    try:
        did = pair.dispatch("qa-code-critic")
        # K-D2 (fresh): a check that still stands is not stale -> refused with today's sentence
        _r, _n, refusal = probe(pair, ["TC-1"], did, node_ids=[f"{FILE}::test_one"])
        check_eq("K-D2 [fresh] refused, text == scope_refusal == today's literal", (refusal, refusal),
                 (SCOPE_TEXT, ER.scope_refusal(["TC-1"], did, ["TC-9"], "S5")))
        pair.set_text(PAIR.replace("LIMIT = 3", "LIMIT = 4"))
        request, notes, refusal = probe(pair, ["TC-1"], did, node_ids=[f"{FILE}::test_one"])
        check_eq("K-D1 a stale re-probe outside the scope, node_ids, the critic: admitted", (refusal, bool(request)), ("", True))
        check("K-D1 the note says why and that no review is claimed",
              any("admitted as a re-probe of a live check that went stale (test_one)" in n
                  and "its review is not re-checked here" in n for n in notes), str(notes))
        request, notes, refusal = probe(pair, ["TC-1"], did)
        check_eq("K-D1 without node_ids (manifest rows of the case): admitted too", (refusal, bool(request)), ("", True))
        refused = {
            "missing receipt (TC-3)": dict(cases=["TC-3"], node_ids=[f"{FILE}::test_three"]),
            "not required (TC-4)": dict(cases=["TC-4"], node_ids=[f"{FILE}::test_four"]),
            "two rows, one missing (TC-5)": dict(cases=["TC-5"], node_ids=None),
            "purpose initial": dict(cases=["TC-1"], purpose="initial"),
            "purpose repair_verify": dict(cases=["TC-1"], purpose="repair_verify"),
            "a node with no row": dict(cases=["TC-1"], node_ids=[f"{FILE}::test_nowhere"]),
            "a node of another file (M10)": dict(cases=["TC-1"], node_ids=["tests/test_other.py::test_one"]),
            "node_ids with two cases": dict(cases=["TC-1", "TC-2"], node_ids=[f"{FILE}::test_one"]),
        }
        for name, over in refused.items():
            cases = over.pop("cases")
            _r, _n, refusal = probe(pair, cases, did, **over)
            check_eq(f"K-D2 [{name}] stays refused with the one sentence",
                     refusal, ER.scope_refusal(cases, did, ["TC-9"], "S5"))
        # E17: build_mine_request refuses dispatch_id + evidence_only before the door, so the guard is asked directly
        use_project(pair.root)
        PL._reset()
        dispatch_record = {"id": did, "role": "qa-code-critic"}
        ask = lambda only: ER._admitted_outside(["TC-1"], ["TC-1"], [f"{FILE}::test_one"], pair.manifest(), pair.task,
                                                dispatch_record, "red_probe", only)
        check_eq("K-D2 [evidence_only (E17)] control: the same ask without evidence_only is admitted", ask(False)[0], True)
        check_eq("K-D2 [evidence_only (E17)] a read is never admitted outside the scope", ask(True), (False, []))
        other = pair.dispatch("qa-automator")
        _r, _n, refusal = probe(pair, ["TC-1"], other, node_ids=[f"{FILE}::test_one"])
        check_eq("K-D2 [role is not qa-code-critic] stays refused", refusal, ER.scope_refusal(["TC-1"], other, ["TC-9"], "S5"))
        (pair.root / FILE).rename(pair.root / "tests" / "gone.py")
        PL._reset()
        _r, _n, refusal = probe(pair, ["TC-1"], pair.dispatch("qa-code-critic"), node_ids=[f"{FILE}::test_one"])
        check_eq("K-D2 [unknown: the test file is gone] stays refused", refusal,
                 ER.scope_refusal(["TC-1"], CRITIC, ["TC-9"], "S5"))
    finally:
        pair.close()


def reprobe_admitted_never_raises():
    pair = Pair()
    try:
        pair.set_text(PAIR.replace("LIMIT = 3", "LIMIT = 4"))
        use_project(pair.root)
        manifest, task = pair.manifest(), pair.task
        check_eq("K-D4 control: a stale row is admitted", PL.reprobe_admitted(pair.entry("test_one"), manifest, task), (True, ""))
        for name, args in {"entry None": (None, manifest, task), "entry {}": ({}, manifest, task),
                           "manifest None": (pair.entry("test_one"), None, task),
                           "task_root missing": (pair.entry("test_one"), manifest, Path(tempfile.gettempdir()) / "qa-no-such-task"),
                           "task_root None": (pair.entry("test_one"), manifest, None)}.items():
            got = PL.reprobe_admitted(*args)
            ok = (got[0] is True and got[1] == "") if name == "manifest None" else (got[0] is False and bool(got[1]))
            check(f"K-D4 [{name}] never raises; {'the row alone is still stale' if name == 'manifest None' else 'not admitted'}",
                  ok and isinstance(got[1], str), str(got))
        missing = PL.reprobe_admitted(pair.entry("test_three"), manifest, task)
        check_eq("K-D4 a row with no receipt (missing) is not admitted, with the state's why", missing,
                 (False, PL.WHY_PROBE_MISSING))
    finally:
        pair.close()


def settle_uses_the_same_predicate():
    import test_probe_debt as TD
    w = TD.world(scope=("TC-1",))
    try:
        TD.put_manifest(w, [TD.row(w, "test_a"), TD.row(w, "test_b", case="TC-9"), TD.row(w, "test_c", case="TC-8")])
        for iid in ("test_a", "test_b", "test_c"):
            TD.record(w, iid)
        # test_b has a receipt for other bytes (stale); test_c has none (missing)
        write(w.task_root / live_ref("test_b"), WT.live_body(instance_id="test_b", case_version="cv_x",
                                                            test_content_hash="e" * 64, test_code_sha="f" * 64))
        manifest = json.loads((w.task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        for test in manifest["tests"]:
            if test["instance_id"] == "test_b":
                digest = __import__("hashlib").sha256((w.task_root / live_ref("test_b")).read_bytes()).hexdigest()
                test["sensitivity_proof"] = {"receipt_ref": {"path": live_ref("test_b"), "sha256": digest}}
        TD.put_manifest(w, manifest["tests"])
        PL._reset()
        check_eq("K-D3 control: test_b is stale, test_c is missing",
                 [PL.reprobe_admitted(TD.D._row_named(w.manifest, i), w.manifest, w.task_root)[0] for i in ("test_b", "test_c")],
                 [True, False])
        stub = TD.Stub(w)
        doc = TD.settle(w, stub)
        check_eq("K-D3 the stale item outside the scope is probed, the missing one is left", stub.kinds(), ["probe:test_a", "probe:test_b"])
        left = {i["instance_id"]: i for i in doc["left"]}
        outcome = next(o for o in doc["outcomes"] if o["result"] == "outside_scope")
        check_eq("K-D3 the left item says the one sentence (scope_refusal), as the outcome does",
                 (sorted(left), left["test_c"]["reason_words"], outcome["words"]),
                 (["test_c"], ER.scope_refusal(["TC-8"], TD.CRITIC, ["TC-1"], "S5"), ER.scope_refusal(["TC-8"], TD.CRITIC, ["TC-1"], "S5")))
    finally:
        TD.cleanup(w.project)


# --- K-D5 / K-D5n / K-D6: the rebind and the second asking (R6a, R6b) -------------------------------------------

def rebind_world(hand_edit: bool):
    """A seeded story (`test_manifest_from_tests.seed`) whose `test_limit` row holds a live receipt, the proof flag and
    an obligation binding; two REAL `manifest_from_tests.py` runs with a module-level edit between. R6a: the proof is in
    the file BEFORE the first run (the seed path) - never written into the projection after `events.jsonl` exists,
    unless `hand_edit` (K-D5n, the guard against repeating that experiment)."""
    import hashlib
    import test_manifest_from_tests as MFT
    fix = Fixture({}, [])
    root = fix.root
    (root / "tests").mkdir(exist_ok=True)
    task = MFT.seed(root)
    links = json.loads((task / "state" / "story-case-links.json").read_text(encoding="utf-8"))["links"]
    version = next(link["version"] for link in links if link["case_id"] == "TC-001")
    ref_path = "work/sensitivity-receipts/test_limit-live-0123456789abcdef.json"
    write(task / ref_path, WT.live_body(instance_id="test_limit", case_version=version, test_content_hash="e" * 64,
                                        test_code_sha="f" * 64))
    ref = {"path": ref_path, "sha256": hashlib.sha256((task / ref_path).read_bytes()).hexdigest()}
    proof = {"sensitivity_proof": {"receipt_ref": ref}, "sensitivity_proof_required": True}
    binding = {"obligation_id": "TS-1-O1", "obligation_hash": "h", "instance_ids": ["test_limit"],
               "sensitivity": "proven", "probe_receipt_ref": ref_path}
    path = task / "work" / "automation-manifest.json"

    def put_in_file():
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["tests"].append({"case": "TC-001", "covers": ["TC-001"], "file": "tests/test_coupon.py",
                             "test": "test_limit", "instance_id": "test_limit", "status": "green", **proof})
        doc["obligation_bindings"] = [binding]
        write(path, doc)

    def row_of():
        doc = json.loads(path.read_text(encoding="utf-8"))
        return next(t for t in doc["tests"] if t["instance_id"] == "test_limit"), doc

    if not hand_edit:
        put_in_file()
    first = MFT.run(root)
    if hand_edit:
        doc = json.loads(path.read_text(encoding="utf-8"))
        next(t for t in doc["tests"] if t["instance_id"] == "test_limit").update(proof)
        doc["obligation_bindings"] = [binding]
        write(path, doc)
    before, before_doc = row_of()
    source = root / "tests" / "test_coupon.py"
    source.write_text(source.read_text(encoding="utf-8").replace("import pytest\n", "import pytest\n\nLIMIT_EXTRA = 1\n", 1),
                      encoding="utf-8")
    second = MFT.run(root)
    after, after_doc = row_of()
    return dict(fix=fix, task=task, root=root, rcs=(first.returncode, second.returncode), before=before, after=after,
                bindings=(before_doc.get("obligation_bindings"), after_doc.get("obligation_bindings")), manifest=after_doc)


def admission_survives_the_rebind():
    w = rebind_world(hand_edit=False)
    try:
        before, after = w["before"], w["after"]
        check_eq("K-D5 both real rebinds exit 0", w["rcs"], (0, 0))
        check_eq("K-D5 the row's bound sha MOVED (the rebind re-bound the bytes)",
                 before["trace_binding"]["test_content_sha"] != after["trace_binding"]["test_content_sha"], True)
        check_eq("K-D5 the receipt ref, the proof flag and case_version_links are kept (E19a)",
                 [after.get(k) for k in ("sensitivity_proof", "sensitivity_proof_required", "case_version_links")],
                 [before.get(k) for k in ("sensitivity_proof", "sensitivity_proof_required", "case_version_links")])
        check_eq("K-D5 the obligation binding is kept", w["bindings"][1], w["bindings"][0])
        use_project(w["root"])
        PL._reset()
        check_eq("K-D5 reprobe_admitted on the re-read row: (True, '')",
                 PL.reprobe_admitted(after, w["manifest"], w["task"]), (True, ""))
        did = "S5-qa-code-critic-1"
        write(w["task"] / "state" / "controller.json", {"dispatches": {did: {
            "id": did, "stage": "S5", "role": "qa-code-critic", "status": "running", "scope": ["TC-009"]}}})
        fix = w["fix"]
        request, notes, _reuse, _verified = ER.build_mine_request(
            w["root"], ["TC-001"], cfg=fix.cfg, task="QA-700", dispatch_id=did, purpose="red_probe", again=True,
            reason="probe", node_ids=["tests/test_coupon.py::test_limit"], probe=lambda spec: fix.provenance,
            cwd=str(w["root"]))
        check("K-D5 the real build_mine_request admits it, with the note",
              any("admitted as a re-probe of a live check that went stale (test_limit)" in n for n in notes), str(notes))
    finally:
        w["fix"].close()


def hand_edit_after_journal_is_not_the_writer():
    w = rebind_world(hand_edit=True)
    try:
        check_eq("K-D5n a proof written into the projection AFTER events.jsonl exists is gone after the rebind "
                 "(why R6a forbids that fixture)",
                 (w["before"].get("sensitivity_proof") is not None, w["after"].get("sensitivity_proof")), (True, None))
    finally:
        w["fix"].close()


def settle_asks_again_after_the_rebind():
    import hashlib
    import test_probe_debt as TD

    class Rebinder(TD.Stub):
        """The stub rebind, then what a REAL rebind may change: re-pin a case version, store no novelty."""

        def _manifest(self, args):
            got = super()._manifest(args)
            if "--dry-run" not in args and not self.write_rc:
                path = self.w.task_root / "work" / "automation-manifest.json"
                doc = json.loads(path.read_text(encoding="utf-8"))
                for test in doc["tests"]:
                    if test["instance_id"] in ("test_repin", "test_word", "test_both", "test_late"):
                        test["case_version_links"] = [{"case_id": test["case"], "version": "cv_new"}]
                    if test["instance_id"] == "test_nov":
                        test.pop("novelty", None)
                write(path, doc)
            return got
    w = TD.world(scope=("TC-1",))
    try:
        ids = {"test_repin": "TC-9", "test_nov": "TC-8", "test_keep": "TC-7", "test_word": "TC-6", "test_both": "TC-6",
               "test_late": "TC-5"}
        rows = []
        for iid, case in ids.items():   # test_late binds the current bytes: no rebind of its own (a REPROBE item)
            rows.append(TD.row(w, iid, bound=None if iid == "test_late" else "old", case=case,
                               required=iid in ("test_repin", "test_keep", "test_word", "test_both", "test_late"),
                               **({"novelty": {"value": "changed", "basis": "x"}} if iid == "test_nov" else {})))
            TD.record(w, iid)
        for test in rows:
            if test["instance_id"] != "test_word":   # the word item has NO receipt: only a person's word opens it
                ref = f"work/sensitivity-receipts/{test['instance_id']}-live-0123456789abcdef.json"
                write(w.task_root / ref, WT.live_body(instance_id=test["instance_id"], case_version="cv_x",
                                                      test_content_hash="e" * 64, test_code_sha="f" * 64))
                digest = hashlib.sha256((w.task_root / ref).read_bytes()).hexdigest()
                test["sensitivity_proof"] = {"receipt_ref": {"path": ref, "sha256": digest}}
        TD.put_manifest(w, rows)
        word_text = ER.scope_refusal(["TC-6"], TD.CRITIC, ["TC-1"], "S5")   # the person's word is for test_word's case only
        write(w.task_root / "pipeline.json", {"stage_overrides": [{
            "stage": "S5", "match": word_text, "decision": "go on", "at": "2026-09-30T06:00:00+00:00"}]})
        PL._reset()
        stub = Rebinder(w)
        doc = TD.settle(w, stub)
        probed = [k.split(":")[1] for k in stub.kinds() if k.startswith("probe:")]
        left = {i["instance_id"]: i for i in doc["left"]}
        check_eq("K-D6 re-pinned case version and dropped novelty: no probe; a kept rebind, a word item and a stale+word item are probed",
                 sorted(probed), ["test_both", "test_keep", "test_word"])
        for iid, case in {"test_repin": "TC-9", "test_nov": "TC-8", "test_late": "TC-5"}.items():   # F3: late = an earlier rebind re-pinned it
            outcome = next(o for o in doc["outcomes"] if o["instance_id"] == iid and o["result"] == "outside_scope")
            check_eq(f"K-D6 [{iid}] left with reason scope, the words are scope_refusal",
                     (left[iid]["reason"], outcome["words"]),
                     ("scope", ER.scope_refusal([case], TD.CRITIC, ["TC-1"], "S5")))
        check_eq("K-D6 [word_item_survives_the_rebind] a person's word stays a word across the rebind",
                 "test_word" in left, False)
        check_eq("K-D6 [stale_and_word_item_survives_the_rebind] a stale receipt AND a word: the word passes it (F1)",
                 "test_both" in left, False)
    finally:
        TD.cleanup(w.project)


def main():
    code_sha_equal_to_today()
    append_alone_is_exact()
    module_change_with_an_append_stales_both()
    unparseable_file_goes_stale_on_append()
    editing_the_function_goes_stale()
    one_predicate_everywhere()
    the_words_follow_the_answer()
    the_door_for_a_stale_check()
    reprobe_admitted_never_raises()
    settle_uses_the_same_predicate()
    admission_survives_the_rebind()
    hand_edit_after_journal_is_not_the_writer()
    settle_asks_again_after_the_rebind()
    finish("test_receipts_per_function")


if __name__ == "__main__":
    main()
