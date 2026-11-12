"""proof_level.py: the one reader of the proof-level vocabulary (D-0010, D-0012).

Every reader of "how sure are we that this test's check works" used to carry its own idea of a
receipt: `acceptance` demanded a product mutation of every probe, three modules spelled "is a proof
required" by hand, `window_record` read two receipt shapes with two rules. Here that one module is
held to the spec, rule by rule: the vocabulary file (present, absent, malformed), `level_of`'s five
rules in their order, the one `proof_required` predicate, `reached()` over the receipts a row can
name (valid, invalid, both levels, tie), and the facts a receipt binds.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))
import acceptance  # noqa: E402
import contract as C  # noqa: E402
import proof_level as PL  # noqa: E402
import red_sandbox as RS  # noqa: E402

SHIPPED = PL.LEVELS_FILE

# The rows below name a REAL test file under a real project: "the current bytes of a row's test"
# have one reader, the file on disk (Amendment 2 of t-016), so a row with an invented sha proves
# nothing any more. SHA_NOW is that file's raw sha256, as manifest_from_tests.py writes it.
TEST_REL = "tests/test_x.py"
TEST_SRC = "def test_x():\n    assert 1 + 1 == 2\n"
PROJECT = {"root": None, "sha": ""}


def sha_now() -> str:
    return PROJECT["sha"]


def the_project() -> Path:
    root = temp_dir("qa-levels-project-")
    write(root / "qa-factory" / "config.json", {"tests_root": "tests"})
    write(root / TEST_REL, TEST_SRC)
    use_project(root)
    PROJECT.update(root=root, sha=digest(root / TEST_REL))
    return root


def write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=1), encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt(iid="i1", **over) -> dict:
    """A receipt `contract.sensitivity_proof_issues` accepts, in the pre-change red_sandbox shape."""
    body = {"instance_id": iid, "case_version": "cv_x", "test_content_hash": sha_now(),
            "source_revision": "src", "build_id": "build", "mutation": "real_behavior",
            "expected_assertion_failure": "denied", "actual_failure": "denied",
            "assertion_location": "t.py:4", "restoration_evidence": "restored",
            "failure_kind": "assertion", "immutable": True, "receipt_hash": "h-" + iid}
    body.update(over)
    return body


def put(task: Path, name: str, body: dict) -> dict:
    path = write(task / "work" / "sensitivity-receipts" / f"{name}.json", body)
    return {"path": path.relative_to(task).as_posix(), "sha256": digest(path)}


def entry(iid="i1", **over) -> dict:
    row = {"instance_id": iid, "case": "TC-1", "covers": ["TC-1"], "file": TEST_REL,
           "case_version_links": [{"case_id": "TC-1", "version": "cv_x"}],
           "new_or_changed": True, "trace_binding": {"test_content_sha": sha_now()}}
    row.update(over)
    return row


def live(iid="i1", **over) -> dict:
    base = {"mutation": "invert", "proof_level": PL.LIVE, "probe_tool": "probe_by_code.py",
            "mutation_kind": "assertion"}
    base.update(over)
    return receipt(iid, **base)


def binding(iid, ref, *, oid="OB-1") -> dict:
    return {"obligation_id": oid, "instance_ids": [iid], "sensitivity": "proven",
            "proof_kind": "executed_red_probe", "probe_receipt_ref": ref["path"]}


# --- the vocabulary file: present, absent, malformed --------------------------------------------

def the_shipped_vocabulary():
    PL._reset()
    doc = PL.document()
    rows = PL.levels()
    check_eq("the shipped file has the two levels, lowest rank first",
             [(r["id"], r["rank"]) for r in rows], [("live", 1), ("catches_broken_product", 2)])
    check_eq("their words are the owner's", [r["words"] for r in rows],
             ["the check is live", "catches a broken product"])
    check_eq("only the live level is required (D-0012: new or changed tests)",
             [r["required"] for r in rows], [True, False])
    check_eq("producers", [r["producer"] for r in rows], ["probe_by_code.py", "red_sandbox.py --probe"])
    check_eq("mutation kinds are data, not code", [r["mutation_kinds"] for r in rows],
             [["assertion"], ["real_behavior"]])
    check_eq("no level and unchanged tests have their own words",
             (PL.words(None), PL.not_required_words()), ("not probed", "not probed (unchanged test)"))
    check_eq("a handed test has its own words, in data (t-134 R6)",
             (PL.handed_words(), doc["handed_words"]),
             ("not probed (handed to the person)", "not probed (handed to the person)"))
    check_eq("R1: the vocabulary carries no words of its own for a legacy row (owner decision 30.09)",
             ("unmeasured_words" in doc, hasattr(PL, "unmeasured_words")), (False, False))
    check_eq("R1: a handed test never reads with the unchanged words",
             PL.handed_words() != PL.not_required_words(), True)
    check_eq("and bytes nobody can read have theirs: unknown, never 'not probed' (FR-41)",
             PL.unknown_words(), "proof level unknown (the test file cannot be found)")
    check_eq("and a receipt kept over a comment-only change says so", PL.comment_only_words(),
             "the receipt holds over a comment-only change")
    check_eq("FB-10: the words of an unchanged-code passage are the vocabulary's own, not the comment-only ones",
             (PL.code_unchanged_words(), PL.code_unchanged_words() != PL.comment_only_words()),
             ("the receipt holds: the test's code is the same as when it was proven", True))
    check_eq("review words cover every verdict and the absence of one",
             sorted(doc["review_words"]), ["", "approved", "approved_with_fixes", "rejected", "unverified"])
    check_eq("unverified is never the word for a rejection",
             (PL.review_words("unverified"), PL.review_words("rejected")),
             ("the code critic could not verify it", "rejected by the code critic"))
    check_eq("no verdict at all", PL.review_words(None), "review not recorded")
    check_in("a verdict the vocabulary lacks is said, not swallowed",
             "not recognised", PL.review_words("Unverified"))
    check_eq("an id the vocabulary lacks is said, not dressed as 'not probed'",
             PL.words("mystery"), "unknown proof level mystery")
    check_eq("the vocabulary is loaded once", PL.document() is doc, True)
    check_eq("rank of none and of an unknown id is below every level",
             (PL.rank(None), PL.rank("mystery"), PL.rank("live")), (0, 0, 1))


def the_vocabulary_is_absent_or_malformed():
    tmp = temp_dir("qa-levels-")
    try:
        good = json.loads(SHIPPED.read_text(encoding="utf-8"))
        cases = {
            "absent": None,
            "not json": "{ nope",
            "not an object": "[1, 2]",
            "no levels": {**good, "levels": []},
            "a level without words": {**good, "levels": [{**good["levels"][0], "words": ""}]},
            "a rank twice": {**good, "levels": [good["levels"][0], {**good["levels"][1], "rank": 1}]},
            "an id twice": {**good, "levels": [good["levels"][0], {**good["levels"][1], "id": "live"}]},
            "a rank that is not a number": {**good, "levels": [{**good["levels"][0], "rank": "1"}]},
            "no none_words": {k: v for k, v in good.items() if k != "none_words"},
            "no unknown_words": {k: v for k, v in good.items() if k != "unknown_words"},
            "no handed_words": {k: v for k, v in good.items() if k != "handed_words"},
            "empty handed_words": {**good, "handed_words": ""},
            "no comment_only_words": {k: v for k, v in good.items() if k != "comment_only_words"},
            "no code_unchanged_words": {k: v for k, v in good.items() if k != "code_unchanged_words"},
            "review words without the empty verdict": {
                **good, "review_words": {k: v for k, v in good["review_words"].items() if k}},
        }
        for name, body in cases.items():
            PL.LEVELS_FILE = tmp / (name.replace(" ", "_") + ".json")
            if body is not None:
                write(PL.LEVELS_FILE, body)
            PL._reset()
            try:
                PL.levels()
                raised = None
            except PL.LevelsUnavailable as exc:
                raised = str(exc)
            check(f"{name}: LevelsUnavailable, never a traceback of another kind", raised is not None)
            check_in(f"{name}: it names the file", "references/verification-levels.json", raised or "")
            check_in(f"{name}: and the door", "reinstall the plugin", raised or "")
        check("LevelsUnavailable is a ValueError, so every caller's refusal path takes it",
              issubclass(PL.LevelsUnavailable, ValueError))
        # Every entry point reads the file, so every one says so.
        PL.LEVELS_FILE = tmp / "absent.json"
        PL._reset()
        for label, call in (("words", lambda: PL.words("live")),
                            ("level_of an explicit level", lambda: PL.level_of({"proof_level": "live"})),
                            ("review_words", lambda: PL.review_words("approved")),
                            ("handed_words", PL.handed_words),
                            ("words_for a reason that has words", lambda: PL.words_for("handed")),
                            ("probe_problem", lambda: PL.probe_problem({"proof_level": "live"}))):
            try:
                call()
                said = ""
            except PL.LevelsUnavailable as exc:
                said = str(exc)
            check_in(f"{label} says the vocabulary is unavailable", "verification-levels.json", said)
        try:
            acceptance.validate_window(
                {"schema_version": 2, "input_hash": "h", "required_quality_checks": [],
                 "instances": [{"schema_version": 2, "instance_id": "i", "input_hash": "h",
                                "outcome": "passed", "change_disposition": "new_or_changed",
                                "change_basis_ref": "x", "probe": {"proof_level": "live"},
                                "evidence_refs": []}]}, tmp)
            said = ""
        except PL.LevelsUnavailable as exc:
            said = str(exc)
        check_in("a window that needs the levels says so instead of guessing them",
                 "reinstall the plugin", said)
        # R1 edge: a project copy of the vocabulary that still carries `unmeasured_words` (any value) is read
        # as before - the key is ignored, it is no shape error.
        for label, old in (("text", "not probed (whether this test is new was not measured)"), ("not text", 7),
                           ("empty", "")):
            PL.LEVELS_FILE = write(tmp / f"old_copy_{label.replace(' ', '_')}.json", {**good, "unmeasured_words": old})
            PL._reset()
            try:
                PL.levels()
                said = ""
            except PL.LevelsUnavailable as exc:
                said = str(exc)
            check_eq(f"R1 edge: an old copy with `unmeasured_words` ({label}) is ignored, no shape error", said, "")
            check_eq(f"...({label}) and its words are today's", PL.words_for("unmeasured"), "not probed (unchanged test)")
        # A failure is not cached: the reinstalled file works on the next call.
        PL.LEVELS_FILE = tmp / "absent.json"
        PL._reset()
        write(PL.LEVELS_FILE, good)
        check_eq("and a file put back is picked up", PL.words("live"), "the check is live")
    finally:
        PL.LEVELS_FILE = SHIPPED
        PL._reset()
        cleanup(tmp)


# --- level_of ---------------------------------------------------------------------------------

def level_of_rules():
    PL._reset()
    # rule 1: an explicit KNOWN level wins over everything else on the record
    check_eq("1: explicit live wins over a product-looking mutation",
             PL.level_of({"proof_level": "live", "mutation_kind": "real_behavior"}), "live")
    check_eq("1: explicit product wins over probe_by_code's tool",
             PL.level_of({"proof_level": "catches_broken_product", "probe_tool": "probe_by_code.py"}),
             "catches_broken_product")
    check_eq("1: an explicit UNKNOWN level is None, even next to evidence of another level",
             PL.level_of({"proof_level": "mystery", "probe_tool": "probe_by_code.py",
                          "mutation_kind": "assertion"}), None)
    check_eq("1: an explicit level of the wrong type is unknown, not absent",
             PL.level_of({"proof_level": 2, "probe_tool": "probe_by_code.py"}), None)
    check_eq("1: an empty or null level counts as absent",
             (PL.level_of({"proof_level": "", "probe_tool": "probe_by_code.py"}),
              PL.level_of({"proof_level": None, "mutation_kind": "real_behavior"})),
             ("live", "catches_broken_product"))
    # rule 2: probe_by_code's tool, or a window_probe key (an old mutable record) is live
    check_eq("2: probe_tool probe_by_code.py", PL.level_of({"probe_tool": "probe_by_code.py"}), "live")
    check_eq("2: a window_probe key (the record probe_by_code has always written)",
             PL.level_of({"window_probe": {}, "mutation_kind": "real_behavior"}), "live")
    check_eq("2 before 3: probe_by_code's old record said real_behavior and was live",
             PL.level_of({"probe_tool": "probe_by_code.py", "mutation_kind": "real_behavior"}), "live")
    # rule 3: mutation_kind, else mutation, among a level's kinds
    check_eq("3: mutation_kind assertion", PL.level_of({"mutation_kind": "assertion"}), "live")
    check_eq("3: mutation_kind real_behavior", PL.level_of({"mutation_kind": "real_behavior"}),
             "catches_broken_product")
    check_eq("3: `mutation` when there is no mutation_kind",
             PL.level_of({"mutation": "real_behavior"}), "catches_broken_product")
    check_eq("3: mutation_kind is preferred over mutation",
             PL.level_of({"mutation_kind": "assertion", "mutation": "real_behavior"}), "live")
    check_eq("3: a mutation nobody knows (`invert`, replacement code) says nothing",
             (PL.level_of({"mutation": "invert"}), PL.level_of({"mutation_kind": "assertion_edit"})),
             (None, None))
    # rule 4: a receipt with every PROOF_FIELDS and no probe_tool is a pre-change red_sandbox receipt
    old = receipt(mutation="def add(a, b):\n    return a - b\n")
    check_eq("4: every PROOF_FIELDS and no probe_tool", PL.level_of(old), "catches_broken_product")
    check_eq("4: a proof field missing is not that receipt",
             PL.level_of({k: v for k, v in old.items() if k != "build_id"}), None)
    check_eq("4: a proof field empty is not that receipt", PL.level_of(dict(old, build_id="")), None)
    check_eq("4: another tool's receipt is not a red_sandbox one",
             PL.level_of(dict(old, probe_tool="someone_else.py")), None)
    # rule 5
    check_eq("5: nothing to go on", (PL.level_of({}), PL.level_of(None), PL.level_of("live"),
                                     PL.level_of([])), (None, None, None, None))


def probe_problem_matrix():
    PL._reset()
    check_eq("a live block asks for no mutation kind",
             PL.probe_problem({"proof_level": "live", "mutation_kind": "assertion"}), "")
    check_eq("not even a missing one", PL.probe_problem({"proof_level": "live"}), "")
    check_eq("a product block with a product mutation",
             PL.probe_problem({"proof_level": "catches_broken_product", "mutation_kind": "real_behavior"}), "")
    check_eq("a product block with an assertion mutation claims what it did not do",
             PL.probe_problem({"proof_level": "catches_broken_product", "mutation_kind": "assertion"}),
             "mutation_kind")
    check_eq("a block with no level keeps today's rule: real_behavior or a gap",
             (PL.probe_problem({"mutation_kind": "real_behavior"}),
              PL.probe_problem({"mutation_kind": "assertion_edit"}), PL.probe_problem({})),
             ("", "mutation_kind", "mutation_kind"))
    check_eq("an unknown level is its own problem", PL.probe_problem({"proof_level": "mystery"}), "level")
    check_eq("a probe that is not an object is a mutation-kind gap, not a crash",
             PL.probe_problem(None), "mutation_kind")


# --- proof_required ---------------------------------------------------------------------------

def proof_required_is_the_one_predicate():
    handed_row = {"case": "TC-9", "reason": "handed_to_person", "detail": "ios: run it on a device"}
    manifest = {"unresolved": [handed_row]}
    for key, value in (("sensitivity_proof_required", True), ("new_or_changed", True),
                       ("change_disposition", "new_or_changed")):
        check_eq(f"{key} demands a proof", PL.proof_required({key: value, "covers": ["TC-1"]}, manifest), True)
    check_eq("an unchanged row does not", PL.proof_required(
        {"change_disposition": "unchanged", "covers": ["TC-1"]}, manifest), False)
    check_eq("a row that says nothing does not", PL.proof_required({"covers": ["TC-1"]}, manifest), False)
    check_eq("a handed case, through a link, is never required",
             PL.proof_required({"new_or_changed": True, "covers": ["TC-9"]}, manifest), False)
    check_eq("nor through the pinned case links",
             PL.proof_required({"new_or_changed": True,
                                "case_version_links": [{"case_id": "TC-9", "version": "cv_1"}]}, manifest), False)
    check_eq("nor through the row's own `case`",
             PL.proof_required({"new_or_changed": True, "case": "TC-9"}, manifest), False)
    check_eq("one handed case among several exempts the row (nothing runs for it here)",
             PL.proof_required({"new_or_changed": True, "covers": ["TC-1", "TC-9"]}, manifest), False)
    area = {"unresolved": [{"case": "core/TC-9", "reason": "handed_to_person", "detail": "p: w"}]}
    check_eq("a handed row keyed `<area>/TC-9` still exempts the bare id the links spell",
             PL.proof_required({"new_or_changed": True, "covers": ["TC-9"]}, area), False)
    check_eq("another case is not exempted", PL.proof_required({"new_or_changed": True, "covers": ["TC-1"]}, area), True)
    check_eq("an empty case never matches an empty handed case",
             PL.proof_required({"new_or_changed": True}, {"unresolved": [
                 {"case": "", "reason": "handed_to_person", "detail": "p: w"}]}), True)
    check_eq("no manifest, an empty one, a broken one",
             (PL.proof_required({"new_or_changed": True}, None), PL.proof_required({"new_or_changed": True}, {}),
              PL.proof_required({"new_or_changed": True}, {"unresolved": "junk"})), (True, True, True))
    check_eq("no row", (PL.proof_required(None, manifest), PL.proof_required({}, manifest)), (False, False))
    check_eq("a reason other than handing exempts nothing",
             PL.proof_required({"new_or_changed": True, "covers": ["TC-9"]},
                               {"unresolved": [{"case": "TC-9", "reason": "blocked_by_env"}]}), True)


# --- t-134 P5-C: the stored novelty, and the predicate that reads it -------------------------------------
# The rule under test: a row WITHOUT a `novelty` key keeps today's rule exactly; a row WITH the key can
# only gain a requirement, and every doubt about the value lands on "required" (FR-4, FR-41).

def before_t134(entry, manifest) -> bool:
    """`proof_required` as it stood before t-134, copied verbatim: the reference the equality table
    compares the new function with. It must never be edited to follow the new code."""
    if not isinstance(entry, dict):
        return False
    wanted = bool(entry.get("sensitivity_proof_required") or entry.get("new_or_changed")
                  or entry.get("change_disposition") == "new_or_changed")
    if not wanted:
        return False
    mine = {str(case) for case in C.manifest_test_links(entry) if case}
    if entry.get("case"):
        mine.add(str(entry["case"]))
    return not (mine & PL._handed_keys(manifest))


HANDED = {"case": "TC-9", "reason": "handed_to_person", "detail": "ios: run it on a device"}
IID = "TC-1::test_x"          # aliases: TC-1::test_x, test_x
IID_ALIASES = ["TC-1::test_x", "test_x"]
FLAG_VALUES = (None, False, 0, "", True, 1, "yes")     # None = the key is absent


def legacy_rows():
    """Every row WITHOUT a `novelty` key that the three flags can make: 7 x 7 x 3 values, on a case that
    is handed and on one that is not (the flag values a hand-written row can carry, not only bools)."""
    for sens in FLAG_VALUES:
        for new in FLAG_VALUES:
            for disposition in (None, "unchanged", "new_or_changed"):
                for cases in (["TC-1"], ["TC-9"]):
                    row = {"instance_id": IID, "case": cases[0], "covers": cases}
                    for key, value in (("sensitivity_proof_required", sens), ("new_or_changed", new),
                                       ("change_disposition", disposition)):
                        if value is not None:
                            row[key] = value
                    yield row


def bindings_of(*ids, disposition="new_or_changed") -> dict:
    return {"obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": list(ids),
                                     "change_disposition": disposition}]}


def manifests_for_the_table():
    handed = {"unresolved": [HANDED]}
    live = bindings_of(*IID_ALIASES)
    return {
        "None": None, "{}": {}, "not a manifest": [], "handed": handed,
        "bindings say new_or_changed": live,
        "bindings say new_or_changed, aliases retracted": {**live, "retracted_instances": IID_ALIASES},
        "bindings say unchanged": bindings_of(*IID_ALIASES, disposition="unchanged"),
        "bindings say new_or_changed and the case is handed": {**live, **handed},
        "bindings that are not a list": {"obligation_bindings": "junk"},
    }


def a_row_without_the_key_keeps_todays_rule_byte_for_byte():
    PL._reset()
    manifests = manifests_for_the_table()
    rows = list(legacy_rows())
    differ, ran, seen_true, seen_false = [], 0, 0, 0
    for row in rows:
        for label, manifest in manifests.items():
            ran += 1
            was, now = before_t134(row, manifest), PL.proof_required(row, manifest)
            seen_true += was
            seen_false += not was
            if was is not now:
                differ.append((label, row, was, now))
    check_eq(f"equality table: {len(rows)} legacy rows x {len(manifests)} manifests, old and new agree on every one",
             differ[:2], [])
    check("the table is not one-sided: it holds both required and not-required rows", seen_true > 100 and seen_false > 100,
          f"{seen_true} required, {seen_false} not")
    check_eq("...and it is big enough to mean something", ran, len(rows) * len(manifests))
    check_eq("entries that are not rows: False, before and after", [(before_t134(x, {}), PL.proof_required(x, {}))
                                                                    for x in (None, [], "x", 3, {})],
             [(False, False)] * 5)
    row = {"instance_id": IID, "case": "TC-1", "covers": ["TC-1"]}
    check_eq("a legacy row that no flag calls new is NOT required, though a binding calls it new_or_changed "
             "under a live alias (the binding is not read)", PL.proof_required(row, bindings_of(*IID_ALIASES)), False)
    check_eq("a legacy row whose flag says unchanged, the same", PL.proof_required(
        dict(row, change_disposition="unchanged"), bindings_of(*IID_ALIASES)), False)
    check_eq("a legacy row's reason is never 'unchanged': it is unmeasured (or handed)", [PL.not_required_why(r, m)
             for r in rows for m in manifests.values() if not PL.proof_required(r, m)
             and PL.not_required_why(r, m) not in ("unmeasured", "handed")], [])


_DEFAULT = object()


def fresh_row(nov=_DEFAULT, **over) -> dict:
    """A row that carries a `novelty` (a fresh unchanged unless told otherwise; None is a null novelty) and
    none of the three flags, over the real test file."""
    row = {"instance_id": IID, "case": "TC-1", "covers": ["TC-1"], "file": TEST_REL,
           "novelty": unchanged_novelty() if nov is _DEFAULT else nov}
    row.update(over)
    return row


def unchanged_novelty(*rels, **over) -> dict:
    rels = rels or (TEST_REL,)
    nov = {"value": "unchanged", "basis": "the function is the same at the base",
           "base": {"kind": "s0", "sha": "a" * 40}, "measured_on": {r: digest(PROJECT["root"] / r) for r in rels},
           "measured_by": "manifest_from_tests.py", "measured_at": "2026-09-30T12:00:00"}
    nov.update(over)
    return nov


def novelty_of_reads_the_stored_field():
    PL._reset()
    root = PROJECT["root"]
    check_eq("key absent: (None, '') - a legacy row", PL.novelty_of({"case": "TC-1"}), (None, ""))
    check_eq("an entry that is not a row: (None, '')", (PL.novelty_of(None), PL.novelty_of("x"), PL.novelty_of([])),
             ((None, ""),) * 3)
    check_eq("fresh unchanged, the project found through the hook layer",
             PL.novelty_of(fresh_row()), ("unchanged", "the function is the same at the base"))
    check_eq("...and with the project given", PL.novelty_of(fresh_row(), project=root),
             ("unchanged", "the function is the same at the base"))
    for value in ("new", "changed", "unknown"):
        stale = {"value": value, "basis": f"stored {value}", "measured_on": {TEST_REL: "0" * 64}}
        check_eq(f"{value} is returned as stored, whatever the files hold now (a later edit cannot undo it)",
                 PL.novelty_of({"novelty": stale}), (value, f"stored {value}"))
    check_eq("a basis that is not text reads as ''", PL.novelty_of({"novelty": {"value": "new", "basis": 5}}), ("new", ""))
    for label, bad in (("null", None), ("a list", ["unchanged"]), ("a number", 7), ("{}", {}),
                       ("a bare string", "unchanged"), ("value in capitals", {"value": "UNCHANGED"}),
                       ("value with a leading space", {"value": " unchanged"}),
                       ("value with a trailing newline", {"value": "unchanged\n"}),
                       ("value that is a list", {"value": ["unchanged"]}), ("value null", {"value": None}),
                       ("value true", {"value": True}), ("a value nobody defined", {"value": "same"})):
        check_eq(f"malformed, {label}: unknown, and it says so", PL.novelty_of({"novelty": bad}),
                 ("unknown", PL.WHY_NOVELTY_MALFORMED))
    resolved = {"value": "unchanged", "basis": "resolved when the window was built", "resolved": True}
    check_eq("the window-item form: the value as stored, nothing re-hashed (no measured_on needed)",
             PL.novelty_of({"novelty": resolved}), ("unchanged", "resolved when the window was built"))
    # R2: `resolved` skips the re-hash ONLY on the item form (neither `measured_on` nor `measured_by`, by key
    # presence). A block that names the file it was measured on is a row form: `resolved` is ignored.
    stale_files = {TEST_REL: "0" * 64}
    for label, block in (("measured_on that no longer matches", dict(resolved, measured_on=stale_files)),
                         ("measured_on null", dict(resolved, measured_on=None)),
                         ("measured_on empty", dict(resolved, measured_on={})),
                         ("measured_by alone", dict(resolved, measured_by="manifest_from_tests.py")),
                         ("measured_by null", dict(resolved, measured_by=None)),
                         ("both keys, the hash stale", dict(resolved, measured_on=stale_files,
                                                            measured_by="manifest_from_tests.py"))):
        check_eq(f"R2: resolved true beside {label}: row form, resolved ignored, unknown",
                 PL.novelty_of({"novelty": block})[0], "unknown")
        check_eq(f"R2: ...{label}: the row is required and its reason is not 'unchanged'",
                 (PL.proof_required({"case": "TC-1", "novelty": block}, {}),
                  PL.not_required_why({"case": "TC-1", "novelty": block}, {})), (True, ""))
    check_eq("R2: resolved true beside a measured_on that MATCHES: row form, the check runs and passes",
             PL.novelty_of({"novelty": dict(resolved, measured_on={TEST_REL: digest(root / TEST_REL)})},
                           project=root)[0], "unchanged")
    check_eq("R2 invariant: the item form (neither key) is still not re-hashed", PL.novelty_of(
        {"novelty": {"value": "unchanged", "resolved": True, "basis": "b"}}), ("unchanged", "b"))
    for label, flag in (("1", 1), ("the string 'true'", "true"), ("the string 'yes'", "yes"), ("the string 'True'", "True"),
                        ("a list", [True]), ("0", 0), ("null", None)):
        check_eq(f"R2 edge: resolved {label} (not the boolean true) never skips the re-hash",
                 PL.novelty_of({"novelty": {"value": "unchanged", "resolved": flag}})[0], "unknown")
    check_eq("...a resolved value outside the closed set is still malformed",
             PL.novelty_of({"novelty": {"value": "Unchanged", "resolved": True}}), ("unknown", PL.WHY_NOVELTY_MALFORMED))
    check_eq("`resolved` that is not the boolean true does not skip the check",
             PL.novelty_of({"novelty": {"value": "unchanged", "resolved": "true"}})[0], "unknown")
    before = json.dumps(fresh_row(), sort_keys=True)
    row = fresh_row()
    listing = sorted(p.name for p in root.rglob("*"))
    PL.novelty_of(row)
    check_eq("it writes nothing: the row is as it was, and so is the project", (json.dumps(row, sort_keys=True), sorted(
        p.name for p in root.rglob("*"))), (before, listing))


def a_measured_unchanged_that_cannot_be_trusted_is_unknown():
    PL._reset()
    root = PROJECT["root"]
    good = digest(root / TEST_REL)
    words = "changed since the measurement, or cannot be read"
    cases = {
        "measured_on absent": {"measured_on": None},
        "measured_on empty": {"measured_on": {}},
        "measured_on a list": {"measured_on": [TEST_REL]},
        "measured_on a string": {"measured_on": TEST_REL},
    }
    for label, over in cases.items():
        nov = unchanged_novelty()
        nov.pop("measured_on")
        if over["measured_on"] is not None:
            nov["measured_on"] = over["measured_on"]
        got = PL.novelty_of({"novelty": nov})
        check_eq(f"row-form unchanged, {label}: unknown", got[0], "unknown")
        check_in(f"...{label}: and the words say it names no file", "names no file", got[1])
    for label, name in (("an absolute path", str(root / TEST_REL)), ("a POSIX root", "/" + TEST_REL),
                        ("a drive path", "C:\\x\\test_x.py"), ("a drive-relative path", "C:test_x.py"),
                        ("a UNC path", "\\\\host\\share\\test_x.py"),
                        ("`..` inside", "tests/../tests/test_x.py"), ("`..` first", "../tests/test_x.py"),
                        ("`..` with a backslash", "tests\\..\\tests\\test_x.py"),
                        ("an empty name", ""), ("a blank name", "  "), ("a name with NUL", "tests/test_x.py\x00")):
        got = PL.novelty_of({"novelty": unchanged_novelty(measured_on={name: good})}, project=root)
        check_eq(f"a measured path that is {label}: unknown, though its sha is right", got[0], "unknown")
        check_in(f"...{label}: the words name the path and the failure", words, got[1])
    (root / "tests" / "..dots.py").write_text("x = 1\n", encoding="utf-8")
    try:
        got = PL.novelty_of({"novelty": unchanged_novelty("tests/..dots.py")}, project=root)
        check_eq("(control) `tests/..dots.py` is a legal relative path: unchanged", got[0], "unchanged")
    finally:
        (root / "tests" / "..dots.py").unlink()
    got = PL.novelty_of({"novelty": unchanged_novelty(measured_on={"tests/nope.py": good})}, project=root)
    check_eq("a measured file that is gone: unknown", got[0], "unknown")
    check_in("...and the words name it", "tests/nope.py changed since the measurement", got[1])
    got = PL.novelty_of({"novelty": unchanged_novelty(measured_on={"tests": good})}, project=root)
    check_eq("a measured path that is a directory: unknown", got[0], "unknown")
    for label, sha in (("a different sha", "0" * 64), ("an empty sha", ""), ("no sha", None), ("a number", 5),
                       ("the right sha in capitals", good.upper())):
        got = PL.novelty_of({"novelty": unchanged_novelty(measured_on={TEST_REL: sha})}, project=root)
        check_eq(f"measured_on holds {label}: unknown", got[0], "unknown")
    real_project = PL._project
    try:
        PL._project = lambda: None
        got = PL.novelty_of({"novelty": unchanged_novelty()})
        check_eq("the project root cannot be resolved: unknown", got[0], "unknown")
        check_in("...and the words name the first path", f"{TEST_REL} changed since the measurement", got[1])
        check_eq("...though a project given by the caller still works",
                 PL.novelty_of({"novelty": unchanged_novelty()}, project=root)[0], "unchanged")
    finally:
        PL._project = real_project
    # the file changes after the measurement: the measured value turns into unknown, the words name it
    extra = root / "tests" / "conftest.py"
    extra.write_text("FIXTURE = 1\n", encoding="utf-8")
    try:
        nov = unchanged_novelty(TEST_REL, "tests/conftest.py")
        check_eq("two measured files, both as recorded: unchanged", PL.novelty_of({"novelty": nov}, project=root)[0],
                 "unchanged")
        extra.write_text("FIXTURE = 2\n", encoding="utf-8")
        got = PL.novelty_of({"novelty": nov}, project=root)
        check_eq("one of two measured files changed since (the helper, not the test): unknown", got[0], "unknown")
        check_eq("...and the words name that file", got[1], f"tests/conftest.py {words}")
    finally:
        extra.unlink()


def the_hash_cache_never_trusts_a_young_key():
    """Edge 4: a cache keyed (path, size, mtime_ns) is fooled by a same-size rewrite inside one mtime tick.
    The direction kept: a file younger than the margin is re-hashed on every question, so the rewrite is seen."""
    import os
    import time
    import types
    root = PROJECT["root"]
    rel = "tests/test_cache.py"
    path = root / rel
    calls = []
    real_hashlib = PL.hashlib

    def counting(data=b""):
        calls.append(1)
        return real_hashlib.sha256(data)
    try:
        PL.hashlib = types.SimpleNamespace(sha256=counting)
        path.write_text("a = 1\n", encoding="utf-8")
        row = {"novelty": unchanged_novelty(measured_on={rel: real_hashlib.sha256(path.read_bytes()).hexdigest()})}
        first = os.stat(path)
        PL._reset()
        calls.clear()
        check_eq("a young file: fresh", PL.novelty_of(row, project=root)[0], "unchanged")
        PL.novelty_of(row, project=root)
        check_eq("a young file is hashed on EVERY question (its key is not trusted)", len(calls), 2)
        path.write_text("a = 2\n", encoding="utf-8")            # the same size ...
        os.utime(path, ns=(first.st_atime_ns, first.st_mtime_ns))  # ... in the same mtime tick
        check_eq("same size, same mtime_ns, young: the rewrite is SEEN (unknown)", PL.novelty_of(row, project=root)[0],
                 "unknown")
        # an aged file settles into the cache: one hash however often it is asked
        path.write_text("a = 1\n", encoding="utf-8")
        old = time.time_ns() - 3600 * 10 ** 9 * 2
        os.utime(path, ns=(old, old))
        PL._reset()
        calls.clear()
        for _ in range(3):
            check_eq("an aged file: fresh", PL.novelty_of(row, project=root)[0], "unchanged")
        check_eq("...hashed ONCE for three questions (FR-27: 24 rows of one story do not re-read it 24 times)",
                 len(calls), 1)
        path.write_text("a = 22\n", encoding="utf-8")            # another size: another key
        os.utime(path, ns=(old, old))
        check_eq("an aged file rewritten with ANOTHER size is seen at once", PL.novelty_of(row, project=root)[0], "unknown")
        path.write_text("a = 1\n", encoding="utf-8")
        os.utime(path, ns=(old + 10 ** 9, old + 10 ** 9))       # another mtime: another key
        check_eq("...and one rewritten with another mtime, back to the recorded bytes, is fresh again",
                 PL.novelty_of(row, project=root)[0], "unchanged")
        calls.clear()
        PL._reset()
        PL.novelty_of(row, project=root)
        check_eq("_reset forgets the cache: the next question hashes again", len(calls), 1)
    finally:
        PL.hashlib = real_hashlib
        path.unlink(missing_ok=True)
        PL._reset()


def proof_required_with_a_novelty_key():
    PL._reset()
    handed = {"unresolved": [HANDED]}
    root = PROJECT["root"]
    # 1. the value decides when no flag does
    check_eq("a fresh unchanged row with no flag and no binding: not required", PL.proof_required(fresh_row(), {}), False)
    for value in ("new", "changed", "unknown"):
        check_eq(f"novelty {value}: required, though no flag says so", PL.proof_required(
            fresh_row({"value": value, "basis": "b"}), {}), True)
    check_eq("a flag still adds to a fresh unchanged (a layer only adds)", PL.proof_required(
        fresh_row(new_or_changed=True), {}), True)
    check_eq("...each of the three flags", [PL.proof_required(fresh_row(**{k: v}), None) for k, v in (
        ("sensitivity_proof_required", True), ("new_or_changed", True), ("change_disposition", "new_or_changed"))],
        [True] * 3)
    check_eq("a role's `change_disposition: unchanged` never overrules a measured new", PL.proof_required(
        fresh_row({"value": "new", "basis": "b"}, change_disposition="unchanged"), {}), True)
    # 2. the adversarial table of R4: every one is required
    fresh = unchanged_novelty()
    table = {
        "novelty null": None, "novelty a list": ["unchanged"], "novelty a number": 7, "novelty {}": {},
        "novelty value UNCHANGED": {"value": "UNCHANGED", "measured_on": fresh["measured_on"]},
        "novelty ' unchanged' as the value": {"value": " unchanged", "measured_on": fresh["measured_on"]},
        "novelty 'unchanged\\n' as the value": {"value": "unchanged\n", "measured_on": fresh["measured_on"]},
        "novelty ' unchanged' as the whole field": " unchanged", "novelty 'unchanged\\n' as the whole field": "unchanged\n",
        "novelty the bare string unchanged": "unchanged",
        "unchanged, measured_on absent": {k: v for k, v in fresh.items() if k != "measured_on"},
        "unchanged, measured_on empty": dict(fresh, measured_on={}),
        "unchanged, an absolute path": dict(fresh, measured_on={str(root / TEST_REL): digest(root / TEST_REL)}),
        "unchanged, a path with ..": dict(fresh, measured_on={"tests/../tests/test_x.py": digest(root / TEST_REL)}),
        "unchanged, a file gone": dict(fresh, measured_on={"tests/gone.py": "0" * 64}),
        "unchanged, a different sha": dict(fresh, measured_on={TEST_REL: "0" * 64}),
    }
    for label, nov in table.items():
        row = fresh_row(nov)
        check_eq(f"R4: {label}: required", PL.proof_required(row, {}), True)
        check_eq(f"R4: {label}: and its reason is never 'unchanged'", PL.not_required_why(row, {}), "")
    real_project = PL._project
    try:
        PL._project = lambda: None
        check_eq("R4: unchanged, the project root unresolvable: required", PL.proof_required(fresh_row(), {}), True)
    finally:
        PL._project = real_project
    # a measured file changes after the measurement (mutation c): stale, so required
    extra = root / "tests" / "conftest.py"
    extra.write_text("FIXTURE = 1\n", encoding="utf-8")
    try:
        row = fresh_row(unchanged_novelty(TEST_REL, "tests/conftest.py"))
        check_eq("two measured files as recorded: not required", PL.proof_required(row, {}), False)
        extra.write_text("FIXTURE = 2\n", encoding="utf-8")
        check_eq("R4/R5: a measured file (a helper) changed since: a stale unchanged is required", PL.proof_required(row, {}), True)
    finally:
        extra.unlink()
    # 3. the binding layer
    row = fresh_row(instance_id=IID)
    live = bindings_of(*IID_ALIASES)
    check_eq("unchanged + a binding new_or_changed under the canonical alias: required", PL.proof_required(row, live),
             True)
    check_eq("...under the bare alias only (the row is spelled another way in the binding)",
             PL.proof_required(row, bindings_of("test_x")), True)
    check_eq("...under an alias of another row: not required", PL.proof_required(row, bindings_of("test_y")), False)
    check_eq("...a binding that says unchanged: not required", PL.proof_required(
        row, bindings_of(*IID_ALIASES, disposition="unchanged")), False)
    check_eq("...a binding with no disposition: not required", PL.proof_required(
        row, {"obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": IID_ALIASES}]}), False)
    check_eq("...a binding that says 'New_Or_Changed': not required (exact text, no phrase reading)", PL.proof_required(
        row, bindings_of(*IID_ALIASES, disposition="New_Or_Changed")), False)
    check_eq("RETRACTED alias only: not required - the alias is retracted, the measured value stands", PL.proof_required(
        row, {**bindings_of("TC-1::test_x"), "retracted_instances": ["TC-1::test_x"]}), False)
    check_eq("...the same binding, the alias NOT retracted: required", PL.proof_required(
        row, {**bindings_of("TC-1::test_x"), "retracted_instances": ["TC-1::other"]}), True)
    check_eq("one alias retracted, the binding lists another live one: required", PL.proof_required(
        row, {**bindings_of(*IID_ALIASES), "retracted_instances": ["TC-1::test_x"]}), True)
    check_eq("both aliases retracted: not required", PL.proof_required(
        row, {**bindings_of(*IID_ALIASES), "retracted_instances": IID_ALIASES}), False)
    check_eq("a second binding under a live alias wins over a first that lists a retracted one", PL.proof_required(
        row, {"obligation_bindings": bindings_of("TC-1::test_x")["obligation_bindings"] +
              bindings_of("test_x")["obligation_bindings"], "retracted_instances": ["TC-1::test_x"]}), True)
    for label, manifest in (("manifest None", None), ("manifest {}", {}), ("manifest a list", []),
                            ("bindings a string", {"obligation_bindings": "x"}),
                            ("bindings a dict", {"obligation_bindings": {"instance_ids": IID_ALIASES}}),
                            ("bindings None", {"obligation_bindings": None}),
                            ("a binding that is not an object", {"obligation_bindings": ["x", 3, None]}),
                            ("instance_ids a string", {"obligation_bindings": [
                                {"change_disposition": "new_or_changed", "instance_ids": "TC-1::test_x"}]}),
                            ("instance_ids None", {"obligation_bindings": [
                                {"change_disposition": "new_or_changed", "instance_ids": None}]}),
                            ("retracted_instances not a list", {"retracted_instances": "TC-1::test_x"})):
        try:
            got = PL.proof_required(row, manifest)
        except Exception as exc:  # the test's own report of a crash
            got = f"raised {type(exc).__name__}"
        check_eq(f"{label}: bindings ignored, no exception, not required", got, False)
    # 4. the handed exemption comes last
    for label, nov in (("new", {"value": "new", "basis": "b"}), ("changed", {"value": "changed", "basis": "b"}),
                       ("unknown", {"value": "unknown", "basis": "b"}), ("null", None),
                       ("a stale unchanged", dict(fresh, measured_on={TEST_REL: "0" * 64}))):
        h = fresh_row(nov, case="TC-9", covers=["TC-9"])
        check_eq(f"a handed row with novelty {label}: not required (today's exemption)", PL.proof_required(h, handed), False)
        check_eq(f"...{label}: the reason is 'handed'", PL.not_required_why(h, handed), "handed")
        check_eq(f"...{label}: a row of another case in the same manifest is still required", PL.proof_required(
            fresh_row(nov), handed), True)
    h = fresh_row(case="TC-9", covers=["TC-9"])
    check_eq("a handed row that a binding calls new_or_changed: not required", PL.proof_required(
        h, {**handed, **bindings_of(*[i for i in C.instance_id_aliases(h)])}), False)
    check_eq("a handed row with a flag and a fresh unchanged: not required", PL.proof_required(
        dict(h, new_or_changed=True), handed), False)
    check_eq("no row at all, with the key elsewhere", PL.proof_required({"novelty": {"value": "new"}}, {}), True)
    check_eq("a row of only the key, unchanged and malformed measured_on type", PL.proof_required(
        {"novelty": {"value": "unchanged", "measured_on": 5}}, {}), True)


def a_window_item_carries_a_resolved_novelty():
    """`acceptance.validate_window` and `window_record._comment_only` ask `proof_required(item, {})` of a
    window item; an item carries `{"value", "basis", "resolved": true}` (P5-G) or nothing at all."""
    item = {"instance_id": IID, "change_disposition": "unchanged"}
    check_eq("an item with no novelty keeps today's rule (unchanged: not required)", PL.proof_required(item, {}), False)
    check_eq("...and its reason is unmeasured", PL.not_required_why(item, {}), "unmeasured")
    for value, want in (("unchanged", False), ("new", True), ("changed", True), ("unknown", True)):
        got = dict(item, novelty={"value": value, "basis": "resolved at build", "resolved": True})
        check_eq(f"a resolved {value} item: required is {want}", PL.proof_required(got, {}), want)
    check_eq("a resolved unchanged item whose role wrote new_or_changed: required (flags add)", PL.proof_required(
        {"instance_id": IID, "change_disposition": "new_or_changed",
         "novelty": {"value": "unchanged", "resolved": True}}, {}), True)
    check_eq("a resolved malformed item: required", PL.proof_required(
        dict(item, novelty={"value": "Unchanged", "resolved": True}), {}), True)
    # t-187 F-B control: the row is kept from the item form by `manifest_put` (it refuses `resolved` on a
    # `tests[]` row, see test_manifest_from_tests.py), NOT by this reader - a window item built by
    # `window_record.build` must keep reading through the one predicate exactly as before.
    check_eq("t-187 F-B control: a window item's `{unchanged, resolved: true}` still reads not required",
             (PL.proof_required(dict(item, novelty={"value": "unchanged", "basis": "resolved at build",
                                                    "resolved": True}), {}), PL.novelty_of(
                 {"novelty": {"value": "unchanged", "basis": "resolved at build", "resolved": True}})),
             (False, ("unchanged", "resolved at build")))


def why_no_live_check_is_demanded():
    PL._reset()
    handed = {"unresolved": [HANDED]}
    # R1 (owner decision 30.09): a green test whose novelty was not measured is counted as proven, with no
    # words of its own - `unmeasured` reads exactly as `unchanged` does today; `handed` keeps its own.
    check_eq("R1: the unmeasured words equal today's words, byte for byte",
             PL.words_for("unmeasured").encode("utf-8"), b"not probed (unchanged test)")
    check_eq("R1: ...and they are the `not_required_words()` text", PL.words_for("unmeasured"), PL.not_required_words())
    check_eq("R1: unchanged reads with the same words", PL.words_for("unchanged"), PL.not_required_words())
    check_eq("R1: handed reads with `handed_words()`, which differ", (PL.words_for("handed"), PL.handed_words()),
             ("not probed (handed to the person)", "not probed (handed to the person)"))
    check_eq("R1: a check is demanded: no words", PL.words_for(""), "")
    for label, odd in (("an unknown reason", "mystery"), ("None", None), ("a number", 7), ("a list", ["unchanged"]),
                       ("a dict", {"unchanged": 1}), ("bytes", b"unchanged"), ("capitals", "UNCHANGED"),
                       ("a padded reason", " unchanged"), ("True", True)):
        try:
            got = PL.words_for(odd)
        except Exception as exc:  # the test's own report of a crash
            got = f"raised {type(exc).__name__}"
        check_eq(f"R1 edge: words_for {label}: '' and no exception", got, "")
    check_eq("R1: the reason and the words of a keyless not-required row",
             (PL.not_required_why({"case": "TC-1", "covers": ["TC-1"]}, {}),
              PL.words_for(PL.not_required_why({"case": "TC-1", "covers": ["TC-1"]}, {}))),
             ("unmeasured", "not probed (unchanged test)"))
    check_eq("R1: the words of a row's reason through the one accessor, for every reason the function returns",
             {reason: PL.words_for(reason) for reason in ("", "unchanged", "handed", "unmeasured")},
             {"": "", "unchanged": PL.not_required_words(), "handed": PL.handed_words(),
              "unmeasured": PL.not_required_words()})
    check_eq("a legacy row that no flag calls new: unmeasured", PL.not_required_why({"case": "TC-1", "covers": ["TC-1"]},
                                                                                  {}), "unmeasured")
    check_eq("...whatever its own disposition says", PL.not_required_why(
        {"case": "TC-1", "change_disposition": "unchanged"}, None), "unmeasured")
    check_eq("a legacy row that IS flagged is required: ''", PL.not_required_why(
        {"case": "TC-1", "new_or_changed": True}, {}), "")
    check_eq("a legacy row flagged but handed: handed", PL.not_required_why(
        {"case": "TC-9", "covers": ["TC-9"], "new_or_changed": True}, handed), "handed")
    # t-175: `handed` is decided before anything else says about the row; `proof_required` is untouched.
    handed_keyless = {"case": "TC-9", "covers": ["TC-9"]}
    handed_fresh = fresh_row(case="TC-9", covers=["TC-9"])
    check_eq("a keyless, unflagged handed row: handed (never unmeasured)",
             PL.not_required_why(handed_keyless, handed), "handed")
    check_eq("a fresh-unchanged handed row: handed (never unchanged)",
             PL.not_required_why(handed_fresh, handed), "handed")
    check_eq("...and their words are the handed words",
             [PL.words_for(PL.not_required_why(r, handed)) for r in (handed_keyless, handed_fresh)],
             [PL.handed_words()] * 2)
    check_eq("...the same rows without the handing keep their reasons",
             [PL.not_required_why(r, {}) for r in (handed_keyless, handed_fresh)], ["unmeasured", "unchanged"])
    check_eq("a handed row is still never required (today's exemption)",
             [PL.proof_required(r, handed) for r in (handed_keyless, handed_fresh, dict(handed_keyless, new_or_changed=True))],
             [False, False, False])
    check_eq("a handed row with a live binding and a flag: handed, not required",
             (PL.not_required_why(dict(handed_fresh, new_or_changed=True), handed),
              PL.proof_required(dict(handed_fresh, new_or_changed=True), handed)), ("handed", False))
    check_eq("a row that is not handed and is required stays ''",
             PL.not_required_why(dict(handed_keyless, new_or_changed=True), {}), "")
    check_eq("a measured, fresh unchanged: unchanged", PL.not_required_why(fresh_row(), {}), "unchanged")
    check_eq("a resolved unchanged (window form): unchanged", PL.not_required_why(
        {"novelty": {"value": "unchanged", "resolved": True}}, {}), "unchanged")
    check_eq("a fresh unchanged that a live binding calls new_or_changed: required, ''", PL.not_required_why(
        fresh_row(), bindings_of(*IID_ALIASES)), "")
    check_eq("...and under a retracted alias only it is unchanged", PL.not_required_why(
        fresh_row(), {**bindings_of("TC-1::test_x"), "retracted_instances": ["TC-1::test_x"]}), "unchanged")
    for value in ("new", "changed", "unknown"):
        check_eq(f"novelty {value}: '' (a live check is owed)", PL.not_required_why(
            fresh_row({"value": value, "basis": "b"}), {}), "")
    check_eq("a stale unchanged: '' (owed), never 'unchanged'", PL.not_required_why(
        fresh_row(unchanged_novelty(measured_on={TEST_REL: "1" * 64})), {}), "")
    # the invariant: 'unchanged' is reachable only through a measured, fresh unchanged
    unreachable = []
    for row in legacy_rows():
        for manifest in (None, {}, handed, bindings_of(*IID_ALIASES)):
            if PL.not_required_why(row, manifest) == "unchanged":
                unreachable.append(row)
    check_eq("the reason 'unchanged' is reached by no legacy row over the whole equality table", unreachable[:2], [])
    for bad in (None, [], 7, {}, "unchanged", " unchanged", "unchanged\n", {"value": "UNCHANGED"},
                {"value": "unchanged"}, {"value": "unchanged", "measured_on": {}}):
        check("...nor by a malformed or unmeasured novelty " + json.dumps(bad), PL.not_required_why(
            {"case": "TC-1", "novelty": bad}, {}) != "unchanged")
    # every reason is consistent with the predicate
    inconsistent = []
    for row in [fresh_row(), fresh_row({"value": "new"}), {"case": "TC-1"}, {"case": "TC-1", "new_or_changed": True},
                fresh_row(case="TC-9", covers=["TC-9"])]:
        for manifest in (None, {}, handed):
            if (PL.not_required_why(row, manifest) == "") is not PL.proof_required(row, manifest):
                inconsistent.append((row, manifest))
    check_eq("'' if and only if the predicate says required", inconsistent, [])
    check_eq("something that is not a row is not a row that is required (a decision returned to the coordinator)",
             (PL.proof_required(None, {}), PL.not_required_why(None, {})), (False, "unmeasured"))
    import ledger
    check_eq("the level id `not_required` is kept (the counts of delivery_summary do not move)",
             ledger.PROOF_NOT_REQUIRED, "not_required")


# --- reached ----------------------------------------------------------------------------------

def reached_over_the_receipts_a_row_names():
    tmp = temp_dir("qa-reached-")
    try:
        PL._reset()
        row = entry()
        check_eq("no receipt anywhere", PL.reached(row, {}, tmp),
                 {"level": None, "words": "not probed", "ref": {}, "issues": ["no sensitivity receipt"]})
        # the row's own receipt, live
        a = put(tmp, "a-live", live())
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": a}), {}, tmp)
        check_eq("a live receipt on the row: the check is live", (got["level"], got["words"], got["issues"]),
                 ("live", "the check is live", []))
        check_eq("and its ref is the row's", got["ref"], a)
        # only through an obligation binding
        manifest = {"obligation_bindings": [binding("i1", a)]}
        got = PL.reached(row, manifest, tmp)
        check_eq("a receipt named only by the binding is reached", (got["level"], got["ref"]["path"]),
                 ("live", a["path"]))
        # an old red_sandbox receipt: no proof_level, no probe_tool (edge row 1)
        p = put(tmp, "p-old", receipt())
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": p}), {}, tmp)
        check_eq("an old red_sandbox receipt is `catches a broken product`, valid",
                 (got["level"], got["words"], got["issues"]), ("catches_broken_product",
                                                                 "catches a broken product", []))
        # both levels present: the best one is shown (edge row 6)
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": a}),
                         {"obligation_bindings": [binding("i1", p)]}, tmp)
        check_eq("both levels: the higher one is shown, though the row names the lower",
                 (got["level"], got["ref"]["path"]), ("catches_broken_product", p["path"]))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": p}),
                         {"obligation_bindings": [binding("i1", a)]}, tmp)
        check_eq("and the other way round", got["level"], "catches_broken_product")
        # the same path named twice is one candidate
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": a}), {"obligation_bindings": [binding("i1", a)]}, tmp)
        check_eq("de-duplicated by path", (got["level"], got["issues"]), ("live", []))
        # BYTES RULE: a receipt is valid for a row only for the bytes its test holds NOW (the file)
        old_bytes = put(tmp, "live-old-bytes", live(test_content_hash="sha-before"))
        new_bytes = put(tmp, "live-new-bytes", live(test_content_hash=sha_now()))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": old_bytes}),
                         {"obligation_bindings": [binding("i1", new_bytes)]}, tmp)
        check_eq("a receipt for other bytes does not count; the one for the current bytes is reached",
                 (got["level"], got["ref"]["path"], got["issues"]), ("live", new_bytes["path"], []))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": old_bytes}), {}, tmp)
        check_eq("alone, a receipt for other bytes shows NO level (FR-41)", (got["level"], got["words"], got["ref"]),
                 (None, "not probed", {}))
        check_in("and the issue names both hashes and the door", "other bytes (test_content_hash sha-before, the "
                 f"test file now hashes {sha_now()}) and other code: probe the current bytes again with "
                 "probe_by_code.py --instance i1", got["issues"])
        stale_product = put(tmp, "p-stale", receipt(test_content_hash="sha-before"))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": stale_product}),
                         {"obligation_bindings": [binding("i1", new_bytes)]}, tmp)
        check_eq("a HIGHER level for old bytes does not outrank a lower one for the current bytes",
                 (got["level"], got["ref"]["path"]), ("live", new_bytes["path"]))
        check_eq("valid_level: other bytes have no level for this row",
                 PL.valid_level(entry(), old_bytes, tmp), None)
        check_eq("valid_level: the current bytes do", PL.valid_level(entry(), new_bytes, tmp), "live")
        # Amendment 2: a row that binds no bytes is NOT lenient - its current bytes come from the one
        # reader, the file. The t-030 trap on such a row: a receipt for the old bytes of a test
        # that has since changed must not stand for it.
        unbound = entry(sensitivity_proof={"receipt_ref": old_bytes})
        unbound.pop("trace_binding")
        got = PL.reached(unbound, {}, tmp)
        check_eq("t-030 trap, no trace_binding: a receipt for old bytes shows no level", (got["level"], got["words"]),
                 (None, "not probed"))
        check_in("...and names the bytes the file holds now", f"the test file now hashes {sha_now()}",
                 " ".join(got["issues"]))
        unbound_now = dict(unbound, sensitivity_proof={"receipt_ref": new_bytes})
        check_eq("no trace_binding, a receipt for the file's bytes as they are: live",
                 PL.reached(unbound_now, {}, tmp)["level"], "live")
        check_eq("a stale trace_binding does not rescue a receipt for its (old) bytes: the file decides",
                 PL.reached(entry(sensitivity_proof={"receipt_ref": old_bytes},
                                  trace_binding={"test_content_sha": "sha-before"}), {}, tmp)["level"], None)
        check_eq("the test is found through its node path when the row names no file",
                 PL.reached(dict({k: v for k, v in unbound_now.items() if k != "file"},
                                 selector=f"{TEST_REL}::test_x"), {}, tmp)["level"], "live")
        # the file cannot be found: the bytes are unknown - no level, and said as unknown (FR-41)
        gone = entry(sensitivity_proof={"receipt_ref": new_bytes}, file="tests/test_gone.py")
        got = PL.reached(gone, {}, tmp)
        check_eq("a test file that cannot be found: no level is reached", (got["level"], got["ref"]), (None, {}))
        check_eq("...and the words say unknown, not 'not probed'", got["words"], PL.unknown_words())
        check_in("...the unknown words carry the word", "unknown", got["words"])
        check_in("...the issue names the file and why", "tests/test_gone.py cannot be found under the project",
                 " ".join(got["issues"]))
        check_eq("no file and no node path at all: unknown too",
                 PL.reached({k: v for k, v in gone.items() if k != "file"}, {}, tmp)["words"], PL.unknown_words())
        check_eq("valid_level: unknown bytes are not a valid level (no shield for never-downgrade)",
                 PL.valid_level(gone, new_bytes, tmp), None)
        check_eq("no receipt and no file: nothing was probed, which is a fact",
                 PL.reached({"instance_id": "i1", "file": "tests/test_gone.py"}, {}, tmp)["words"], "not probed")
        # tie: same rank, both for the current bytes - the row's own receipt (first found)
        twin = put(tmp, "live-new-bytes-twin", live(test_content_hash=sha_now(), receipt_hash="other"))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": new_bytes}),
                         {"obligation_bindings": [binding("i1", twin)]}, tmp)
        check_eq("tie on rank and bytes: the row's own receipt", got["ref"]["path"], new_bytes["path"])
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": twin}),
                         {"obligation_bindings": [binding("i1", new_bytes)]}, tmp)
        check_eq("tie on rank and bytes, the other way round: still the row's own", got["ref"]["path"], twin["path"])
        check_eq("retracted ids leave a binding's list",
                 (PL.without_retracted(["a", "b", "c"], {"retracted_instances": ["b"]}),
                  PL.without_retracted(["a"], {}), PL.without_retracted(None, None)), (["a", "c"], ["a"], []))
        # invalid row, valid binding: the row's issues are not reported (issues only when NONE is valid)
        broken = {"path": a["path"], "sha256": "0" * 64}
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": broken}),
                         {"obligation_bindings": [binding("i1", p)]}, tmp)
        check_eq("an invalid row receipt and a valid binding one: reached, no issues",
                 (got["level"], got["issues"]), ("catches_broken_product", []))
        # nothing valid: every candidate's issues, named
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": broken}), {}, tmp)
        check_eq("nothing valid: not probed", (got["level"], got["words"]), (None, "not probed"))
        check_in("and the issue says the hash does not match", "hash does not match", got["issues"])
        # another instance's receipt is not this instance's proof
        other = put(tmp, "other", live("i2"))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": other}), {}, tmp)
        check_eq("a receipt of another instance is invalid here", got["level"], None)
        check_in("with the reason", "does not match the manifest instance", got["issues"])
        # an unknown level in a receipt is no valid receipt (edge row 11)
        odd = put(tmp, "odd", live(proof_level="mystery"))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": odd}), {}, tmp)
        check_eq("an unknown proof level is no valid receipt", got["level"], None)
        check_in("and the issue names it", "unknown proof level mystery", got["issues"])
        odd2 = put(tmp, "odd2", live(proof_level=None, probe_tool="someone_else.py", mutation_kind="other",
                                     mutation="invert"))
        got = PL.reached(entry(sensitivity_proof={"receipt_ref": odd2}), {}, tmp)
        check_in("a receipt no rule places names its tool", "unknown proof level someone_else.py", got["issues"])
        # the old mutable probe_by_code record, reached through a binding (edge row 2, delivery side)
        legacy_body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "i1",
                       "verdict": "intended_failure", "mutation": "invert", "mutation_kind": "real_behavior",
                       "window_probe": {"verdict": "intended_failure"}}
        legacy = put(tmp, "legacy-probe", legacy_body)
        check_eq("that record is the live check to the window's reader",
                 PL.level_of(legacy_body), "live")
        got = PL.reached(row, {"obligation_bindings": [binding("i1", legacy)]}, tmp)
        check_eq("but not a valid receipt at delivery: it is mutable", got["level"], None)
        check_in("and the reason names the door", "rerun probe_by_code.py --instance i1", got["issues"])
        check_in("and says why", "predates receipts", got["issues"])
        # the inline receipt of a legacy row is still a receipt
        got = PL.reached(entry(sensitivity_proof=receipt()), {}, tmp)
        check_eq("a legacy inline receipt on the row is reached", (got["level"], got["ref"]), ("catches_broken_product", {}))
        got = PL.reached(entry(sensitivity_proof="red probe exists"), {}, tmp)
        check_eq("a string is not a receipt", got["level"], None)
        check_eq("a row that is not an object is not a crash",
                 PL.reached(None, None, tmp)["issues"], ["no sensitivity receipt"])
        check_eq("nor is a missing task root",
                 PL.reached(entry(sensitivity_proof={"receipt_ref": a}), {}, None)["level"], None)
        # valid_level: what the publishers ask before they replace a ref
        check_eq("valid_level: the level of a valid ref FOR THIS ROW", PL.valid_level(row, p, tmp),
                 "catches_broken_product")
        check_eq("valid_level: another instance's receipt has no level here", PL.valid_level(row, other, tmp), None)
        check_eq("valid_level: no ref", (PL.valid_level(row, None, tmp), PL.valid_level(row, {}, tmp)), (None, None))
    finally:
        PL._reset()
        cleanup(tmp)


# --- the facts a receipt binds ----------------------------------------------------------------

def binding_facts_are_the_ones_red_sandbox_read():
    tmp = temp_dir("qa-facts-")
    try:
        task = tmp / "task"
        write(task / "work" / "automation-manifest.json", {
            "head": "head-1", "tests": [
                {"instance_id": "i1", "case_version_links": [{"case_id": "TC-1", "version": "cv_a"}],
                 "file": TEST_REL, "trace_binding": {"test_content_sha": "row-sha"}},
                {"instance_id": "i2", "case_version_links": [{"case_id": "TC-2", "version": "cv_b"}],
                 "file": TEST_REL},
                {"instance_id": "i3"}]})
        write(task / "work" / "run-blocks" / "b1.json", {
            "results": [{"instance_id": "i1", "source_fingerprint": {"source_sha": "src-1", "test_content_sha": "run-sha"}},
                        {"instance_id": "i2", "source_fingerprint": {"source_sha": "src-2", "test_content_sha": "run-sha-2"}},
                        {"instance_id": "i3", "source_fingerprint": {"source_sha": "src-3", "test_content_sha": "run-sha-3"}}],
            "runtime_provenance": {"observed_runtime_identity": "build-1", "environment_id": "env-1"}})
        check_eq("the row's test bytes win over the run block's, source and build come from the run",
                 PL.binding_facts(task, "i1"),
                 {"case_version": "cv_a", "test_content_hash": "row-sha", "source_revision": "src-1",
                  "build_id": "build-1"})
        # Amendment 2: the run block's source_fingerprint.test_content_sha is a fingerprint over
        # several files, another quantity - never a receipt's test_content_hash.
        check_eq("with no trace_binding the file's own bytes stand, never the run's fingerprint",
                 PL.binding_facts(task, "i2")["test_content_hash"], sha_now())
        check_eq("an instance that names no file: no bytes, and the run's fingerprint is not taken instead",
                 PL.binding_facts(task, "i3")["test_content_hash"], "")
        check_eq("an instance nothing names: every fact empty, none invented",
                 PL.binding_facts(task, "i4"),
                 {"case_version": "", "test_content_hash": "", "source_revision": "head-1", "build_id": ""})
        target = {"instance_id": "i1"}
        via_red = RS.manifest_bindings(task, {"targets": [target], "original_hashes": {"f": "h"}})
        check_eq("red_sandbox.manifest_bindings is these facts plus its own restoration text",
                 via_red["i1"], {**PL.binding_facts(task, "i1"),
                                 "restoration_evidence": "red_sandbox --verify-receipt: 1 main-tree file "
                                                         "hashes unchanged after the probe"})
        try:
            RS.manifest_bindings(task, {"targets": [{"instance_id": "i4"}], "original_hashes": {}})
            said = ""
        except ValueError as exc:
            said = str(exc)
        check_in("and still refuses, naming every missing fact, as before",
                 "carry no case_version, test_content_hash, build_id", said)
    finally:
        cleanup(tmp)


def binding_facts_read_the_blocks_in_the_stories_order():
    """t-149 F-order: the last row per instance wins, so the block ORDER is the fact. It is the story's one
    order (`run_history.read_run_blocks`: the block's own clock, a reparse right after the block it
    supersedes), not file-name order - the reparse of an OLD attempt whose id starts with a letter sorts
    after every `2026...` block by name, and its source revision and build identity were bound instead."""
    tmp = temp_dir("qa-facts-order-")
    try:
        task = tmp / "task"
        write(task / "work" / "automation-manifest.json", {"head": "head-1", "tests": [
            {"instance_id": "i1", "case_version_links": [{"case_id": "TC-1", "version": "cv_a"}],
             "file": TEST_REL, "trace_binding": {"test_content_sha": "row-sha"}}]})
        runs = task / "work" / "run-blocks"

        def block(name: str, attempt: str, started: str, source: str, build: str, **extra) -> None:
            write(runs / name, {"attempt_id": attempt, "block_id": attempt, "attempt_started_at": started,
                                "results": [{"instance_id": "i1", "source_fingerprint": {"source_sha": source}}],
                                "runtime_provenance": {"observed_runtime_identity": build}, **extra})
        first = "20260930T050000000000Z-f302aa.json"
        block(first, "f302aa", "2026-09-30T05:00:00+00:00", "src-old", "build-old")
        block("20260930T051000000000Z-b2bb.json", "b2bb", "2026-09-30T05:10:00+00:00", "src-new", "build-new")
        block("f302aa-reparse-0123.json", "f302aa", "2026-09-30T05:00:00+00:00", "src-old-reparse", "build-old-reparse",
              reparse_of="work/run-blocks/" + first, supersedes_block_id="f302aa")
        got = PL.binding_facts(task, "i1")
        check_eq("F-order: the source and build come from the LATER attempt, not from the old attempt's reparse "
                 "block that sorts last by file name", (got["source_revision"], got["build_id"]), ("src-new", "build-new"))
        write(runs / "20260930T052000000000Z-list.json", [1, 2])
        (runs / "20260930T053000000000Z-bad.json").write_text("{nope", encoding="utf-8")
        check_eq("F-order: a block that is not an object, or not JSON, is skipped as before",
                 PL.binding_facts(task, "i1")["source_revision"], "src-new")
        for path in runs.glob("*.json"):
            path.unlink()
        check_eq("F-order: no block at all: no source, the manifest's head, no build",
                 (PL.binding_facts(task, "i1")["source_revision"], PL.binding_facts(task, "i1")["build_id"]),
                 ("head-1", ""))
    finally:
        cleanup(tmp)


def no_level_literal_in_acceptance():
    """The levels are spelled in the data file and named by ONE module; the acceptance check asks
    proof_level and carries no id, no rank and no mutation kind of its own."""
    source = (SCRIPTS / "acceptance.py").read_text(encoding="utf-8")
    # (`failure_kind != "assertion"` is a failure kind, not a level or a mutation kind: it stays.)
    for literal in ('"live"', "'live'", "catches_broken_product", "real_behavior", "assertion_edit"):
        check_not_in(f"acceptance.py carries no {literal}", literal, source)
    check_in("it asks proof_level", "proof_level.probe_problem", source)


def the_one_reader_of_current_bytes():
    """current_test_sha: the raw sha256 of the file on disk, resolved under the project."""
    check_eq("a row's file under the project: its raw sha256", PL.current_test_sha({"file": TEST_REL}), sha_now())
    check_eq("the same through the node path", PL.current_test_sha({"trace_binding": {"selector": f"{TEST_REL}::test_x"}}),
             sha_now())
    check_eq("backslashes in a Windows-spelled path", PL.current_test_sha({"file": TEST_REL.replace("/", "\\")}), sha_now())
    check_eq("a file that is not there, none named, an absolute path, a non-row: ''",
             (PL.current_test_sha({"file": "tests/nope.py"}), PL.current_test_sha({}),
              PL.current_test_sha({"file": str(PROJECT["root"] / TEST_REL)}), PL.current_test_sha(None)), ("", "", "", ""))
    check_eq("an explicit project wins", PL.current_test_sha({"file": TEST_REL}, project=PROJECT["root"]), sha_now())
    check_eq("claimed: the trace_binding when there is one",
             PL.claimed_test_sha({"file": TEST_REL, "trace_binding": {"test_content_sha": "bound"}}), "bound")
    check_eq("claimed: the file's bytes when the row binds none", PL.claimed_test_sha({"file": TEST_REL}), sha_now())
    check_eq("claimed: nothing when neither", PL.claimed_test_sha({"file": "tests/nope.py"}), "")


def comment_only_changes_keep_the_receipt():
    """t-016 Amendment 3 (D-0017, "cosmetic is measured, not judged"): a receipt counts over a
    comment-only change of its test - raw bytes stay the file's identity, and diff_scope's one
    classifier (`executable_sha`) says whether a change was cosmetic."""
    import diff_scope
    tmp = temp_dir("qa-comment-only-")
    rel = "tests/test_y.py"
    path = PROJECT["root"] / rel
    before = "import pytest\n\n\ndef test_y(client):\n    total = client.total()\n    assert total == 3\n"
    try:
        write(path, before)
        raw_before, code_before = digest(path), diff_scope.executable_sha(before)
        row = entry(file=rel, trace_binding={"test_content_sha": raw_before})
        measured = put(tmp, "y-live", live(test_content_hash=raw_before, test_code_sha=code_before))
        legacy = put(tmp, "y-legacy", live(test_content_hash=raw_before, receipt_hash="legacy"))
        check_eq("on the bytes it measured: live, no note",
                 PL.reached(dict(row, sensitivity_proof={"receipt_ref": measured}), {}, tmp)["words"],
                 "the check is live")
        # a comment line added to the test: other raw bytes, the same code
        write(path, before.replace("    assert", "    # the client sums the lines\n    assert"))
        check("the raw bytes did change", digest(path) != raw_before)
        got = PL.reached(dict(row, sensitivity_proof={"receipt_ref": measured}), {}, tmp)
        check_eq("a comment-only edit: the level is still reached", (got["level"], got["ref"], got["issues"]),
                 ("live", measured, []))
        check_eq("...and the words say which proof it is (FR-41)", got["words"],
                 "the check is live (the receipt holds over a comment-only change)")
        check_eq("...the note is the vocabulary's", PL.comment_only_words(),
                 "the receipt holds over a comment-only change")
        check_eq("valid_level agrees: it still shields against a downgrade", PL.valid_level(row, measured, tmp), "live")
        check_eq("a receipt written before test_code_sha existed counts on raw bytes only: not reached",
                 PL.reached(dict(row, sensitivity_proof={"receipt_ref": legacy}), {}, tmp)["level"], None)
        # equal rank: the receipt for these very bytes is preferred to one that holds over comments
        exact = put(tmp, "y-exact", live(test_content_hash=digest(path),
                                          test_code_sha=code_before, receipt_hash="exact"))
        got = PL.reached(dict(row, sensitivity_proof={"receipt_ref": measured}),
                         {"obligation_bindings": [binding("i1", exact)]}, tmp)
        check_eq("tie on rank: the exact-bytes receipt wins over the row's own comment-only one",
                 (got["ref"]["path"], got["words"]), (exact["path"], "the check is live"))
        # an assert changed: other code - the level is gone
        write(path, before.replace("== 3", "== 4"))
        got = PL.reached(dict(row, sensitivity_proof={"receipt_ref": measured}), {}, tmp)
        check_eq("an assert changed: not reached", (got["level"], got["words"]), (None, "not probed"))
        check_in("...and the issue says other code", "and other code: probe the current bytes again",
                 " ".join(got["issues"]))
        # critic t-048, end to end: an assert made VACUOUS by a change a per-line reader called prose
        # (the expected list element `"alice",` became `*names,` - `names == [*names]` always holds)
        # does NOT keep "the check is live"
        listed = ("import pytest\n\n\ndef test_y(client):\n    names = client.names()\n"
                  "    assert names == [\n        \"alice\",\n    ]\n")
        write(path, listed)
        listed_receipt = put(tmp, "y-listed", live(test_content_hash=digest(path),
                                                   test_code_sha=diff_scope.executable_sha(listed),
                                                   receipt_hash="listed"))
        listed_row = dict(row, sensitivity_proof={"receipt_ref": listed_receipt})
        check_eq("the list-element test: live", PL.reached(listed_row, {}, tmp)["level"], "live")
        write(path, listed.replace('"alice",', "*names,"))
        got = PL.reached(listed_row, {}, tmp)
        check_eq("the assert made vacuous by a one-line edit: the receipt does NOT hold", (got["level"], got["words"]),
                 (None, "not probed"))
        write(path, listed.replace("    assert", "    # the stub returns one name\n    assert"))
        check_eq("...while a comment beside it keeps it (the control)", PL.reached(listed_row, {}, tmp)["words"],
                 "the check is live (the receipt holds over a comment-only change)")
        # a test file that is not Python has no code sha: only raw equality counts
        js = dict(row, file="tests/test_y.js")
        write(PROJECT["root"] / "tests/test_y.js", "// a\ntest('x', () => expect(1).toBe(1));\n")
        check_eq("a non-.py test file: no code sha", PL.current_code_sha(js), "")
        (PROJECT["root"] / "tests/test_y.js").unlink()
        write(path, before.replace("== 3", "== 4"))
        # bytes that are not UTF-8: no code sha, only the raw rule (the safe direction)
        path.write_bytes(before.encode("utf-8") + b"# \xff\xfe not utf-8\n")
        check_eq("undecodable bytes have no code sha", PL.current_code_sha({"file": rel}), "")
        check_eq("...so a comment-looking change of them is not held over", PL.reached(
            dict(row, sensitivity_proof={"receipt_ref": measured}), {}, tmp)["level"], None)
        check_eq("code_sha of nothing and of non-bytes", (PL.code_sha(None), PL.code_sha(b"\xff")), ("", ""))
        check_eq("code_sha of bytes is diff_scope's executable_sha of their text",
                 PL.code_sha(before.encode("utf-8")), code_before)
    finally:
        path.unlink(missing_ok=True)
        cleanup(tmp)


# --- t-043 C: one identity of a test, one predicate ------------------------------------------------------------

def same_test_truth_table():
    """`same_test(now, bound)`: the first rule that matches wins, and every equality needs two NON-EMPTY values
    (MC4: a predicate that counts "" == "" keeps a proof over code nobody measured)."""
    ident = {"instance_content_sha": "c1", "instance_code_sha": "k1", "job_id": "j"}

    def carrier(raw="r1", code="f1", identity=None, **extra):
        return {"input_hash": raw, "test_code_sha": code, "instance_identity": identity or {}, **extra}
    check_eq("1: both carry an identity, equal content sha: instance (the file's shas are not consulted)",
             PL.same_test(carrier(identity=ident), carrier("r2", "f2", identity=dict(ident, job_id="other"))), "instance")
    check_eq("1: both, content differs, code equal: instance_code",
             PL.same_test(carrier(identity=ident), carrier(identity=dict(ident, instance_content_sha="c2"))), "instance_code")
    check_eq("1: both, both differ: '' - even though the file's raw and code shas are equal (fork F-C3 a)",
             PL.same_test(carrier(identity=ident), carrier(identity={"instance_content_sha": "c2",
                                                                    "instance_code_sha": "k2", "job_id": "j"})), "")
    check_eq("1: both carry one, both content shas EMPTY and the code shas differ: '', not 'the same'",
             PL.same_test(carrier(identity={"instance_content_sha": "", "instance_code_sha": "k1"}),
                          carrier(identity={"instance_content_sha": "", "instance_code_sha": "k2"})), "")
    check_eq("2: neither carries one: the raw file rule", PL.same_test(carrier(), carrier()), "raw")
    check_eq("3: neither, raw differs, code sha equal: file_code (a receipt of t-023 that recorded it)",
             PL.same_test(carrier("r1", "f1"), carrier("r2", "f1")), "file_code")
    check_eq("4: neither, raw differs and only one side has a code sha: ''",
             PL.same_test(carrier("r1", "f1"), carrier("r2", "")), "")
    check_eq("two absent raw shas are never equal", PL.same_test(carrier("", ""), carrier("", "")), "")
    check_eq("nor two absent code shas beside different raw ones", PL.same_test(carrier("r1", ""), carrier("r2", "")), "")
    check_eq("an identity whose code sha is empty is none at all (then the raw rule)", PL.same_test(
        carrier(identity={"instance_content_sha": "c", "instance_code_sha": ""}),
        carrier(identity={"instance_content_sha": "c", "instance_code_sha": ""})), "raw")
    check_eq("1b: the bound side has an identity, now has none because a MEASUREMENT failed: ''",
             PL.same_test(carrier(why=PL.WHY_NO_CODE), carrier(identity=ident)), "")
    for cause in sorted(PL.MEASUREMENT):
        check_eq(f"1b for every measurement cause: {cause[:34]}",
                 PL.same_test(carrier(why=cause), carrier(identity=ident)), "")
    for cause in sorted(PL.FALL_THROUGH):
        check_eq(f"a cause that is no failure falls through to the file rule: {cause[:34]}",
                 PL.same_test(carrier(why=cause), carrier(identity=ident)), "raw")
    for cause in sorted(PL.MEASUREMENT):
        check_eq(f"1b is symmetric: the BOUND side has none because its measurement failed ({cause[:24]}): ''",
                 PL.same_test(carrier(identity=ident), carrier(why=cause)), "")
    for cause in sorted(PL.FALL_THROUGH):
        check_eq(f"...and a bound side that has none for no failure ({cause[:24]}) is the file rule",
                 PL.same_test(carrier(identity=ident), carrier(why=cause)), "raw")
    check_eq("the older carrier has none (a review from before), now has one: the file rule",
             PL.same_test(carrier(identity=ident), carrier()), "raw")
    check_eq("...and its raw differs and it recorded no code sha: ''",
             PL.same_test(carrier("r2", "f1", identity=ident), carrier("r1", "")), "")
    check_eq("carriers that are not objects say nothing", (PL.same_test(None, None), PL.same_test({}, {})), ("", ""))
    check_eq("proof_identity: a receipt's test_content_hash, a record's test_file_sha256 (never its fingerprint), "
             "a window carrier's input_hash",
             (PL.proof_identity({"test_content_hash": "a", "input_hash": "fp"})["input_hash"],
              PL.proof_identity({"test_file_sha256": "b", "input_hash": "fp"})["input_hash"],
              PL.proof_identity({"input_hash": "c"})["input_hash"]), ("a", "b", "c"))
    check_eq("proof_identity: an identity with no code sha is none; the flat sha of an old record is never one",
             (PL.proof_identity({"instance_identity": {"instance_content_sha": "x"}})["instance_identity"],
              PL.proof_identity({"instance_content_sha": "old-conftest-only"})["instance_identity"]), ({}, {}))
    check_eq("proof_identity: an identity keeps only its three keys",
             PL.proof_identity({"instance_identity": dict(ident, extra="x")})["instance_identity"], ident)
    check_eq("proof_identity: what a carrier recorded about why it has none travels",
             PL.proof_identity({"input_hash": "r", "instance_identity_why": PL.WHY_NO_CODE}).get("why"), PL.WHY_NO_CODE)
    check_eq("proof_identity of nothing", PL.proof_identity(None),
             {"input_hash": "", "test_code_sha": "", "instance_identity": {}})
    check_in("the block a repeated probe is answered under is one constant", "already probed on these bytes",
             PL.PROBE_BLOCK)


def rh1_9_compare_identity():
    """RH1-9 N1 (AR-13, AR-28, AR-4, AR-20): K-A the comparator's truth table, K-B `same_test` over it, K-N the node/path
    rules, K-C the census of the places that compare a test's identity."""
    import ast
    import tempfile

    def side(code="", content=""):
        return {"instance_code_sha": code, "instance_content_sha": content}
    # K-A: rules 1-3, then the inconvenient inputs. The error direction: never "same" on an unknown.
    for label, a, b, want in (
            ("1: code equal, content equal -> same by content", side("k", "c"), side("k", "c"), ("same", "content")),
            ("1: code equal, content differs (a comment) -> same by code", side("k", "c1"), side("k", "c2"), ("same", "code")),
            ("1: code equal, one content absent -> same by code", side("k", "c"), side("k", ""), ("same", "code")),
            ("1: code differs, content EQUAL -> different by code (E2)", side("k1", "c"), side("k2", "c"), ("different", "code")),
            ("1: code differs, content differs -> different by code", side("k1", "c1"), side("k2", "c2"), ("different", "code")),
            ("2: one side has no code, content equal -> same by content (legacy)", side("", "c"), side("k", "c"), ("same", "content")),
            ("2: no code at all, content differs -> different by content", side("", "c1"), side("", "c2"), ("different", "content")),
            ("3: nothing on either side -> unknown", side(), side(), ("unknown", "")),
            ("3: code on one side only, no content on the other -> unknown", side("k", ""), side("", ""), ("unknown", "")),
            ("3: content on one side only -> unknown", side("", "c"), side("", ""), ("unknown", "")),
            ("blank values on both sides are none -> unknown", side(" ", "\t"), side(" ", "\t"), ("unknown", "")),
            ("a value is stripped: ' k ' equals 'k'", side(" k ", ""), side("k", ""), ("same", "code")),
            ("hex in another case is another value", side("ABC", ""), side("abc", ""), ("different", "code")),
            ("0 and None are none", side(0, None), side(None, 0), ("unknown", "")),
            ("other keys are never read", {"input_hash": "r", "test_code_sha": "x"}, {"input_hash": "r", "test_code_sha": "x"},
             ("unknown", ""))):
        check_eq(f"K-A compare_identity: {label}", PL.compare_identity(a, b), want)
    check_eq("K-A: a list is not an identity", PL.compare_identity([side("k", "c")], side("k", "c")), ("unknown", ""))
    check_eq("K-A: None and None", PL.compare_identity(None, None), ("unknown", ""))
    check_eq("K-A: a string is not an identity", PL.compare_identity("k", side("k", "c")), ("unknown", ""))

    # K-B: `same_test` over the comparator. The existing table (same_test_truth_table) stays as it is; two new rows.
    def carrier(raw="r1", code="f1", identity=None, **extra):
        return {"input_hash": raw, "test_code_sha": code, "instance_identity": identity or {}, **extra}
    check_eq("K-B (E2): equal content sha, DIFFERENT code sha -> '' (the one intended change of behaviour)",
             PL.same_test(carrier(identity={"instance_content_sha": "c", "instance_code_sha": "k1"}),
                          carrier(identity={"instance_content_sha": "c", "instance_code_sha": "k2"})), "")
    check_eq("K-B (F5, accepted risk): a legacy carrier with no identity against a test with no run, the same raw bytes "
             "after a move -> raw",
             PL.same_test(carrier("r1", "f1", why=PL.WHY_NO_REQUEST), carrier("r1", "f1")), "raw")
    check_in("K-B: the accepted risk is named in the docstring of same_test", "ACCEPTED RISK (F5)", PL.same_test.__doc__)

    # K-N: `same_path` and `node_selects_row`.
    for label, a, b, want in (
            ("a backslash is a slash", "tests\\sub\\test_m.py", "tests/sub/test_m.py", True),
            ("a Windows absolute path ends in the POSIX relative one", "C:\\proj\\tests\\test_m.py", "tests/test_m.py", True),
            ("and the other way round", "tests/test_m.py", "C:\\proj\\tests\\test_m.py", True),
            ("the tail must stand on a boundary", "xtests/test_m.py", "tests/test_m.py", False),
            ("the case counts (F3)", "Tests/test_m.py", "tests/test_m.py", False),
            ("an empty path is no path", "", "", False),
            ("None is no path", None, "tests/test_m.py", False)):
        check_eq(f"K-N same_path: {label}", PL.same_path(a, b), want)
    check("K-N: the private name is gone", not hasattr(PL, "_same_path"))
    row = entry("test_x", file="tests/t.py")
    for label, selected, node_file, want in (
            ("the row's own id, its own file", "test_x", "tests/t.py", True),
            ("the file by its tail", "test_x", "t.py", True),
            ("a parameter with a slash", "test_x[a/b-1]", "t.py", True),
            ("a parameter with '::'", "test_x[a::b]", "t.py", True),
            ("a nested bracket", "test_x[[n]]", "t.py", True),
            ("another file", "test_x", "tests/other.py", False),
            ("the same file in another case", "test_x", "Tests/T.py", False),
            ("another function", "test_y[a]", "t.py", False)):
        check_eq(f"K-N node_selects_row: {label}", PL.node_selects_row(row, selected, node_file), want)
    check_eq("K-N node_selects_row: a class-qualified row and a nested bracket",
             PL.node_selects_row(entry("TestC::test_x", file="tests/t.py"), "TestC::test_x[[n]]", "t.py"), True)
    check_eq("K-N node_selects_row: no node file and strict -> no row",
             PL.node_selects_row(row, "test_x", None, strict=True), False)

    # K-C: the census (AR-13). (a) the named functions call the comparator; (b) the comparisons of a test's sha keys by
    # subscript or `.get` live in proof_level.py, plus the named exceptions. Limit of (b): a comparison made through local
    # variables (as `same_instance_bytes` did) is invisible to it; (a) holds those three functions only.
    keys = ("instance_content_sha", "instance_code_sha")

    def operand_key(node) -> bool:
        if isinstance(node, ast.Subscript):
            return isinstance(node.slice, ast.Constant) and node.slice.value in keys
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value in keys)

    def hits(source: str) -> list:
        """(function name or '') of every `==`/`!=` with an operand that reads one of the keys."""
        tree = ast.parse(source)
        found = []

        def walk(node, owner):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    walk(child, child.name)
                    continue
                if isinstance(child, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in child.ops) \
                        and any(operand_key(x) for x in [child.left, *child.comparators]):
                    found.append(owner)
                walk(child, owner)
        walk(tree, "")
        return found
    with tempfile.TemporaryDirectory(prefix="qa-census-") as tmp:
        sample = Path(tmp) / "sample.py"
        sample.write_text('def f(x, y):\n    return x.get("instance_code_sha") == y\n', encoding="utf-8")
        check_eq("K-C control: the detector finds a sample comparison", hits(sample.read_text(encoding="utf-8")), ["f"])
    outside = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == "proof_level.py":
            continue
        outside += [(path.name, owner) for owner in hits(path.read_text(encoding="utf-8"))]
    check_eq("K-C (b): outside proof_level.py the identity keys are compared only by the named exceptions "
             "(an exception that is no longer in the code is red too; a raise needs a verdict naming it, AR-20)",
             sorted(set(outside)), [("probe_by_code.py", "author_binding")])
    # (a) the sites that decide through the comparator (E13: the spec leaves the list empty until N2-N4 are merged; this
    # branch carries N1-N4 together, so the three names are here).
    callers = (("execution_request.py", "same_instance_bytes"), ("run_history.py", "_compare_shas"),
               ("acceptance.py", "green_on_current_bytes_why"))
    for name, owner in callers:
        tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
        body = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == owner)
        called = {n.func.attr for n in ast.walk(body) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        check(f"K-C (a): {name}:{owner} calls the comparator", bool(called & {"compare_identity", "same_test"}))


def crlf_line_endings_are_not_code():
    """Edge 8: LF -> CRLF changes the file's raw sha and not its code: a receipt that recorded `test_code_sha` (and
    no per-test identity) holds by the file's code, and says so."""
    import diff_scope
    tmp = temp_dir("qa-crlf-")
    rel = "tests/test_z.py"
    path = PROJECT["root"] / rel
    source = "def test_z():\n    total = 1 + 2\n    assert total == 3\n"
    try:
        path.write_bytes(source.encode("utf-8"))
        raw = digest(path)
        row = entry(file=rel, trace_binding={"test_content_sha": raw})
        measured = put(tmp, "z-live", live(test_content_hash=raw, test_code_sha=diff_scope.executable_sha(source)))
        path.write_bytes(source.replace("\n", "\r\n").encode("utf-8"))
        check("the raw bytes changed", digest(path) != raw)
        got = PL.reached(dict(row, sensitivity_proof={"receipt_ref": measured}), {}, tmp)
        check_eq("CRLF: the level holds, and the words say it is by the code of the test",
                 (got["level"], got["words"]), ("live", f"the check is live ({PL.comment_only_words()})"))
    finally:
        path.unlink(missing_ok=True)
        cleanup(tmp)


TWO_TESTS = ("def test_a(db):\n    assert db.names() == ['alice']\n\n\ndef test_b():\n    assert 1 == 1\n")
DB_CONFTEST = ("import pytest\n\n\n@pytest.fixture\ndef db():\n    return Db()\n\n\nclass Db:\n"
               "    def names(self):\n        return ['alice']\n")


def instance_identity_and_reached_per_instance():
    import test_probe_binding as PB
    fix = PB.Fixture({"tests/conftest.py": DB_CONFTEST, "tests/test_x.py": TWO_TESTS},
                     [PB.row("test_a", "TC-1", "tests/test_x.py"), PB.row("test_b", "TC-2", "tests/test_x.py")])
    try:
        manifest_path = fix.task / "work" / "automation-manifest.json"
        entry = json.loads(manifest_path.read_text(encoding="utf-8"))["tests"][0]
        test = fix.root / "tests" / "test_x.py"
        check_eq("no request selects the instance: {}, and the job directory is not created for the question",
                 (PL.instance_identity(entry, fix.task)["instance_identity"], (fix.task / "state" / "execution-jobs").exists()),
                 ({}, False))
        job = fix.job(["TC-1", "TC-2"], completed=False)
        got = PL.instance_identity(entry, fix.task)
        check_eq("the identity is the job's, re-measured", got["instance_identity"]["instance_content_sha"],
                 job["request"]["instance_contracts"]["test_a"]["instance_content_sha"])
        # a command that is not pytest, a file that is gone, a selector the job lacks: {} with a MEASUREMENT cause
        stored = next((fix.task / "state" / "execution-jobs").glob("*.json"))
        original = stored.read_text(encoding="utf-8")
        body = json.loads(original)
        body["request"]["command"]["argv"] = ["dotnet", "test"]
        stored.write_text(json.dumps(body), encoding="utf-8")
        PL._reset()
        check_eq("a command that is not pytest: {}, a measurement cause", (PL.instance_identity(entry, fix.task)["instance_identity"],
                                                                           PL.instance_identity(entry, fix.task)["why"]),
                 ({}, PL.WHY_UNMEASURED))
        stored.write_text(original, encoding="utf-8")
        PL._reset()
        moved = test.with_suffix(".moved")
        test.rename(moved)
        gone = PL.instance_identity(entry, fix.task)
        check_eq("a test file that is gone: {}, no input_hash, and the cause says the file", (
            gone["instance_identity"], gone["input_hash"], gone["why"]), ({}, "", PL.WHY_NO_FILE))
        moved.rename(test)
        PL._reset()
        # reached, per instance: a receipt of test_a as the probe wrote it - identity measured by the producer
        now = PL.instance_identity(entry, fix.task)
        live_body = live("test_a", case_version="cv_1", test_content_hash=now["input_hash"],
                         test_code_sha=now["test_code_sha"], instance_identity=now["instance_identity"])
        ref = put(fix.task, "test_a-live-1", live_body)
        proven = dict(entry, sensitivity_proof={"receipt_ref": ref})
        original_text = test.read_bytes()

        def reach():
            PL._reset()
            return PL.reached(proven, {}, fix.task)
        check_eq("at the probed bytes: live, no note", (reach()["level"], reach()["words"]), ("live", "the check is live"))
        test.write_bytes(original_text.replace(b"assert 1 == 1", b"assert 2 == 2"))
        got = reach()
        check_eq("ANOTHER test of the file edited: the level holds, and it is the same test (no comment-only note)",
                 (got["level"], got["words"], got["issues"]), ("live", "the check is live", []))
        check_eq("...valid_level agrees", (PL.valid_level(proven, ref, fix.task)), "live")
        test.write_bytes(original_text.replace(b"    assert db", b"    # what the fixture holds\n    assert db"))
        got = reach()
        check_eq("a comment in the test: the level holds, and the words say by what (FR-41)",
                 (got["level"], got["words"]), ("live", f"the check is live ({PL.code_unchanged_words()})"))
        test.write_bytes(original_text.replace(b"['alice']", b"['bob']"))
        got = reach()
        check_eq("a code edit of the test: not reached", (got["level"], got["words"]), (None, "not probed"))
        check_in("...and the issue says the bytes and the door", "and other code: probe the current bytes again with "
                 "probe_by_code.py --instance test_a", got["issues"])
        test.write_bytes(original_text)
        (fix.root / "tests" / "conftest.py").write_text(DB_CONFTEST.replace("['alice']", "['bob']"), encoding="utf-8")
        got = reach()
        check_eq("a fixture the test uses changed (the file's raw bytes are equal!): not reached",
                 (got["level"], got["words"]), (None, "not probed"))
        check_in("...said as the same file with a changed dependency", "measured on this very file", got["issues"])
        (fix.root / "tests" / "conftest.py").write_text(DB_CONFTEST, encoding="utf-8")
        # a receipt that carries no identity (before per-test binding), the same file: the raw rule as ever
        old = put(fix.task, "test_a-live-2", live("test_a", case_version="cv_1", test_content_hash=now["input_hash"],
                                                 receipt_hash="legacy"))
        legacy = dict(entry, sensitivity_proof={"receipt_ref": old})
        PL._reset()
        check_eq("a receipt with no identity, the same raw bytes: live", PL.reached(legacy, {}, fix.task)["level"], "live")
        test.write_bytes(original_text.replace(b"assert 1 == 1", b"assert 2 == 2"))
        PL._reset()
        check_eq("...and after another test's edit its raw bytes differ, it recorded no code sha: not reached",
                 PL.reached(legacy, {}, fix.task)["level"], None)
        test.write_bytes(original_text)
        # tie of two receipts of one level: the very bytes, then the same test, then only the same code
        check_eq("holds_over_comments is a thin wrapper of same_test", (
            PL.holds_over_comments(proven, live_body, now=PL.instance_identity(entry, fix.task)),
            PL.holds_over_comments(proven, {})), (False, False))
    finally:
        fix.close()
        use_project(PROJECT["root"])
        PL._reset()


def the_identity_cache_reads_the_job_directory_once():
    """FR-27: 20 rows of one story -> the job directory is parsed ONCE per state of it, and a change of the
    directory (a new job) is seen by the next call."""
    import execution_request as ER
    import test_probe_binding as PB
    rows = [PB.row(f"test_{n}", "TC-1", "tests/test_many.py") for n in range(20)]
    text = "".join(f"def test_{n}():\n    assert {n} == {n}\n\n\n" for n in range(20))
    fix = PB.Fixture({"tests/test_many.py": text}, rows, scope=("TC-1",))
    real = ER.JobStore.jobs
    reads = []
    try:
        fix.job(["TC-1"], completed=False)
        entries = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"]

        def counted(self):
            reads.append(1)
            return real(self)
        ER.JobStore.jobs = counted
        PL._reset()
        found = [PL.instance_identity(e, fix.task)["instance_identity"] for e in entries]
        check_eq("20 rows, all measured", len([f for f in found if f]), 20)
        check_eq("...and the job directory was read ONCE", len(reads), 1)
        PL.instance_identity(entries[0], fix.task)
        check_eq("...a second question of the same state reads nothing more", len(reads), 1)
        ER.JobStore.jobs = real
        fix.job(["TC-1"], completed=False)  # the directory changed: a new job
        ER.JobStore.jobs = counted
        PL.instance_identity(entries[0], fix.task)
        check_eq("a new job in the directory: read again", len(reads), 2)
        # the cache never hides a helper edited under it
        before = PL.instance_identity(entries[0], fix.task)["instance_identity"]["instance_content_sha"]
        (fix.root / "tests" / "test_many.py").write_text(text.replace("assert 0 == 0", "assert 0 == 0  # x\n    pass"),
                                                          encoding="utf-8")
        after = PL.instance_identity(entries[0], fix.task)["instance_identity"]["instance_content_sha"]
        check("an edit of the test file under a cached identity is seen (the raw sha is in the key)", before != after)
        PL._reset()
        check_eq("_reset forgets the caches", len(PL._IDENTITY_CACHE) + len(PL._JOBS_CACHE), 0)
    finally:
        ER.JobStore.jobs = real
        fix.close()
        use_project(PROJECT["root"])
        PL._reset()


# --- HF8-18 N1: a receipt of another spelling of the same test (C-K5, C-K6) --------------------------------------

def other_spelling_world():
    """The Story of `test_run_freshness` (a real project, a receipt measured on the current bytes, its probe record), a receipt
    that can be written under ANY instance id, and the text the test's bytes are edited to afterwards."""
    import test_run_freshness as RF
    import test_probe_binding as PB
    s = RF.receipt_story()
    edit = PB.TEST_A.replace('names == ["alice"]', 'names == ["bob"]')
    now_before = PL.instance_identity(s.entry, s.task, s.root)

    def put_receipt(iid: str, name: str, *, record_node="tests/test_a.py::test_a", over=None, with_record=True) -> dict:
        body = {"instance_id": iid, "case_version": "cv_1", "test_content_hash": now_before["input_hash"],
                "source_revision": "src", "build_id": "b", "mutation": "invert", "expected_assertion_failure": "x",
                "actual_failure": "x", "assertion_location": "t.py:1", "restoration_evidence": "r", "failure_kind": "assertion",
                "proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
                "receipt_hash": "h-" + name, "test_code_sha": now_before["test_code_sha"],
                "instance_identity": now_before["instance_identity"], "probe_record": f"work/probes/{name}.json"}
        body.update(over or {})
        path = PB.write(s.task / "work" / "sensitivity-receipts" / f"{name}-live.json", body)
        if with_record:
            PB.write(s.task / "work" / "probes" / f"{name}.json", {
                "probe_tool": "probe_by_code.py", "instance_id": iid, "verdict": "intended_failure", "test_node": record_node,
                "mutation": "invert", "mutation_detail": {"line": 3, "mutation": "invert"},
                "mutated_file": {"path": "tests/test_a.py", "sha256": now_before["input_hash"]}})
        return {"receipt_ref": {"path": path.relative_to(s.task).as_posix(), "sha256": PB.digest(path)}}

    def row(iid: str, proof=None) -> dict:
        out = dict(s.entry, instance_id=iid)
        out.pop("sensitivity_proof", None)
        if proof is not None:
            out["sensitivity_proof"] = proof
        return out
    return s, edit, put_receipt, row


def the_receipt_of_another_spelling_of_the_same_test():
    s, edit, put_receipt, row = other_spelling_world()
    try:
        # (a) the receipt of the bare `test_a`, the row is `test_a[p]`
        bare = put_receipt("test_a", "test_a")
        mine = row("test_a[p]", bare)
        got = PL.probe_freshness(mine, {}, s.task)
        check_eq("C-K5 control: the bytes did not change - the row is `missing`, nothing is offered",
                 (got["state"], got["replay"]), ("missing", None))
        s.put("tests/test_a.py", edit)
        got = PL.probe_freshness(mine, {}, s.task)
        check_eq("C-K5 (a): a bare receipt, the row `test_a[p]`, other bytes - stale, with its own why",
                 (got["state"], got["why"]), ("stale", PL.WHY_PROBE_OTHER_INSTANCE))
        check_eq("C-K5 (a): ...the replay names the ROW's instance and node, the mutation is the recorded one",
                 got["replay"], {"test": "tests/test_a.py::test_a[p]", "instance": "test_a[p]", "mutation": "invert", "oracle": ""})
        reached = PL.reached(mine, {}, s.task)
        check("C-K6: ...and until a new probe `reached` gives no level, with the same issue (the old receipt counts for nothing)",
              reached["level"] is None and any("instance_id does not match" in str(i) for i in reached["issues"]), str(reached))
        check_eq("C-K6: ...the receipt's issues are the contract's own (nothing was changed)",
                 C.sensitivity_proof_issues(mine, s.task), ["sensitivity_proof.instance_id does not match the manifest instance"])
        # C-K6: the NEW receipt, measured on the current bytes under the row's own instance id, is what counts
        fresh_now = PL.instance_identity(mine, s.task, s.root)
        new = put_receipt("test_a[p]", "test_a-p", over={"test_content_hash": fresh_now["input_hash"],
                                                          "test_code_sha": fresh_now["test_code_sha"],
                                                          "instance_identity": fresh_now["instance_identity"]})
        check_eq("C-K6: after the probe the level comes from the NEW receipt",
                 PL.reached(row("test_a[p]", new), {}, s.task)["level"], "live")
        # (c) a receipt of another function
        other = put_receipt("test_y", "test_y")
        check_eq("C-K5 (c): a receipt of `test_y` for the row `test_a[p]` - missing (M-C2)",
                 PL.probe_freshness(row("test_a[p]", other), {}, s.task)["state"], "missing")
        # (d) the receipt file's hash does not match
        bad = {"receipt_ref": {"path": bare["receipt_ref"]["path"], "sha256": "0" * 64}}
        check_eq("C-K5 (d): the instance differs and the hash is wrong - missing",
                 PL.probe_freshness(row("test_a[p]", bad), {}, s.task)["state"], "missing")
        # an issue besides the instance one: another case version, a setup failure, an unknown level
        for label, over in (("another case version", {"case_version": "cv_9"}), ("a setup failure", {"failure_kind": "setup"}),
                            ("an unknown level", {"proof_level": "bogus-level"})):
            ref = put_receipt("test_a", "test_a-x", over=over)
            check_eq(f"C-K5: the instance differs AND {label} - missing (M-C1: the ONLY issue)",
                     PL.probe_freshness(row("test_a[p]", ref), {}, s.task)["state"], "missing")
        # (f) the same function name in another FILE
        elsewhere = put_receipt("test_a", "test_a-f", record_node="tests/b.py::test_a")
        check_eq("C-K5 (f): the record of the receipt is in another file - missing (M-C2a)",
                 PL.probe_freshness(row("test_a[p]", elsewhere), {}, s.task)["state"], "missing")
        nonode = put_receipt("test_a", "test_a-n", record_node="")
        check_eq("an unknown file (the record names no node) - missing, never a guess",
                 PL.probe_freshness(row("test_a[p]", nonode), {}, s.task)["state"], "missing")
        norecord = put_receipt("test_a", "test_a-r", with_record=False)
        check_eq("no record of the probe at all - missing",
                 PL.probe_freshness(row("test_a[p]", norecord), {}, s.task)["state"], "missing")
        # (g) the case-prefixed spelling of the row
        check_eq("C-K5 (g): `TC-002::test_a[p]` against a bare receipt - admitted",
                 PL.probe_freshness(row("TC-002::test_a[p]", bare), {}, s.task)["state"], "stale")
        # (h) a hash identity names no function
        hashed = put_receipt("ti_0123456789abcdef0123", "ti_0123456789abcdef0123")
        check_eq("C-K5 (h): `ti_...` against `ti_....[p]` - not admitted",
                 PL.probe_freshness(row("ti_0123456789abcdef0123[p]", hashed), {}, s.task)["state"], "missing")
        check_eq("the one predicate, asked directly: True for the control row",
                 PL._wrong_instance_only(mine, mine, s.task), True)
        check_eq("...and False for a row whose receipt is its own",
                 PL._wrong_instance_only(row("test_a", bare), row("test_a", bare), s.task), False)
        # the doors outside the dispatch: admitted for the row of another spelling, refused with no receipt
        check_eq("C-K11/K12 ground: `reprobe_admitted` takes the row of another spelling",
                 PL.reprobe_admitted(mine, {}, s.task), (True, ""))
        check_eq("...and refuses the row with no receipt at all", PL.reprobe_admitted(row("test_a[p]"), {}, s.task)[0], False)
    finally:
        s.close()


def the_replay_keeps_the_class_and_reads_the_record_by_the_receipts_names():
    """F4 and F7 (b): a test in a class keeps its class chain in the replayed node; the record behind a receipt with no `probe_record` is
    read by the receipt's own instance id; a `probe_record` outside the task root is refused. Kills: the class chain dropped
    (`_split_node(test)[1]`); the fallback by `instance_id`; the refusal of a record outside the task root."""
    import test_probe_binding as PB
    s, edit, put_receipt, row = other_spelling_world()
    try:
        s.put("tests/test_a.py", edit)
        classed = put_receipt("test_a", "test_a", record_node="tests/test_a.py::TestK::test_a")
        got = PL.probe_freshness(row("test_a[p]", classed), {}, s.task)
        check_eq("F4: a method of a class - the replay node keeps the class chain, then the row's own instance",
                 (got["state"], got["replay"] and got["replay"]["test"]), ("stale", "tests/test_a.py::TestK::test_a[p]"))
        byid = put_receipt("test_a", "test_a", over={"probe_record": ""})
        got = PL.probe_freshness(row("test_a[p]", byid), {}, s.task)
        check_eq("F7 (b): no `probe_record` on the receipt - the record is read by the receipt's OWN instance id",
                 (got["state"], got["replay"] and got["replay"]["test"]), ("stale", "tests/test_a.py::test_a[p]"))
        outside = s.root / "outside-probe.json"
        PB.write(outside, {"probe_tool": "probe_by_code.py", "instance_id": "test_a", "verdict": "intended_failure",
                           "test_node": "tests/test_a.py::test_a", "mutation": "invert", "mutation_detail": {"line": 3, "mutation": "invert"},
                           "mutated_file": {"path": "tests/test_a.py", "sha256": "0" * 64}})
        away = put_receipt("test_a", "test_a-away", over={"probe_record": str(outside)}, with_record=False)
        check_eq("F7 (b): a `probe_record` outside the task root is not read - missing, nothing is replayed",
                 (PL.probe_freshness(row("test_a[p]", away), {}, s.task)["state"], PL._instance_record(
                     C.sensitivity_proof_receipt(row("test_a[p]", away), s.task)[0], s.task)), ("missing", None))
    finally:
        s.close()


def the_receipt_of_a_neighbour_through_the_obligation_binding():
    s, edit, put_receipt, row = other_spelling_world()
    try:
        neighbour = put_receipt("test_a[a]", "test_a-a", record_node="tests/test_a.py::test_a[a]")
        path = neighbour["receipt_ref"]["path"]
        manifest = {"obligation_bindings": [{"obligation_id": "OB-1", "sensitivity": "proven", "probe_receipt_ref": path,
                                              "instance_ids": ["test_a[a]", "test_a[b]"]}]}
        s.put("tests/test_a.py", edit)
        got = PL.probe_freshness(row("test_a[b]"), manifest, s.task)
        check_eq("C-K5 (b): the receipt of `test_a[a]` reaches `test_a[b]` by the binding - stale",
                 (got["state"], got["why"]), ("stale", PL.WHY_PROBE_OTHER_INSTANCE))
        check_eq("C-K5 (b): ...the record is read by the receipt's own instance id, the replay is the ROW's `test_a[b]` (M-C6)",
                 got["replay"], {"test": "tests/test_a.py::test_a[b]", "instance": "test_a[b]", "mutation": "invert", "oracle": ""})
        check_eq("C-K5 (b): the sibling `test_a[a]` holds its own receipt: stale by the plain rule",
                 PL.probe_freshness(row("test_a[a]", neighbour), manifest, s.task)["why"], PL.WHY_PROBE_CHANGED)
    finally:
        s.close()


def the_own_stale_receipt_wins_over_the_neighbours():
    """C-K5 (e): the shape the 12586 fixture holds - the row's OWN stale receipt AND the neighbour's by the binding."""
    s, edit, put_receipt, row = other_spelling_world()
    try:
        neighbour = put_receipt("test_a[a]", "test_a-a", record_node="tests/test_a.py::test_a[a]")
        own = put_receipt("test_a[b]", "test_a-b", record_node="tests/test_a.py::test_a[b]")
        manifest = {"obligation_bindings": [{"obligation_id": "OB-1", "sensitivity": "proven",
                                              "probe_receipt_ref": neighbour["receipt_ref"]["path"],
                                              "instance_ids": ["test_a[a]", "test_a[b]"]}]}
        s.put("tests/test_a.py", edit)
        got = PL.probe_freshness(row("test_a[b]", own), manifest, s.task)
        check_eq("C-K5 (e): own stale receipt + the neighbour's by the binding - stale by the PLAIN rule (N1 does not take part)",
                 (got["state"], got["why"]), ("stale", PL.WHY_PROBE_CHANGED))
        check_eq("C-K5 (e): ...the replay is from the row's OWN record", got["replay"],
                 {"test": "tests/test_a.py::test_a[b]", "instance": "test_a[b]", "mutation": "invert", "oracle": ""})
    finally:
        s.close()


def ep1_37_the_file_of_a_selector_is_the_contracts():
    """EP1-37 p. 4 (B-2): the newest job that selected a row is found through the file the CONTRACT names, so a `file:line` selector
    (whose first token is no node id) is not read as a file called `a.spec.ts:12`; another file's job is still nobody's (the
    dangerous error is an identity measured on the wrong file), and a request without a contract file keeps the old reading."""
    import proof_level as PL
    entry = {"file": "tests/a.spec.ts", "instance_id": "adds one"}
    request = {"selected_instance_ids": ["adds one"], "command": {"selector_args": {"adds one": ["/tests/a\\.spec\\.ts:12"]}},
               "instance_contracts": {"adds one": {"file": "tests/a.spec.ts"}}}
    found = PL._newest_request([("job-1", request)], entry)
    check_eq("a file:line job is found through the contract's file", (found[1], found[2]) if found else None, ("adds one", "job-1"))
    other = {**request, "instance_contracts": {"adds one": {"file": "tests/b.spec.ts"}}}
    check_eq("another file's job is not this row's", PL._newest_request([("job-2", other)], entry), None)
    bare = {k: v for k, v in request.items() if k != "instance_contracts"}
    check_eq("no contract file: the token read as a node id names no file of the row", PL._newest_request([("job-3", bare)], entry), None)
    pytest_job = {"selected_instance_ids": ["test_x"], "command": {"selector_args": {"test_x": ["tests/test_a.py::test_x"]}}}
    check_eq("a pytest job keeps the old reading", bool(PL._newest_request([("job-4", pytest_job)], {"file": "tests/test_a.py", "instance_id": "test_x"})), True)


def main():
    root = the_project()
    try:
        the_shipped_vocabulary()
        the_vocabulary_is_absent_or_malformed()
        level_of_rules()
        probe_problem_matrix()
        proof_required_is_the_one_predicate()
        a_row_without_the_key_keeps_todays_rule_byte_for_byte()
        novelty_of_reads_the_stored_field()
        a_measured_unchanged_that_cannot_be_trusted_is_unknown()
        the_hash_cache_never_trusts_a_young_key()
        proof_required_with_a_novelty_key()
        a_window_item_carries_a_resolved_novelty()
        why_no_live_check_is_demanded()
        the_one_reader_of_current_bytes()
        reached_over_the_receipts_a_row_names()
        comment_only_changes_keep_the_receipt()
        binding_facts_are_the_ones_red_sandbox_read()
        binding_facts_read_the_blocks_in_the_stories_order()
        no_level_literal_in_acceptance()
        same_test_truth_table()
        rh1_9_compare_identity()
        crlf_line_endings_are_not_code()
        instance_identity_and_reached_per_instance()
        the_identity_cache_reads_the_job_directory_once()
        the_receipt_of_another_spelling_of_the_same_test()
        the_replay_keeps_the_class_and_reads_the_record_by_the_receipts_names()
        the_receipt_of_a_neighbour_through_the_obligation_binding()
        the_own_stale_receipt_wins_over_the_neighbours()
    finally:
        cleanup(root)
    ep1_37_the_file_of_a_selector_is_the_contracts()
    finish("test_proof_level")


if __name__ == "__main__":
    main()
