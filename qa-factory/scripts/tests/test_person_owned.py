#!/usr/bin/env python3
"""RN1-9 Part A: `person_owned.py`, the one reader of `references/person-owned.json` (E-1..E-4, E-11).

A lint over data and a token check - not a detector of a role's or person's wording (FR-12 n/a). Keys: the E-rows of the
spec; negative controls on temp copies of the file; every ask_person row of `story_run.KNOWN_REFUSALS` has a code route.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import person_owned as PO  # noqa: E402

PACKAGE = SCRIPTS.parent
SHIPPED = PACKAGE / "references" / "person-owned.json"


def run_check(file=None):
    cmd = [sys.executable, "-B", str(SCRIPTS / "person_owned.py"), "--check"] + (["--file", str(file)] if file else [])
    return subprocess.run(cmd, capture_output=True, text=True)


def e1_why_absent_or_not_a_value() -> None:
    for bad in (None, "", "   ", 7, ["access"], {"id": "access"}):
        check(f"E-1 why_person {bad!r} is refused", PO.question_rule(bad, "the probe record") != "")
    check_eq("E-1 a class with a reading passes", PO.question_rule("access", "the probe record"), "")


def e2_token_not_phrase() -> None:
    check_eq("E-2 ' Access ' is the class access", PO.normalize(" Access "), "access")
    check_eq("E-2 ' Access ' passes", PO.question_rule(" Access ", "x"), "")
    check_eq("E-2 non-str normalizes to empty", PO.normalize(5), "")
    for bad in ("access, money", chr(0x430) + "ccess", "access_", "access money"):
        rule = PO.question_rule(bad, "x")
        check(f"E-2b {bad!r} is refused", rule != "")
    check_in("E-2b the sentence lists the ids", "`money`", PO.question_rule("access, money", "x"))


def e2c_checked() -> None:
    for bad in ("", "  \n ", None, 3, ["x"]):
        check(f"E-2c checked {bad!r} is refused", PO.question_rule("access", bad) != "")
    check_in("E-2c the refusal names `checked`", "`checked` is empty", PO.question_rule("access", ""))
    check_eq("E-2c any non-empty string passes", PO.question_rule("access", "a"), "")


def e2d_checked_limit() -> None:
    check_eq("E-2d 300 chars stay whole", PO.checked_text("a" * 300), "a" * 300)
    cut = PO.checked_text("a" * 301)
    check_eq("E-2d 301 chars: 300 with the cut mark counted", (len(cut), cut[-1]), (300, "…"))
    check_eq("E-2d newlines fold to one line", PO.checked_text("one\n two\r\n\tthree"), "one two three")
    check_eq("E-2d None is empty", PO.checked_text(None), "")


def e3_unreadable_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        good = json.loads(SHIPPED.read_text(encoding="utf-8"))
        cases = {
            "absent": None,
            "not_json": "{not json",
            "empty_classes": dict(good, classes=[]),
            # canon part 2 (t-769, mutant rn1-9-a-m3): with no code route left, the empty list is the ONLY thing wrong - a `load`
            # that accepted `classes: []` would pass this file, where `empty_classes` above is also refused by its route naming a class
            "empty_classes_alone": dict(good, classes=[], code_routes={}),
            "duplicate_id": dict(good, classes=good["classes"] + [good["classes"][0]]),
            "bad_route": dict(good, code_routes={"story_budget": "nope"}),
            "bad_id": dict(good, classes=[{"id": "Bad Id", "says": "x"}]),
            "array": [1, 2],
        }
        for name, body in cases.items():
            path = tmp / f"{name}.json"
            if isinstance(body, str):
                path.write_text(body, encoding="utf-8")
            elif body is not None:
                path.write_text(json.dumps(body), encoding="utf-8")
            done = run_check(path)
            check_eq(f"E-3 --check on {name} exits 2", done.returncode, 2)
            check(f"E-3 --check on {name} names a reason", "person-owned:" in done.stdout and len(done.stdout.strip()) > 20)
    done = run_check()
    check_eq("E-3 --check on the shipped file is green", (done.returncode, "ok" in done.stdout), (0, True))
    real = PO.load
    try:
        def broken(path=None):
            raise PO.PersonOwnedUnreadable("test: unreadable")
        PO.load = broken
        check_eq("E-3 unreadable file: the question goes (rule is empty)", PO.question_rule("nope", ""), "")
        check_eq("E-3 unreadable file: status names the cause", PO.status(), "unread: test: unreadable")
        check_eq("E-3 unreadable file: no code route", PO.code_route("executor"), None)
    finally:
        PO.load = real
    check_eq("E-3 readable file: status ok", PO.status(), "ok")


def e4_closed_variety() -> None:
    rule = PO.question_rule("nope", "x")
    check_in("E-4 `nope` is refused naming the file", "references/person-owned.json", rule)
    check_in("E-4 the conductor door is carried", PO.CONDUCTOR_DOOR, rule)
    wrule = PO.class_rule("nope", "x", PO.WAIVER_DOOR)
    check_in("E-4 waiver door names --why-person <id>", "--why-person <id>", wrule)
    check_not_in("E-4 waiver door does not tell to set `why_person` to", "`why_person` set to", wrule)
    check_eq("E-4 ids are the file's, in order", PO.class_ids()[:2], ("access", "requirement_intent"))
    check_eq("E-4 code route", PO.code_route("story_budget"), "money")
    check_eq("E-4 absent route", PO.code_route("no_such_row"), None)


def known_refusals_have_routes() -> None:
    import story_run
    rows = [row for row in story_run.KNOWN_REFUSALS if row[2] == "ask_person"]
    check("KNOWN_REFUSALS has ask_person rows (positive control)", len(rows) >= 3)
    for row in rows:
        check(f"ask_person row {row[0]} has a code route", PO.code_route(row[0]) is not None)


def e11_share() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        empty = PO.share(root)
        check_eq("E-11 no sources: zeros", (empty["questions"], empty["classified"], empty["unclassified"], empty["words"]),
                 (0, 0, 0, {"classified": 0, "unclassified": 0}))
        check_eq("E-11 needless is unknown, not a number", empty["needless"], "unknown")
        (root / "state").mkdir()
        rows = [{"source": "conductor", "why_person": "access", "checked": "x", "class_check": "ok"},
                {"source": "fallback"},
                {"source": "code", "why_person": None, "class_check": "unread: gone"},
                {"source": "conductor", "why_person": "nope"}]
        (root / "state" / "driver-questions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
        (root / "pipeline.json").write_text(json.dumps({
            "stage_overrides": [{"stage": "S5"}, {"stage": "S6", "why_person": "gate_word"}],
            "gate_waivers": [{"gate": "A", "why_person": "Access"}],
            "remarks": "not a list"}), encoding="utf-8")
        got = PO.share(root)
        check_eq("E-11 questions / classified / unclassified", (got["questions"], got["classified"], got["unclassified"]), (4, 1, 3))
        check_eq("E-11 by_source", got["by_source"], {"conductor": 2, "fallback": 1, "code": 1, "delivery": 0})
        check_eq("E-11 by_class", got["by_class"], {"access": 1})
        check_eq("E-11 class_check_unread", got["class_check_unread"], 1)
        check_eq("E-11 words: old entries are unclassified", got["words"], {"classified": 2, "unclassified": 1})
        check_eq("E-11 needless is still unknown", got["needless"], "unknown")
        done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "person_owned.py"), "--share", "--task-root", str(root), "--json"],
                              capture_output=True, text=True)
        check_eq("E-11 CLI --share --json round trip", json.loads(done.stdout), got)


def k2_share_roads() -> None:
    """B-1: a word the DRIVER recorded (`by` = `driver`) is never counted on the interactive counter (the critic's scratch shape)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pipeline.json").write_text(json.dumps({
            "stage_overrides": [{"stage": "S5", "by": "driver", "at": "T"}, {"stage": "S6", "by": "driver", "why_person": "access"}],
            "remarks": [{"stage": "S1", "text": "x", "by": "human", "why_person": "risk"}]}), encoding="utf-8")
        got = PO.share(root)
        check_eq("K2 two driver-shaped words (one classed): interactive `unclassified` is 0", got["words"], {"classified": 1, "unclassified": 0})
        check_eq("K2 ...they sit on the driver counter", got["driver_words"], {"classified": 1, "unclassified": 1})
        (root / "pipeline.json").write_text(json.dumps({"stage_overrides": [{"stage": "S5", "by": "driver"}, {"stage": "S6", "by": "driver"}]}),
                                            encoding="utf-8")
        got = PO.share(root)
        check_eq("K2 the scratch shape: two driver words, no class -> `unclassified: 0` on the interactive counter",
                 (got["words"]["unclassified"], got["driver_words"]["unclassified"]), (0, 2))
        (root / "pipeline.json").write_text(json.dumps({"stage_overrides": [{"stage": "S5", "by": "human"}]}), encoding="utf-8")
        check_eq("K2 negative control: the same word by `human` IS interactive-unclassified", PO.share(root)["words"]["unclassified"], 1)


def m6_as_class() -> None:
    check_eq("m-6 as_class: a class, normalized", PO.as_class(" Money "), "money")
    for bad in ("nope", "", None, 5, ["access"], "access, money"):
        check_eq(f"m-6 as_class({bad!r}) is empty", PO.as_class(bad), "")
    real = PO.load
    try:
        def broken(path=None):
            raise PO.PersonOwnedUnreadable("test: unreadable")
        PO.load = broken
        check_eq("m-6 as_class: an unreadable file classifies nothing", PO.as_class("access"), "")
    finally:
        PO.load = real
    check("m-6 the three copies are gone: no `_is_class`, no `in ids` test in person_owned.py",
          "_is_class" not in (SCRIPTS / "person_owned.py").read_text(encoding="utf-8") and not hasattr(PO, "_is_class"))


def one_reader() -> None:
    def holders():
        found = []
        for base in (SCRIPTS, PACKAGE / "hooks"):
            for path in base.rglob("*.py"):
                if "tests" in path.relative_to(base).parts:
                    continue
                if "person-owned.json" in path.read_text(encoding="utf-8", errors="replace"):
                    found.append(path.name)
        return found
    found = holders()
    check("one reader: the walk finds person_owned.py (positive control)", "person_owned.py" in found)
    check_eq("one reader: only person_owned.py names the file", sorted(set(found)), ["person_owned.py"])


def main() -> None:
    for scenario in (e1_why_absent_or_not_a_value, e2_token_not_phrase, e2c_checked, e2d_checked_limit, e3_unreadable_file,
                     e4_closed_variety, known_refusals_have_routes, e11_share, k2_share_roads, m6_as_class, one_reader):
        scenario()
    harness.finish("person_owned")


if __name__ == "__main__":
    main()
