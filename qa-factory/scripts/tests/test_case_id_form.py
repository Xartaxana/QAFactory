#!/usr/bin/env python3
"""B-013: the shape of a case id is the PROJECT's (`config.case_id_form`), not a regex in the contract.

TP1-13877's strategy writes `TP1-13877_TC_001`; the contract knew only `TC-\\d+`, so
`case_ids("TP1-13877_TC_001")` was `[]`, every manifest binding read "missing" for every case
and the automator spent about 35 calls reading factory code before it halted. Everything here asks
one of three questions of `case_forms.py` and of the contract wrappers on top of it: does a project
that never sets the key see EXACTLY what it saw before (K1), does a project that sets it see its own
ids whole and nothing else (K2-K4, K7, K9), and does a form that cannot be read fall back to the
default and say so instead of raising (K5, K8)? K6 asks it across time and across two projects in one
process. Keys K1-K9 are named in each check.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    check, check_eq, check_in, cleanup, finish, temp_dir, temp_project, use_project,
)
import case_forms as F  # noqa: E402
import contract as C  # noqa: E402
import hooklib  # noqa: E402
import readiness as R  # noqa: E402

PROJECT_FORM = "{ticket}_TC_{nnn}"
TICKET = "TP1-13877"
PROJECT_ID = f"{TICKET}_TC_001"
_DROP = object()
VALID_TEMPLATES = ("X{nnn}", "TC{nnn}", "{ticket}X{nnn}", "{ticket}.TC.{nnn}", "case_{nnn}_{ticket}",
                   "TC-{nnn}-{ticket}", "{nnn}x", "{ticket}_TC_{nnn}", "{ticket}_TC_{nnn}_v2")


def legacy_case_ids(value) -> list:
    """The contract's own reading before B-013, verbatim."""
    return list(dict.fromkeys(re.findall(r"TC-\d+", str(value or ""))))


def cfg_path(root: Path) -> Path:
    return root / "qa-factory" / "config.json"


def write_cfg(root: Path, value=_DROP, raw: str | None = None) -> None:
    """Rewrite the project's config with `case_id_form` = value (or without the key). The mtime is
    moved forward by hand: the contract's read cache is keyed by (path, mtime_ns, size), and two
    writes inside one clock tick with equal sizes would share a key on a fast machine."""
    path = cfg_path(root)
    before = path.stat().st_mtime_ns if path.exists() else 0
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if value is _DROP:
            cfg.pop("case_id_form", None)
        else:
            cfg["case_id_form"] = value
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    bumped = max(path.stat().st_mtime_ns, before + 5_000_000)
    os.utime(path, ns=(bumped, bumped))
    # the contract revalidates a resolution at most once per 2 s (case_config_reset's docstring): a
    # test that rewrites the config it then asks about says so, like every other process would by waiting
    C.case_config_reset()


def story_dir(root: Path, ticket: str = TICKET) -> Path:
    d = root / "qa-factory" / "artifacts" / ticket
    (d / "work").mkdir(parents=True, exist_ok=True)
    return d


def write_case(story: Path, area: str, case: str, name: str | None = None) -> Path:
    path = story / "work" / "test-cases" / area / (name or f"{case}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {case}\narea: {area}\nstatus: Draft\ntask: {story.name}\n---\n"
                    f"Requirements: R-1\nPlan row: TS-1\n# {case}\n", encoding="utf-8")
    return path


def corpus() -> list:
    big_id_text = " ".join(f"TC-{i}" for i in range(1, 10001))
    filler = "lorem ipsum dolor sit amet, consectetur adipiscing elit " * 2  # ~114 bytes
    big = "".join(f"{filler}TC-{i}\n" for i in range(1, 10001))
    return [
        "TC-001", "TC-001/TC-002/TC-003", "speakers/TC-001", "TC-012::test_x[eu]",
        "TC-012--x--y", "TC-012#3", "ATC-12", "TC-0123", "", None, 17, 0, False, True, 3.5,
        ["TC-1"], ("TC-1", "TC-2"), {"case": "TC-2"}, {}, [], b"TC-3",
        "tc-001", "TC-", "TC-A", "TC--1", "TC-1 TC-1 TC-2", "see TC-7, TC-8.", "TC-001TC-002",
        "XTC-5x", "R-1 covers TC-9", "TC-1\nTC-2\r\nTC-3", "TC-" + chr(0x661) + chr(0x662),
        "TP1-13877_TC_001", "TP1-13877-TC-001", "  TC-4  ", "\tTC-5\t",
        big_id_text, big,
    ]


def k1_differential() -> None:
    """K1: with no key the new reading equals the legacy one, value for value."""
    values = corpus()
    root = temp_project("qa-factory-caseform-k1-")
    try:
        story = story_dir(root)
        use_project(root)
        for label, anchor in (("process project", None), ("story folder", story)):
            bad = [repr(v)[:40] for v in values if C.case_ids(v, anchor) != legacy_case_ids(v)]
            check_eq(f"K1 differential over {len(values)} values via {label}", bad, [])
        # the same values through the pure module, no project at all
        bad = [repr(v)[:40] for v in values if F.ids_in(v, {}) != legacy_case_ids(v)]
        check_eq("K1 differential through case_forms with an empty config", bad, [])
        check_eq("K1 case_ids keeps its one-argument call", C.case_ids("TC-001/TC-002"), ["TC-001", "TC-002"])
        check("K1 an id inside a longer word is still read, as it always was",
              C.case_ids("ATC-12") == ["TC-12"])
        # a form that only restates the default is the default
        check_eq("K1 explicit TC-{nnn} is the default form only", F.forms({"case_id_form": "TC-{nnn}"}), ("TC-{nnn}",))
        check_eq("K1 explicit list of the default is the default form only",
                 F.forms({"case_id_form": ["TC-{nnn}", "TC-{nnn}"]}), ("TC-{nnn}",))
    finally:
        cleanup(root)


def k2_k3_project_form() -> None:
    root = temp_project("qa-factory-caseform-k2-")
    try:
        story = story_dir(root)
        write_cfg(root, PROJECT_FORM)
        use_project(root)
        for label, anchor in (("process project", None), ("story folder", story)):
            check_eq(f"K2 the project's own id is one id ({label})",
                     C.case_ids(PROJECT_ID, anchor), [PROJECT_ID])
            check_eq(f"K2 mixed text returns both forms in order ({label})",
                     C.case_ids(f"TC-002 then {PROJECT_ID} and TC-002 again, {TICKET}_TC_010", anchor),
                     ["TC-002", PROJECT_ID, f"{TICKET}_TC_010"])
            for label2, text in (("no number", f"{TICKET}_TC_"), ("underscore in the ticket", "TP1_13877_TC_001"),
                                 ("letters both sides", f"X{PROJECT_ID}x"), ("letter after", f"{PROJECT_ID}x"),
                                 ("lower-case letter before", f"x{PROJECT_ID}"), ("digit before", f"9{PROJECT_ID}"),
                                 ("lower-case ticket", "tp1-13877_TC_001"),
                                 ("wrong separator", f"{TICKET}-TC_001")):
                check_eq(f"K2 {label2} names no case ({label})", C.case_ids(text, anchor), [])
            check_eq(f"K2 a compound of project ids is read whole ({label})",
                     C.case_ids(f"{PROJECT_ID}/{TICKET}_TC_002/{TICKET}_TC_003", anchor),
                     [PROJECT_ID, f"{TICKET}_TC_002", f"{TICKET}_TC_003"])
            check_eq(f"K2 an id followed by a title keeps the id ({label})",
                     C.case_ids(f"{PROJECT_ID}-login.md", anchor), [PROJECT_ID])
            check_eq(f"K2 an instance id keeps its case ({label})",
                     C.case_ids(f"{PROJECT_ID}::test_x[eu]", anchor), [PROJECT_ID])
        check_eq("K2 the forms in force, configured first", C.case_id_forms(story), (PROJECT_FORM, "TC-{nnn}"))
        check_eq("K2 the ids are maximal: a longer number is one id",
                 C.case_ids(f"{TICKET}_TC_0123"), [f"{TICKET}_TC_0123"])
        check_eq("K2 ids are case-sensitive in text", C.case_ids(f"{TICKET}_tc_001"), [])

        # K3: containment. The default form inside a longer id must not split it.
        write_cfg(root, "{ticket}-TC-{nnn}")
        check_eq("K3 the ticket-prefixed id is exactly one id", C.case_ids(f"{TICKET}-TC-001"), [f"{TICKET}-TC-001"])
        check_eq("K3 in running text too", C.case_ids(f"see ({TICKET}-TC-001), and {TICKET}-TC-002."),
                 [f"{TICKET}-TC-001", f"{TICKET}-TC-002"])
        check_eq("K3 a bare TC id still reads beside it", C.case_ids(f"TC-001 {TICKET}-TC-002"),
                 ["TC-001", f"{TICKET}-TC-002"])
        check_eq("K3 the legacy reading had cut it to the inner TC id", legacy_case_ids(f"{TICKET}-TC-001"), ["TC-001"])
    finally:
        cleanup(root)


def k4_identity_helpers() -> None:
    root = temp_project("qa-factory-caseform-k4-")
    try:
        story = story_dir(root)
        write_cfg(root, PROJECT_FORM)
        use_project(root)
        for label, anchor in (("process project", None), ("story folder", story)):
            check_eq(f"K4 split_case_key reads a project id tail ({label})",
                     C.split_case_key(f"code-executor/{PROJECT_ID}", anchor), ("code-executor", PROJECT_ID))
            check_eq(f"K4 a bare project id splits to no area ({label})",
                     C.split_case_key(PROJECT_ID, anchor), ("", PROJECT_ID))
            compound = f"{PROJECT_ID}/{TICKET}_TC_002"
            check_eq(f"K4 a compound of two project ids comes back whole ({label})",
                     C.split_case_key(compound, anchor), ("", compound))
            check_eq(f"K4 case_key adds the area ({label})",
                     C.case_key(PROJECT_ID, "speakers", anchor), f"speakers/{PROJECT_ID}")
            check_eq(f"K4 case_key is idempotent ({label})",
                     C.case_key(f"speakers/{PROJECT_ID}", "other", anchor), f"speakers/{PROJECT_ID}")
            check_eq(f"K4 case_key leaves a compound alone ({label})",
                     C.case_key(compound, "speakers", anchor), compound)
            check(f"K4 a bare id matches any area ({label})",
                  C.case_matches(PROJECT_ID, PROJECT_ID, "speakers", artifacts=anchor))
            check(f"K4 an area-less reader finds an area's record ({label})",
                  C.case_matches(f"speakers/{PROJECT_ID}", PROJECT_ID, artifacts=anchor))
            check(f"K4 two areas are two cases ({label})",
                  not C.case_matches(f"speakers/{PROJECT_ID}", PROJECT_ID, "detail", artifacts=anchor))
            check(f"K4 a different number never matches ({label})",
                  not C.case_matches(f"speakers/{PROJECT_ID}", f"{TICKET}_TC_002", "speakers", artifacts=anchor))
            check_eq(f"K4 _case_keys names every project id in a cell ({label})",
                     C._case_keys(f"{PROJECT_ID}/{TICKET}_TC_002", "speakers", anchor),
                     [f"speakers/{PROJECT_ID}", f"speakers/{TICKET}_TC_002"])
        check_eq("K4 is_case_id: the whole value only", [C.is_case_id(v) for v in
                 (PROJECT_ID, "TC-001", f" {PROJECT_ID}", f"{PROJECT_ID} ", f"{PROJECT_ID}x", "", None, 5)],
                 [True, True, False, False, False, False, False, False])

        # case_area of a content-addressed version with no front matter: the id directory is layout
        version = root / "docs" / "cases" / "cases" / PROJECT_ID / "cv_x.md"
        version.parent.mkdir(parents=True)
        version.write_text("no front matter here\n", encoding="utf-8")
        check_eq("K4 case_area of .../cases/<project id>/cv_x.md is empty", C.case_area(version), "")
        write_cfg(root, _DROP)
        check_eq("K4 negative control: without the key the id directory reads as an area",
                 C.case_area(version), PROJECT_ID)
        write_cfg(root, PROJECT_FORM)

        # the case tree: file names, ids and the index
        art = story_dir(root, "TP1-13877")
        one = write_case(art, "speakers", PROJECT_ID)
        two = write_case(art, "speakers", "TC-002")
        three = write_case(art, "detail", f"{TICKET}_TC_003", name=f"{TICKET}_TC_003-open-detail.md")
        (art / "work" / "test-cases" / "speakers" / "critic-findings.md").write_text("x\n", encoding="utf-8")
        found = sorted(p.name for p in C.case_files(art))
        check_eq("K4 case_files finds project-form and TC files, not other markdown", found,
                 sorted([one.name, two.name, three.name]))
        check_eq("K4 case_id of a project-form file name", C.case_id(one), PROJECT_ID)
        check_eq("K4 case_id of a project-form file with a title", C.case_id(three), f"{TICKET}_TC_003")
        index = C.case_index(art)
        check_eq("K4 case_index keys are the three ids", sorted(index), sorted([PROJECT_ID, "TC-002", f"{TICKET}_TC_003"]))
        check_eq("K4 case_index reads the area of a project-form case", index[PROJECT_ID]["area"], "speakers")
        check("K4 the index resolves a bare project id", PROJECT_ID in index and f"speakers/{PROJECT_ID}" in index)
        write_cfg(root, _DROP)
        check_eq("K4 negative control: without the key only the TC case is a case",
                 sorted(p.name for p in C.case_files(art)), [two.name])
        write_cfg(root, PROJECT_FORM)
    finally:
        cleanup(root)


def invalid_templates() -> list:
    reserved = list("/:#,[]*?\"<>|") + [chr(92)]
    out = [("no {nnn}", "{ticket}_TC_"), ("two {nnn}", "TC_{nnn}_{nnn}"), ("{area} placeholder", "{area}_TC_{nnn}"),
           ("double hyphen", "TC--{nnn}"), ("double hyphen after the ticket", "{ticket}--TC-{nnn}"),
           ("whitespace", "TC {nnn}"), ("tab", "TC\t{nnn}"), ("two {ticket}", "{ticket}_{ticket}_{nnn}"),
           ("unclosed brace", "TC-{nnn"), ("stray brace", "TC}-{nnn}"), ("empty placeholder", "TC-{}{nnn}"),
           ("upper-case placeholder", "TC-{NNN}"), ("only a ticket", "{ticket}"),
           ("no literal: bare {nnn}", "{nnn}"), ("no literal: {ticket}{nnn}", "{ticket}{nnn}"),
           ("no alphanumeric literal: {ticket}-{nnn}", "{ticket}-{nnn}"),
           ("no alphanumeric literal: {ticket}_{nnn}", "{ticket}_{nnn}"), ("punctuation only", ".-_{nnn}"),
           ("{ticket} glued to {nnn}", "{ticket}{nnn}TC"), ("literal ends with a hyphen", "TC{nnn}-"),
           ("literal starts with a hyphen", "-TC{nnn}")]
    out += [(f"reserved {c!r}", f"TC{c}{{nnn}}") for c in reserved]
    return out


def k5_invalid_templates() -> None:
    for label, template in invalid_templates():
        cfg = {"case_id_form": template}
        check_eq(f"K5 {label}: fall back to the default form", F.forms(cfg), ("TC-{nnn}",))
        found = F.problems(cfg)
        check(f"K5 {label}: problems() names it", len(found) >= 1 and all(repr(template) in p for p in found), str(found))
        check(f"K5 {label}: and says what is expected",
              all("{nnn}" in p or "placeholder" in p or "--" in p or "separate" in p or "whitespace" in p
                  or "brace" in p or "more than once" in p or "letter or digit" in p for p in found), str(found))
        check_eq(f"K5 {label}: the default still reads", F.ids_in("TC-001 x", cfg), ["TC-001"])
    for label, value in (("integer", 5), ("dict", {}), ("float", 1.5), ("true", True), ("false", False),
                         ("empty dict of forms", {"a": 1})):
        cfg = {"case_id_form": value}
        check_eq(f"K5 top-level {label}: default only", F.forms(cfg), ("TC-{nnn}",))
        check(f"K5 top-level {label}: problems() says what type it wants",
              len(F.problems(cfg)) == 1 and "text or a list" in F.problems(cfg)[0], str(F.problems(cfg)))
    for label, entry in (("empty string", ""), ("blank string", "  "), ("integer", 5), ("dict", {}),
                         ("None", None), ("nested list", ["{ticket}_TC_{nnn}"])):
        cfg = {"case_id_form": [PROJECT_FORM, entry]}
        check_eq(f"K5 list entry {label}: the valid entry is kept", F.forms(cfg), (PROJECT_FORM, "TC-{nnn}"))
        check_eq(f"K5 list entry {label}: exactly one problem", len(F.problems(cfg)), 1)
        check_eq(f"K5 list entry {label}: the valid entry still reads",
                 F.ids_in(PROJECT_ID, cfg), [PROJECT_ID])
    cfg = {"case_id_form": [PROJECT_FORM, "bad"]}
    check_eq("K5 [valid, 'bad'] keeps the valid one", F.forms(cfg), (PROJECT_FORM, "TC-{nnn}"))
    check("K5 [valid, 'bad'] names 'bad' and only 'bad'",
          len(F.problems(cfg)) == 1 and "'bad'" in F.problems(cfg)[0], str(F.problems(cfg)))
    cfg = {"case_id_form": ["bad", "TC--{nnn}", "{area}"]}
    check_eq("K5 several invalid entries give one problem each or more", len(F.problems(cfg)) >= 3, True)
    check_eq("K5 all invalid: default only", F.forms(cfg), ("TC-{nnn}",))
    both = F.problems({"case_id_form": "T C--{nnn}"})
    check("K5 one entry with two faults names both", any("whitespace" in p for p in both)
          and any("--" in p for p in both), str(both))
    # the edge behaviour: absent/""/null/[]/junk config is the default and never a problem or a raise
    for label, cfg in (("no key", {}), ("empty string", {"case_id_form": ""}), ("blank string", {"case_id_form": "   "}),
                       ("null", {"case_id_form": None}), ("empty list", {"case_id_form": []}),
                       ("config is None", None), ("config is a list", []), ("config is text", "x"), ("config is int", 5)):
        check_eq(f"K5 {label}: default form only", F.forms(cfg), ("TC-{nnn}",))
        check_eq(f"K5 {label}: no problem to report", F.problems(cfg), [])
        check_eq(f"K5 {label}: ids_in still works", F.ids_in("a TC-1 b", cfg), ["TC-1"])
    # duplicates and order
    cfg = {"case_id_form": ["{ticket}-TC-{nnn}", PROJECT_FORM, "{ticket}-TC-{nnn}", "TC-{nnn}"]}
    check_eq("K5 configured forms keep their order, repeats and the default dropped",
             F.forms(cfg), ("{ticket}-TC-{nnn}", PROJECT_FORM, "TC-{nnn}"))
    # valid but unusual shapes are accepted: the contract is the grammar, not a taste
    for template in VALID_TEMPLATES:
        check_eq(f"K5 {template!r} is a valid form", F.problems({"case_id_form": template}), [])
    check_in("K5 the glued-{ticket}{nnn} reason names the fix", "put literal text between them",
             " ".join(F.problems({"case_id_form": "{ticket}{nnn}TC"})))
    check_in("K5 the hyphen reason names the fix", "end the literal text with a letter or digit",
             " ".join(F.problems({"case_id_form": "TC{nnn}-"})))
    # F1: maximal means the longest id of any form, in whichever order the config lists them
    short, long_ = "{ticket}_TC_{nnn}", "{ticket}_TC_{nnn}_v2"
    for label, order in (("short first", [short, long_]), ("long first", [long_, short])):
        cfg = {"case_id_form": order}
        check_eq(f"F1 {label}: the long id is one id", F.ids_in("AB-1_TC_1_v2", cfg), ["AB-1_TC_1_v2"])
        check_eq(f"F1 {label}: is_id agrees", F.is_id("AB-1_TC_1_v2", cfg), True)
        check_eq(f"F1 {label}: both ids in running text, each read whole",
                 F.ids_in("AB-1_TC_1 then AB-1_TC_2_v2, TC-7", cfg), ["AB-1_TC_1", "AB-1_TC_2_v2", "TC-7"])
        check_eq(f"F1 {label}: through the contract too", F.ids_in("x AB-1_TC_1_v2", cfg), ["AB-1_TC_1_v2"])
    # the instance separator is not swallowed by a hyphen-free literal
    check_eq("F1 an instance separator after an id stays outside it",
             F.ids_in("TC1---x", {"case_id_form": "TC{nnn}"}), ["TC1"])
    check_in("K5 the no-literal reason is plain", "add literal text", " ".join(F.problems({"case_id_form": "{nnn}"})))
    check_eq("K5 a bare {nnn} falls back: no phantom ids from bare numbers",
             F.ids_in("12 and 345", {"case_id_form": "{nnn}"}), [])


def k5_pure_module() -> None:
    check_eq("K5 is_id on a non-string is False, never a raise", [F.is_id(v, {}) for v in (None, 5, [], b"TC-1")],
             [False] * 4)
    check_eq("K5 ids_in is maximal and in order, once each",
             F.ids_in("TC-12 TC-1 TC-12 TC-123", {}), ["TC-12", "TC-1", "TC-123"])
    check_eq("K5 example under the default", F.example("TP1-13797", {}), "TC-001")
    cfg = {"case_id_form": PROJECT_FORM}
    check_eq("K5 example under the project form", F.example("TP1-13797", cfg), "TP1-13797_TC_001")
    check_eq("K5 example numbers", F.example("TP1-13797", cfg, 12), "TP1-13797_TC_012")
    check_eq("K5 example is itself an id", F.is_id(F.example("TP1-13797", cfg, 7), cfg), True)
    check_eq("K5 example with no ticket stays a visible placeholder", F.example(None, cfg), "<TICKET>_TC_001")
    check_eq("K5 example with a bad ticket stays a placeholder", F.example("not a ticket", cfg), "<TICKET>_TC_001")
    check_eq("K5 example with a bad number", F.example("TP1-13797", cfg, "x"), "TP1-13797_TC_001")
    # a hostile 1 MB text must not stall a guarded form: a long run of capitals with no hyphen
    hostile = ("A1" * 500_000) + " " + ("A" * 1000 + "-") * 500
    check_eq("K5 a long capital run is read in one pass and names nothing", F.ids_in(hostile, cfg), [])


def k6_temporal_and_two_projects() -> None:
    root = temp_project("qa-factory-caseform-k6a-")
    other = temp_project("qa-factory-caseform-k6b-")
    plain = temp_dir("qa-factory-caseform-k6c-")
    try:
        story, story_b = story_dir(root), story_dir(other, "PROJ-1")
        use_project(root)
        mixed = f"{PROJECT_ID} TC-001"
        check_eq("K6 before the key exists: TC only", C.case_ids(mixed, story), ["TC-001"])
        check_eq("K6 before the key exists (process project): TC only", C.case_ids(mixed), ["TC-001"])
        # a plain rewrite, no timestamp help: the size differs, which is what a person's edit does
        cfg_path(root).write_text(cfg_path(root).read_text(encoding="utf-8").replace(
            '"case_id_form": ""', f'"case_id_form": "{PROJECT_FORM}"'), encoding="utf-8")
        C.case_config_reset()  # the 2 s window itself is proven with an injected clock in test_case_id_form_sites.py
        check_eq("K6 after the key is written the next call reads both", C.case_ids(mixed, story), [PROJECT_ID, "TC-001"])
        check_eq("K6 and so does the process-project call", C.case_ids(mixed), [PROJECT_ID, "TC-001"])
        check_eq("K6 stored ids are never rewritten: the TC id reads the same", C.case_ids("TC-001", story), ["TC-001"])
        write_cfg(root, "")
        check_eq("K6 clearing the key drops the form again", C.case_ids(mixed, story), ["TC-001"])

        # two projects, two forms, one process: each story sees its own project
        write_cfg(root, PROJECT_FORM)
        write_cfg(other, "{ticket}-TC-{nnn}")
        text = f"PROJ-1_TC_001 PROJ-1-TC-001 {PROJECT_ID}"
        check_eq("K6 project A reads its own form", C.case_ids(text, story),
                 ["PROJ-1_TC_001", "TC-001", PROJECT_ID])
        check_eq("K6 project B reads its own form", C.case_ids(text, story_b), ["PROJ-1-TC-001"])
        check_eq("K6 project A again after B", C.case_ids(text, story), ["PROJ-1_TC_001", "TC-001", PROJECT_ID])
        check_eq("K6 the forms of each", (C.case_id_forms(story), C.case_id_forms(story_b)),
                 ((PROJECT_FORM, "TC-{nnn}"), ("{ticket}-TC-{nnn}", "TC-{nnn}")))
        case_b = write_case(story_b, "a", "PROJ-1-TC-001")
        check_eq("K6 a case file is named by its own project's form while the process stands in A",
                 C.case_id(case_b), "PROJ-1-TC-001")
        idx_b = C.case_index(story_b)
        check_eq("K6 case_index of B is keyed by B's form", sorted(idx_b), ["PROJ-1-TC-001"])
        check("K6 and its area-qualified lookups use B's form too (A's would read it as no case)",
              "a/PROJ-1-TC-001" in idx_b and idx_b["a/PROJ-1-TC-001"]["area"] == "a")

        # the config is read at most once per (path, mtime_ns, size)
        reads = []
        original = Path.read_text

        def counting(self, *args, **kwargs):
            if self.name == "config.json":
                reads.append(str(self))
            return original(self, *args, **kwargs)

        def count_reads(times: int) -> int:
            del reads[:]
            Path.read_text = counting
            try:
                for _ in range(times):
                    C.case_ids(mixed, story)
                    C.is_case_id(PROJECT_ID, story)
            finally:
                Path.read_text = original
            return len(reads)

        write_cfg(root, PROJECT_FORM)  # a fresh (path, mtime_ns, size)
        check_eq("K6 200 calls on one unchanged config read it exactly once", count_reads(100), 1)
        write_cfg(root, "{ticket}-TC-{nnn}")
        check_eq("K6 one rewrite is one more read", count_reads(50), 1)
        check_eq("K6 and then none", count_reads(50), 0)
        write_cfg(root, PROJECT_FORM)

        # what cannot be read is the default, never a raise
        for label, raw in (("broken JSON", "{not json"), ("a JSON list", "[]"), ("a JSON string", '"x"'),
                           ("empty file", ""), ("null", "null")):
            write_cfg(root, raw=raw)
            check_eq(f"K6 config is {label}: default only", C.case_ids(f"{PROJECT_ID} TC-1", story), ["TC-1"])
            check_eq(f"K6 config is {label}: forms", C.case_id_forms(story), ("TC-{nnn}",))
            check_eq(f"K6 config is {label}: is_case_file_name", C.is_case_file_name(f"{PROJECT_ID}.md", story), False)
        cfg_path(root).unlink()
        C.case_config_reset()
        check_eq("K6 no config at all: default only", C.case_ids(f"{PROJECT_ID} TC-1", story), ["TC-1"])
        check_eq("K6 no config at all (process project): default only", C.case_ids(f"{PROJECT_ID} TC-1"), ["TC-1"])
        check_eq("K6 no project anywhere: default only",
                 C.case_ids(f"{PROJECT_ID} TC-1", plain / "somewhere" / "deep"), ["TC-1"])

        # out of any project: the process is pinned to a directory that carries no qa-factory/config.json
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(plain)
            check_eq("K6 outside a project: default only", C.case_ids(f"{PROJECT_ID} TC-1"), ["TC-1"])
            check_eq("K6 outside a project: the default example", C.case_id_example(TICKET), "TC-001")
    finally:
        for d in (root, other, plain):
            cleanup(d)


def k7_file_names() -> None:
    root = temp_project("qa-factory-caseform-k7-")
    try:
        story = story_dir(root)
        use_project(root)
        default_true = ("TC-001.md", "tc-001.md", "TC-001-login.md", "TC-0123.md", "TC-001.MD", "TC-001_login.md",
                        "TC-7 login.md", "Tc-9.Md")
        always_false = ("critic-findings.md", f"{PROJECT_ID}.json", "cv_ab.md", "TC-001.txt", "TC-001", ".md", "",
                        "TC-001a.md", "TC-.md", "notes-TC-001.md", "XTC-001.md", "TC-001.md.bak", None)
        project_true = (f"{PROJECT_ID}.md", f"{PROJECT_ID}-login.md", f"{TICKET.lower()}_tc_001.md",
                        f"{TICKET}_tc_001.md", f"{TICKET}_TC_0123.md")
        project_false = (f"{PROJECT_ID}x.md", f"9{PROJECT_ID}.md", f"{TICKET}_TC_.md", "TP1_13877_TC_001.md",
                         f"{PROJECT_ID}.json")
        for label, key in (("no key", _DROP), ("key", PROJECT_FORM)):
            write_cfg(root, key)
            for anchor in (None, story):
                for name in default_true:
                    check(f"K7 {label}: {name!r} is a case file name", C.is_case_file_name(name, anchor))
                for name in always_false:
                    check(f"K7 {label}: {name!r} is not", not C.is_case_file_name(name, anchor))
            for name in project_true:
                check(f"K7 {label}: {name!r} is a case file name only with the key",
                      C.is_case_file_name(name, story) == (key is not _DROP))
            for name in project_false:
                check(f"K7 {label}: {name!r} is not", not C.is_case_file_name(name, story))
        check("K7 a path is judged by its last component", F.is_case_file_name("a/b/TC-001.md", {})
              and F.is_case_file_name("a" + chr(92) + "TC-001.md", {}))
    finally:
        cleanup(root)


def k8_readiness() -> None:
    absent = R.check_case_id_form({})
    check_eq("K8 absent: ok", absent["status"], "ok")
    check_eq("K8 absent: the factory's own", absent["owner"], "factory")
    check_eq("K8 absent: says the default", absent["note"], "default TC-{nnn}")
    check("K8 absent: carries no remedy (nothing to do)", "remedy" not in absent)
    for label, cfg in (("empty string", {"case_id_form": ""}), ("null", {"case_id_form": None}),
                       ("empty list", {"case_id_form": []})):
        check_eq(f"K8 {label}: same answer as absent", R.check_case_id_form(cfg), absent)
    valid = R.check_case_id_form({"case_id_form": PROJECT_FORM})
    check_eq("K8 valid: ok", valid["status"], "ok")
    check_eq("K8 valid: the factory's own", valid["owner"], "factory")
    check_in("K8 valid: names the form", PROJECT_FORM, valid["note"])
    check_in("K8 valid: and that the default is read too", "TC-{nnn}", valid["note"])
    check_eq("K8 a list of forms: ok", R.check_case_id_form({"case_id_form": [PROJECT_FORM, "{ticket}-TC-{nnn}"]})["status"], "ok")
    invalid = R.check_case_id_form({"case_id_form": "{ticket}_TC_"})
    check_eq("K8 invalid: missing", invalid["status"], "missing")
    check_eq("K8 invalid: the person's to fix", invalid["owner"], "user")
    check_in("K8 invalid: names the entry", "{ticket}_TC_", invalid["note"])
    check_in("K8 invalid: names the problem", "{nnn}", invalid["note"])
    check_in("K8 invalid: names the door", "Fix or clear config.case_id_form", invalid["note"])
    check_in("K8 invalid: says what is used meanwhile", "until then the factory uses TC-{nnn}", invalid["note"])
    check("K8 invalid: has a remedy a person can carry out",
          invalid["remedy"]["kind"] == "human_step" and invalid["remedy"]["steps"], str(invalid.get("remedy")))
    partial = R.check_case_id_form({"case_id_form": [PROJECT_FORM, "bad"]})
    check_eq("K8 one valid and one invalid entry: missing", partial["status"], "missing")
    check_in("K8 partial: names the bad entry", "'bad'", partial["note"])
    check_in("K8 partial: and says the valid one is in use", f"until then the factory uses {PROJECT_FORM}, TC-{{nnn}}", partial["note"])
    for cfg in (None, [], "x", 5, {"case_id_form": 5}, {"case_id_form": {}}):
        try:
            out = R.check_case_id_form(cfg)
            check(f"K8 {cfg!r}: an answer, never a raise", out["status"] in ("ok", "missing"))
        except Exception as exc:  # noqa: BLE001
            check(f"K8 {cfg!r}: an answer, never a raise", False, repr(exc))
    check("K8 case_id_form is an optional top-level key", "case_id_form" in R.OPTIONAL_TOP_KEYS)
    template = json.loads((Path(R.PLUGIN_ROOT) / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    check_eq("K8 the template carries the key, empty", template.get("case_id_form"), "")
    check_in("K8 and its note says empty means TC-{nnn}", "empty means TC-{nnn}", template.get("case_id_form_note", ""))
    check_in("K8 and the grammar", "{nnn} is the case number", template.get("case_id_form_note", ""))
    check("K8 cases_root_note no longer says the store holds TC-NNN.md",
          "TC-NNN.md" not in template["cases_root_note"] and "<case id>.md" in template["cases_root_note"])
    check("K8 a template key that is optional is not a missing key", "case_id_form" not in R.template_top_keys())


def k9_non_ascii_literal() -> None:
    u = chr(0xDC)
    root = temp_project("qa-factory-caseform-k9-")
    try:
        story = story_dir(root)
        template = f"{u}C-{{nnn}}"
        write_cfg(root, template)
        use_project(root)
        for anchor in (None, story):
            check_eq("K9 a literal outside ASCII is recognised", C.case_ids(f"a {u}C-12 b", anchor), [f"{u}C-12"])
        check_eq("K9 with the ticket form too", F.ids_in(f"{TICKET}{u}001", {"case_id_form": "{ticket}" + u + "{nnn}"}),
                 [f"{TICKET}{u}001"])
        check_eq("K9 the config round-trips through JSON", C.case_id_forms(story), (template, "TC-{nnn}"))
        check("K9 as a file name", C.is_case_file_name(f"{u}C-12.md", story))
        check_eq("K9 as an example", C.case_id_example(TICKET, story), f"{u}C-001")
        check_eq("K9 the default still reads beside it", C.case_ids(f"{u}C-1 TC-2", story), [f"{u}C-1", "TC-2"])
        check_eq("K9 no problem reported", F.problems({"case_id_form": template}), [])
        check_eq("K9 readiness accepts it", R.check_case_id_form({"case_id_form": template})["status"], "ok")
    finally:
        cleanup(root)


def k10_scope_keys() -> None:
    """t-845 C3-12: `scope_keys(cell)` is the keys a window may use for a manifest cell - the exact text always, plus
    each bare id when the cell is a compound of ids only. `case_ids` (the ledger's and `check_result_rows`'s reader) is
    a different question and does not move."""
    default = {}
    for label, cell, want in (
            ("bare", "TC-009", ["TC-009"]),
            ("area", "speakers/TC-009", ["speakers/TC-009"]),
            ("compound", "TC-001/TC-002/TC-003", ["TC-001/TC-002/TC-003", "TC-001", "TC-002", "TC-003"]),
            ("area with two slashes", "a/b/TC-1", ["a/b/TC-1"]),
            ("a repeated id in a compound", "TC-001/TC-001", ["TC-001/TC-001", "TC-001"]),
            ("a trailing slash after an area", "speakers/", ["speakers/"]),
            ("a trailing slash after an id", "TC-001/", ["TC-001/"]),
            ("a compound with a part that is no id", "TC-001/notes", ["TC-001/notes"]),
            ("surrounding whitespace is trimmed", "  speakers/TC-009 ", ["speakers/TC-009"]),
            ("empty", "", []), ("only whitespace", "  ", []), ("None", None, [])):
        check_eq(f"K10 scope_keys: {label}", C.scope_keys(cell, cfg=default), want)
    check_eq("K10 case_ids is unchanged: an area cell still reads as its bare id", C.case_ids("speakers/TC-009", cfg=default),
             ["TC-009"])
    check_eq("K10 case_ids is unchanged: a compound still reads as its ids", C.case_ids("TC-001/TC-002", cfg=default),
             ["TC-001", "TC-002"])
    compound = f"{PROJECT_ID}/{TICKET}_TC_002"
    check_eq("K10 outside a project (default form only) a compound of project ids is an AREA key: exact only",
             C.scope_keys(compound, cfg=default), [compound])
    root = temp_project("qa-factory-caseform-k10-")
    try:
        story = story_dir(root)
        write_cfg(root, PROJECT_FORM)
        use_project(root)
        for label, kwargs in (("cfg from case_config(story)", {"cfg": C.case_config(story)}), ("artifacts=story", {"artifacts": story}),
                              ("the process's own project", {})):
            check_eq(f"K10 project form: a bare project id ({label})", C.scope_keys(PROJECT_ID, **kwargs), [PROJECT_ID])
            check_eq(f"K10 project form: an area key ({label})", C.scope_keys(f"speakers/{PROJECT_ID}", **kwargs),
                     [f"speakers/{PROJECT_ID}"])
            check_eq(f"K10 project form: a compound of project ids ({label})", C.scope_keys(compound, **kwargs),
                     [compound, PROJECT_ID, f"{TICKET}_TC_002"])
            check_eq(f"K10 project form: a compound of both forms ({label})", C.scope_keys(f"TC-001/{PROJECT_ID}", **kwargs),
                     [f"TC-001/{PROJECT_ID}", "TC-001", PROJECT_ID])
    finally:
        cleanup(root)


def main() -> None:
    k1_differential()
    k2_k3_project_form()
    k4_identity_helpers()
    k5_invalid_templates()
    k5_pure_module()
    k6_temporal_and_two_projects()
    k7_file_names()
    k8_readiness()
    k9_non_ascii_literal()
    k10_scope_keys()
    finish("test_case_id_form")


if __name__ == "__main__":
    main()
