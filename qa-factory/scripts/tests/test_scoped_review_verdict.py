"""Gate A reads the case critic's verdict PER PLAN ROW, from its own receipt (FB-19, CX1-12).

The rule under test: a row's verdict is the word of the ACCEPTED critic that covered it, read from the `verdict`
column of the roll-call (with no such column, the round's own `Verdict:` word) in the bytes that critic's receipt
measured (a line-start suffix of today's `critic-findings.md`, rounds being prepended, up to where the next-older
receipt begins), for the row's cases only. Every doubt is `partial`, never `accepted`, and says its basis.
Expectations come from the receipt and the cases of the row, not from the code's output (FR-58)."""
import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
from controller import Controller  # noqa: E402
import critic_rollcall as R  # noqa: E402
import gate_brief as GB  # noqa: E402

ROWS = [{"id": f"TS-{i}", "design_review_required": True} for i in (1, 2, 3)]
MAPPING = {f"TS-{i}": {f"TC-{i}"} for i in (1, 2, 3)}
ALL = ["TC-1", "TC-2", "TC-3"]


def round_text(number: int, declared: str, rows: list, column: bool = True) -> str:
    """One round the way the controller-era critics write it: a HEADING first, `Verdict:` a few lines below it."""
    text = (f"# Critic findings - area - round {number} - dispatch d{number}\n\nVerdict: {declared}\n\n"
            "## Roll-call\n\n")
    text += ("| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n" if column
             else "| plan row | case | reviewed | note |\n|---|---|---|---|\n")
    for case, reviewed, word in rows:
        plan_row = "TS-" + case.split("-")[-1].split(",")[0].strip()
        text += (f"| {plan_row} | {case} | {reviewed} | {word} | seen - approved |\n" if column
                 else f"| {plan_row} | {case} | {reviewed} | approved in prose |\n")
    return text + "\n"


def put(root: Path, area: str, text: str) -> dict:
    path = root / "work" / "test-cases" / area / "critic-findings.md" if area else \
        root / "work" / "test-cases" / "critic-findings.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def prepend(root: Path, area: str, text: str) -> dict:
    """A new round on TOP of the area's file; the earlier bytes stay as they were."""
    path = root / "work" / "test-cases" / area / "critic-findings.md"
    return put(root, area, text + path.read_text(encoding="utf-8"))


def critic(ident: str, scope: list, *refs) -> dict:
    return {"id": ident, "stage": "S4", "role": "qa-case-critic", "status": "accepted",
            "scope": scope, "input_hash": "input", "evidence_refs": list(refs)}


def author() -> dict:
    return {"id": "author", "stage": "S4", "role": "qa-case-designer", "status": "accepted",
            "scope": ALL, "input_hash": "input"}


def verdicts(c: Controller, dispatches: dict, mapping=None, rows=None, cases=None) -> dict:
    state = {"source_revision": "src", "plan_revision": "plan", "dispatches": dispatches}
    cases = cases or ALL
    links = [{"case_id": case, "version": "cv_" + case} for case in cases]
    with patch.object(c, "_row_cases", return_value=mapping or MAPPING), \
            patch.object(c, "_rollcall_reviewed", return_value=set(cases)), \
            patch("contract.story_case_links", return_value=links):
        return {r["plan_row"]: r["verdict"] for r in c._build_design_reviews(state, rows or ROWS)}


# --- the reader: one receipt, the cases of one row ---------------------------------------------------

def reader_reads_the_verdict_column() -> None:
    def read(text, cases, sha=None, area="", data=None):
        raw = text.encode("utf-8") if data is None else data
        return R.scoped_verdict(raw, sha or hashlib.sha256(text.encode("utf-8")).hexdigest(), cases, area=area)

    mixed = round_text(1, "reject", [("TC-1", "yes", "approve"), ("TC-2", "yes", "reject")])
    check_eq("a rejecting round keeps its approved case accepted", read(mixed, {"TC-1"}), ("accepted", {"TC-1"}))
    check_eq("and rejects the one it rejected", read(mixed, {"TC-2"}), ("reject", {"TC-2"}))
    check_eq("both together: the refusal holds", read(mixed, {"TC-1", "TC-2"}), ("reject", {"TC-1", "TC-2"}))
    check_eq("a case the roll-call does not name is not listed (the caller's gap)",
             read(mixed, {"TC-1", "TC-3"}), ("accepted", {"TC-1"}))
    check_eq("none of the cases named: no word", read(mixed, {"TC-3"}), ("", set()))
    check_eq("no cases at all: partial", read(mixed, set()), ("partial", set()))
    check_eq("a case that is not a string is read as its text, not raised on", read(mixed, [1, None])[0], "")

    # E1/E2/E7: the declared word of the round beside the cells.
    only_approvals = round_text(1, "reject", [("TC-1", "yes", "approve")])
    # HF4-11: `reject` is a failing case. A round that says `reject` over cells that hold no `reject` contradicts its own table:
    # code does not rewrite the critic's word (FR-35) and does not approve it either - it is `partial`, with the rule's door
    # (the keys of the seam are in test_carried_concerns.py).
    why_e1 = []
    check_eq("E1: an overall rejection with nothing but approvals in the cells is never read as approval (HF4-11: partial, "
             "the critic is told to rewrite the line)",
             R.scoped_verdict(only_approvals.encode("utf-8"), hashlib.sha256(only_approvals.encode("utf-8")).hexdigest(),
                              {"TC-1"}, why=why_e1), ("partial", {"TC-1"}))
    check_eq("E1: ... the basis is the rule's", [basis for basis, _ in why_e1], ["round_word_rule"])
    check_eq("E2: an approving round with a rejecting cell rejects that case",
             read(round_text(1, "approve", [("TC-1", "yes", "reject")]), {"TC-1"}), ("reject", {"TC-1"}))
    check_eq("E7: an unknown declared word is kept as it is (FR-35)",
             read(round_text(1, "rejected", [("TC-1", "yes", "approve")]), {"TC-1"}), ("rejected", {"TC-1"}))
    check_eq("a round with no Verdict line approves nothing",
             read("## Roll-call\n\n| plan row | case | reviewed | verdict |\n|---|---|---|---|\n"
                  "| TS-1 | TC-1 | yes | approve |\n", {"TC-1"}), ("partial", {"TC-1"}))

    # M-3: the edges of the column.
    check_eq("each approving word of the list is accepted",
             {read(round_text(1, "approve", [("TC-1", "yes", w)]), {"TC-1"})[0]
              for w in ("approve", "approve_with_fixes", "approve_with_concerns")}, {"accepted"})
    check_eq("a value outside the list is partial", read(round_text(1, "approve", [("TC-1", "yes", "ok")]), {"TC-1"}),
             ("partial", {"TC-1"}))
    check_eq("an empty value is partial", read(round_text(1, "approve", [("TC-1", "yes", "")]), {"TC-1"}),
             ("partial", {"TC-1"}))
    check_eq("reviewed: no is partial whatever the word", read(round_text(1, "approve", [("TC-1", "no", "approve")]),
                                                              {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("a case on two rows that disagree takes the stricter",
             read(round_text(1, "reject", [("TC-1", "yes", "approve"), ("TC-1", "yes", "reject")]), {"TC-1"}),
             ("reject", {"TC-1"}))
    check_eq("an approving row beside a partial one is partial",
             read(round_text(1, "partial", [("TC-1", "yes", "approve"), ("TC-1", "yes", "partial")]), {"TC-1"}),
             ("partial", {"TC-1"}))
    # L-4 (A): a table with NO `verdict` column gives every row the round's OWN declared word, as main reads it.
    for declared, want in (("approve", "accepted"), ("approve_with_concerns", "accepted"), ("approve_with_fixes", "accepted"),
                           ("reject", "reject"), ("partial", "partial")):
        check_eq(f"A: no `verdict` column, the round says {declared}: the row takes it ({want})",
                 read(round_text(1, declared, [("TC-1", "yes", "x"), ("TC-2", "yes", "x")], column=False),
                      {"TC-1", "TC-2"}), (want, {"TC-1", "TC-2"}))
    check_eq("A: no column and no Verdict line: partial",
             read("## Roll-call\n\n| plan row | case | reviewed | note |\n|---|---|---|---|\n| TS-1 | TC-1 | yes | ok |\n",
                  {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("A: no column and an unknown declared word: the word is kept as the critic wrote it",
             read(round_text(1, "rejected", [("TC-1", "yes", "x")], column=False), {"TC-1"}), ("rejected", {"TC-1"}))
    check_eq("A: no column, the round approves, the row says reviewed: no - partial (a row read as nobody's)",
             read(round_text(1, "approve", [("TC-1", "no", "x")], column=False), {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("A: the prose of `note` is never read for a word",
             read(round_text(1, "reject", [("TC-1", "yes", "x")], column=False).replace("approved in prose", "approve"),
                  {"TC-1"}), ("reject", {"TC-1"}))
    mixed_column = round_text(1, "reject", [("TC-1", "yes", "approve"), ("TC-2", "yes", "reject")])
    check_eq("A: the column, when there is one, wins per row over the round's word",
             read(mixed_column, {"TC-1"}), ("accepted", {"TC-1"}))
    check_eq("no roll-call table at all: partial", read("Verdict: approve\n", {"TC-1"}), ("partial", {"TC-1"}))

    # M-2: ALL the case ids of a cell, through the one matcher.
    several = round_text(1, "approve", [("TC-1, TC-2", "yes", "approve")])
    check_eq("a cell naming two cases lists both", read(several, {"TC-1", "TC-2"}), ("accepted", {"TC-1", "TC-2"}))
    check_eq("an area key matches the bare id of a roll-call in that area", read(several, {"a/TC-2"}, area="a"),
             ("accepted", {"a/TC-2"}))
    check_eq("and not the same number of another area", read(several, {"b/TC-2"}, area="a"), ("", set()))
    check_eq("a bare key matches the roll-call of any area", read(several, {"TC-2"}, area="a"), ("accepted", {"TC-2"}))


def reader_takes_only_the_bytes_the_receipt_measured() -> None:
    old = round_text(1, "reject", [("TC-1", "yes", "reject"), ("TC-2", "yes", "reject")])
    new = round_text(2, "approve", [("TC-2", "yes", "approve")])
    old_sha = hashlib.sha256(old.encode("utf-8")).hexdigest()
    both = (new + old).encode("utf-8")
    check_eq("B-1: the receipt of a round under a heading is the end of the file after a new round went on top",
             R.scoped_verdict(both, old_sha, {"TC-1"}), ("reject", {"TC-1"}))
    check_eq("the new round's own receipt is the whole file",
             R.scoped_verdict(both, hashlib.sha256(both).hexdigest(), {"TC-2"}), ("accepted", {"TC-2"}))
    check_eq("the old round's TC-2 is read from the old round, not the new one",
             R.scoped_verdict(both, old_sha, {"TC-2"}), ("reject", {"TC-2"}))
    check_eq("the sha is case-insensitive hex", R.scoped_verdict(both, old_sha.upper(), {"TC-1"}),
             ("reject", {"TC-1"}))
    edited = (new + old.replace("| reject | seen", "| approve | seen", 1)).encode("utf-8")
    check_eq("E5: bytes of the old round edited after its receipt are approved by nothing",
             R.scoped_verdict(edited, old_sha, {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("an edit can not be repaired by a receipt that matches no end of the file",
             R.scoped_verdict(both, "0" * 64, {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("an empty hash measures nothing", R.scoped_verdict(both, "", {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("an absent hash measures nothing", R.scoped_verdict(both, None, {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("an empty file measures nothing", R.scoped_verdict(b"", old_sha, {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("a receipt hashed from the middle of a line is not a line-start end",
             R.scoped_verdict(both, hashlib.sha256(both[5:]).hexdigest(), {"TC-1"}), ("partial", {"TC-1"}))
    with patch.object(R, "parse_rollcall", side_effect=ValueError("broken table")):
        check_eq("K3: an exception while reading is partial, never raised and never accepted",
                 R.scoped_verdict(both, old_sha, {"TC-1"}), ("partial", {"TC-1"}))
    check_eq("not a bytes object: partial too", R.scoped_verdict("text", old_sha, {"TC-1"}), ("partial", {"TC-1"}))


def reader_reads_only_the_round_of_the_receipt() -> None:
    """B-2: the declared word and the roll-call come from the verified round's slice, never from the round below."""
    def whole(text: bytes, cases=("TC-1",)):
        return R.scoped_verdict(text, hashlib.sha256(text).hexdigest(), set(cases))

    older = round_text(1, "approve", [("TC-1", "yes", "approve")])
    doubt = ("# Critic findings - area - round 2 - dispatch d2\n\nVerdict: partial\n\nNothing was reviewed this round.\n\n")
    check_eq("B-2: a covering round that says partial and has no roll-call is partial, whatever round 1 below approved",
             whole((doubt + older).encode("utf-8")), ("partial", {"TC-1"}))
    older_mixed = round_text(1, "approve", [("TC-1", "yes", "approve"), ("TC-2", "yes", "reject")])
    check_eq("B-2: the same, when round 1 below also holds a rejected case (the shape that leaked an approval)",
             whole((doubt + older_mixed).encode("utf-8")), ("partial", {"TC-1"}))
    check_eq("B-2: and the same with a roll-call that has no `verdict` column below",
             whole((doubt + round_text(1, "approve", [("TC-1", "yes", "x")], column=False)).encode("utf-8")),
             ("partial", {"TC-1"}))
    check_eq("B-2: a covering round with no Verdict line is partial although its roll-call approves and round 1 below "
             "says approve",
             whole(("# Critic findings - area - round 2 - dispatch d2\n\n## Roll-call\n\n"
                    "| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
                    "| TS-1 | TC-1 | yes | approve | ok |\n\n" + older).encode("utf-8")), ("partial", {"TC-1"}))
    rejecting_below = round_text(1, "reject", [("TC-1", "yes", "reject")])
    check_eq("an approving round over a rejecting one: the covering round's word stands for its own cases",
             whole((round_text(2, "approve", [("TC-1", "yes", "approve")]) + rejecting_below).encode("utf-8")),
             ("accepted", {"TC-1"}))
    check_eq("a case only the older round names is not listed by the covering round",
             whole((round_text(2, "approve", [("TC-2", "yes", "approve")]) + rejecting_below).encode("utf-8"),
                   ("TC-1", "TC-2")), ("accepted", {"TC-2"}))
    no_verdict_below = ("# Critic findings - area - round 1 - dispatch d1\n\n## Roll-call\n\n"
                        "| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
                        "| TS-1 | TC-1 | yes | approve | ok |\n\n")
    stacked = (round_text(2, "approve", [("TC-2", "yes", "approve")]) + no_verdict_below).encode("utf-8")
    check_eq("a later round's Verdict line is never read for the earlier round (round 1 has none)",
             R.scoped_verdict(stacked, hashlib.sha256(no_verdict_below.encode("utf-8")).hexdigest(), {"TC-1"}),
             ("partial", {"TC-1"}))

    # The slice itself: ends at the next level-1 heading, or the end; a fence hides a `# ` line.
    slice_of = R._round_slice
    check_eq("the slice ends where the next round's header begins",
             slice_of("# A round 2\nVerdict: approve\n## Roll-call\n# A round 1\nVerdict: reject\n"),
             "# A round 2\nVerdict: approve\n## Roll-call\n")
    check_eq("a text of one round is whole", slice_of("# A round 1\nVerdict: reject\n"), "# A round 1\nVerdict: reject\n")
    check_eq("a text with no header at all is whole", slice_of("Verdict: reject\n"), "Verdict: reject\n")
    check_eq("something before the first header: that header belongs to the older round",
             slice_of("Verdict: approve\n\n# A round 1\nVerdict: reject\n"), "Verdict: approve\n\n")
    check_eq("blank lines before the own header do not make it an older round's",
             slice_of("\n\n# A round 2\nVerdict: approve\n# A round 1\n"), "\n\n# A round 2\nVerdict: approve\n")
    check_eq("a level-2 heading is not a round header", slice_of("# A\n## B\nx\n"), "# A\n## B\nx\n")
    check_eq("a `# ` line inside a code fence is not a round header",
             slice_of("# A\n```\n# comment\n```\nVerdict: approve\n# A1\n"), "# A\n```\n# comment\n```\nVerdict: approve\n")
    check_eq("an empty text", slice_of(""), "")
    check_eq("a `~~~` line inside a ``` fence does not close it: the `# ` line under it is still fenced",
             slice_of("# A\n```\n~~~\n# not a header\n```\nVerdict: approve\n# A1\n"),
             "# A\n```\n~~~\n# not a header\n```\nVerdict: approve\n")
    check_eq("a fence that never closes hides nothing: the older round's header still ends the round",
             slice_of("# A round 2\n```\nunclosed\n# A round 1\nVerdict: approve\n"), "# A round 2\n```\nunclosed\n")


OLDER = ("Verdict: approve\n\n## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
         "| TS-1 | TC-1 | yes | approve | ok |\n\n")   # round 1 written with NO `# ` header (R-1's probe A layout)


def sha(text) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


def a_round_ends_where_the_older_receipt_begins() -> None:
    """R-1: the receipts are where rounds really end; a header is not required for the cut, and a slice that still
    holds two roll-calls cannot tell where its round ends."""
    def read(text, receipts=(), cases=("TC-1",)):
        why = []
        got = R.scoped_verdict(text.encode("utf-8"), sha(text), set(cases), why=why, receipts=receipts)
        return got, [basis for basis, _ in why[:1]]

    note_only = "Round 2: only TC-2 was looked at, notes follow.\n\n"   # no header, no Verdict line, no roll-call
    check_eq("the receipt-suffix cut: a header-less newest round ends where round 1's receipt begins, so round 1's "
             "approval never speaks for it", read(note_only + OLDER, receipts=[sha(OLDER)]),
             (("partial", {"TC-1"}), ["unreadable"]))
    check_eq("no older receipt and no header: the whole file is one round (the measured limit the card's `# ` header "
             "rule and the older round's receipt close)", read(note_only + OLDER)[0], ("accepted", {"TC-1"}))
    check_eq("a file of one header-less round and no other receipt is read whole, as before",
             read(OLDER)[0], ("accepted", {"TC-1"}))
    fenced = "# Critic findings - round 2\n\n```\nan example the critic never closed\n\n"
    check_eq("an unclosed fence in the newest round never carries round 1 into it: the receipt cut holds without a "
             "header", read(fenced + OLDER, receipts=[sha(OLDER)])[0], ("partial", {"TC-1"}))
    check_eq("and with round 1's header but no receipt, the unclosed fence hides nothing either",
             read(fenced + "# Critic findings - round 1\n\n" + OLDER)[0], ("partial", {"TC-1"}))
    probe_a = ("## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
               "| TS-1 | TC-1 | yes | approve | ok |\n\n")   # round 2: an approving table and no Verdict line
    why = []
    check_eq("two roll-calls in one round (no header, no older receipt): partial, never round 1's approve",
             R.scoped_verdict((probe_a + OLDER).encode("utf-8"), sha(probe_a + OLDER), {"TC-1"}, why=why),
             ("partial", {"TC-1"}))
    check_eq("and the reason says so", why, [("two_rollcalls", "two roll-calls in one round: where this round ends "
                                                                "cannot be told")])
    check_eq("the same file with round 1's receipt known: the newest round is read alone (no Verdict line: partial)",
             read(probe_a + OLDER, receipts=[sha(OLDER)]), (("partial", {"TC-1"}), ["unreadable"]))
    # The conflict pair: a receipt that measured the bytes of TWO rounds (round 2 between has no accepted receipt).
    middle = round_text(2, "reject", [("TC-1", "yes", "reject")])
    top = round_text(3, "approve", [("TC-2", "yes", "approve")])
    check_eq("a receipt over two rounds: with headers the header ends the newest round first (TC-1 is not its case)",
             read(top + middle + OLDER, receipts=[sha(OLDER)])[0], ("", set()))
    bare = lambda text: text.split("\n", 1)[1]   # the same rounds without their `# ` header line
    check_eq("without headers the receipt wins: the slice runs to round 1's receipt, holds two roll-calls, partial",
             read(bare(top) + bare(middle) + OLDER, receipts=[sha(OLDER)]), (("partial", {"TC-1"}), ["two_rollcalls"]))
    check_eq("a receipt newer than this one is no end of this round",
             R.scoped_verdict((note_only + OLDER).encode("utf-8"), sha(OLDER), {"TC-1"}, receipts=[sha(note_only + OLDER)]),
             ("accepted", {"TC-1"}))
    edited = (note_only + OLDER.replace("| approve | ok", "| reject | ok")).encode("utf-8")
    why = []
    check_eq("a receipt whose suffix is not found: partial, naming the receipt",
             R.scoped_verdict(edited, sha(note_only + OLDER), {"TC-1"}, why=why), ("partial", {"TC-1"}))
    check("receipt_mismatch, the receipt's hash named", why and why[0][0] == "receipt_mismatch"
          and f"(sha256 {sha(note_only + OLDER)[:12]})" in why[0][1], why)


def each_basis_says_where_the_word_came_from() -> None:
    """R-2: `verdict_basis` on every row that is not accepted - the field code branches on (the refusal, the driver)."""
    root = temp_dir("qa-scoped-review-basis-")
    try:
        c = Controller(root)

        def basis(text=None, ref=None, mapping=None) -> dict:
            ref = ref or put(root, "area", text)
            state = {"source_revision": "src", "plan_revision": "plan",
                     "dispatches": {"author": author(), "critic1": critic("critic1", ALL, ref)}}
            links = [{"case_id": case, "version": "cv_" + case} for case in ALL]
            with patch.object(c, "_row_cases", return_value=mapping or MAPPING), \
                    patch.object(c, "_rollcall_reviewed", return_value=set(ALL)), \
                    patch("contract.story_case_links", return_value=links):
                return {r["plan_row"]: (r["verdict"], r.get("verdict_basis")) for r in c._build_design_reviews(state, ROWS)}

        check_eq("column / no_review / unreadable: the cell word, an unreviewed row, a word outside the list",
                 basis(round_text(1, "approve", [("TC-1", "yes", "reject"), ("TC-2", "no", "approve"),
                                                 ("TC-3", "yes", "ok")])),
                 {"TS-1": ("reject", "column"), "TS-2": ("partial", "no_review"), "TS-3": ("partial", "unreadable")})
        check_eq("round_word: no column, the round's own word",
                 basis(round_text(1, "reject", [(case, "yes", "x") for case in ALL], column=False)),
                 {f"TS-{n}": ("reject", "round_word") for n in (1, 2, 3)})
        check_eq("no_review: a case the roll-call does not name; an accepted row carries no basis",
                 basis(round_text(1, "approve", [("TC-1", "yes", "approve"), ("TC-2", "yes", "approve")])),
                 {"TS-1": ("accepted", None), "TS-2": ("accepted", None), "TS-3": ("partial", "no_review")})
        good = put(root, "area", round_text(1, "approve", [(case, "yes", "approve") for case in ALL]))
        check_eq("receipt_mismatch: bytes the receipt did not measure",
                 set(basis(ref={"path": good["path"], "sha256": "0" * 64}).values()), {("partial", "receipt_mismatch")})
        check_eq("unreadable: a ref to a file that is not there",
                 set(basis(ref={"path": "work/test-cases/gone/critic-findings.md", "sha256": "0" * 64}).values()),
                 {("partial", "unreadable")})
        probe_a = ("## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
                   + "".join(f"| TS-{n} | TC-{n} | yes | approve | ok |\n" for n in (1, 2, 3)) + "\n")
        check_eq("two_rollcalls: a slice holding two roll-calls",
                 set(basis(probe_a + OLDER).values()), {("partial", "two_rollcalls")})
    finally:
        cleanup(root)


def the_row_names_the_round_that_produced_its_word() -> None:
    """R-2 (i)-(iii), m-2: the M-5 word names the LATER dispatch; a later round gate A cannot read is a doubt, not a
    skip; a `reject` beside an unnamed case stays `reject`; reasons past the third are counted."""
    root = temp_dir("qa-scoped-review-origin-")
    try:
        c = Controller(root)

        def build(dispatches, mapping=None) -> dict:
            state = {"source_revision": "src", "plan_revision": "plan", "dispatches": dispatches}
            links = [{"case_id": case, "version": "cv_" + case} for case in ALL]
            with patch.object(c, "_row_cases", return_value=mapping or MAPPING), \
                    patch.object(c, "_rollcall_reviewed", return_value=set(ALL)), \
                    patch("contract.story_case_links", return_value=links):
                return {r["plan_row"]: r for r in c._build_design_reviews(state, ROWS)}

        first = put(root, "area", round_text(1, "approve", [(case, "yes", "approve") for case in ALL]))
        second = prepend(root, "area", round_text(2, "reject", [("TC-2", "yes", "approve"), ("TC-1", "yes", "reject")]))
        got = build({"author": author(), "critic1": critic("critic1", ALL, first),
                     "critic2": critic("critic2", ["TC-2"], second)})
        check("R-2 (i): the M-5 refusal names the later dispatch whose round rejects the case",
              got["TS-1"]["verdict"] == "reject" and got["TS-1"]["verdict_basis"] == "column"
              and got["TS-1"]["verdict_source"].startswith("round of dispatch critic2: a later accepted critic round "
                                                           "refuses it: the roll-call's verdict for TC-1 is 'reject'"),
              got["TS-1"])
        stale = {"path": second["path"], "sha256": "0" * 64}
        got = build({"author": author(), "critic1": critic("critic1", ALL, first), "critic2": critic("critic2", ["TC-2"], stale)})
        check("m-2: a later accepted round whose bytes were edited may be rejecting the row: partial, not skipped",
              got["TS-1"]["verdict"] == "partial" and got["TS-1"]["verdict_basis"] == "receipt_mismatch"
              and "round of dispatch critic2" in got["TS-1"]["verdict_source"], got["TS-1"])
        mixed = put(root, "other", round_text(1, "reject", [("TC-1", "yes", "reject")]))
        got = build({"author": author(), "critic1": critic("critic1", ALL, mixed)},
                    mapping={"TS-1": {"TC-1", "TC-2"}, "TS-2": {"TC-2"}, "TS-3": {"TC-3"}})
        check("R-2 (iii): a reject beside an unnamed case stays reject, and both reasons are given",
              got["TS-1"]["verdict"] == "reject" and "verdict for TC-1 is 'reject'" in got["TS-1"]["verdict_source"]
              and "does not name TC-2" in got["TS-1"]["verdict_source"], got["TS-1"])
        many = put(root, "many", round_text(1, "approve", [(f"TC-{n}", "no", "approve") for n in range(1, 6)]))
        got = build({"author": author(), "critic1": critic("critic1", [f"TC-{n}" for n in range(1, 6)], many)},
                    mapping={"TS-1": {f"TC-{n}" for n in range(1, 6)}, "TS-2": set(), "TS-3": set()})
        check("R-2 (ii): reasons past the third are counted, not dropped",
              got["TS-1"]["verdict_source"].endswith("(and 2 more)"), got["TS-1"])
    finally:
        cleanup(root)


def the_controller_passes_the_receipts_of_the_same_file() -> None:
    """R-1 at the gate: the older accepted receipt of the SAME file ends the newer round, header or not."""
    root = temp_dir("qa-scoped-review-receipts-")
    try:
        c = Controller(root)
        first = put(root, "area", OLDER.replace("| TS-1 | TC-1 | yes | approve | ok |",
                                                "| TS-1 | TC-1 | yes | approve | ok |\n| TS-2 | TC-2 | yes | approve | ok |"))
        second = prepend(root, "area", "Round 2: TC-2 was looked at again; the table is still to come.\n\n")
        dispatches = {"author": author(), "critic1": critic("critic1", ALL, first),
                      "critic2": critic("critic2", ["TC-2"], second)}
        got = verdicts(c, dispatches, mapping={"TS-1": {"TC-1"}, "TS-2": {"TC-2"}, "TS-3": {"TC-1"}})
        check_eq("round 2 has no header, no Verdict line and no table: TS-2 (its scope) is partial, never round 1's "
                 "approve; TS-1 reads round 1", got, {"TS-1": "accepted", "TS-2": "partial", "TS-3": "accepted"})
    finally:
        cleanup(root)


def the_roll_call_parser_carries_every_id_and_the_verdict_column() -> None:
    table = ("## Roll-call\n\n| plan row | case | reviewed | verdict | note |\n|---|---|---|---|---|\n"
             "| TS-1 | TC-1, TC-2 | yes | `Approve` | see TC-9 |\n| TS-2 | TC-3 | no | reject | - |\n"
             "| TS-3 | TC-4 | yes | | |\n")
    rows = R.parse_rollcall(table)
    check_eq("B: every id of the case cell, not the first only", [r["ids"] for r in rows],
             [["TC-1", "TC-2"], ["TC-3"], ["TC-4"]])
    check_eq("B: the verdict column, lower case, backticks off, an empty cell as ''", [r["verdict"] for r in rows],
             ["approve", "reject", ""])
    check_eq("the keys the older readers use keep their values",
             [(r["plan_row"], r["case"], r["reviewed"], r["cell"]) for r in rows],
             [("TS-1", "TC-1", True, "yes"), ("TS-2", "TC-3", False, "no"), ("TS-3", "TC-4", True, "yes")])
    plain = R.parse_rollcall("## Roll-call\n\n| plan row | case | reviewed | note |\n|---|---|---|---|\n"
                             "| TS-1 | TC-1 | yes | and TC-7 |\n")
    check_eq("no `verdict` column: None, which is not an empty word", [r["verdict"] for r in plain], [None])
    check_eq("the older `case` is still the first id of the whole row (the prose included)",
             [(r["case"], r["ids"]) for r in R.parse_rollcall(
                 "## Roll-call\n\n| plan row | case | reviewed |\n|---|---|---|\n| TS-1 | TC-1 | yes |\n")],
             [("TC-1", ["TC-1"])])
    nocase = R.parse_rollcall("## Roll-call\n\n| plan row | what | reviewed |\n|---|---|---|\n| TS-1 | TC-5 | yes |\n")
    check_eq("no `case` column: the row names no case for the per-case reader, `case` unchanged",
             [(r["case"], r["ids"]) for r in nocase], [("TC-5", [])])
    raw = ("# R round 1\nVerdict: approve\n\n## Roll-call\n\n| plan row | what | reviewed |\n|---|---|---|\n"
           "| TS-1 | TC-5 | yes |\n").encode("utf-8")
    check_eq("and the per-case reader then lists nothing of it",
             R.scoped_verdict(raw, hashlib.sha256(raw).hexdigest(), {"TC-5"}), ("", set()))


# --- the controller: one verdict per plan row ----------------------------------------------------------

def a_scoped_repair_clears_only_its_case() -> None:
    root = temp_dir("qa-scoped-review-")
    try:
        c = Controller(root)
        first = put(root, "area", round_text(1, "reject", [("TC-1", "yes", "reject"), ("TC-2", "yes", "reject"),
                                                           ("TC-3", "yes", "approve")]))
        second = prepend(root, "area", round_text(2, "approve", [("TC-2", "yes", "approve")]))
        dispatches = {"author": author(), "critic1": critic("critic1", ALL, first),
                      "critic2": critic("critic2", ["TC-2"], second)}
        check_eq("main's reader (the newest round's word, on every row) is the false accept this node ends",
                 c._declared_review_verdict(root), "accepted")
        check_eq("scoped repair clears only its case: TC-1 stays rejected, TC-2 is re-approved, TC-3 was approved",
                 verdicts(c, dispatches), {"TS-1": "reject", "TS-2": "accepted", "TS-3": "accepted"})

        prepend(root, "area", round_text(3, "approve", [("TC-1", "yes", "approve")]))
        check_eq("a newer round nobody accepted approves nothing (E4)", verdicts(c, dispatches)["TS-1"], "reject")

        text = (root / second["path"]).read_text(encoding="utf-8")
        (root / second["path"]).write_text(text.replace("| reject | seen", "| approve | seen", 1), encoding="utf-8")
        got = verdicts(c, dispatches)
        check("E5: round 1 edited after its receipt: the rows it covered are not approved",
              got["TS-1"] != "accepted" and got["TS-3"] != "accepted", got)
    finally:
        cleanup(root)


def the_older_layout_of_one_folder_per_round_is_read_the_same() -> None:
    root = temp_dir("qa-scoped-review-folders-")
    try:
        c = Controller(root)
        first = put(root, "round1", round_text(1, "reject", [("TC-1", "yes", "approve"), ("TC-2", "yes", "reject"),
                                                             ("TC-3", "yes", "reject")]))
        second = put(root, "round2", round_text(2, "approve", [("TC-2", "yes", "approve")]))
        dispatches = {"author": author(), "critic1": critic("critic1", ALL, first),
                      "critic2": critic("critic2", ["TC-2"], second)}
        check_eq("two folders, two receipts: the repaired case is accepted, the other rejection stands",
                 verdicts(c, dispatches), {"TS-1": "accepted", "TS-2": "accepted", "TS-3": "reject"})
    finally:
        cleanup(root)


def every_doubt_is_partial() -> None:
    root = temp_dir("qa-scoped-review-doubt-")
    outside = temp_dir("qa-scoped-review-outside-")
    try:
        c = Controller(root)
        ref = put(root, "area", round_text(1, "approve", [(case, "yes", "approve") for case in ALL]))
        check_eq("a sound receipt over approving cells: every row accepted",
                 verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, ref)}),
                 {"TS-1": "accepted", "TS-2": "accepted", "TS-3": "accepted"})
        no_column = put(root, "area", round_text(1, "approve", [(case, "yes", "approve") for case in ALL],
                                                 column=False))
        check_eq("M-4 (L-4 A): until the critic writes the `verdict` column every row takes the round's own word, "
                 "as main reads it - an approving round accepts",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, no_column)}).values()),
                 {"accepted"})
        no_column_reject = put(root, "area", round_text(1, "reject", [(case, "yes", "approve") for case in ALL],
                                                        column=False))
        check_eq("and a rejecting round rejects every row it lists",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, no_column_reject)}).values()),
                 {"reject"})
        unreviewed = put(root, "area", round_text(1, "partial", [("TC-1", "yes", "approve"), ("TC-2", "no", "approve"),
                                                                 ("TC-3", "yes", "approve")]))
        check_eq("a row the receipt marks unreviewed cannot be approved, the others stand",
                 verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, unreviewed)}),
                 {"TS-1": "accepted", "TS-2": "partial", "TS-3": "accepted"})
        short = put(root, "area", round_text(1, "approve", [("TC-1", "yes", "approve"), ("TC-2", "yes", "approve")]))
        check_eq("a case the roll-call does not name is partial",
                 verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, short)}),
                 {"TS-1": "accepted", "TS-2": "accepted", "TS-3": "partial"})
        approving = round_text(1, "approve", [(case, "yes", "approve") for case in ALL])
        stray = put(outside, "area", approving)
        (outside / "work" / "test-cases" / "area").rename(outside / "test-cases")
        escaping = {"path": "../" + outside.name + "/test-cases/critic-findings.md", "sha256": stray["sha256"]}
        check_eq("a ref that escapes the story is partial although its hash is right",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, escaping)}).values()),
                 {"partial"})
        absolute = {"path": str(outside / "test-cases" / "critic-findings.md"), "sha256": stray["sha256"]}
        check_eq("an absolute ref is partial",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, absolute)}).values()),
                 {"partial"})
        missing = {"path": "work/test-cases/gone/critic-findings.md", "sha256": "0" * 64}
        check_eq("a file that is not there is partial",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, missing)}).values()),
                 {"partial"})
        check_eq("a ref without a hash is partial",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, {"path": ref["path"]})}
                              ).values()), {"partial"})
        with patch.object(Controller, "_read_findings_ref", side_effect=OSError("unreadable")):
            check_eq("an unreadable ref raises nothing and is partial",
                     set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, ref)}).values()),
                     {"partial"})
    finally:
        cleanup(root)
        cleanup(outside)


def the_older_form_keeps_the_older_rule() -> None:
    root = temp_dir("qa-scoped-review-old-")
    try:
        c = Controller(root)
        put(root, "area", round_text(1, "reject", [("TC-1", "yes", "reject")]))
        notes = {"path": "S4-critic.txt", "sha256": "0" * 64}
        check_eq("I4: a receipt without a findings ref keeps the last refusing word of the findings on disk",
                 set(verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, notes)}).values()), {"reject"})
        check_eq("no critic covers the rows: the older rule too",
                 set(verdicts(c, {"author": author()}).values()), {"reject"})
        stray = {"path": "work/test-code/critic-findings.md", "sha256": "0" * 64}
        check_eq("a findings file outside test-cases/ is not a case critic's receipt (the scan's own name rule)",
                 Controller._findings_refs({"evidence_refs": [stray]}), [])
        (root / "work" / "test-cases" / "area" / "critic-findings.md").unlink()
        put(root, "elsewhere", round_text(1, "partial", [("TC-9", "no", "partial")]))
        ref = put(root, "area", round_text(1, "approve", [("TC-1", "yes", "approve")]))
        mapping = dict(MAPPING, **{"TS-9": set()})
        rows = ROWS[:1] + [{"id": "TS-9", "design_review_required": True}]
        check_eq("a row with no cases keeps the older rule (the last refusing word on disk), the other row its own",
                 verdicts(c, {"author": author(), "critic1": critic("critic1", ALL, ref)}, mapping=mapping, rows=rows),
                 {"TS-1": "accepted", "TS-9": "partial"})
    finally:
        cleanup(root)


def a_later_round_that_rejects_a_case_out_of_its_scope_holds() -> None:
    root = temp_dir("qa-scoped-review-later-")
    try:
        c = Controller(root)
        first = put(root, "area", round_text(1, "approve", [(case, "yes", "approve") for case in ALL]))
        second = prepend(root, "area", round_text(2, "reject", [("TC-2", "yes", "approve"), ("TC-1", "yes", "reject"),
                                                                ("TC-3", "no", "approve")]))
        dispatches = {"author": author(), "critic1": critic("critic1", ALL, first),
                      "critic2": critic("critic2", ["TC-2"], second)}
        check_eq("M-5: a later accepted round that rejects TC-1 outside its scope refuses that row; "
                 "its unreviewed row (TC-3) and its approval (TC-2) change nothing",
                 verdicts(c, dispatches), {"TS-1": "reject", "TS-2": "accepted", "TS-3": "accepted"})
        dispatches["critic2"]["status"] = "running"
        check_eq("a round that is not accepted holds nothing", set(verdicts(c, dispatches).values()), {"accepted"})
    finally:
        cleanup(root)


def rows_share_cases_and_areas_do_not_blur() -> None:
    root = temp_dir("qa-scoped-review-share-")
    try:
        c = Controller(root)
        ref = put(root, "area", round_text(1, "reject", [("TC-1, TC-2", "yes", "approve"), ("TC-3", "yes", "reject")]))
        dispatches = {"author": author(), "critic1": critic("critic1", ALL, ref)}
        check_eq("a plan row with two cases reads both ids of the roll-call row",
                 verdicts(c, dispatches, mapping={"TS-1": {"TC-1", "TC-2"}, "TS-2": {"TC-2"}, "TS-3": {"TC-3"}}),
                 {"TS-1": "accepted", "TS-2": "accepted", "TS-3": "reject"})
        check_eq("E9: the same case on two plan rows: both get its outcome",
                 verdicts(c, dispatches, mapping={"TS-1": {"TC-3"}, "TS-2": {"TC-3"}, "TS-3": {"TC-3", "TC-1"}}),
                 {"TS-1": "reject", "TS-2": "reject", "TS-3": "reject"})

        # Two areas hold TC-1: the controller's keys are `<area>/TC-1`, the roll-call writes bare ids.
        a = put(root, "a", round_text(1, "approve", [("TC-1", "yes", "approve")]))
        keys = ["a/TC-1", "b/TC-1"]
        two = {"TS-1": {"a/TC-1"}, "TS-2": {"b/TC-1"}}
        both = {"author": dict(author(), scope=keys), "critic1": critic("critic1", keys, a)}
        check_eq("a roll-call of area a approves a/TC-1 and says nothing about b/TC-1",
                 verdicts(c, both, mapping=two, rows=ROWS[:2], cases=keys), {"TS-1": "accepted", "TS-2": "partial"})
        b = put(root, "b", round_text(1, "reject", [("TC-1", "yes", "reject")]))
        both["critic1"]["evidence_refs"] = [a, b]
        check_eq("E6: two refs, each read for its own area's cases",
                 verdicts(c, both, mapping=two, rows=ROWS[:2], cases=keys), {"TS-1": "accepted", "TS-2": "reject"})
    finally:
        cleanup(root)


def the_gate_refuses_a_rejected_row_and_names_the_word() -> None:
    root = temp_dir("qa-scoped-review-gate-")
    try:
        c = Controller(root)
        ref = put(root, "area", round_text(1, "reject", [("TC-1", "yes", "reject"), ("TC-2", "yes", "approve"),
                                                         ("TC-3", "yes", "approve")]))
        dispatches = {"author": author(), "critic1": critic("critic1", ALL, ref)}
        state = {"source_revision": "src", "plan_revision": "plan", "dispatches": dispatches}
        links = [{"case_id": case, "version": "cv_" + case} for case in ALL]
        with patch.object(c, "_row_cases", return_value=MAPPING), \
                patch.object(c, "_rollcall_reviewed", return_value=set(ALL)), \
                patch("contract.story_case_links", return_value=links):
            reviews = c._build_design_reviews(state, ROWS)
            problems = c._design_review_problems({"design_reviews": reviews, "input_revision": "plan"}, state, ROWS,
                                                 {case: "cv_" + case for case in ALL})
        check("only the rejected row is refused by the gate, and the refusal names the critic's word",
              len(problems) == 1 and "TS-1" in problems[0] and "'reject'" in problems[0], problems)
    finally:
        cleanup(root)


def the_refusal_names_the_true_source() -> None:
    """L-4: the refusal quotes where the word came from, and never a word the critic did not write."""
    root = temp_dir("qa-scoped-review-source-")
    try:
        c = Controller(root)

        def gate(dispatches) -> tuple:
            state = {"source_revision": "src", "plan_revision": "plan", "dispatches": dispatches}
            links = [{"case_id": case, "version": "cv_" + case} for case in ALL]
            with patch.object(c, "_row_cases", return_value=MAPPING), \
                    patch.object(c, "_rollcall_reviewed", return_value=set(ALL)), \
                    patch("contract.story_case_links", return_value=links):
                reviews = c._build_design_reviews(state, ROWS)
                return reviews, c._design_review_problems({"design_reviews": reviews, "input_revision": "plan"}, state,
                                                          ROWS, {case: "cv_" + case for case in ALL})

        def one(text):
            ref = put(root, "area", text)
            return gate({"author": author(), "critic1": critic("critic1", ALL, ref)}), ref

        (reviews, problems), _ = one(round_text(1, "approve", [(case, "yes", "x") for case in ALL], column=False))
        check_eq("no column + approve: nothing refused, and no source on an accepted row",
                 (problems, [r.get("verdict_source") for r in reviews]), ([], [None, None, None]))
        (reviews, problems), _ = one(round_text(1, "reject", [(case, "yes", "x") for case in ALL], column=False))
        check("no column + reject: refused, naming the round's own word and that no per-case verdict exists",
              len(problems) == 3 and all("the round's word is 'reject'" in p and "no per-case verdict for TC-" in p
                                         and "`verdict` column" in p and "round of dispatch critic1" in p
                                         for p in problems), problems)
        check("and it never says the critic declared an approval it did not write (the door's clause aside)",
              not any("approv" in p.split(" — ")[0] for p in problems), problems)
        (reviews, problems), _ = one(round_text(1, "partial", [(case, "yes", "x") for case in ALL], column=False))
        check("no column + partial: the critic's own word partial is quoted", len(problems) == 3
              and all("the round's word is 'partial'" in p for p in problems), problems)
        check("R-2: no column - the sentence says there is no per-case verdict for the row, never that the critic's "
              "verdict for this row is 'partial'", all("no per-case verdict for this row" in p
                                                       and "the case critic's verdict for this row" not in p
                                                       for p in problems), problems)
        (reviews, problems), _ = one(round_text(1, "approve", [("TC-1", "yes", "reject"), ("TC-2", "yes", "approve"),
                                                               ("TC-3", "yes", "approve")]))
        check("a column word is quoted as the roll-call's own, and called the critic's verdict for the row",
              len(problems) == 1 and "the roll-call's verdict for TC-1 is 'reject'" in problems[0]
              and "the case critic's verdict for this row is 'reject'" in problems[0], problems)
        (reviews, problems), _ = one(round_text(1, "approve", [("TC-1", "yes", "ok"), ("TC-2", "yes", "approve"),
                                                               ("TC-3", "yes", "approve")]))
        check("a cell word outside the list is a doubt: gate A says it cannot read an approving word, and quotes the cell",
              len(problems) == 1 and "gate A cannot read an approving word of the case critic for this row" in problems[0]
              and "'ok', which is no word of the critic's list" in problems[0]
              and "verdict for this row is" not in problems[0], problems)
        (reviews, problems), ref = one(round_text(1, "approve", [(case, "yes", "approve") for case in ALL]))
        edited = {"path": ref["path"], "sha256": "0" * 64}
        reviews, problems = gate({"author": author(), "critic1": critic("critic1", ALL, edited)})
        check("driver2 (FR-1): a receipt whose bytes are gone names the edited file and the receipt, does not blame "
              "the critic, and names both doors",
              len(problems) == 3 and all(ref["path"] in p and "edited after that review was accepted" in p
                                         and "receipt (sha256 000000000000)" in p and "round of dispatch critic1" in p
                                         and "the critic's word is not in question" in p
                                         and "run the critic round again" in p and "waiver.py --task" in p
                                         and "declared verdict" not in p and "verdict for this row is" not in p
                                         for p in problems), problems)
        check_eq("and its basis is the field the driver can branch on",
                 [r.get("verdict_basis") for r in reviews], ["receipt_mismatch"] * 3)
        put(root, "area", round_text(1, "reject", [(case, "yes", "reject") for case in ALL]))
        reviews, problems = gate({"author": author(), "critic1": critic("critic1", ALL, {"path": "S4.txt", "sha256": ""})})
        check("the older rule (no findings ref) keeps the older sentence, where the declared word is the source",
              len(problems) == 3 and all("own declared verdict is 'reject'" in p for p in problems)
              and not any("verdict_source" in r for r in reviews), problems)
    finally:
        cleanup(root)


# --- the brief ---------------------------------------------------------------------------------------

def the_brief_reads_the_rows_through_the_gate_route() -> None:
    root = temp_dir("qa-scoped-review-brief-")
    try:
        check_eq("no controller state: no rows to show", GB.accepted_review_summary(root), [])
        (root / "state").mkdir()
        (root / "state" / "controller.json").write_text("{}", encoding="utf-8")
        request = {"design_reviews": [{"plan_row": "TS-1", "verdict": "accepted", "author_basis": "scope",
                                       "reviewer_dispatch_id": "c1"},
                                      {"plan_row": "TS-2", "verdict": "reject", "reviewer_dispatch_id": "c1"},
                                      "not a review"]}
        with patch.object(Controller, "build_gate_decision", return_value=request):
            check_eq("the rows are the ones the decision would carry, word and row only",
                     GB.accepted_review_summary(root),
                     [{"plan_row": "TS-1", "verdict": "accepted"}, {"plan_row": "TS-2", "verdict": "reject"}])
        sourced = {"design_reviews": [{"plan_row": "TS-1", "verdict": "partial", "verdict_basis": "receipt_mismatch",
                                       "verdict_source": "round of dispatch d1: why", "reviewer_dispatch_id": "d1"},
                                      {"plan_row": "TS-2", "verdict": "accepted", "reviewer_dispatch_id": "d1"},
                                      {"plan_row": "TS-15", "verdict": "accepted", "reviewer_dispatch_id": ""}]}
        with patch.object(Controller, "build_gate_decision", return_value=sourced):
            got = GB.accepted_review_summary(root)
        check_eq("a refused row carries the basis of its word, never the conductor's prose; a row no critic covered "
                 "is marked", got,
                 [{"plan_row": "TS-1", "verdict": "partial", "basis": "receipt_mismatch"},
                  {"plan_row": "TS-2", "verdict": "accepted"}, {"plan_row": "TS-15", "verdict": "accepted", "no_critic": True}])
        line = GB._head_lines({"gate_reviews": got, "roll_call": {}})[-1]
        check("n-1, m-4: the brief line gives the first reason in plain words, no dispatch id, and does not count a row "
              "no critic reviewed as accepted",
              "TS-1 partial; 1 accepted; 1 with no case critic review. First reason (TS-1): the critic's findings "
              "were edited after the review was accepted." in line and "dispatch" not in line, line)
        with patch.object(Controller, "build_gate_decision", side_effect=RuntimeError("state unreadable")):
            check_eq("the brief does not fail for want of a receipt", GB.accepted_review_summary(root), [])
    finally:
        cleanup(root)


def main() -> None:
    reader_reads_the_verdict_column()
    reader_takes_only_the_bytes_the_receipt_measured()
    reader_reads_only_the_round_of_the_receipt()
    a_round_ends_where_the_older_receipt_begins()
    each_basis_says_where_the_word_came_from()
    the_row_names_the_round_that_produced_its_word()
    the_controller_passes_the_receipts_of_the_same_file()
    the_roll_call_parser_carries_every_id_and_the_verdict_column()
    a_scoped_repair_clears_only_its_case()
    the_older_layout_of_one_folder_per_round_is_read_the_same()
    every_doubt_is_partial()
    the_older_form_keeps_the_older_rule()
    a_later_round_that_rejects_a_case_out_of_its_scope_holds()
    rows_share_cases_and_areas_do_not_blur()
    the_gate_refuses_a_rejected_row_and_names_the_word()
    the_refusal_names_the_true_source()
    the_brief_reads_the_rows_through_the_gate_route()
    finish("test_scoped_review_verdict")


if __name__ == "__main__":
    main()
