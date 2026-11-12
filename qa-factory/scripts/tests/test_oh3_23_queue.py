"""OH3-23: the t-1201 queue (Q2, Q3, Q4, Q6, Q8, Q9, Q10, Q14). Keys H1-H4, H6-H8 of the spec's section 6; H5 is removed.

H1 Q2: the three audit readers of the deferred table read a variant heading and a mixed-case column. H2 one walker. H3 Q3: one marker
pattern, any case: the audit finds it, `resolve` refuses until it is named, then removes it. H4 Q6: the three config states and an
unreadable register are said, never raised. H6 Q9: `sizing.compute` is byte-identical to the output pinned BEFORE the split.
H7 Q10: the `deferred` line says the row SHOULD be in the backlog. H8 Q14: the dead reader is gone.
Q4 and Q8 are closed in the report (no code); H5 returns only if a grep finds a list of the six section ids in code.

Run: `python -B test_oh3_23_queue.py`. No Cyrillic here (the package is English, FR-30).
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import audit_factory as A  # noqa: E402
import project_decisions as PD  # noqa: E402
import runtime_paths as RP  # noqa: E402
import sizing  # noqa: E402

NL = "\n"
VARIANT = "## Deferred Decisions (gates)"
DD_TABLE = ("| ID | Essence + where the marker is | ASKED | status |" + NL + "|---|---|---|---|" + NL
            + "| DD-1 | app_repo not given | which repositories hold the application? | open |" + NL
            + "| DD-2 | stand url for the environment | | open |" + NL)
MARKER = "[DEFERRED: risk areas not named]"
LOWER = "[deferred: risk areas not named]"
ESSENCE = "risk areas not named"

# H6: `sizing.compute` output (key order included) of five inputs, hashed BEFORE the Q9 split (the first four in the commit that
# precedes it; "branches" from the code at ff448aca). A refactor of `compute` moves none of them; a helper that reorders
# `reasoning` (row notes, unverifiable lines, defect note, precedent line) moves "branches".
H6_PINNED = {
    # re-pinned by GM2-2 (t-1927): the O7 rewrite renamed the keys and words the fixtures and the outputs carry; digests from `digest(sizing.compute(...))`
    "15045-weighted": "233fdc859162389095fcc0d04c625d5dc8607ded44c047d1026e9b04597c5cd4",
    "12586": "34fcf8e608a6b167dd069e980b83048b82f9028c902ca745f9f1b3e0db2e02cc",
    "14857": "eb2f3f5559b1d973472a4628c2939850b3b83b311847ef606e54d335636416ab",     # re-pinned by GM2-7 (the register is synthetic now)
    "empty": "967ede49b53f9a8ef8cddef44786440d11c217df074020fff32f4a7fbc98f1b1",
    "branches": "8454926d35d561f12acf921d404e20d9388504d870432a6fe836f85c711227d9",     # GM2-2: the ledger task key in the "nearest precedent" line is TP1-1 now
}
# Re-pinned by OH3-34 (f8e0da73, bfe7fe23, 670dd8be): a P1 area bumps a row by the surface it names, never by requirement words
# (the branch input loses its "R-1: area" line: 6 -> 5), and sizing.json carries the areas' state (every output gains it).
# Door for a deliberate change (F-5): a changed `reasoning` word or `compute` field turns these rows red on purpose; read the JSON diff
# of the two outputs, and only when it is the change you meant, re-pin from `digest(sizing.compute(...))`.
H6_REGISTER = ("## Register" + NL + NL + "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |" + NL
               + "|---|---|---|---|---|---|---|---|" + NL
               + "| R-1 | budgets spend tracking shown | story | - | yes | - | diff:src/a.py:1 | degraded |" + NL
               + "| R-2 | a second requirement | story | - | yes | - | diff:src/b.py:1 | |" + NL
               + "| R-3 | a third requirement | story | - | yes | - | diff:src/c.py:1 | bogus |" + NL
               + "| R-4 | a fourth requirement | story | - | yes | - | diff:src/d.py:1 | cosmetic |" + NL
               + "| R-5 | not checkable | story | - | no | - | none | cosmetic |" + NL)
H6_STRATEGY = "# s" + NL + NL + "**P1 areas.** budgets, spend tracking" + NL


def digest(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=False, ensure_ascii=False).encode("utf-8")).hexdigest()


def h1_three_audits_read_a_variant_table() -> None:
    root = temp_dir("qa-oh3-23-h1-")
    try:
        backlog = root / "qa-factory" / "factory-backlog.md"
        backlog.parent.mkdir(parents=True)
        text = "# Backlog" + NL + NL + VARIANT + NL + NL + DD_TABLE
        backlog.write_text(text, encoding="utf-8")
        table = PD.deferred_table(text)
        check_eq("H1: deferred_table reads the variant heading, lower-cased columns and both rows",
                 (table["headings"], table["columns"], [r[0] for r in table["rows"]]),
                 ([VARIANT], ["id", "essence + where the marker is", "asked", "status"], ["DD-1", "DD-2"]))
        found = A.deferred_rows_without_a_question(backlog)
        check_eq("H1: the `asked` audit finds the row with an empty `ASKED` cell, and only it", [("DD-2" in f, "DD-1" in f) for f in found], [(True, False)])
        profile = root / "qa-factory" / "project-profile.md"
        profile.write_text("# profile" + NL, encoding="utf-8")
        missing = A.required_facts_without_a_deferral({}, backlog, profile)
        check_eq("H1: the required-facts audit sees the two deferrals under the variant heading: only topics 3 and 7 are missing", len(missing), 2)
        check_not_in("H1: ... the application repositories are deferred", "application repositories", missing)
        check_not_in("H1: ... the environment is deferred", "environment access", missing)
        marker_file = root / "qa-factory" / "strategy" / "test-strategy.md"
        marker_file.parent.mkdir()
        marker_file.write_text("[DEFERRED: nothing pairs this]" + NL, encoding="utf-8")
        lines = A.a13_unpaired_markers(A.a13_marker_list([marker_file]), backlog, text, root)
        check_eq("H1: the marker audit names the variant heading as the reason", (len(lines), "heading" in lines[0] if lines else False), (1, True))
        check_eq("H1: no section, empty table and a header only give empties (the audits stay quiet)",
                 [PD.deferred_table(t)["rows"] for t in ("", "# x" + NL, VARIANT + NL, VARIANT + NL + NL + DD_TABLE.split(NL)[0] + NL + "|---|---|---|---|" + NL)],
                 [[], [], [], []])
        twice = PD.deferred_table(text + NL + "## deferred decisions again" + NL + NL + DD_TABLE.replace("DD-1", "DD-3").replace("DD-2", "DD-4"))
        check_eq("H1: two headings: both are named and the rows of both are kept", (len(twice["headings"]), [r[0] for r in twice["rows"]]),
                 (2, ["DD-1", "DD-2", "DD-3", "DD-4"]))
        opening = PD.deferred_table(VARIANT + NL + NL + DD_TABLE + NL + VARIANT + " (b)" + NL + NL + "| DD-7 | stand url unknown | | open |" + NL + NL
                                    + VARIANT + " (c)" + NL + NL + DD_TABLE.replace("DD-1", "DD-8").replace("DD-2", "DD-9"))
        check_eq("H1: a DD row opening a later section is a row, not a header; the header row of a later section is not a row",
                 [r[0] for r in opening["rows"]], ["DD-1", "DD-2", "DD-7", "DD-8", "DD-9"])
        check_eq("H1: ... and the first table's header stays the columns", opening["columns"][0], "id")
        check_eq("H1: the writer's reader keeps the exact heading: the variant is not its table", PD.parse_rows(text), [])
    finally:
        cleanup(root)


def h2_one_walker() -> None:
    walk = re.compile(r"""startswith\(\s*["']## deferred decisions""", re.I)       # a heading walked by its prefix, in any case
    check_eq("H2: audit_factory.py holds no walk of the deferred-decisions heading of its own", len(walk.findall(
        (SCRIPTS / "audit_factory.py").read_text(encoding="utf-8"))), 0)
    check_eq("H2: control: the same search finds the walk in the shape the audit had", len(walk.findall(
        'in_section = line.strip().lower().startswith("## deferred decisions")')), 1)
    check_eq("H2: the one reader walks the prefix by its constant, once", (SCRIPTS / "project_decisions.py").read_text(
        encoding="utf-8").count("startswith(DEFERRED_PREFIX)"), 1)


def _marker_project() -> Path:
    root = temp_project("qa-oh3-23-h3-")
    strategy = root / "qa-factory" / "strategy"
    strategy.mkdir(parents=True, exist_ok=True)
    (strategy / "test-strategy.md").write_text(f"# s{NL}{NL}{MARKER}{NL}", encoding="utf-8")
    (strategy / "aspect-profile.md").write_text(f"# a{NL}{NL}{LOWER}{NL}", encoding="utf-8")
    return root


def h3_one_marker_in_any_case() -> None:
    root = _marker_project()
    try:
        strategy = root / "qa-factory" / "strategy"
        found = A.a13_marker_list([strategy / "aspect-profile.md"])
        check_eq("H3: the audit finds `[deferred: x]`", [e for _f, e in found], [ESSENCE])
        bare = strategy / "bare.md"
        bare.write_text("[Deferred:]" + NL + "[DEFERRED:]" + NL, encoding="utf-8")
        PD.upsert(root, field_refs=["doc:strategy/test-strategy.md"], essence=ESSENCE, asked="batch 1: q", scope="project", owner="user")
        backlog = root / "qa-factory" / "factory-backlog.md"
        text = backlog.read_text(encoding="utf-8")
        check_eq("H3: a lower-case marker pairs with its open row", A.a13_unpaired_markers(found, backlog, text, root), [])
        said = A.a13_unpaired_markers(A.a13_marker_list([bare]), backlog, text, root)
        check_eq("H3: a bare marker in either spelling is still reported (no essence)", (len(said), all("no essence" in s for s in said)), (2, True))
        try:
            PD.resolve(root, "DD-1", "answered", "batch 2", None, ["qa-factory/strategy/test-strategy.md"], MARKER)
            refusal = ""
        except ValueError as exc:
            refusal = str(exc)
        check_eq("H3: resolve with the exact token named, a case variant live elsewhere: refused, in the refusal's own form",
                 refusal, "paired deferred marker remains; name every marker file in this resolution")
        check_in("H3: ... and nothing was removed", MARKER, (strategy / "test-strategy.md").read_text(encoding="utf-8"))
        closed = PD.resolve(root, "DD-1", "answered", "batch 2", None,
                            ["qa-factory/strategy/test-strategy.md", "qa-factory/strategy/aspect-profile.md"], MARKER)
        check_eq("H3: resolve with both files named closes the row", closed["status"], "closed")
        left = [(strategy / n).read_text(encoding="utf-8") for n in ("test-strategy.md", "aspect-profile.md")]
        check_eq("H3: ... and removes the marker in either spelling", [bool(PD.DEFERRED_MARKER.search(t)) for t in left], [False, False])
    finally:
        cleanup(root)


def _compute_in(project: Path, config=None, register="rows") -> dict:
    """`sizing.compute` of a one-row story under `project`, whose config is `config` (None: no file; a Path: a folder) and whose register is
    `rows` (the normal one) or a folder."""
    (project / "qa-factory").mkdir(parents=True, exist_ok=True)
    cfg = project / "qa-factory" / "config.json"
    if isinstance(config, Path):
        config.mkdir()
    elif config is not None:
        cfg.write_text(config, encoding="utf-8")
    task = project / "qa-factory" / "artifacts" / "T-1"
    (task / "work").mkdir(parents=True)
    reg = task / "work" / "requirements-register.md"
    if register == "folder":
        reg.mkdir()
    else:
        reg.write_text("## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable |\n|---|---|---|---|---|---|---|\n"
                       "| R-1 | a requirement | story | - | yes | - | diff:src/a.py:1 |\n", encoding="utf-8")
    return sizing.compute(task, project)


def h4_config_and_register_states() -> None:
    lines, results = {}, {}
    for label, config in (("absent", None), ("invalid JSON", "{"), ("a list", "[1, 2]"), ("an empty object", "{}"), ("a folder", "folder")):
        root = temp_dir("qa-oh3-23-h4-")
        try:
            try:
                result = _compute_in(root, (root / "qa-factory" / "config.json") if config == "folder" else config)
            except Exception as exc:  # noqa: BLE001 - a raise is the named failure
                check(f"H4: config {label}: no exception", False, repr(exc))
                continue
            results[label] = result
            lines[label] = [l for l in result["reasoning"] if "config.json" in l]
        finally:
            cleanup(root)
    for label, want in (("absent", "no qa-factory/config.json under"), ("invalid JSON", "could not be read (JSONDecodeError)"),
                        ("a list", "is a JSON list, not an object"), ("an empty object", "is an empty object"),
                        ("a folder", "could not be read (")):
        check_eq(f"H4: config {label}: one line, and it says {want!r}", (len(lines.get(label, [])), want in " ".join(lines.get(label, []))), (1, True))
    check_eq("H4: ... and in every state the weights are the defaults, the story is sized",
             sorted({(r["config"]["weights_source"], r["verifiable_count"]) for r in results.values()}), [("default", 1)])
    root = temp_dir("qa-oh3-23-h4-")
    try:
        result = _compute_in(root, "{}", register="folder")
        text = " ".join(result["reasoning"])
        check_in("H4: a register that is a folder says it could not be read", "work/requirements-register.md could not be read (", text)
        check_not_in("H4: ... and is not told as `no register`", "no work/requirements-register.md", text)
        check_eq("H4: ... it is computed as empty", result["verifiable_count"], 0)
    finally:
        cleanup(root)
    root = temp_dir("qa-oh3-23-h4-")
    try:
        (root / "qa-factory").mkdir()
        (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        check_in("H4: an absent register is still `no work/requirements-register.md`", "no work/requirements-register.md",
                 sizing.compute(task, root)["reasoning"])
    finally:
        cleanup(root)


def h6_compute_is_unchanged_by_the_split() -> None:
    for key, story in (("15045-weighted", "TP1-15045"), ("12586", "TP1-12586"), ("14857", "TP1-14857")):
        project = FIXTURES / f"sizing-{key}" / "qa-factory"
        check_eq(f"H6: compute on sizing-{key} is byte-identical to the pre-split output",
                 digest(sizing.compute(project / "stories" / story, project.parent)), H6_PINNED[key])
    root = temp_dir("qa-oh3-23-b-")
    try:
        # a P1 area, row notes (no impact, a bogus impact), an unverifiable row, a defect ticket of more than 3 rows and a ledger:
        # the branches of `_weigh_rows`, `_apply_reducers` and `_precedent_line` the three fixtures above do not reach
        (root / "qa-factory" / "strategy").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text('{"project": "t"}', encoding="utf-8")  # not empty: no line carries the temp path
        (root / "qa-factory" / "strategy" / "test-strategy.md").write_text(H6_STRATEGY, encoding="utf-8")
        task = root / "qa-factory" / "artifacts" / "T-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(H6_REGISTER, encoding="utf-8")
        ledger = RP.record_new(root, "estimation-ledger.jsonl")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({"task": "TP1-1", "forecast": {"computed_budget": 20}, "drivers": ["budgets spend tracking"]}) + NL,
                          encoding="utf-8")
        result = sizing.compute(task, root, "bug")
        check_eq("H6: the fifth input reaches the branches it is there for",
                 (len([l for l in result["reasoning"] if l.startswith(("R-1: area", "R-2: no impact", "R-3: impact value", "R-5:", "defect ticket", "nearest"))]),
                  result["reducers_applied"][-1]["name"]), (5, "defect-cap"))
        check_eq("H6: compute on the branch input is byte-identical to the pre-split output", digest(result), H6_PINNED["branches"])
    finally:
        cleanup(root)
    root = temp_dir("qa-oh3-23-")
    try:
        task = root / "T-0"
        (task / "work").mkdir(parents=True)
        check_eq("H6: compute on an empty task is byte-identical to the pre-split output",
                 digest(sizing.compute(task, None)), H6_PINNED["empty"])
    finally:
        cleanup(root)


def h7_the_deferred_line_does_not_claim_a_row() -> None:
    root = temp_dir("qa-oh3-23-h7-")
    try:
        strategy = root / "qa-factory" / "strategy"
        strategy.mkdir(parents=True)
        (strategy / "test-strategy.md").write_text(sizing.RISK_AREAS_DEFERRED_MARKER + NL, encoding="utf-8")
        result = _compute_in(root, "{}")
        line = next((l for l in result["reasoning"] if l.startswith("risk areas deferred")), "")
        check_in("H7: the line says the row SHOULD be in qa-factory/factory-backlog.md", "and its row should be in qa-factory/factory-backlog.md", line)
        check_not_in("H7: ... and does not claim a row it did not read", "its row is in", line)
    finally:
        cleanup(root)


def h8_the_dead_reader_is_gone() -> None:
    check("H8: sizing has no read_strategy_p1_areas", not hasattr(sizing, "read_strategy_p1_areas"))
    check("H8: ... strategy_area_state, the reader it was a member of, stays", hasattr(sizing, "strategy_area_state"))


def main() -> int:
    h1_three_audits_read_a_variant_table()
    h2_one_walker()
    h3_one_marker_in_any_case()
    h4_config_and_register_states()
    h6_compute_is_unchanged_by_the_split()
    h7_the_deferred_line_does_not_claim_a_row()
    h8_the_dead_reader_is_gone()
    return finish("test_oh3_23_queue")


if __name__ == "__main__":
    main()
