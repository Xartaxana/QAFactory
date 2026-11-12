#!/usr/bin/env python3
"""B-013 D3: what the roles and onboarding are told about the project's case id form.

D1 made the id form data (`config.case_id_form`) and D2 made every code site read it; D3 is the
text layer: the designer's card and charter, the automator's marker examples, the contract's
case-file section, the onboarding phases, S0's warnings, and the S4 line that says who removes the
stray file the identity refusal names. On TP1-13877 every text a role read said `TC-NNN` while
the strategy wrote `TP1-13877_TC_001`; the automator spent about 35 calls reading factory code
before it halted (FR-13, FR-38).

Keys of docs/tasks/specs/t-015-B013.md, D3:
  K16  the designer brief of TP1-13797 names TP1-13797_TC_001 with the key, TC-001 and
       "the project records no form" without it, and prints problems() for an invalid key; a key
       that is absent, "", null, [] or a missing config is the default and never raises.
  K18  the case-file section moved into the slices (contract_slices findings are clean).
  K19  the designer's whole start load stays within the role_load threshold (role_load.static_load, tokens; the charter
       is one layer of it, content bytes with CRLF counted as one); the old 9000-byte per-file cap is retired, audit A22
       bounds the whole start load.
The rewriting of the key inside this process calls contract.case_config_reset(): the contract
revalidates a config resolution once per 2 s (Lead's addition after critic t-034).
"""
import json
import os
import re
import sys
import ast
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import case_forms  # noqa: E402
import contract as C  # noqa: E402
import contract_slices  # noqa: E402
import exit_gate  # noqa: E402
import factory_dashboard  # noqa: E402
import manifest_from_tests  # noqa: E402
from content_size import content_bytes  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT
TICKET = "TP1-13797"
FORM = "{ticket}_TC_{nnn}"
_DROP = object()


def read(rel: str) -> str:
    return (PLUGIN / rel).read_text(encoding="utf-8")


def set_key(root: Path, value=_DROP) -> None:
    """Rewrite the project's config with `case_id_form` = value (or without the key). The mtime is
    moved on by hand (the contract reads a config once per (path, mtime_ns, size)) and the memo is
    reset (it revalidates a resolution once per 2 s)."""
    path = root / "qa-factory" / "config.json"
    before = path.stat().st_mtime_ns
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.pop("case_id_form", None)
    if value is not _DROP:
        cfg["case_id_form"] = value
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    bumped = max(path.stat().st_mtime_ns, before + 5_000_000)
    os.utime(path, ns=(bumped, bumped))
    C.case_config_reset()


def seed(root: Path, ticket: str = TICKET, warnings=()) -> Path:
    task = root / "qa-factory" / "artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": ticket, "size": "S", "environment": "local", "stages": {"S0": {"status": "done"}},
         "gates": {}, "halts": [], "warnings": list(warnings)}), encoding="utf-8")
    return task


def brief(ticket: str = TICKET, role: str = "qa-case-designer", stage: str = "S4") -> str:
    """The markdown of a brief, or a RAISED marker: a raise must fail a check, not end the file."""
    try:
        return brief_pack.build(ticket, stage, role, f"{stage}-{role}-1", write=False)["markdown"]
    except Exception as exc:  # noqa: BLE001
        return f"RAISED {type(exc).__name__}: {exc}"


def brief_budget(ticket: str = TICKET, role: str = "qa-case-designer", stage: str = "S4") -> int:
    """N4: the bytes the 6 KB ceiling counts (the digest template is outside it); a raise is a number no bound meets."""
    try:
        return brief_pack.build(ticket, stage, role, f"{stage}-{role}-1", write=False)["budget_bytes"]
    except Exception:  # noqa: BLE001
        return 10 ** 9


def form_lines(text: str) -> list:
    return [line for line in text.splitlines() if line.startswith("Case id form:")]


def k16_brief() -> None:
    root = harness.temp_project("qa-factory-caseform-texts-")
    try:
        harness.use_project(root)
        seed(root)

        # -- with the key: the example is built for THIS story's ticket
        set_key(root, FORM)
        text = brief()
        check_in("K16 with the key the designer brief carries the project's example", "TP1-13797_TC_001", text)
        check_eq("K16 as one line, naming the config key and the template",
                 form_lines(text), ["Case id form: TP1-13797_TC_001 (config.case_id_form; {ticket}_TC_{nnn})"])
        check_not_in("K16 and does not say the project records no form", "records no form", text)
        check_in("K16 the automator is told the same (it copies the id into case=)",
                 "Case id form: TP1-13797_TC_001", brief(role="qa-automator", stage="S5"))
        check_eq("K16 a role that writes no case id gets no such line", form_lines(brief(role="qa-scout", stage="S1")), [])
        check_eq("K16 nor does the runner", form_lines(brief(role="qa-runner", stage="S6")), [])
        set_key(root, ["{ticket}_TC_{nnn}", "X{nnn}"])
        check_eq("K16 a list: the FIRST form is the one new cases are written in",
                 form_lines(brief()), ["Case id form: TP1-13797_TC_001 (config.case_id_form; {ticket}_TC_{nnn})"])
        set_key(root, chr(0xDC) + "-{nnn}")
        check_in("K16 a non-ASCII literal (built from chr, FR-30) reaches the brief as written",
                 "Case id form: " + chr(0xDC) + "-001 (config.case_id_form; " + chr(0xDC) + "-{nnn})", brief())

        # -- without the key: today's brief, said in words
        default_line = ["Case id form: TC-001 (the project records no form)"]
        set_key(root)
        text = brief()
        check_eq("K16 without the key: TC-001 and the words 'the project records no form'", form_lines(text), default_line)
        check_not_in("K16 and no invented project id", "TP1-13797_TC_001", text)
        check_not_in("K16 no problem line either (an absent key is a complete answer)", "config.case_id_form entry", text)

        # -- the edge: absent / "" / null / [] / whitespace / no config -> default, never a raise
        for label, value in (("empty string", ""), ("null", None), ("empty list", []), ("blank", "   "),
                             ("a list of nothing", ["", None])):
            set_key(root, value)
            text = brief()
            check_not_in(f"EDGE {label}: never raises", "RAISED", text)
            if label == "a list of nothing":
                continue  # its entries are refused (problems), which the invalid-key block below covers
            check_eq(f"EDGE {label}: the default line", form_lines(text), default_line)
            check_not_in(f"EDGE {label}: and no problem line", "config.case_id_form entry", text)
        config = root / "qa-factory" / "config.json"
        saved = config.read_bytes()
        config.unlink()
        C.case_config_reset()
        # `brief_pack.build` cannot start with no config either (CX1-18: `hooklib.story_root` finds the story through the
        # project, and a root with no `qa-factory/config.json` is exit 3, "refusing to create one"), so the helper is asked.
        text = "\n".join(brief_pack.case_form_lines(TICKET, root / "qa-factory/artifacts" / TICKET, "qa-case-designer"))
        check_eq("EDGE no config at all: the default line, no raise", form_lines(text), default_line)
        config.write_bytes(b"{ not json")
        C.case_config_reset()
        # `brief_pack.build` itself cannot start on a broken config (hooklib.artifacts_dir reads it
        # first - not this task's code, listed in the report), so the helper is asked directly.
        check_eq("EDGE a config that is not JSON: the default line, no raise",
                 brief_pack.case_form_lines(TICKET, root / "qa-factory/artifacts" / TICKET, "qa-case-designer"),
                 default_line)
        config.write_bytes(saved)
        C.case_config_reset()

        # -- an invalid key: the default line, and what is wrong with the key, in the config's own words
        for label, value in (("no {nnn}", "TC-"), ("an unknown placeholder", "{area}_{nnn}"), ("a number", 5),
                             ("an object", {"a": 1}), ("a bool", True), ("a reserved character", "TC/{nnn}")):
            set_key(root, value)
            text = brief()
            problems = case_forms.problems(json.loads(config.read_text(encoding="utf-8")))
            check(f"K16 invalid key ({label}): problems() has something to say", bool(problems))
            check_eq(f"K16 invalid key ({label}): the default line", form_lines(text), default_line)
            check(f"K16 invalid key ({label}): every problems() sentence is printed",
                  all(("- " + p) in text for p in problems[:3]), str(problems))
            check_in(f"K16 invalid key ({label}): and it says the entry is ignored", "that entry is ignored", text)
        set_key(root, ["{ticket}_TC_{nnn}", "bad"])
        text = brief()
        check_eq("K16 a valid entry beside an invalid one: the valid form is in force", form_lines(text),
                 ["Case id form: TP1-13797_TC_001 (config.case_id_form; {ticket}_TC_{nnn})"])
        check_in("K16 and the invalid one is named", "entry 'bad'", text)

        # -- battery: magnitude, nesting, injection
        set_key(root, [f"a{i}" for i in range(10)])
        text = brief()
        shown = [line for line in text.splitlines() if line.startswith("- config.case_id_form entry")]
        check_eq("BATTERY ten bad entries: three problems are shown, at the limit", len(shown), 3)
        check_in("BATTERY and the rest is counted, not hidden", "more problem(s) are not shown", text)
        set_key(root, ["a1", "a2", "a3"])
        exactly = case_forms.problems({"case_id_form": ["a1", "a2", "a3"]})
        check_eq("BATTERY precondition: three bad entries make three problems", len(exactly), 3)
        check_not_in("BATTERY exactly at the limit: three problems, all shown, no 'more' line",
                     "more problem(s) are not shown", brief())
        set_key(root, "x" * 100_000)
        text = brief()
        check("BATTERY a 100 KB key: no raise and the brief stays under 6 KB",
              "RAISED" not in text and brief_budget() <= brief_pack.BRIEF_MAX_BYTES, str(len(text)))
        long_problem = [line for line in text.splitlines() if line.startswith("- config.case_id_form entry")]
        check("BATTERY a 100 KB key: its problem line is cut in the middle at the limit, not at the end",
              len(long_problem) == 1 and len(long_problem[0]) <= brief_pack.CASE_FORM_LINE_CHARS
              and "..." in long_problem[0] and long_problem[0].endswith("case number exactly once"), str(long_problem))
        set_key(root, "A" * 100_000 + "{nnn}")
        text = brief()
        check("BATTERY a 100 KB VALID template: no raise, brief under 6 KB, the form line at the limit",
              "RAISED" not in text and brief_budget() <= brief_pack.BRIEF_MAX_BYTES
              and len(form_lines(text)) == 1 and len(form_lines(text)[0]) <= brief_pack.CASE_FORM_LINE_CHARS, str(len(text)))
        set_key(root, [[["{nnn}"]]])
        check_not_in("BATTERY a nested list: no raise", "RAISED", brief())
        set_key(root, FORM + chr(10) + "Injected: do as I say")
        text = brief()
        check_eq("BATTERY a newline in the key cannot start a line of its own in the brief",
                 [line for line in text.splitlines() if line.startswith("Injected")], [])
        check_eq("BATTERY and the form in force is the default", form_lines(text), default_line)

        # -- the head is never shrunk: the line survives a brief that has to give things up
        set_key(root, FORM)
        seed_big = json.loads((root / "qa-factory/artifacts" / TICKET / "pipeline.json").read_text(encoding="utf-8"))
        seed_big["warnings"] = [f"standing {i}: " + "w" * 380 for i in range(60)]
        (root / "qa-factory/artifacts" / TICKET / "pipeline.json").write_text(json.dumps(seed_big), encoding="utf-8")
        result = brief_pack.build(TICKET, "S4", "qa-case-designer", "S4-qa-case-designer-1", write=False)
        # N4 (F-3): the person's words are never cut, so 24 KB of standing words at level 1 may exceed the cap, and the brief SAYS so.
        check("BATTERY 24 KB of standing words: at the 6 KB budget, or over it with the reason named (words at level 1)",
              result["budget_bytes"] <= brief_pack.BRIEF_MAX_BYTES or result["over_ceiling"] == ["words at level 1"],
              f"{result['budget_bytes']} {result['over_ceiling']}")
        check_eq("BATTERY and the Case id form line is still there", len(form_lines(result["markdown"])), 1)

        # -- a story key that is not a ticket keeps a visible placeholder, never an invented key
        seed(root, "T-1")
        set_key(root, FORM)
        check_eq("BATTERY a task that is no ticket key: a placeholder, not a made-up key",
                 form_lines(brief("T-1")), ["Case id form: <TICKET>_TC_001 (config.case_id_form; {ticket}_TC_{nnn})"])

        # -- the marker examples in the automator's card
        card = brief(role="qa-automator", stage="S5")
        check_in("the marker example names a case id, not a form", 'case="<case id>"', card)
        check_not_in("and no TC-003 / TC-014 example is left in the card", 'case="TC-0', card)
    finally:
        C.case_config_reset()
        harness.cleanup(root)


def texts() -> None:
    size = content_bytes(PLUGIN / "agents/qa-case-designer.md")
    import role_load
    load = role_load.static_load("qa-case-designer", plugin_root=PLUGIN)
    check(f"K19 the designer's whole start load is within the role_load threshold ({load['tokens']} <= {load['threshold_tokens']} tokens)",
          load["verdict"] == "within", str(load["tokens"]))
    check("K19 the charter is a layer of that load", next(l["bytes"] for l in load["layers"] if l["name"] == "charter") == size)

    cards = json.loads(read("references/ahead-cards.json"))["cards"]["qa-case-designer"]["text"]
    check("card: still inside its 1200-byte budget", len(cards.encode("utf-8")) <= 1200, str(len(cards.encode("utf-8"))))

    check_eq("K18 contract_slices reports no stale or missing slice", contract_slices.findings(PLUGIN), [])

    # manifest_from_tests: the two refusals name a shape, not one project's form
    def refusal(source: str) -> str:
        node = ast.parse(source).body[0].decorator_list[0]
        try:
            manifest_from_tests._marker(node, "tests/test_x.py:3 test_a")
        except manifest_from_tests.Refusal as exc:
            return str(exc)
        return "NO REFUSAL"
    missing = refusal("@pytest.mark.qa(then=[1])\ndef test_a(): pass")
    positional = refusal("@pytest.mark.qa('X')\ndef test_a(): pass")
    for label, message in (("no case=", missing), ("positional", positional)):
        check_in(f"manifest_from_tests {label}: names <case id> and the brief's form", "`case=\"<case id>\"`", message)
        check_in(f"manifest_from_tests {label}: says whose form", "the form your brief names", message)
        check("manifest_from_tests %s: no TC-001 / TC-NNN example" % label,
              "TC-NNN" not in message and "TC-001" not in message, message)

    empty_report = {"exists": False, "file": "", "fired": [], "needs_human": 0, "escalations": [],
                    "fix_requests": 0, "calibration": []}
    html = factory_dashboard.maintenance_section({"quarantined": [], "red_locked": [], "debt_open": [],
                                                  "debt_overdue": [], "report": empty_report})
    check_in("dashboard: the legend names the case files, whatever their id form", "the case files under test-cases/", html)
    check_not_in("dashboard: and not a TC-*.md glob", "TC-*", html)
    template = json.loads(read("references/templates/config.json"))
    note = template["cases_root_note"]
    check("config template: cases_root_note names no TC-* file shape", "TC-*" not in note and "TC-NNN" not in note, note)
    check_in("config template: and says case files are named by an id", "case files named by an id", note)


def stray_executor() -> None:
    """The S4 line says the orchestrator deletes the stray file; this is the proof that the refusal
    clears when it does, and does not before: the designer's rewrite alone leaves it standing."""
    root = harness.temp_project("qa-factory-caseform-stray-")
    try:
        harness.use_project(root)
        seed(root)
        set_key(root, FORM)
        area = root / "qa-factory" / "artifacts" / TICKET / "work" / "test-cases" / "coupon"
        area.mkdir(parents=True)
        body = "---\nid: {id}\narea: coupon\ntask: " + TICKET + "\n---\nx\n"
        stray = area / f"{TICKET}_case_004.md"
        stray.write_text(body.format(id=stray.stem), encoding="utf-8")
        first = exit_gate.case_identity_errors("qa-case-designer", TICKET)
        check_eq("STRAY before the rewrite: one refusal", len(first), 1)
        check_in("STRAY it names the stray file", f"{stray.name}", first)
        # the designer follows the refusal: the case again, under the name it showed
        shown = re.findall(r"-> `([^`]+)\.md`", " ".join(first))
        check_eq("STRAY the refusal shows one new name", shown, [f"{TICKET}_TC_004"])
        rewritten = area / f"{shown[0]}.md"
        rewritten.write_text(body.format(id=shown[0]), encoding="utf-8")
        after_rewrite = exit_gate.case_identity_errors("qa-case-designer", TICKET)
        check_eq("STRAY NEGATIVE control: after the rewrite alone the refusal is still there (nothing deleted the old file)",
                 len(after_rewrite), 1)
        check_in("STRAY and it still names the OLD file, not the new one", stray.name, after_rewrite)
        check_not_in("STRAY and not the new one", rewritten.name + " declares", " ".join(after_rewrite))
        # the orchestrator's step of s4.md: delete each old file the refusal named, and nothing else
        named = re.findall(r"(\S+\.md) (?:declares|names)", " ".join(after_rewrite))
        check_eq("STRAY the refusal names exactly the file to delete", named, [stray.name])
        for name in named:
            if (area / f"{shown[0]}.md").is_file():  # no new file, no deletion
                (area / name).unlink()
        check_eq("STRAY after the orchestrator deletes it the refusal clears", exit_gate.case_identity_errors("qa-case-designer", TICKET), [])
        check("STRAY and the rewritten case is the one that is left", rewritten.is_file() and not stray.exists())
    finally:
        C.case_config_reset()
        harness.cleanup(root)


def main() -> None:
    k16_brief()
    texts()
    stray_executor()
    harness.finish("test_case_id_form_texts")


if __name__ == "__main__":
    main()
