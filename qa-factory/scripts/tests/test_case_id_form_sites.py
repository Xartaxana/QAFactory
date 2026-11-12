#!/usr/bin/env python3
"""B-013 D2: every site that names a case id goes through the project's id form (`config.case_id_form`).

D1 built the recogniser (`case_forms.py`, the contract wrappers); D2 is the sweep: the eighteen scripts
that carried their own `TC-<n>` pattern or `TC-*.md` glob now ask the helper. This file proves it on a
trimmed copy of the live run that exposed the defect (fixtures/case-id-form-13877/: TP1-13877, three
cases named `TP1-13877_TC_001..003`), always in pairs: WITH `case_id_form` the site sees the project's
cases, WITHOUT it (the negative control) it sees what the old code saw - nothing. Keys K10-K15 and the
positional invariants I1-I5 of docs/tasks/specs/t-015-B013.md are named in each check; PERF is the Lead's
addition after critic t-027 (the config is resolved once per story in the quadratic loops).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import traceback
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project,
)
import ast  # noqa: E402
import artifact_producer  # noqa: E402
import case_versions  # noqa: E402
import contract as C  # noqa: E402
import critic_rollcall  # noqa: E402
import exit_gate  # noqa: E402
import finalize_task  # noqa: E402
import gate_brief  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import handoff_check  # noqa: E402
import judge_cases  # noqa: E402
import ledger  # noqa: E402
import manifest_from_tests  # noqa: E402
import manifest_view  # noqa: E402
import migrate_artifacts  # noqa: E402
import render_case_appendix  # noqa: E402
import s5_precheck  # noqa: E402
import traceability  # noqa: E402
import validate_artifacts as va  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "case-id-form-13877"
SCRIPTS = Path(__file__).resolve().parents[1]
TICKET = "TP1-13877"
FORM = "{ticket}_TC_{nnn}"
IDS = [f"{TICKET}_TC_00{n}" for n in (1, 2, 3)]
AREA = "code-executor"
_DROP = object()


def set_key(root: Path, value=_DROP, reset: bool = True, **extra) -> None:
    """Rewrite the project's config with `case_id_form` = value (or without the key), and any other
    top-level keys. The mtime is moved forward by hand: the contract reads the config once per
    (path, mtime_ns, size), and two writes inside one clock tick would share a key."""
    path = root / "qa-factory" / "config.json"
    before = path.stat().st_mtime_ns
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.pop("case_id_form", None)
    if value is not _DROP:
        cfg["case_id_form"] = value
    cfg.update(extra)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    bumped = max(path.stat().st_mtime_ns, before + 5_000_000)
    os.utime(path, ns=(bumped, bumped))
    if reset:
        C.case_config_reset()  # the contract revalidates a resolution once per 2 s; see config_window()


def install(root: Path) -> Path:
    """The fixture story inside a throwaway project: <root>/qa-factory/artifacts/TP1-13877/."""
    story = root / "qa-factory" / "artifacts" / TICKET
    shutil.copytree(FIXTURE, story)
    return story


def project(key=_DROP, **extra):
    root = temp_project("qa-factory-caseform-sites-")
    set_key(root, key, **extra)
    use_project(root)
    return root


def refusal(fn, event, cfg):
    """The blocking text of a guard check, or None when it lets the call through."""
    return G._blocked(fn, event, cfg)


def write_ev(path):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


# --- K10 ---------------------------------------------------------------------------------------

def k10_fixture() -> None:
    cases = sorted(p.name for p in (FIXTURE / "work" / "test-cases" / AREA).glob("*.md"))
    check_eq("K10 the fixture carries the three case files", cases, [f"{i}.md" for i in IDS])
    check_eq("K10 and the content-addressed store beside them (cases/)",
             sorted(p.name for p in (FIXTURE / "work" / "test-cases" / "cases").iterdir()), IDS)
    check_eq("K10 and the story's pinned snapshots (state/case-versions/)",
             sorted(p.name for p in (FIXTURE / "state" / "case-versions").iterdir()), IDS)
    links = json.loads((FIXTURE / "state" / "story-case-links.json").read_text(encoding="utf-8"))
    check_eq("K10 story-case-links.json pins the three ids", [x["case_id"] for x in links["links"]], IDS)
    check("K10 every pinned path exists and its bytes are the recorded content (line ends aside)",
          all((FIXTURE / x["path"]).is_file() and hashlib.sha256(
              (FIXTURE / x["path"]).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == x["content_hash"]
              for x in links["links"]))
    manifest = json.loads((FIXTURE / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    check_eq("K10 the manifest names the three cases and binds their Then clauses",
             ([u["case"] for u in manifest["unresolved"]], len(manifest["then_bindings"])), (IDS, 8))
    check("K10 run-report.json is there", (FIXTURE / "work" / "run-report.json").is_file())
    every = [p for p in FIXTURE.rglob("*") if p.is_file()]
    check("K10 English only (FR-30): every fixture file is ASCII", all(all(b < 128 for b in p.read_bytes()) for p in every))
    check("K10 no control byte (FR-29) in any fixture file",
          not any(b in p.read_bytes() for p in every for b in (7, 8, 11, 12)))
    check("K10 the fixture leaves out the live controller.json (its project_root is a foreign path)",
          not (FIXTURE / "state" / "controller.json").exists())


# --- K11 ---------------------------------------------------------------------------------------

def one_run(key) -> dict:
    """Everything K11 asks, on a fresh copy of the fixture under a project with (or without) the key."""
    root = project(key)
    try:
        story = install(root)
        rows = ledger.build(story)["rows"]
        findings = s5_precheck.run(story)["findings"]
        index = C.case_index(story)
        return {
            "no_bindings": sorted({f["case"] for f in findings if str(f.get("id", "")).endswith(":no-bindings")}),
            "identity": exit_gate.case_identity_errors("qa-case-designer", TICKET),
            "discovered": sorted(p.name for p in case_versions.discover_cases(story)),
            "index": sorted(index),
            "area_key": f"{AREA}/{IDS[0]}" in index,
            "ledger": " ".join(f"{r['ref']} {r['detail']}" for r in rows if r["kind"] == "plan_row"),
            "files": sorted(p.name for p in C.case_files(story)),
            "glob": sorted(p.name for p in C.case_glob(story / "work" / "test-cases", story)),
        }
    finally:
        cleanup(root)


def k11_story() -> None:
    with_key, without = one_run(FORM), one_run(_DROP)
    check_eq("K11 with the key: s5_precheck.run has no `no-bindings` for any case", with_key["no_bindings"], [])
    check_eq("K11 NEGATIVE control (no key): bindings are missing for all 3 cases", without["no_bindings"], IDS)
    check_eq("K11 with the key: case_identity_errors == []", with_key["identity"], [])
    check_eq("K11 NEGATIVE control (no key): case_identity_errors names one refusal", len(without["identity"]), 1)
    named = without["identity"][0] if without["identity"] else ""
    check("K11 NEGATIVE control: and it names the 3 files", all(f"{i}.md" in named for i in IDS), named[:300])
    check_eq("K11 with the key: case_versions.discover_cases finds 3", with_key["discovered"], [f"{i}.md" for i in IDS])
    check_eq("K11 NEGATIVE control (no key): discover_cases finds none", without["discovered"], [])
    check_eq("K11 with the key: C.case_index has 3 keys", with_key["index"], IDS)
    check("K11 and the area-qualified key resolves", with_key["area_key"])
    check("K11 NEGATIVE control (no key): the area-qualified key does not", not without["area_key"])
    check("K11 the ledger rows name TP1-13877_TC_001..003", all(i in with_key["ledger"] for i in IDS),
          with_key["ledger"][:400])
    check_eq("K11 with the key: case_files reads the 3 pinned snapshots", len(with_key["files"]), 3)
    check_eq("K11 with the key: case_glob finds the 3 authoring files (the store's cv_*.md are not cases)",
             with_key["glob"], [f"{i}.md" for i in IDS])
    check_eq("K11 NEGATIVE control (no key): case_glob finds none", without["glob"], [])


def k11_ledger_join_on_a_synthetic_manifest() -> None:
    """The ledger builds on the sample, so the join is proven on the sample; this adds a manifest with
    tests[] because the sample's tests[] is empty (all three cases are manual-human)."""
    root = project(FORM)
    try:
        story = install(root)
        # HF2-6a: the run record is the source of `pass` - only an entry with no identity of its own (no instance_id,
        # no marker apart from its case) may join a row by the case; an identified entry never takes another test's row.
        entry = {"file": "tests/test_open.py", "case": IDS[0], "covers": [IDS[0]], "critic_verdict": "approved"}
        identified = {"instance_id": "test_open[a]", "file": "tests/test_open.py", "marker": "P-open",
                      "case": IDS[0], "covers": [IDS[0]], "critic_verdict": "approved"}
        report = {"current_results": [{"instance_id": "other-instance", "case": IDS[0], "status": "passed",
                                       "attempt_id": "a1"}], "execution_status": "executed"}
        state, detail = ledger.test_state(entry, report, {}, story)
        check_eq("K11 a result row naming only the project id joins the manifest test (legacy entry)", state, "passed_green")
        state, detail = ledger.test_state(identified, report, {}, story)
        check_eq("K11 counter-key: an identified entry never takes another instance's row (HF2-6)", state,
                 "not_executed:" + ledger.NO_RUN_RESULT)
        set_key(root, _DROP)
        state, detail = ledger.test_state(entry, report, {}, story)
        check("K11 NEGATIVE control (no key): the legacy entry no longer joins the row", state.startswith("not_executed"), state)
        check_eq("K11 NEGATIVE control (no key): the manifest test links no case at all",
                 C.manifest_test_links(entry, C.case_config(story)), [])
    finally:
        cleanup(root)


# --- K12 / I1 / I2: the guard ------------------------------------------------------------------

def k12_guard() -> None:
    store = "docs/test-cases"
    root = project(FORM, cases_root=store)
    try:
        (root / store / AREA).mkdir(parents=True)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg_default = {"cases_root": store}
        outside = root / "qa-factory" / "artifacts" / TICKET / "work" / "test-cases" / AREA / f"{IDS[0]}.md"
        inside = root / store / AREA / f"{IDS[0]}.md"
        tc_outside = root / "elsewhere" / "TC-001.md"

        check("K12/I1 a project-form case outside the store is refused",
              bool(refusal(G.case_store_check, write_ev(outside), cfg)))
        check_eq("K12/I1 inside the store it is allowed", refusal(G.case_store_check, write_ev(inside), cfg), None)
        text = refusal(G.case_store_check, write_ev(outside), cfg) or ""
        check_in("K12 the refusal names the store and the project's own example",
                 f"`{store}/<area>/{IDS[0]}.md`", text)
        check_not_in("K12 and no longer the hard-coded TC-NNN form", "TC-NNN", text)
        check("K12/I1 a TC-001.md outside the store is refused (the default form is always read)",
              bool(refusal(G.case_store_check, write_ev(tc_outside), cfg)))
        check_in("K12 outside any story the example keeps a visible placeholder",
                 f"`{store}/<area>/<TICKET>_TC_001.md`", refusal(G.case_store_check, write_ev(tc_outside), cfg) or "")
        check_eq("K12/I1 a non-case .md passes", refusal(G.case_store_check, write_ev(root / "elsewhere" / "notes.md"), cfg), None)
        check_eq("K12/I1 so does the findings file", refusal(
            G.case_store_check, write_ev(root / "elsewhere" / "critic-findings.md"), cfg), None)
        check_eq("K12/I1 and a same-named .json", refusal(
            G.case_store_check, write_ev(root / "elsewhere" / f"{IDS[0]}.json"), cfg), None)
        check_eq("K12/I1 a Read is never this check's business", refusal(
            G.case_store_check, {"tool_name": "Read", "tool_input": {"file_path": str(outside)}}, cfg), None)

        # I1: without the key the project form is unrecognised, so it is never refused; TC still is
        check_eq("K12/I1 NEGATIVE control (no key): the project-form path is not recognised, so not refused",
                 refusal(G.case_store_check, write_ev(outside), cfg_default), None)
        default_text = refusal(G.case_store_check, write_ev(tc_outside), cfg_default) or ""
        check("K12/I1 without the key TC-001.md outside is still refused", bool(default_text))
        check_in("K12 and its example is the default form", f"`{store}/<area>/TC-001.md`", default_text)

        # I1: an invalid form falls back to the default, never to "recognises nothing"
        bad = dict(cfg_default, case_id_form="{ticket}_TC_")
        check("K12/I1 with an invalid form TC-001.md is still refused",
              bool(refusal(G.case_store_check, write_ev(tc_outside), bad)))
        check_eq("K12/I1 with an invalid form the project-form path is not read as a case",
                 refusal(G.case_store_check, write_ev(outside), bad), None)
        for label, junk in (("an integer", 5), ("a dict", {}), ("null", None), ("an empty list", [])):
            check("K12/I1 with case_id_form " + label + " TC-001.md is still refused",
                  bool(refusal(G.case_store_check, write_ev(tc_outside), dict(cfg_default, case_id_form=junk))))

        # I1: recognition first, then cases_root: an empty store is silent for EVERY path
        silent = {"cases_root": "", "case_id_form": FORM}
        check_eq("K12/I1 cases_root empty: silent for a project-form path",
                 refusal(G.case_store_check, write_ev(outside), silent), None)
        check_eq("K12/I1 cases_root empty: silent for TC-001.md", refusal(G.case_store_check, write_ev(tc_outside), silent), None)
        check_eq("K12/I1 no cases_root key at all: silent", refusal(G.case_store_check, write_ev(outside), {"case_id_form": FORM}), None)

        # I1: an unreadable project config falls to the default form, it does not stop recognising cases
        cfg_path = root / "qa-factory" / "config.json"
        cfg_path.write_text("{not json", encoding="utf-8")
        os.utime(cfg_path, ns=(cfg_path.stat().st_mtime_ns + 9_000_000,) * 2)
        check("K12/I1 an unreadable config: the guard still recognises TC-001.md", G._is_case_file("a/TC-001.md", {}))
        check("K12/I1 and does not invent the project form", not G._is_case_file(f"a/{IDS[0]}.md", {}))
        cfg_path.write_text("{}", encoding="utf-8")
        set_key(root, FORM, cases_root=store)

        # I2: the case branch of _owner_of_path is LAST
        owner = G._owner_of_path(str(inside).replace("\\", "/"), cfg)
        check_eq("K12/I2 a project-form case outside the story is the case designer's", owner, ("qa-case-designer", False))
        check_eq("K12/I2 NEGATIVE control (no key): the same path has no owner",
                 G._owner_of_path(str(inside).replace("\\", "/"), cfg_default), (None, False))
        bug = str(root / "qa-factory" / "bugs" / f"{IDS[0]}.md").replace("\\", "/")
        check_eq("K12/I2 a registry-owned artifact is never re-attributed to the case designer",
                 G._owner_of_path(bug, cfg)[0], "qa-bug-reporter")
        check_eq("K12/I2 the registry's own file names keep their owner",
                 G._owner_of_path("/p/qa-factory/artifacts/T-1/work/automation-manifest.json", cfg)[0], "qa-automator")
        check_eq("K12/I2 a TC-001.md is still the designer's",
                 G._owner_of_path("/p/docs/TC-001.md", cfg_default), ("qa-case-designer", False))
        check_eq("K12/I2 a story's own case tree is the registry's, whatever the file is called",
                 G._owner_of_path(str(outside).replace("\\", "/"), cfg_default)[0], "qa-case-designer")
        check("K12 the guard's own pattern is gone", not hasattr(G, "CASE_FILE_RE"))
    finally:
        cleanup(root)


# --- K13 / I5: validate_artifacts --------------------------------------------------------------

def broken_case(story: Path) -> Path:
    path = story / "work" / "test-cases" / AREA / f"{IDS[0]}.md"
    path.write_text(re.sub(r"(?m)^title:.*\n", "", path.read_text(encoding="utf-8")), encoding="utf-8")
    return path


def k13_validate_artifacts() -> None:
    for label, key in (("with the key", FORM), ("NEGATIVE control (no key)", _DROP)):
        wanted = key is not _DROP
        root = project(key)
        try:
            story = install(root)
            path = broken_case(story)
            errors = va.collect_errors(path)
            check_eq(f"K13 {label}: a project-form case with a missing field " + ("reports it" if wanted else "is not read as a case"),
                     any("required field 'title' is missing" in e for e in errors), wanted)
            if wanted:
                check_in("K13 and names the file", f"{IDS[0]}.md", " ".join(errors))
            # the exit gate's whole-story scan is the same door
            gate = exit_gate.collect_errors(TICKET)
            check_eq(f"K13 {label}: exit_gate.collect_errors validates the project-form case",
                     any(e.startswith(f"{IDS[0]}.md:") for e in gate), wanted)

            report = story / "test-report.md"
            item = ("## Left with you\n\n- **Access after cancelling.** ({req}, {case}) To check: the subscription stays "
                    "open until the period ends. How: check by hand on the preview.\n")
            report.write_text(item.format(req="R-1", case=IDS[0]), encoding="utf-8")
            errors = []
            va.check_report_left_with_you(report, errors)
            check_eq(f"K13 {label}: \"Left with you\" naming R-1 and a project id " + ("passes" if wanted else "names no case"),
                     [e for e in errors if "names no R-n" in e] == [], wanted)
            report.write_text(item.format(req="R-1", case="TC-001"), encoding="utf-8")
            errors = []
            va.check_report_left_with_you(report, errors)
            check_eq(f"K13 {label}: and one naming R-1 and TC-001 still passes", errors, [])
            report.write_text(item.format(req="R-1", case="nothing"), encoding="utf-8")
            errors = []
            va.check_report_left_with_you(report, errors)
            check_in(f"K13 {label}: an item with no case id is refused in the new words", "names no R-n and a case id",
                     " ".join(errors))
        finally:
            cleanup(root)

    # I5: the case branch stays before the critic-findings branch. A form whose ids END in
    # `critic-findings` is the one shape both branches could claim.
    root = project("{nnn}critic-findings")
    try:
        store = root / "qa-factory" / "artifacts" / "T-1" / "work" / "test-cases"
        store.mkdir(parents=True)
        both = store / "7critic-findings.md"
        both.write_text("Roll-call\n", encoding="utf-8")
        errors = va.collect_errors(both)
        check("I5 a name both branches could claim goes to the case branch (front matter is asked for)",
              any("no YAML frontmatter" in e for e in errors), str(errors))
        check_not_in("I5 and not to the roll-call reader", "Roll-call", " ".join(errors))
        plain = store / "critic-findings.md"
        plain.write_text("nothing\n", encoding="utf-8")
        check_in("I5 a real critic-findings.md is still read as the findings file", "Roll-call",
                 " ".join(va.collect_errors(plain)))
    finally:
        cleanup(root)


# --- I3 / I4: the exit gate --------------------------------------------------------------------

def k_exit_gate_identity() -> None:
    root = project(FORM)
    try:
        story = install(root)
        cases = story / "work" / "test-cases"
        check_eq("I3 in force and clean: no refusal", exit_gate.case_identity_errors("qa-case-designer", TICKET), [])
        check_eq("I3 only the case designer is judged", exit_gate.case_identity_errors("qa-scout", TICKET), [])
        check_eq("I3 no ticket, nothing to read", exit_gate.case_identity_errors("qa-case-designer", ""), [])
        check("I3 precondition: the store's cases/ holds files that declare an id which is not their name (cv_*.md), "
              "and the clean result above is because they are skipped",
              any(p.parent.parent.name == "cases" and "id:" in p.read_text(encoding="utf-8") for p in cases.rglob("cv_*.md")))

        stray = cases / AREA / "TP1-13877_case_004.md"
        stray.write_text("---\nid: TP1-13877_case_004\narea: code-executor\n---\nx\n", encoding="utf-8")
        errs = exit_gate.case_identity_errors("qa-case-designer", TICKET)
        check_eq("I3 a file whose id is no case id in a recorded form is refused, once", len(errs), 1)
        text = errs[0] if errs else ""
        check_in("I3 the refusal names the file", "TP1-13877_case_004.md", text)
        check_in("I3 says why (the id is no case id in a form recorded here)", "not a case id in a form recorded here", text)
        check_in("I3 names the form in force", f"`{FORM}`", text)
        check_in("I3 names the example for this story", f"`{IDS[0]}`", text)
        check_in("I3 door 1 (F1): the file's own number in the form in force, with id equal to the new name",
                 f"TP1-13877_case_004.md names `TP1-13877_case_004`, which is not a case id in a form recorded here -> "
                 f"`{TICKET}_TC_004.md` with `id: {TICKET}_TC_004`", text)
        check_in("I3 door 1 (F1): it says each case goes under the name shown for it", "under the name shown for it", text)
        check_not_in("I3 door 1 (F1): and no longer 'the same id'", "with the same `id:`", text)
        check_in("I3 door 1 says who removes the stray file", "orchestrator removes the stray file", text)
        check_in("I3 door 2: config.case_id_form, and who writes it", "`config.case_id_form` records the form (the person or qa-onboarding", text)
        check_in("I3 door 3: a person's word passes it", "A person's word passes this check", text)
        stray.unlink()

        # F1: three bad files -> three distinct suggested names, each from the file's own number
        for number in (7, 8, 9):
            (cases / AREA / f"TP1-13877_case_{number:03d}.md").write_text(
                f"---\nid: TP1-13877_case_{number:03d}\n---\nx\n", encoding="utf-8")
        (cases / AREA / "TP1-13877_final.md").write_text("---\nid: TP1-13877_final\n---\nx\n", encoding="utf-8")
        text = " ".join(exit_gate.case_identity_errors("qa-case-designer", TICKET))
        suggested = re.findall(r"-> `([^`]+)\.md`", text)
        check_eq("I3/F1 three numbered bad files and one without a number: four suggestions", len(suggested), 4)
        check_eq("I3/F1 all four names are distinct", len(set(suggested)), 4)
        check("I3/F1 each numbered file keeps its own number", all(f"{TICKET}_TC_{n:03d}" in suggested for n in (7, 8, 9)),
              str(suggested))
        check("I3/F1 every suggestion is itself a case id in the form in force", all(C.is_case_id(s, story) for s in suggested))
        for name in ("TP1-13877_case_007", "TP1-13877_case_008", "TP1-13877_case_009", "TP1-13877_final"):
            (cases / AREA / f"{name}.md").unlink()

        # F7: a UTF-8 byte-order mark in front of the front matter does not hide the file
        (cases / AREA / "TP1-13877_case_010.md").write_text(
            chr(0xFEFF) + "---\nid: TP1-13877_case_010\n---\nx\n", encoding="utf-8")
        check_in("I3/F7 a file that starts with a BOM is still judged",
                 "TP1-13877_case_010.md", " ".join(exit_gate.case_identity_errors("qa-case-designer", TICKET)))
        (cases / AREA / "TP1-13877_case_010.md").unlink()

        renamed = cases / AREA / "TP1-13877_TC_005.md"
        renamed.write_text("---\nid: TP1-13877_TC_006\n---\nx\n", encoding="utf-8")
        text = " ".join(exit_gate.case_identity_errors("qa-case-designer", TICKET))
        check_in("I3 a name that differs from the declared id is refused (id == stem)", "TP1-13877_TC_005.md declares `TP1-13877_TC_006`", text)
        renamed.unlink()

        no_id = cases / AREA / "notes-on-the-area.md"
        no_id.write_text("---\ntitle: notes\n---\nno id here\n", encoding="utf-8")
        plain = cases / AREA / "readme.md"
        plain.write_text("just words, id: not-front-matter\n", encoding="utf-8")
        check_eq("I3 a markdown file with no front-matter id is out of scope", exit_gate.case_identity_errors("qa-case-designer", TICKET), [])
        no_id.unlink(), plain.unlink()

        version_dir = cases / "cases" / "TC-9"
        version_dir.mkdir(parents=True)
        (version_dir / "cv_x.md").write_text("---\nid: something-else\n---\n", encoding="utf-8")
        (cases / AREA / "case-versions").mkdir()
        (cases / AREA / "case-versions" / "cv_y.md").write_text("---\nid: another\n---\n", encoding="utf-8")
        check_eq("I3 a path with a CASE_STORE_DIRS component is skipped, at any depth",
                 exit_gate.case_identity_errors("qa-case-designer", TICKET), [])

        # default-form cases keep working and are judged the same way
        (cases / AREA / "TC-001.md").write_text("---\nid: TC-002\n---\nx\n", encoding="utf-8")
        text = " ".join(exit_gate.case_identity_errors("qa-case-designer", TICKET))
        check_in("I3 a TC file whose id differs from its name is refused as before", "TC-001.md declares `TC-002`", text)
        (cases / AREA / "TC-001.md").write_text("---\nid: TC-001\n---\nx\n", encoding="utf-8")
        check_eq("I3 and a TC file that agrees passes (the default form is always read)",
                 exit_gate.case_identity_errors("qa-case-designer", TICKET), [])
        (cases / AREA / "TC-001.md").unlink()

        # I3 + F4: the scan follows cases_root
        shared = root / "docs" / "test-cases" / AREA
        shared.mkdir(parents=True)
        set_key(root, FORM, cases_root="docs/test-cases")
        (shared / f"{TICKET}_bad.md").write_text(f"---\nid: {TICKET}_bad\ntask: {TICKET}\n---\nx\n", encoding="utf-8")
        (shared / "OTHER-1_bad.md").write_text("---\nid: OTHER-1_bad\ntask: OTHER-1\n---\nx\n", encoding="utf-8")
        text = " ".join(exit_gate.case_identity_errors("qa-case-designer", TICKET))
        listed = text.split(". Way on:")[0]
        check_in("I3/F4 with cases_root set the project's store is scanned", f"{TICKET}_bad.md", listed)
        check_not_in("I3/F4 and only this story's files there (another story's are not its business)", "OTHER-1_bad.md", text)
        check_eq("I3/F4 the per-story tree is not what is scanned any more (its three project-form ids are valid here)",
                 [i for i in IDS if f"{i}.md declares" in listed or f"{i}.md names" in listed], [])
        set_key(root, _DROP, cases_root="")
        text = " ".join(exit_gate.case_identity_errors("qa-case-designer", TICKET))
        check_in("I3 NEGATIVE control (no key, no store): the per-story tree's project-form files are refused, all 3",
                 IDS[2] + ".md", text)
        check("I3 NEGATIVE control names all three", all(f"{i}.md" in text for i in IDS), text[:300])
        suggested = re.findall(r"-> `([^`]+)\.md`", text)
        check_eq("I3/F1 an id that is only an unrecognised FORM is told its own number in the default form (no key)",
                 sorted(suggested), ["TC-001", "TC-002", "TC-003"])
    finally:
        cleanup(root)


def i4_scoped_errors() -> None:
    original = exit_gate.collect_errors
    error = f"{IDS[0]}.md: required field 'title' is missing"
    try:
        exit_gate.collect_errors = lambda task="", facts_text="": [
            error, "run-report.json: execution_status outside the vocabulary"]
        for label, key, expected in (("with the key", FORM, [error]), ("NEGATIVE control (no key)", _DROP, [])):
            root = project(key)
            try:
                got = exit_gate.scoped_errors("qa-case-designer", TICKET)
                check_eq(f"I4 {label}: a case-file error is S4's for a recognised name", got, expected)
                check_eq(f"I4 {label}: the runner does not see it", exit_gate.scoped_errors("qa-runner", TICKET),
                         ["run-report.json: execution_status outside the vocabulary"])
            finally:
                cleanup(root)
        root = project(FORM)
        try:
            exit_gate.collect_errors = lambda task="", facts_text="": ["TC-006.md: required field 'title' is missing"]
            check_eq("I4 a TC name is still attributed", exit_gate.scoped_errors("qa-case-designer", TICKET),
                     ["TC-006.md: required field 'title' is missing"])
            exit_gate.collect_errors = lambda task="", facts_text="": ["notes.md: x", f"{IDS[0]}.json: broken"]
            check_eq("I4 a file that is not a case name is not attributed by the case rule",
                     exit_gate.scoped_errors("qa-case-designer", TICKET), [])
        finally:
            cleanup(root)
    finally:
        exit_gate.collect_errors = original


# --- K14: gate_brief / critic_rollcall ---------------------------------------------------------

def k14_gate_brief_and_rollcall() -> None:
    table = ("## Roll-call\n\n| plan row | case | reviewed |\n|---|---|---|\n"
             f"| TS-6 | {IDS[0]} | yes |\n| TS-9 | {IDS[1]} | no |\n")
    for label, key in (("with the key", FORM), ("NEGATIVE control (no key)", _DROP)):
        root = project(key)
        try:
            story = install(root)
            drafts = story / "work" / "bug-drafts"
            drafts.mkdir(parents=True)
            (drafts / "BD-1.json").write_text(json.dumps({"id": "BD-1", "case": IDS[1]}), encoding="utf-8")
            wanted = key is not _DROP
            items = gate_brief.packet_items(story, "A")
            check_eq(f"K14 {label}: packet_items (gate A) finds the pinned project ids", all(i in items for i in IDS), wanted)
            items_b = gate_brief.packet_items(story, "B")
            check_eq(f"K14 {label}: packet_items (gate B) finds the draft's project id", IDS[1] in items_b, wanted)
            check_in(f"K14 {label}: and the draft id BD-1", "BD-1", " ".join(items_b))
            said = gate_brief.attribute(IDS, f"approved. {IDS[0]} as written; {IDS[2]} I am not sure about", story)
            check_eq(f"K14 {label}: attribute names the ids the person wrote",
                     said["named"], [IDS[0], IDS[2]] if wanted else [])
            check_eq(f"K14 {label}: and prints the ones the person did not", said["not_named"],
                     [IDS[1]] if wanted else IDS)
            rows = critic_rollcall.parse_rollcall(table)
            check_eq(f"K14 {label}: parse_rollcall reads the case of each row", [r["case"] for r in rows],
                     IDS[:2] if wanted else ["", ""])
            check_eq(f"K14 {label}: with the story it reads the story's project",
                     [r["case"] for r in critic_rollcall.parse_rollcall(table, story)], IDS[:2] if wanted else ["", ""])
        finally:
            cleanup(root)
    root = project(_DROP)
    try:
        check_eq("K14 a TC id is read either way", [r["case"] for r in critic_rollcall.parse_rollcall(
            table.replace(IDS[0], "TC-001"))][0], "TC-001")
        check("K14 critic_rollcall carries no pattern of its own any more", not hasattr(critic_rollcall, "CASE_ID_RE"))
        check("K14 gate_brief's ITEM_ID_RE no longer names a case", "TC-" not in gate_brief.ITEM_ID_RE.pattern)
        check_eq("K14 the old TC id is still an item", gate_brief.attribute(["TC-001", "TS-2"], "TC-001 fine")["named"], ["TC-001"])
    finally:
        cleanup(root)


# --- the other sites (one check each, in the site table's order) ------------------------------

def other_sites() -> None:
    for label, key in (("with the key", FORM), ("NEGATIVE control (no key)", _DROP)):
        wanted = key is not _DROP
        root = project(key)
        try:
            story = install(root)
            first = story / "work" / "test-cases" / AREA / f"{IDS[0]}.md"

            # handoff_check: the case's own front matter
            art = SimpleNamespace(root=story)
            got = handoff_check._plan_row_of(art, None, {"case": IDS[0]})
            check_eq(f"site handoff_check {label}: the plan row comes from a project-form case's front matter",
                     got[0] if got else None, "TS-6" if wanted else None)
            got = handoff_check._requirements_of(art, None, {"case": IDS[0]})
            check_eq(f"site handoff_check {label}: and its requirements", got[0] if got else None, "R-6, R-7" if wanted else None)
            got = handoff_check._plan_row_of(art, None, {"case": f"{AREA}/{IDS[0]}"})
            check_eq(f"site handoff_check {label}: an area-qualified key is read by its id",
                     got[0] if got else None, "TS-6" if wanted else None)

            # artifact_producer: the door that publishes a case
            data = {"frontmatter": {"id": IDS[0]}, "body": "x"}
            try:
                out = artifact_producer.publish(story, "case", data, f"work/test-cases/{AREA}/{IDS[0]}.md")
                outcome = "reached validation" if out.get("valid") is False else "published"
            except ValueError as exc:
                outcome = str(exc)
            check(f"site artifact_producer {label}: the filename gate " + ("passes a project-form name" if wanted
                  else "refuses it and names the form"),
                  (outcome == "reached validation") if wanted else ("one case id in a form this project records" in outcome), outcome)
            if not wanted:
                check_in("site artifact_producer NEGATIVE control: the refusal names the example for this story",
                         "for this story `TC-001`", outcome)

            # case_versions: identity of a candidate
            candidate = case_versions.validate_candidate(first)
            check_eq(f"site case_versions {label}: the key of a project-form case",
                     candidate["key"], f"{AREA}/{IDS[0]}" if wanted else IDS[0])

            # manifest_view: --case <id> in any area and spelling
            manifest = {"tests": [{"case": IDS[0], "area": AREA, "file": "t.py", "instance_id": "i-1"}]}
            check_eq(f"site manifest_view {label}: a lower-case --case with its area selects the test",
                     len(manifest_view.pick_tests(manifest, [f"{AREA}/{IDS[0]}".lower()])), 1 if wanted else 0)
            check_eq(f"site manifest_view {label}: another area does not", len(manifest_view.pick_tests(
                manifest, [f"other/{IDS[0]}"])), 0)

            # manifest_from_tests: the story's own config decides the bare id
            fresh = manifest_from_tests.Story(TICKET, story)
            check_eq(f"site manifest_from_tests {label}: the bare id of an area-qualified key",
                     fresh.bare(f"{AREA}/{IDS[0]}"), IDS[0] if wanted else f"{AREA}/{IDS[0]}")

            # migrate_artifacts: a row whose instance id IS a case id
            check_eq(f"site migrate_artifacts {label}: a case-shaped instance id",
                     migrate_artifacts._is_case_shaped_id(f"{AREA}/{IDS[0]}"), wanted)
            check_eq(f"site migrate_artifacts {label}: but never a function-derived one",
                     migrate_artifacts._is_case_shaped_id(f"{IDS[0]}::test_x"), False)
            check_eq("site migrate_artifacts the default form is read either way", migrate_artifacts._is_case_shaped_id("TC-012"), True)

            # traceability: a draft with no case field is read by its file name
            drafts = story / "work" / "bug-drafts"
            drafts.mkdir(parents=True, exist_ok=True)
            (drafts / f"{IDS[1].lower()}.json").write_text(json.dumps({"id": "BD-7", "title": "x"}), encoding="utf-8")
            records = traceability.bug_records(root / "qa-factory", story)
            found = [r["cases"] for r in records if r["id"] == "BD-7"]
            check_eq(f"site traceability {label}: the draft's case comes from its file name", found,
                     [[IDS[1]]] if wanted else [[]])

            # case tree scanners
            check_eq(f"site render_case_appendix {label}: the appendix of the authoring store",
                     all(i in render_case_appendix.render(story / "work" / "test-cases") for i in IDS), wanted)
            (story / "state" / "story-case-links.json").unlink()
            shutil.rmtree(story / "state" / "case-versions")
            check_eq(f"site judge_cases {label}: an unpinned story is read from its authoring files",
                     sorted(name for name, _v, _p in judge_cases.pinned_cases(story)), IDS if wanted else [])
        finally:
            cleanup(root)


def sites_pin_batch_and_env() -> None:
    """case_versions.pin_batch resolves the story's config once; its result must be the same links."""
    root = project(FORM)
    try:
        story = install(root)
        records = []
        for i in IDS:
            path = story / "work" / "test-cases" / AREA / f"{i}.md"
            candidate = case_versions.validate_candidate(path)
            records.append({"case_id": candidate["case_id"], "area": candidate["area"], "version": "cv_" + candidate["content_hash"][:20],
                            "content_hash": candidate["content_hash"], "path": str(path)})
        (story / "state" / "story-case-links.json").unlink()
        result = case_versions.pin_batch(story, records)
        check_eq("site case_versions.pin_batch pins three project-form cases", sorted(x["case_id"] for x in result["links"]), IDS)
        check_eq("site case_versions.unpinned then finds nothing to pin", case_versions.unpinned(story), [])
        again = case_versions.pin_batch(story, records)
        check_eq("site case_versions.pin_batch is idempotent on the same bytes", sorted(x["case_id"] for x in again["links"]), IDS)
    finally:
        cleanup(root)


# --- PERF: the config is resolved once per story in the quadratic loops ----------------------------

def perf_config_resolved_once() -> None:
    root = project(FORM)
    calls = []
    # Count RESOLUTIONS (`_case_config` calls), not stats: the contract's 2 s memo makes the stat count 1
    # whether or not a loop is hoisted, so a stat counter cannot see a loop that went back to per-call
    # resolution (mutation M13 survived it). A hoisted loop asks once; an unhoisted one asks per cell.
    original = C._case_config
    try:
        story = install(root)

        def counting(artifacts=None):
            calls.append(str(artifacts))
            return original(artifacts)

        n = 40
        results = {f"i{k}": {"instance_id": f"i{k}", "case": f"{TICKET}_TC_{k:03d}", "status": "passed", "attempt_id": f"a{k}"}
                   for k in range(1, n + 1)}
        blocked = [{"case": f"{TICKET}_TC_{900 + k}", "attempt_position": 1, "instance_id": f"b{k}"} for k in range(n)]
        positions = {key: 10 + i for i, key in enumerate(results)}
        ghosts = {f"g{k}": {"instance_id": f"g{k}", "case": f"{TICKET}_TC_{800 + k}", "current_reason": finalize_task.JOIN_FAILED,
                            "status": "partial"} for k in range(n)}
        merged = dict(ghosts, **results)
        ghost_positions = {key: i for i, key in enumerate(merged)}
        entries = [{"instance_id": f"j{k}", "file": "t.py", "marker": f"m{k}", "case": f"{TICKET}_TC_{k:03d}",
                    "covers": [f"{TICKET}_TC_{k:03d}"], "critic_verdict": "approved"} for k in range(1, n + 1)]
        report = {"current_results": list(results.values()), "execution_status": "executed"}
        manifest = {"tests": entries, "unresolved": [{"case": f"{TICKET}_TC_{k:03d}", "reason": "blocked_by_env"} for k in range(1, n + 1)]}

        C._case_config = counting
        del calls[:]
        finalize_task._project_env_blocks(blocked, results, positions, {}, False)
        check("PERF finalize_task._project_env_blocks: a 40x40 loop resolves the config once", len(calls) <= 2, str(len(calls)))
        del calls[:]
        finalize_task._supersede_join_ghosts(merged, ghost_positions, {}, False)
        check("PERF finalize_task._supersede_join_ghosts: a 40x40 loop resolves it once", len(calls) <= 2, str(len(calls)))
        del calls[:]
        [ledger.test_state(e, report, {}, story) for e in entries]
        check("PERF ledger.test_state: 40 tests x 40 results resolve it once per test, not per result",
              len(calls) <= 2 * n, str(len(calls)))
        del calls[:]
        manifest_view.pick_tests(manifest, [f"{TICKET}_TC_{900 + k}" for k in range(n)])
        check("PERF manifest_view.pick_tests: 40 tests x 40 cases resolve it once", len(calls) <= 2, str(len(calls)))
        del calls[:]
        story_obj = manifest_from_tests.Story(TICKET, story)
        story_obj.manifest = manifest
        del calls[:]
        [story_obj.manifest_has(f"{TICKET}_TC_{900 + k}") for k in range(n)]
        check("PERF manifest_from_tests.Story.manifest_has: 40 cases x 40 rows resolve it never (held by the story)",
              len(calls) == 0, str(len(calls)))
        del calls[:]
        found = migrate_artifacts._retract_case_ghosts(
            story, TICKET, root, {"tests": [{"instance_id": f"{TICKET}_TC_{k:03d}", "case": f"{TICKET}_TC_{k:03d}"} for k in range(1, n + 1)]
                                  + [{"instance_id": f"f::r{k}", "case": f"{TICKET}_TC_{500 + k}", "covers": [f"{TICKET}_TC_{500 + k}"]}
                                     for k in range(n)]})
        check("PERF migrate_artifacts._retract_case_ghosts: 40 ghosts x 40 rows resolve it once", len(calls) <= 2, str(len(calls)))
        check_eq("PERF and reports the ghosts it could not retract, as before", len(found["left"]), n)
        del calls[:]
        s5_precheck.check_environment(story, manifest, [f"{TICKET}_TC_{900 + k}" for k in range(n)], {}, {}, [], [])
        check("PERF s5_precheck.check_environment: 40 rows x 40 owned cases resolve it once", len(calls) <= 3, str(len(calls)))
        # the loops critic t-027 did not name: one call per case, and each call over every test
        del calls[:]
        for k in range(n):
            s5_precheck.instances_of_case(manifest, f"{TICKET}_TC_{k + 1:03d}")
            s5_precheck._covering_ids(manifest, f"{TICKET}_TC_{k + 1:03d}")
        check("PERF s5_precheck.instances_of_case/_covering_ids: 40 cases x 40 tests resolve it once per call, not per test",
              len(calls) <= 2 * n + 2, str(len(calls)))
        del calls[:]
        s5_precheck.bindings_of_case({"tests": entries, "then_bindings": [{"case": f"{TICKET}_TC_{k:03d}", "then": 1}
                                                                          for k in range(1, n + 1)]}, IDS[0])
        check("PERF s5_precheck.bindings_of_case: 40 rows x 40 tests resolve it once", len(calls) <= 2, str(len(calls)))
        del calls[:]
        [story_obj.existing_status(f"nomatch{k}") for k in range(n)]
        check("PERF manifest_from_tests.Story.existing_status: 40 x 40 resolve it never (held by the story)",
              len(calls) == 0, str(len(calls)))
        check_eq("PERF instance_id_aliases with cfg= answers as without it",
                 C.instance_id_aliases(entries[0], C.case_config(story)), C.instance_id_aliases(entries[0]))
        source = story / "work" / "test-cases" / AREA / f"{IDS[0]}.md"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        links_file = case_versions.link_path(story)
        links = [{"case_id": f"{TICKET}_TC_{500 + k}", "version": "cv_x", "content_hash": "0", "path": "x"} for k in range(n)]
        links_file.write_text(json.dumps({"links": links, "history": links}), encoding="utf-8")
        del calls[:]
        case_versions._pin_unlocked(story, {"case_id": IDS[0], "area": AREA, "version": "cv_" + digest[:20],
                                            "content_hash": digest, "path": str(source)}, None)
        check("PERF case_versions._pin_unlocked: one pin over 40 links and 40 history rows resolves it once",
              len(calls) <= 2, str(len(calls)))
        check_eq("PERF and the pin lands beside the others", len(json.loads(links_file.read_text(encoding="utf-8"))["links"]), n + 1)
    finally:
        C._case_config = original
        cleanup(root)


def rh1_8_perf_case_holds() -> None:
    """RH1-8 E12 (B-013): `case_stamp.case_holds` over 40 cases x 40 instances resolves the case config ONCE per story - the caller
    hands `cfg` in and every `case_matches` / `manifest_test_keys` of the 1600 pairs shares it. Counts RESOLUTIONS (`_case_config`
    calls), as the block above. Kills: `cfg=None` in the population loop (m11: one resolution per pair)."""
    import case_stamp
    root = project(FORM)
    original = C._case_config
    calls = []
    try:
        story = install(root)
        n = 40
        entries = [{"instance_id": f"j{k}", "file": "t.py", "marker": f"m{k}", "status": "green", "critic_verdict": "approved",
                    "covers": [f"{TICKET}_TC_{k:03d}"]} for k in range(1, n + 1)]
        manifest = {"tests": entries}
        cfg = C.case_config(story)

        def counting(artifacts=None):
            calls.append(str(artifacts))
            return original(artifacts)

        C._case_config = counting
        del calls[:]
        held = case_stamp.case_holds(manifest, case_stamp.run_rows_index({}), cfg)
        check("PERF case_holds: 40 cases x 40 entries resolve the config once", len(calls) <= 2, str(len(calls)))
        check_eq("PERF and answers every case with its own hold (no run: not_run)", sorted(held.values()),
                 sorted(f"not_run:j{k}" for k in range(1, n + 1)))
    finally:
        C._case_config = original
        cleanup(root)


def rh1_8_perf_plan_and_map() -> None:
    """RH1-8 F3 (B-013): the two callers that RUN - `case_stamp.plan` and `check_coverage.collect_cases` - resolve the case config
    ONCE per story over 40 instances, 40 `unresolved[]` rows and 40 pins, not once per pair. Counts RESOLUTIONS (`_case_config`
    calls) with a bound far below 40. Kills: `cfg=None` into `_population_of` / `case_group_key` / `case_matches` inside either."""
    import case_stamp
    import check_coverage
    root = project(FORM)
    original = C._case_config
    calls = []
    try:
        story = install(root)
        n = 40
        entries = [{"instance_id": f"j{k}", "file": "t.py", "marker": f"m{k}", "status": "green", "critic_verdict": "approved",
                    "covers": [f"{TICKET}_TC_{k:03d}"]} for k in range(1, n + 1)]
        rows = [{"case": f"{TICKET}_TC_{k:03d}", "area": AREA, "reason": "blocked_by_env"} for k in range(n + 1, 2 * n + 1)]
        manifest = {"tests": entries, "unresolved": rows}
        (story / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        links = [{"case_id": f"{TICKET}_TC_{k:03d}", "version": "cv_x", "content_hash": "0", "path": "x"} for k in range(1, n + 1)]
        case_versions.link_path(story).write_text(json.dumps({"links": links, "history": links}), encoding="utf-8")

        def counting(artifacts=None):
            # the per-case SOURCE search of the write path (`_case_source` -> `case_id` per case file) is a separate, queued
            # per-case cost (not a matcher loop); this pin counts the matcher loops of `plan` and `collect_cases`
            if not any(f.name == "_case_source" for f in traceback.extract_stack()):
                calls.append(str(artifacts))
            return original(artifacts)

        C._case_config = counting
        del calls[:]
        out = case_stamp.plan(story, manifest)
        check("PERF plan: 40 instances x 40 unresolved rows resolve the config a few times, not per pair", len(calls) <= 8, str(len(calls)))
        check("PERF plan: and it did plan something", bool(out), str(type(out)))
        del calls[:]
        check_coverage.collect_cases(root)
        check("PERF collect_cases: 40 pins x 40 instances x 40 rows resolve the config a few times, not per pair",
              len(calls) <= 8, str(len(calls)))
    finally:
        C._case_config = original
        cleanup(root)


# --- the config-resolution window (root fix of the per-call stat) --------------------------------

def config_window() -> None:
    """A resolution is revalidated at most once per CASE_CONFIG_WINDOW_S: inside it a rewrite by
    ANOTHER writer is not seen, after it (or after case_config_reset) it is. Injected clock: no sleep."""
    root = project(_DROP)
    clock = [1000.0]
    saved, stats = C._CASE_CONFIG_CLOCK, []
    original_stat = C._stat_key
    try:
        story = install(root)
        C._CASE_CONFIG_CLOCK = lambda: clock[0]
        C._stat_key = lambda path: (stats.append(1), original_stat(path))[1]
        C.case_config_reset()
        check_eq("WINDOW the window is 2 s", C.CASE_CONFIG_WINDOW_S, 2.0)
        for label, anchor in (("story", story), ("process project", None)):
            set_key(root, _DROP)
            C._CASE_CONFIG_CLOCK = lambda: clock[0]
            clock[0] = 1000.0
            check_eq(f"WINDOW {label}: before the rewrite the default form", C.case_ids(IDS[0], anchor), [])
            set_key(root, FORM, reset=False)
            del stats[:]
            check_eq(f"WINDOW {label}: rewritten by another writer, inside the window the old form is still read",
                     C.case_ids(IDS[0], anchor), [])
            clock[0] += 1.9
            check_eq(f"WINDOW {label}: still inside at 1.9 s", C.case_ids(IDS[0], anchor), [])
            check_eq(f"WINDOW {label}: and nothing was stat'ed since the first call", len(stats), 0)
            clock[0] += 0.2
            check_eq(f"WINDOW {label}: after the window the new form is read", C.case_ids(IDS[0], anchor), [IDS[0]])
            check_eq(f"WINDOW {label}: one revalidation, not one per call", len(stats), 1)
            for _ in range(500):
                C.case_ids(IDS[0], anchor)
            check_eq(f"WINDOW {label}: 500 more calls inside the next window cost no stat", len(stats), 1)
            set_key(root, _DROP, reset=False)
            check_eq(f"WINDOW {label}: a second rewrite is again unseen inside its window", C.case_ids(IDS[0], anchor), [IDS[0]])
            C.case_config_reset()
            check_eq(f"WINDOW {label}: case_config_reset makes it visible at once", C.case_ids(IDS[0], anchor), [])
        # two projects in one process never share a memo entry
        other = project(FORM)
        try:
            check_eq("WINDOW a second project (process anchor) reads its own form, inside the first one's window",
                     C.case_ids(IDS[0]), [IDS[0]])
        finally:
            cleanup(other)
        use_project(root)
        check_eq("WINDOW and back in the first project it is the first project's form", C.case_ids(IDS[0]), [])
    finally:
        C._CASE_CONFIG_CLOCK, C._stat_key = saved, original_stat
        C.case_config_reset()
        cleanup(root)


# --- K15: FR-17 grep witness -------------------------------------------------------------------

K15_PATTERN = re.compile(r"rglob\(\"TC-|TC-\\d|startswith\(\"TC-|tc-\\d|" + chr(92) + chr(92) + r"bTC-")


def excluded_lines(path: Path) -> set:
    """Lines of docstrings and of `selftest` functions: the two places the spec allows the pattern."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                skip.update(range(body[0].lineno, body[0].end_lineno + 1))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "selftest" in node.name:
            skip.update(range(node.lineno, node.end_lineno + 1))
    return skip


def scan_tree(directory: Path) -> list:
    """(file, line no, text) of every K15 hit outside docstrings and selftest blocks, tests excluded."""
    hits = []
    for path in sorted(directory.glob("*.py")):
        skip = excluded_lines(path)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if K15_PATTERN.search(line) and number not in skip:
                hits.append((path.name, number, line.strip()))
    return hits


def k15_grep_witness() -> None:
    hits = scan_tree(SCRIPTS)
    # case_forms.py DEFINES the default form `TC-{nnn}` and says in two comments that it compiles to the
    # legacy `TC-\d+` exactly; that is the one place the shape belongs, so its comments are the reason listed.
    left = [h for h in hits if h[0] != "case_forms.py"]
    check_eq("K15 no case id pattern or TC-* glob is left in PKG/scripts/*.py outside docstrings and selftest blocks",
             left, [])
    check("K15 the only lines left are case_forms.py's own comments about the default form",
          all(h[0] == "case_forms.py" and h[2].startswith("#") for h in hits), str(hits))
    # positive controls: the scanner finds the pattern it looks for
    sample = SCRIPTS.parent / "scripts"
    probe = 'files = sorted(root.rglob("TC-*.md"))'
    check("K15 positive control: the pattern matches the old glob", bool(K15_PATTERN.search(probe)))
    check("K15 positive control: and the old prefix test", bool(K15_PATTERN.search('if name.startswith("TC-"):')))
    check("K15 positive control: and the old pattern", bool(K15_PATTERN.search('RE = re.compile(r"TC-\\d+")')))
    check("K15 positive control: and the lower-case one", bool(K15_PATTERN.search('re.search(r"tc-\\d+\\.md$", t)')))
    repo = SCRIPTS.parents[2]
    # The control greps the LAST commit that still carried the old glob (8637374, 30.09, before B-013
    # landed in 9a16c31), never HEAD: once the fix is committed, HEAD holds no old glob by design,
    # and a control pinned to HEAD would fail exactly when the work is done.
    old = "8637374"
    if (repo / ".git").exists():
        proc = subprocess.run(["git", "-C", str(repo), "grep", "-n", 'rglob("TC-', old, "--",
                               "ai-packages/qa-factory/scripts/contract.py"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
        check(f"K15 positive control: git grep over {old} finds the old rglob in contract.py",
              proc.returncode == 0 and "contract.py:" in proc.stdout, proc.stdout + proc.stderr)
        line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        check_in("K15 positive control: at the recorded line", ":796:", line)
    else:
        check("K15 positive control (git grep) skipped: this is not a git checkout", True)
    del sample


def hygiene() -> None:
    for path in [Path(__file__).resolve()]:
        data = path.read_bytes()
        check(f"FR-29 {path.name} carries no 0x07/0x08/0x0b/0x0c byte", not any(b in data for b in (7, 8, 11, 12)))
        check(f"FR-30 {path.name} is ASCII only", all(b < 128 for b in data))
    for name in ("contract.py", "exit_gate.py", "guard_pre_tool.py", "gate_brief.py", "critic_rollcall.py",
                 "case_versions.py", "handoff_check.py", "validate_artifacts.py", "artifact_producer.py",
                 "migrate_artifacts.py", "manifest_view.py", "manifest_from_tests.py", "traceability.py",
                 "ledger.py", "finalize_task.py", "s5_precheck.py", "case_forms.py"):
        data = (SCRIPTS / name).read_bytes()
        check(f"FR-29 {name} carries no control byte", not any(b in data for b in (7, 8, 11, 12)))


def main() -> None:
    k10_fixture()
    k11_story()
    k11_ledger_join_on_a_synthetic_manifest()
    k12_guard()
    k13_validate_artifacts()
    k_exit_gate_identity()
    i4_scoped_errors()
    k14_gate_brief_and_rollcall()
    other_sites()
    sites_pin_batch_and_env()
    perf_config_resolved_once()
    rh1_8_perf_case_holds()
    rh1_8_perf_plan_and_map()
    config_window()
    k15_grep_witness()
    hygiene()
    finish("test_case_id_form_sites")


if __name__ == "__main__":
    main()
