#!/usr/bin/env python3
"""The planner's claim reaches the S2 register through code (G1-13): `claim_projector.project` and `s3_claim_errors`.

Pins (spec t-1156 sections 4, 6, 7 and its Lead decisions): the byte pin on four registers (a projected line is the ONLY change, plus
`ids:` / `by_source:`), the exact lines of the 15045 register, idempotence, an edited claim refused, I3 (a projected R is always an
implementation-only claim), the read-only S3 check (no lock, no byte), the edges E1-E23, the seam with GT R5 (a projection that wrote
changes `register_sha256`; `grounding_table.py --refresh` restores it) and both worlds of a register written before this change.
"""
import difflib
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import claim_projector as CP  # noqa: E402
import contract as C  # noqa: E402
import grammar as G  # noqa: E402
import grounding_table as GT  # noqa: E402
import question_register as QR  # noqa: E402

FIX = FIXTURES / "claim-projector"
P15 = FIXTURES / "oracle-provenance"
AFTER = FIXTURES / "after-checks" / "work"
ROOT = temp_project("qa-claims-")
use_project(ROOT)
BOM = chr(0xFEFF)
LS = chr(0x2028)
DASH = chr(0x2014)
NOW_REF = "diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:541"
BEFORE_REF = "diff:-testproject1-backend:src/testproject1/rest_api/routers/workflow.py:540"
REQUIREMENT = "PUT /v1/workflows/{id} answers 403 when the guardrail and the MCP checks both fail."
CLAIMS_HEAD = ["", "## Behaviour claims", "", "| R | before | before_ref | now | now_ref | differs | question | origin |", "|---|---|---|---|---|---|---|---|"]


class Raw(str):
    """A YAML value written as it is (no quotes): the trap cases."""


def val(v):
    return v if isinstance(v, Raw) else json.dumps(v)


def claim(**over):
    base = {"r": "R-28", "row": "G-4", "requirement": REQUIREMENT,
            "impact": Raw("degraded"), "before": "400", "before_ref": BEFORE_REF,
            "now": "403", "now_ref": NOW_REF, "differs": "yes",
            "question": Raw("raise"),
            "ask": {"question": "Which status code must PUT return when both checks fail?",
                    "source_says": Raw('[{quote: "returns the same results as before", where: "register R-19"}]'),
                    "severity": Raw("major"), "owner_role": Raw("po_ba")}}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def yaml_of(claims, rows=("G-4",), top=True):
    out = ["schema_version: 1", "implementation_source: diff", "rows:"]
    for r in rows:
        out += [f"  - id: {r}", "    label: behaviour_change", '    reason: "x"']
    if claims is None:
        return "\n".join(out) + "\n"
    out.append("claims:" + (" []" if claims == [] else ""))
    for c in claims:
        lead = "  - "
        for k, v in c.items():
            if k == "ask":
                out.append("    ask:")
                out += [f"      {ak}: {val(av)}" for ak, av in v.items()]
                continue
            out.append(f"{lead}{k}: {val(v)}")
            lead = "    "
    return "\n".join(out) + "\n"


def story(register=None, readiness=None, grounding=None, manifest=None):
    """A temp story folder; `register`/`readiness` are paths of a fixture (or bytes), `grounding` the YAML text."""
    task = Path(temp_dir("qa-claims-story-")) / "T-1"
    (task / "work").mkdir(parents=True)
    for name, src in (("requirements-register.md", register), ("requirements-readiness.json", readiness)):
        if src is not None:
            (task / "work" / name).write_bytes(src if isinstance(src, bytes) else Path(src).read_bytes())
    if grounding is not None:
        (task / "work" / "grounding.yaml").write_bytes(grounding.encode("utf-8"))
    if manifest is not None:
        shutil.copyfile(manifest, task / "work" / "context-manifest.json")
    return task


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else "-"


def tree(task) -> dict:
    """Every file of the story and its sha256, the lock file aside (a refusal under the lock legitimately creates it; `lock()` asks for it)."""
    return {str(p.relative_to(task)): sha(p) for p in sorted(Path(task).rglob("*")) if p.is_file() and p.name != QR.LOCK_NAME}


def lock(task) -> bool:
    return (Path(task) / "work" / QR.LOCK_NAME).exists()


def put(path, text: str) -> None:
    """Write text with LF endings whatever the platform (`write_text` would turn LF into CRLF on Windows)."""
    Path(path).write_bytes(text.encode("utf-8"))


def reg_of(task) -> Path:
    return Path(task) / "work" / "requirements-register.md"


def rd_of(task) -> Path:
    return Path(task) / "work" / "requirements-readiness.json"


def done(task):
    shutil.rmtree(Path(task).parent, ignore_errors=True)


def inserted(old: bytes, new: bytes) -> list:
    """The lines the new bytes hold between the old ones (the inserts of a line diff, line endings kept)."""
    a, b = old.decode("utf-8").splitlines(keepends=True), new.decode("utf-8").splitlines(keepends=True)
    return [x for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag == "insert" for x in b[j1:j2]]


def claims_row(r: str, q: str) -> str:
    return f"| {r} | 400 | {BEFORE_REF} | 403 | {NOW_REF} | yes | {q} | S3-grounding |"


def register_row(r: str, tail: str = "") -> str:
    """The projected Register line: seven cells, plus `impact` and `delta` (`tail`) where the register has those columns."""
    return f"| {r} | {REQUIREMENT} | derived | aspect:behaviour-change | yes | {DASH} | {NOW_REF} |{tail}"


def pin_ok(old: bytes, new: bytes) -> bool:
    """I4: against the old bytes the new ones differ by inserted lines, the `ids:` line and the `by_source:` line - nothing else."""
    a, b = old.decode("utf-8").splitlines(keepends=True), new.decode("utf-8").splitlines(keepends=True)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal" or tag == "insert":
            continue
        if tag == "replace" and all(x.startswith(("ids:", "by_source:")) for x in a[i1:i2]) and all(x.startswith(("ids:", "by_source:")) for x in b[j1:j2]):
            continue
        if tag == "replace" and i2 - i1 == 1 and a[i1].rstrip("\r\n") == b[j1].rstrip("\r\n") and j2 - j1 == 1:
            continue   # the old last line got its newline (EOF without one): the one extra byte
        return False
    return True


GOOD = yaml_of([claim()])

# --- P-15045: the exact lines (spec 4.3) and the byte pin on the legacy register --------------------------------------------------
t = story(P15 / "requirements-register.md", P15 / "requirements-readiness.json", GOOD)
old_reg, old_rd = reg_of(t).read_bytes(), json.loads(rd_of(t).read_text(encoding="utf-8"))
res = CP.project(t)
new = reg_of(t).read_text(encoding="utf-8").splitlines()
check_eq("15045: projected R-28, no problem, wrote", (res.projected, [str(p) for p in res.problems], res.wrote), (["R-28"], [], True))
check_eq("15045: ids line", new[3], "ids: [R-1, R-13, R-16, R-17, R-18, R-19, R-27, R-28]")
check_eq("15045: by_source line", new[4], "by_source: {story: 0, feature: 0, assumption: 0, discussion: 0, ac: 2, derived: 6}")
want_row = ("| R-28 | PUT /v1/workflows/{id} answers 403 when the guardrail and the MCP checks both fail. | derived | aspect:behaviour-change | yes | "
            + chr(0x2014) + " | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:541 | degraded |")
check_eq("15045: the Register line sits right after the last Register row", new[19], want_row)
check_eq("15045: the claims block is at the end, whole", new[-5:], [
    "## Behaviour claims", "", "| R | before | before_ref | now | now_ref | differs | question | origin |", "|---|---|---|---|---|---|---|---|",
    "| R-28 | 400 | diff:-testproject1-backend:src/testproject1/rest_api/routers/workflow.py:540 | 403 | "
    "diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:541 | yes | Q8 | S3-grounding |"])
check_eq("15045: a blank line before the heading", new[-6], "")
check("15045: the byte pin (only inserted lines + ids/by_source differ)", pin_ok(old_reg, reg_of(t).read_bytes()))
mutant = reg_of(t).read_text(encoding="utf-8").replace("| R-1 | Visual", "| R-1  | Visual").encode("utf-8")
check("15045: NEGATIVE CONTROL - a rewritten untouched row fails the pin", not pin_ok(old_reg, mutant))
rd = json.loads(rd_of(t).read_text(encoding="utf-8"))
q = rd["open_questions"][2]
check_eq("15045: readiness - the first two questions and the verdict are untouched", (rd["open_questions"][:2], rd["verdict"]),
         (old_rd["open_questions"], old_rd["verdict"]))
check_eq("15045: the new question", (q["id"], q["raised_for"], q["before"], q["now"], q["readings"], q["severity"], q["owner_role"]),
         ("Q8", {"claim": "R-28", "origin": "S3-grounding"},
          {"value": "400", "where": "diff:-testproject1-backend:src/testproject1/rest_api/routers/workflow.py:540"},
          {"value": "403", "where": "diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:541"}, C.claim_readings("400", "403"),
          "major", "po_ba"))
check_eq("15045: the missing `register` block is created from the new rows", rd["register"],
         {"total": 8, "by_source": {"story": 0, "feature": 0, "assumption": 0, "discussion": 0, "ac": 2, "derived": 6}})
text = reg_of(t).read_text(encoding="utf-8")
questions = {x["id"]: x for x in rd["open_questions"]}
check_eq("I3: R-28 is implementation-only with its own question and a clean claim row",
         ("R-28" in C.implementation_only(text), C.claim_questions(text)["R-28"],
          C.claim_row_errors(next(r for r in C.behaviour_claims(text) if r["r"] == "R-28"), questions)), (True, "Q8", []))
row28 = next(r for r in C.register_rows(text) if r["r"] == "R-28")
check_eq("I3: source derived, no ac_ref, a diff observable, delta absent on an 8-cell register",
         (row28["source"], row28["ac_ref"], row28["observable"].startswith("diff:"), row28["delta"]), ("derived", DASH, True, None))
# F-C: the projection that wrote changed the register's bytes, so GT R5 compares another sha256 - pinned so the seam cannot be forgotten
check("F-C: the register's sha256 differs after a projection that wrote", hashlib.sha256(old_reg).hexdigest() != sha(reg_of(t)))
# P-twice (E8, F-F): a second run over the same claims writes nothing
before = tree(t)
again = CP.project(t)
check_eq("P-twice: unchanged, nothing projected, wrote False, every file as it was", (again.projected, again.unchanged, again.wrote, tree(t) == before),
         ([], ["R-28"], False, True))
check_eq("P-twice: one question only", len(json.loads(rd_of(t).read_text(encoding="utf-8"))["open_questions"]), 3)
# P-check (v): the legacy register - S3 rows judged, S2's R-16..R-19 (no claims rows) not listed; FR-45
before = tree(t)
check_eq("P-check v: the projected story has no S3 finding", [str(p) for p in CP.s3_claim_errors(t)], [])
lock_before = lock(t)
CP.s3_claim_errors(t)
check_eq("FR-45: the check wrote nothing and created no lock", (tree(t) == before, lock(t) == lock_before), (True, True))
# M8 / E15 (the date gate is kept for S3 rows): the register is dated 2026-10-01, before the oracle cutoff, and its S3 row is judged all the
# same - with its question gone from readiness the check finds it (a check that skipped legacy-dated registers would say [])
good_rd = rd_of(t).read_bytes()
gone = json.loads(good_rd.decode("utf-8"))
gone["open_questions"] = [x for x in gone["open_questions"] if x["id"] != "Q8"]
put(rd_of(t), json.dumps(gone))
found = CP.s3_claim_errors(t)
check_eq("M8 / E15: a legacy-dated register's S3 row whose question is gone is found", [p.rule for p in found], ["R-d"])
check_in("M8 / E15: ...and the text names the question", "question Q8 is not in `open_questions`", found)
# B-1 / E12 (FR-59): the file the question is confirmed in is absent - every S3 row is a finding, never []; not JSON - today's text
rd_of(t).unlink()
before = tree(t)
found = CP.s3_claim_errors(t)
check_eq("B-1 E12 file deleted: one R-d for the conductor, never []", [(p.rule, p.who) for p in found], [("R-d", "conductor")])
check_in("B-1 E12 file deleted: the text", "question Q8 cannot be confirmed: requirements-readiness.json is absent/unreadable", found)
check_eq("B-1 E12 file deleted: the check wrote nothing and created no lock", (tree(t) == before, lock(t) == lock_before), (True, True))
rd_of(t).write_bytes(b"{nope")
found = CP.s3_claim_errors(t)
check_eq("B-1 E12 file not JSON: R-d, today's text (the question is not in open_questions)",
         ([p.rule for p in found], any("question Q8 is not in `open_questions`" in p for p in found)), (["R-d"], True))
rd_of(t).write_bytes(good_rd)
check_eq("B-1: the readiness back as it was: no finding", [str(p) for p in CP.s3_claim_errors(t)], [])
# P-edit (E10)
put(t / "work" / "grounding.yaml", yaml_of([claim(now="404")]))
before = tree(t)
res = CP.project(t)
check_eq("P-edit: an edited claim is refused R-c, both files as they were", ([p.rule for p in res.problems], res.wrote, tree(t) == before), (["R-c"], False, True))
check_in("P-edit: the text names the question, the old and the new reading", "R-28 was raised as Q8 showing now 403; it now shows now 404", res.problems[0])
found = CP.s3_claim_errors(t)
check_eq("P-check: the edited claim differs from its projected row", [p.rule for p in found], ["R-c"])
check_in("P-check: ...and says which field", "now: 403 vs 404", found[0])
done(t)

# --- P-bytes on the other registers, M2 (CRLF + BOM), the temporal worlds ------------------------------------------------------------
dated = (FIX / "requirements-register.md").read_bytes()
crlf = BOM.encode("utf-8") + dated.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
after = AFTER / "requirements-register.md"
WITH_DELTA = " degraded | new |"
cases = (("after-checks 7-cell register (a block before ## Reading forks)", after.read_bytes(), AFTER / "requirements-readiness.json", "R-9",
          [register_row("R-9"), *CLAIMS_HEAD, claims_row("R-9", "Q1")]),
         ("dated register with a claims section", dated, FIX / "requirements-readiness.json", "R-28",
          [register_row("R-28", WITH_DELTA), claims_row("R-28", "Q2")]),
         ("dated register rewritten CRLF + BOM", crlf, FIX / "requirements-readiness.json", "R-28",
          [register_row("R-28", WITH_DELTA), claims_row("R-28", "Q2")]))
for label, reg_bytes, rd_path, r, block in cases:
    t = story(reg_bytes, rd_path, yaml_of([claim(r=r)]))
    res = CP.project(t)
    out = reg_of(t).read_bytes()
    eol = "\r\n" if b"\r\n" in reg_bytes else "\n"
    check_eq(f"{label}: projected", ([str(p) for p in res.problems], res.projected), ([], [r]))
    check(f"{label}: the byte pin", pin_ok(reg_bytes, out))
    check_eq(f"{label}: the inserted lines are exactly the projection (Register line, claims block, line endings kept)", inserted(reg_bytes, out),
             [line + eol for line in block])
    check(f"{label}: `ids:` ends with the new R", C.front_line(out.decode("utf-8"), "ids").strip().endswith(f", {r}]"))
    check(f"{label}: no mixed line endings", (b"\r\n" in out) == (b"\r\n" in reg_bytes) and (out.count(b"\n") == out.count(b"\r\n") or b"\r\n" not in out))
    check(f"{label}: BOM kept", out.startswith(BOM.encode("utf-8")) == reg_bytes.startswith(BOM.encode("utf-8")))
    text = out.decode("utf-8")
    check_eq(f"{label}: the row reads back as an implementation-only claim", (r in C.implementation_only(text), C.claim_questions(text)[r]),
             (True, json.loads(rd_of(t).read_text(encoding="utf-8"))["open_questions"][-1]["id"]))
    if "delta" in text.split("## Register")[1].split("\n")[2]:
        check_in(f"{label}: delta new on a register that has the column", "| new |", [l for l in text.splitlines() if l.startswith(f"| {r} |")][0])
    done(t)
t = story(after.read_bytes(), AFTER / "requirements-readiness.json", yaml_of([claim(r="R-9")]))
res = CP.project(t)
check_in("7-cell register: the note says impact was not written", "impact not written", res.notes)
check("7-cell register: the claims block stands before ## Reading forks", reg_of(t).read_text(encoding="utf-8").index("## Behaviour claims")
      < reg_of(t).read_text(encoding="utf-8").index("## Reading forks"))
done(t)
# temporal: a register written BEFORE this change has no claims section / no `origin` column - read as S2, the projector adds only on a claim
old_world = dated.replace(b"| question | origin |", b"| question |").replace(b"|---|---|---|---|---|---|---|---|\n| R-3", b"|---|---|---|---|---|---|---|\n| R-3").replace(b"| yes | Q1 | |", b"| yes | Q1 |")
t = story(old_world, FIX / "requirements-readiness.json", yaml_of([claim(r="R-28")]))
check_eq("old world: S2's claim row without `origin` reads origin ''", C.behaviour_claims(old_world.decode("utf-8"))[0]["origin"], "")
CP.project(t)
text = reg_of(t).read_text(encoding="utf-8")
check_in("old world: the header got ` origin |` as a suffix", "| question | origin |", text)
check_eq("old world: S2's row is untouched (origin ''), the new one is S3-grounding", [r["origin"] for r in C.behaviour_claims(text)], ["", "S3-grounding"])
check_eq("old world: exactly one S3-grounding row stands in the register", text.count("S3-grounding"), 1)
done(t)
t = story(dated, FIX / "requirements-readiness.json", yaml_of(None))
b0 = tree(t)
res = CP.project(t)
check_eq("no `claims` key: nothing, zero bytes, no lock", (res.projected, res.problems, tree(t) == b0, (t / "work" / QR.LOCK_NAME).exists()), ([], [], True, False))
done(t)

# --- E1..E8: the claim's shape (every claim judged, problems whole, one refused claim holds all) --------------------------------------
def refuse(label, claims_yaml, rule="R-a", expect=None, register=dated, readiness=FIX / "requirements-readiness.json", **kw):
    t = story(register, readiness, claims_yaml)
    b0 = tree(t)
    res = CP.project(t, **kw)
    check_eq(f"{label}: refused {rule}, zero bytes", ([p.rule for p in res.problems][:1], res.wrote, tree(t) == b0), ([rule], False, True))
    if rule == "R-a":
        check(f"{label}: ...and no lock was taken", not lock(t))
    if expect:
        check_in(f"{label}: the text", expect, res.problems[0])
    done(t)
    return res


for label, yml in (("E1 null", "schema_version: 1\nclaims: null\n"), ("E1 empty list", yaml_of([])), ("E1 no key", yaml_of(None))):
    t = story(dated, FIX / "requirements-readiness.json", yml)
    b0 = tree(t)
    res = CP.project(t)
    check_eq(f"{label}: nothing, no problem, no lock", (res.projected, res.problems, tree(t) == b0), ([], [], True))
    done(t)
t = story(dated, FIX / "requirements-readiness.json", None)
res = CP.project(t)
check_eq("E3: no grounding.yaml: nothing and no problem", (res.problems, res.wrote), ([], False))
(t / "work" / "grounding.yaml").write_bytes(b"not: [a mapping\n")
check_eq("E3: an unreadable table is R-e with the reader's who", ([p.rule for p in CP.project(t).problems], CP.project(t).problems[0].who), (["R-e"], "role"))
done(t)
refuse("E2 before: 400 (a number)", yaml_of([claim(before=Raw("400"))]), expect="double quotes")
refuse("E2 comment", yaml_of([claim(requirement=Raw("Does x # not y"))]), expect="comment")
refuse("E2 flow-map entry", "schema_version: 1\nrows:\n  - id: G-4\nclaims:\n  - {r: R-9, before: 400}\n", expect="")
refuse("E2 claims not a list", "schema_version: 1\nclaims: text\n", expect="not a list")
for label, over, expect in (("E7 r=R-0", {"r": "R-0"}, "free register id"), ("E7 r=R-01", {"r": "R-01"}, "free register id"),
                            ("E7 r=r28", {"r": "r28"}, "free register id"), ("E7 row off", {"row": "G-9"}, "no id of `rows[]`"),
                            ("E7 now_ref not diff", {"now_ref": "base:abc:x.py:1"}, "diff:<path>:<line>"),
                            ("E7 question != raise", {"question": Raw("Q3")}, "question: raise"), ("E7 origin other", {"origin": "S2"}, "origin"),
                            ("E7 impact off the scale", {"impact": Raw("huge")}, "impact scale"), ("E7 requirement empty", {"requirement": ""}, "empty"),
                            ("E5 pipe", {"requirement": "a | b"}, "`|`"), ("E5 escaped U+2028", {"requirement": "a b"}, "U+2028"),
                            ("E23 lone surrogate", {"requirement": "a\ud800b"}, "surrogate"),
                            ("E6 differs", {"differs": "maybe"}, "differs"), ("E20 before empty", {"before": ""}, "before")):
    res = refuse(label, yaml_of([claim(**over)]), expect=expect)
refuse("E7 two claims one r", yaml_of([claim(), claim()]), expect="also written by")
res = refuse("M1: the 2nd claim malformed, the 1st (good) is not written", yaml_of([claim(), claim(r="R-29", row="G-9")]), expect="claims[1] (R-29)")
check_in("one refused claim holds all (names the count)", "holds all 2", res.problems[0])
res = refuse("E7: the problems are listed whole (two claims, two flaws)", yaml_of([claim(r="R-0"), claim(r="R-29", impact=Raw("huge"))]))
check_eq("E7: ...both listed", len(res.problems), 2)
# F-4 / E7: a malformed `r` names the next free id (a lock-free read, for the text only)
refuse("F-4 E7: r=r28 names the next free id of the register", yaml_of([claim(r="r28")]), expect="(the next free id is R-4)")
refuse("F-4 E7: ...counting the other claims of the table", yaml_of([claim(r="r28"), claim(r="R-40")]), expect="(the next free id is R-41)")
res = refuse("F-4 E7: a register that cannot be read offers no id", yaml_of([claim(r="r28")]), register=None)
check_not_in("F-4 E7: ...and the text does not guess one", "next free id", res.problems[0])
# FR-45 on a story that was never projected: the read-only check lists the missing claim and creates NO file (no lock)
t = story(dated, FIX / "requirements-readiness.json", GOOD)
b0 = tree(t)
found = CP.s3_claim_errors(t)
check_eq("P-check i/FR-45: an unprojected claim is named, no file was created (the lock above all), no byte moved",
         ([p.rule for p in found], "claim R-28 is not in the register" in found[0], tree(t) == b0, lock(t)), (["R-d"], True, True, False))
done(t)
# B-1: with no S3 row anywhere there is nothing to confirm, so an absent readiness file is silent
t = story(dated, None, yaml_of(None))
check_eq("B-1: no S3 row and no readiness file: nothing to confirm, no finding", [str(p) for p in CP.s3_claim_errors(t)], [])
done(t)
# B-2 (spec 4.7 (b)): `ids:` is read back by the writer and checked by the S3 check
t = story(dated.replace(b"ids: [R-1, R-2, R-3]", b"ids: [R-1, R-2, R-3] extra"), FIX / "requirements-readiness.json", GOOD)
b0 = tree(t)
rep_real, rep_calls = CP.os.replace, []
CP.os.replace = lambda a, b: (rep_calls.append(b), rep_real(a, b))[1]
try:
    res = CP.project(t)
finally:
    CP.os.replace = rep_real
check_eq("B-2 (P3): an `ids:` line the writer cannot extend is refused R-d for the conductor, nothing projected, wrote False",
         ([(p.rule, p.who) for p in res.problems], res.projected, res.wrote), ([("R-d", "conductor")], [], False))
check_in("B-2 (P3): ...the text says R-28 is not in `ids:`", "it is not in the front matter `ids:`", res.problems)
check_eq("B-2 (P3): ...refused BEFORE any replace: no os.replace call, both files byte-equal", (rep_calls, tree(t) == b0), ([], True))
done(t)
t = story(dated, FIX / "requirements-readiness.json", GOOD)
CP.project(t)
check_eq("B-2 (P2): the projected story is clean before `ids:` is damaged", [str(p) for p in CP.s3_claim_errors(t)], [])
text = reg_of(t).read_text(encoding="utf-8")
check("B-2 (P2): the register's `ids:` names R-28", "ids: [R-1, R-2, R-3, R-28]" in text)
put(reg_of(t), text.replace("ids: [R-1, R-2, R-3, R-28]", "ids: [R-1, R-2, R-3]"))
found = CP.s3_claim_errors(t)
check_eq("B-2 (P2): R-28 projected but not in `ids:` is one R-d for the conductor", [(p.rule, p.who) for p in found], [("R-d", "conductor")])
check_in("B-2 (P2): ...the text", "R-28: projected, but not in the front matter `ids:`", found)
done(t)
# F-7: the table of sources the readiness counters are written for is the grammar's set
check_eq("F-7: SOURCE_ORDER is the grammar's set of requirement sources", set(CP.SOURCE_ORDER), G.REQ_SOURCES)
# M8 / F-8: S2's own claims rows are never re-judged at S3 (FR-7: S2's passed debt is not re-asked)
t = story(dated.replace(b"diff:-app/api.py:29", b"bogus"), FIX / "requirements-readiness.json", yaml_of(None))
check_eq("M8: an S2 claims row with a bad before_ref is not listed by the S3 check", [str(p) for p in CP.s3_claim_errors(t)], [])
done(t)
# AT the limit: a 10 000-character requirement is projected whole, one line; BEYOND: the same plus one escaped U+2028 is refused
t = story(dated, FIX / "requirements-readiness.json", yaml_of([claim(requirement="x" * 10000)]))
res = CP.project(t)
line = next(l for l in reg_of(t).read_text(encoding="utf-8").splitlines() if l.startswith("| R-28 |") and "derived" in l)
check_eq("E5 AT: 10 000 characters, whole, one line", (res.projected, "x" * 10000 in line), (["R-28"], True))
done(t)
refuse("E5 BEYOND: 10 000 characters and one U+2028", yaml_of([claim(requirement="x" * 10000 + LS)]), expect="U+2028")
WORDS = "Words " + "".join(map(chr, (0x416, 0x443, 0x43A))) + ", CJK " + chr(0x4E2D) + ", emoji " + chr(0x1F600)   # built: the package is English (FR-30)
t = story(dated, FIX / "requirements-readiness.json", yaml_of([claim(requirement=WORDS)]))
res = CP.project(t)
check_in("E22: non-ASCII verbatim in the register, UTF-8", WORDS, reg_of(t).read_text(encoding="utf-8"))
check_eq("E22: ...and the question is kept whole", json.loads(rd_of(t).read_text(encoding="utf-8"))["open_questions"][1]["raised_for"]["claim"], "R-28")
done(t)
# E9 / M11: taken by the S2 register, whole token
refuse("E9 R-1 taken (Register)", yaml_of([claim(r="R-1")]), rule="R-b", expect="taken in requirements-register.md (Register")
refuse("E9 R-1 on the 15045 register", yaml_of([claim(r="R-27")]), rule="R-b", register=(P15 / "requirements-register.md").read_bytes(),
       readiness=P15 / "requirements-readiness.json", expect="Register")
t = story(P15 / "requirements-register.md", P15 / "requirements-readiness.json", yaml_of([claim(r="R-2")]))
check_eq("E9 / M11: R-2 is FREE in a register that holds R-27 (a whole-token match)", CP.project(t).projected, ["R-2"])
done(t)

# --- E4: the carriers --------------------------------------------------------------------------------------------------------------
for label, kw in (("E4 readiness absent", {"readiness": None}), ("E4 readiness not JSON", {"readiness": b"{nope"}),
                  ("E4 no ## Register", {"register": b"---\nids: [R-1]\n---\n\ntext\n"}),
                  ("E4 ids not inline", {"register": dated.replace(b"ids: [R-1, R-2, R-3]", b"ids:\n  - R-1")}),
                  ("E4 no ids line at all", {"register": dated.replace(b"ids: [R-1, R-2, R-3]\n", b"")}),
                  ("E17 header out of order", {"register": dated.replace(b"| source | derived_from |", b"| derived_from | source |")})):
    t = story(kw.get("register", dated), kw.get("readiness", FIX / "requirements-readiness.json"), GOOD)
    b0 = tree(t)
    res = CP.project(t)
    check_eq(f"{label}: R-d (conductor), zero bytes", ([p.rule for p in res.problems], res.problems[0].who, res.wrote, tree(t) == b0), (["R-d"], "conductor", False, True))
    done(t)
# E4b / M16: a flat legacy register is rewritten in place, never twinned
t = story(None, FIX / "requirements-readiness.json", GOOD)
shutil.copyfile(FIX / "requirements-register.md", t / "requirements-register.md")
res = CP.project(t)
check_eq("E4b: a flat legacy register is rewritten in place; no second copy in work/", (res.projected, (t / "work" / "requirements-register.md").exists(),
         "R-28" in (t / "requirements-register.md").read_text(encoding="utf-8")), (["R-28"], False, True))
done(t)
# a lock held by another writer: R-e (driver), zero bytes
t = story(dated, FIX / "requirements-readiness.json", GOOD)
b0 = tree(t)
with QR.answers_lock(t):
    res = CP.project(t, lock_wait=0.2)
check_eq("lock held: R-e for the driver, nothing written", ([p.rule for p in res.problems], res.problems[0].who, res.wrote, tree(t) == b0), (["R-e"], "driver", False, True))
done(t)

# --- E11 crash replay (M13), E12, E14, M3, M4's neighbour (a claim key and a case key never meet), E19, E20, E21 --------------------------
class Crash(BaseException):
    pass


clean = story(dated, FIX / "requirements-readiness.json", GOOD)
CP.project(clean)
t = story(dated, FIX / "requirements-readiness.json", GOOD)
real, calls = CP.os.replace, []


def boom(a, b):
    calls.append(b)
    if len(calls) == 2:
        raise Crash()
    return real(a, b)


CP.os.replace = boom
try:
    CP.project(t)
except Crash:
    pass
finally:
    CP.os.replace = real
check_eq("E11: after a crash between the writes readiness holds the question and the register lacks the row",
         ("R-28" in reg_of(t).read_text(encoding="utf-8"), len(json.loads(rd_of(t).read_text(encoding="utf-8"))["open_questions"])), (False, 2))
check_in("E11: s3_claim_errors names the pending row", "row pending", CP.s3_claim_errors(t)[0])
res = CP.project(t)
check_eq("E11: the replay converges on the clean run (both files byte-equal; the counters recomputed, never counted twice)",
         (res.projected, json.loads(rd_of(t).read_text(encoding="utf-8")) == json.loads(rd_of(clean).read_text(encoding="utf-8")),
          reg_of(t).read_bytes() == reg_of(clean).read_bytes()), (["R-28"], True, True))
done(t)
# E12: the question is lost from readiness after the projection
rd = json.loads(rd_of(clean).read_text(encoding="utf-8"))
rd["open_questions"] = rd["open_questions"][:1]
put(rd_of(clean), json.dumps(rd))
b0 = tree(clean)
res = CP.project(clean)
check_eq("E12: project does not re-raise (own R, cells equal)", (res.projected, res.unchanged, tree(clean) == b0), ([], ["R-28"], True))
check_in("E12: s3_claim_errors says the question is not in open_questions", "is not in `open_questions`", CP.s3_claim_errors(clean))
done(clean)
# E14: the claim deleted after projection - another claim stays in the table (with an empty `claims` list the move ends at E1, before any note)
t = story(dated, FIX / "requirements-readiness.json", GOOD)
CP.project(t)
put(t / "work" / "grounding.yaml", yaml_of([claim(r="R-29")]))
res = CP.project(t)
check_in("E14: the note says R-28 was projected and is no longer claimed", "R-28 projected, no longer claimed", res.notes)
check_eq("E14: ...the register keeps the row, the new claim is projected", (res.projected, "| R-28 |" in reg_of(t).read_text(encoding="utf-8")), (["R-29"], True))
done(t)
# P-check (ii)(iii)(iv)
t = story(dated, FIX / "requirements-readiness.json", GOOD)
CP.project(t)
good_reg = reg_of(t).read_text(encoding="utf-8")
put(reg_of(t), "".join(l for l in good_reg.splitlines(keepends=True) if not l.startswith("| R-28 |")).replace(", R-28]", "]"))
check_in("P-check iv: Q2 raised and the register row absent -> row pending (the inverse-E12 crash)", "row pending", CP.s3_claim_errors(t)[0])
good_rd = rd_of(t).read_bytes()
gone = json.loads(good_rd.decode("utf-8"))
gone["open_questions"] = gone["open_questions"][:1]
put(rd_of(t), json.dumps(gone))
check_in("P-check ii: a claim gone from the register and from readiness -> not in the register", "claim R-28 is not in the register", CP.s3_claim_errors(t)[0])
rd_of(t).write_bytes(good_rd)
put(reg_of(t), good_reg.replace("| R-3 | silent | silent | silent | n/a:no bugs |", "| R-28 | contradicts:\"x\" (y) | silent | silent | n/a:no bugs |\n| R-3 | silent | silent | silent | n/a:no bugs |"))
found = CP.s3_claim_errors(t)
check("P-check iii: a matrix contradicts row for R-28 -> no longer implementation-only", any("no longer implementation-only" in p for p in found), str(found))
put(reg_of(t), good_reg.replace("| yes | Q2 | S3-grounding |", "| yes | Q2 | S9 |"))
check("M8 / E15: S3 rows are judged by origin, not by the register's date", CP.project(t).problems[0].rule in ("R-d", "R-b", "R-c"))
done(t)
# M4 neighbour: a case key and a claim key with the same numbers never meet
rows = [{"id": "Q1", "raised_for": {"case": "R-28", "then": 1}}]
row, earlier = QR._question_row(rows, {k: "x" for k in QR.QUESTION_KEYS}, {"claim": "R-28", "origin": "S3-grounding"})
check_eq("M4: the claim key is not the case key; the next id", (earlier, row["id"], list(row)[-1]), (None, "Q2", "raised_for"))
# E19: 10 000 claims in one move
many = [claim(r=f"R-{n}", row="G-4") for n in range(100, 10100)]
t = story(dated, FIX / "requirements-readiness.json", yaml_of(many))
res = CP.project(t)
text = reg_of(t).read_text(encoding="utf-8")
ids = [r["question"] for r in C.behaviour_claims(text) if r["origin"] == "S3-grounding"]
check_eq("E19 M9: 10 000 claims, no cap: all projected, contiguous Q ids Q2..Q10001", (len(res.projected), ids[0], ids[-1], len(ids)), (10000, "Q2", "Q10001", 10000))
check_eq("E19: ...and one counter total", json.loads(rd_of(t).read_text(encoding="utf-8"))["register"]["total"], 10003)
done(t)
# E20: before unknown -> projected, delta new, the regression reading says unknown; no BS call
t = story(dated, FIX / "requirements-readiness.json", yaml_of([claim(before="unknown", before_ref="")]))
res = CP.project(t, collected=object())
q = json.loads(rd_of(t).read_text(encoding="utf-8"))["open_questions"][1]
check_eq("E20: unknown before: projected, the question says the code could not be read", (res.projected, q["before"]["where"]),
         (["R-28"], "the code before the change could not be read"))
check_in("E20: delta new, the claims row shows the dash", "| unknown | " + chr(0x2014) + " |", reg_of(t).read_text(encoding="utf-8"))
done(t)
# E21 / M15: a base: ref the slice did not read is refused with the door in the text
class Slice:
    entries, infos = [], []
t = story(dated, FIX / "requirements-readiness.json", yaml_of([claim(before_ref="base:" + "a" * 40 + ":app/api.py:5")]))
b0 = tree(t)
res = CP.project(t, collected=Slice())
check_eq("E21 M15: a base ref the slice cannot show is R-a with the door", ([p.rule for p in res.problems][:1], tree(t) == b0), (["R-a"], True))
check_in("E21: ...the text names `before: \"unknown\"`", 'before: \\"unknown\\"' if False else "unknown", res.problems[0])
done(t)

# --- F-D: the oracle reader on an UNDATED (legacy) register reads an S3 claim, and only that --------------------------------------------
import coverage_contract as CC  # noqa: E402
t = story(P15 / "requirements-register.md", P15 / "requirements-readiness.json", yaml_of([claim(r="R-2")]))
CP.project(t)
legacy = reg_of(t).read_text(encoding="utf-8")
ctx = {"register": legacy, "dated": False, "questions": {}, "cases": {}, "date_problem": ""}
held = CC._oracle_read(ctx, {"id": "TS-1"}, {"obligation_id": "OB-1", "requirement_refs": [{"ref": "R-2"}], "oracle_status": "resolved"})
s2 = CC._oracle_read(ctx, {"id": "TS-1"}, {"obligation_id": "OB-2", "requirement_refs": [{"ref": "R-19"}], "oracle_status": "resolved"})
check_eq("F-D: an S3 claim on an undated register is waiting for the person (unresolved, its question)", (held["status"], held["waiting"], held["question"]),
         ("unresolved", True, "Q8"))
check_eq("F-D: S2's own implementation-only R-19 on the same undated register is still left alone", (s2["status"], s2["waiting"]), ("resolved", False))
done(t)

# --- F-C: GT R5 - the projection that wrote makes R5 fire; `grounding_table.py --refresh` restores it ----------------------------------
def gt_story():
    t = story(None, None, None)
    put(t / "pipeline.json", json.dumps({"ticket": "T-1", "stages": {}, "implementation_source": "diff"}))
    (t / "work" / "impl-diff.txt").write_bytes(b"diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -10,3 +10,3 @@ def a()\n ctx\n-old_a\n+new_a\n tail\n")
    put(t / "work" / "blast-radius.json", json.dumps({"index": {"state": "built"}, "areas": []}))
    put(t / "work" / "requirements-register.md",
        "---\ntask: T-1\ncreated: 2026-10-20\nids: [R-1]\nby_source: {story: 0, feature: 0, assumption: 0, discussion: 0, ac: 1, derived: 0}\n"
        "confidence: high\n---\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
        "|---|---|---|---|---|---|---|---|\n| R-1 | First thing | ac | - | yes | AC1 | diff:src/a.py:10 | access |\n\n## Contradiction matrix\n")
    put(t / "work" / "requirements-readiness.json", json.dumps({"verdict": "ready", "open_questions": []}))
    return t


t = gt_story()
env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
art = ROOT / "qa-factory" / "artifacts" / "T-1"
shutil.rmtree(art, ignore_errors=True)
shutil.copytree(t, art)
sk = run_script("grounding_table.py", "--skeleton", "--task", "T-1", cwd=ROOT, env=env)
check_eq("F-C: the skeleton is written", sk.returncode, 0)
doc, problem = CP.PC.read_grounding(art)
row_id = doc.data["rows"][0]["id"]
GT.write_key(GT.table_path(art), "claims", [{"r": "R-4", "row": row_id, "requirement": "A.", "impact": "degraded", "before": "1", "before_ref": "diff:-src/a.py:11",
                                              "now": "2", "now_ref": "diff:src/a.py:11", "differs": "yes", "question": "raise",
                                              "ask": {"question": "Which?", "source_says": [{"quote": "q", "where": "w"}], "severity": "major", "owner_role": "po_ba"}}])
r5 = lambda: [f.rule for f in GT.check(art) if f.rule == "R5"]   # noqa: E731
check_eq("F-C: before the projection R5 is quiet", r5(), [])
res = CP.project(art)
check_eq("F-C: the projection wrote", (res.projected, [str(p) for p in res.problems]), (["R-4"], []))
check_eq("F-C: R5 now says the register changed since labelling", r5() != [], True)
ref = run_script("grounding_table.py", "--refresh", "--task", "T-1", cwd=ROOT, env=env)
check_eq("F-C: --refresh runs, and R5 is quiet again", (ref.returncode, r5()), (0, []))
shutil.rmtree(art, ignore_errors=True)
done(t)

# --- the CLI (axis 17 form 1) ------------------------------------------------------------------------------------------------------------
shutil.rmtree(art, ignore_errors=True)
shutil.copytree(story(dated, FIX / "requirements-readiness.json", yaml_of([claim(r="R-0")])).parent / "T-1", art)
out = run_script("claim_projector.py", "--task", "T-1", "--check", cwd=ROOT, env=env)
check_eq("CLI --check: findings exit 1, REJECT header with the count, one `- [claims ...]` line each", (out.returncode, out.stdout.splitlines()[0],
         out.stdout.splitlines()[1].startswith("- [claims claims[0]] ")), (1, "REJECT — 1 finding(s) in the grounding claims:", True))
put(art / "work" / "grounding.yaml", GOOD)
out = run_script("claim_projector.py", "--task", "T-1", cwd=ROOT, env=env)
check_eq("CLI project: exit 0, one line per R", (out.returncode, out.stdout.splitlines()[0]), (0, "projected R-28"))
out = run_script("claim_projector.py", "--task", "T-1", "--check", cwd=ROOT, env=env)
check_eq("CLI --check on a projected story: exit 0", out.returncode, 0)
shutil.rmtree(art, ignore_errors=True)
check_eq("BREAKS is exactly the set str.splitlines breaks on (the full code space, both directions)",
         {ch for ch in map(chr, range(0x110000)) if len(("a" + ch + "b").splitlines()) == 2}, set(CP.BREAKS))
cleanup(ROOT)
finish("test_claim_projector")
