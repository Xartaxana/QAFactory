"""OH3-3: `sizing.py` reads the impact scale through `grammar.impact_scale` (AR-13), and says what it dropped (AR-28).

Keys O1..O6 of the node (`docs/tasks/specs/r0107-s4b2-...`, section 2): a project with a complete map gets the weights it always got; a
project with no map or a malformed entry gets the package's classes AND a line saying so; no weight changes without a reasoning line.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, FIXTURES, check, check_eq, check_in, cleanup, finish, temp_project)  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import grammar as G  # noqa: E402
import sizing as S  # noqa: E402

HEAD = ("## Register\n\n"
        "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
        "|---|---|---|---|---|---|---|---|\n")
ROW = "| R-1 | Budgets dashboard totals stay correct after edit | ac | — | yes | AC-1 | diff:a.py:1 | %s |\n"
GOOD = {"priority": "P1", "severity": "major"}


def sized(config, impact: str) -> dict:
    """compute() over a temp project whose config is `config` (a dict, or a ready JSON text) and whose one row has class `impact`
    (`""`: the cell is empty)."""
    text = config if isinstance(config, str) else json.dumps(config)
    project = temp_project("qa-oh33-")
    try:
        (project / "qa-factory" / "config.json").write_text(text, encoding="utf-8")
        task = project / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True)
        (task / "work" / "requirements-register.md").write_text(HEAD + ROW % impact, encoding="utf-8")
        return S.compute(task, project)
    finally:
        cleanup(project)


def weight_and_notes(config, impact: str) -> tuple:
    result = sized(config, impact)
    return result["requirements"][0]["weight"], [l for l in result["reasoning"] if l.startswith("R-1:")], result["reasoning"]


def scale_lines(reasoning: list) -> list:
    return [l for l in reasoning if l.startswith("config.impact_scale ")]


def main() -> int:
    # O1: the complete map moves nothing (the budget of §0.5 of the S4b spec).
    project = FIXTURES / "sizing-15045-weighted" / "qa-factory"
    weighted = S.compute(project / "stories" / "TP1-15045", project.parent)
    check_eq("O1: sizing-15045-weighted keeps computed_budget 32", weighted["computed_budget"], 32)
    check_eq("O1: ... and no whole-map line", scale_lines(weighted["reasoning"]), [])

    # O2: the table of the spec, one row each.
    complete = {"impact_scale": dict(G.IMPACT_SCALE)}
    for cls, tier in (("data-loss", 1.6), ("degraded", 1.0), ("cosmetic", 0.6)):
        weight, notes, reasoning = weight_and_notes(complete, cls)
        check_eq(f"O2: a complete map, class {cls}: the scale's weight, no note, no whole-map line", (weight, notes, scale_lines(reasoning)), (tier, [], []))
    for label, config in (("absent", {"sizing": {}}), ("an empty map", {"impact_scale": {}}), ("a string", {"impact_scale": "x"}),
                          ("a number", {"impact_scale": 5}), ("a list", {"impact_scale": [1]})):
        got = [weight_and_notes(config, cls) for cls in ("degraded", "data-loss", "cosmetic")]
        check_eq(f"O2: whole impact_scale {label}: degraded 1.0, data-loss 1.6, cosmetic 0.6 (the package's classes)", [g[0] for g in got], [1.0, 1.6, 0.6])
        check_eq("O2: ... one whole-map line, and no per-row note", (len(scale_lines(got[0][2])), got[0][1]), (1, []))
        check_in("O2: ... saying the package's classes apply", "the package's default classes apply", scale_lines(got[0][2])[0])
    for label, entry in (("a string", "x"), ("a number", 5), ("null", None)):
        weight, notes, reasoning = weight_and_notes({"impact_scale": {"degraded": entry}}, "degraded")
        check_eq(f"O2: degraded entry that is {label}: 1.0 and a per-row note", (weight, len(notes), scale_lines(reasoning)), (1.0, 1, []))
        check_in(f"O2: ... naming the class and the weight ({label})", "config.impact_scale['degraded'] is a ", notes[0])
        check_in("O2: ... and the default", "weight 1.0 (P2 default)", notes[0])
    weight, notes, _ = weight_and_notes({"impact_scale": {"money": "x"}}, "money")
    check_eq("O2: money entry that is a string: the package's 1.6 and a note that says default", (weight, len(notes)), (1.6, 1))
    check_in("O2: ... 'default'", "weight 1.6 (P0 default)", notes[0])
    weight, notes, _ = weight_and_notes({"impact_scale": {"degraded": {"severity": "minor"}}}, "degraded")
    check_eq("O2: degraded without priority: 1.0 and a note (the finding's K6a-5)", (weight, len(notes)), (1.0, 1))
    check_in("O2: ... says what is missing", "is a map without priority", notes[0])
    weight, notes, _ = weight_and_notes({"impact_scale": {"degraded": {"priority": 3}}}, "degraded")
    check_eq("O2: degraded with priority 3 and no severity: 1.0 and a note", (weight, len(notes)), (1.0, 1))
    weight, notes, _ = weight_and_notes({"impact_scale": {"money": {"priority": "P2"}}}, "money")
    check_eq("O2: money without severity: the map's word is dropped LOUDLY: 1.6 and a note", (weight, len(notes)), (1.6, 1))
    check_in("O2: ... says what is missing", "is a map without severity", notes[0])
    weight, notes, _ = weight_and_notes({"impact_scale": {"x": {"priority": "P9", "severity": "y"}}}, "x")
    check_eq("O2: a priority that has no weight: P2 and a NAMED note (was silent)", (weight, len(notes)), (1.0, 1))
    check_in("O2: ... names the priority", "maps to priority 'P9', which has no weight", notes[0])
    weight, notes, _ = weight_and_notes({"impact_scale": {"custom": "x"}}, "custom")
    check_eq("O2: custom class with a bad entry: 1.0 and the 'outside' note", (weight, len(notes)), (1.0, 1))
    check_in("O2: ... outside", "is outside config.impact_scale", notes[0])
    weight, notes, reasoning = weight_and_notes({"impact_scale": {"Degraded": GOOD}}, "degraded")
    check_eq("O2: a differently-cased valid class does not match (case stays exact): default row, no note", (weight, notes, scale_lines(reasoning)), (1.0, [], []))
    weight, notes, _ = weight_and_notes(complete, "")
    check_eq("O2: no impact cell: 'no impact class recorded', P2", (weight, len(notes)), (1.0, 1))
    check_in("O2: ... said", "no impact class recorded", notes[0])
    weight, notes, _ = weight_and_notes({"impact_scale": {"degraded": GOOD}}, "degraded")
    check_eq("O2: a valid override replaces the class: P1 1.3, no note", (weight, notes), (1.3, []))

    # O2 (GW1-10 F-2): a PARTIAL map; a class it does not mention keeps the package's row, and a weight that moves says so.
    partial = {"impact_scale": {"degraded": {"priority": "P2", "severity": "minor"}}}
    for cls, tier in (("data-loss", 1.6), ("cosmetic", 0.6)):
        weight, notes, _ = weight_and_notes(partial, cls)
        check_eq(f"O2 F-2: partial map, class {cls} not in it: the package's weight {tier} and ONE note", (weight, len(notes)), (tier, 1))
        check_in(f"O2 F-2: ... naming the class and the weight ({cls})", f"class '{cls}' is not in config.impact_scale — the package's weight {tier}", notes[0])
    weight, notes, _ = weight_and_notes(partial, "degraded")
    check_eq("O2 F-2: partial map, the class it holds (P2): no note", (weight, notes), (1.0, []))
    check_eq("O2 F-2: grammar names the unmapped classes of a partial map, none for a whole-map situation",
             (sorted(G.impact_scale_unmapped(partial)), G.impact_scale_unmapped({}), G.impact_scale_unmapped({"impact_scale": {}})),
             (sorted(set(G.IMPACT_SCALE) - {"degraded"}), set(), set()))
    # O2 (GW1-10 F-5): a null or empty priority is not a P2 the project chose
    for label, value in (("null", None), ("empty", "")):
        weight, notes, _ = weight_and_notes({"impact_scale": {"money": {"priority": value, "severity": "x"}}}, "money")
        check_eq(f"O2 F-5: money with a {label} priority: P2 1.0 and ONE note", (weight, len(notes)), (1.0, 1))
        check_in(f"O2 F-5: ... naming the class and the empty priority ({label})", "config.impact_scale['money'] has an empty priority", notes[0])

    # O3: one reader. No `impact_scale` read of the config in sizing.py, no old helper.
    source = (SCRIPTS / "sizing.py").read_text(encoding="utf-8")
    reads = re.findall(r"""(?:\[|\.get\()\s*["']impact_scale["']""", source)
    check_eq("O3: sizing.py reads the config key 'impact_scale' nowhere (cfg[...] and .get( alike)", reads, [])
    check("O3: no impact_scale_of", "impact_scale_of" not in source)
    check("O3: no impact_scale_problem( (the singular helper)", not re.search(r"impact_scale_problem\b", source))
    check("O3: positive control: validate_artifacts.py still reads through grammar", "G.impact_scale(" in (SCRIPTS / "validate_artifacts.py").read_text(encoding="utf-8"))

    # O4: the problems are the merge's own drops (one rule).
    config = {"impact_scale": {"money": "x", "degraded": {"priority": "P3", "severity": "minor"}, "access": {"severity": "minor"}, "novel": 7}}
    problems = G.impact_scale_problems(config)
    merged = G.impact_scale(config)
    check_eq("O4: every dropped class is in problems, no kept class is", sorted(problems), ["access", "money", "novel"])
    check_eq("O4: ... and a dropped class keeps the package row in the merge", (merged["money"], merged["access"], "novel" in merged),
             (G.IMPACT_SCALE["money"], G.IMPACT_SCALE["access"], False))
    check_eq("O4: ... and a kept class is the project's", merged["degraded"]["priority"], "P3")

    # O6: the whole-map line reads the raw value, not the merged scale.
    for label, config in (("absent", {}), ("{}", {"impact_scale": {}}), ("string", {"impact_scale": "x"}), ("number", {"impact_scale": 5}),
                          ("list", {"impact_scale": [1]})):
        line = S.impact_scale_line(config)
        check(f"O6: {label}: the line prints with the new tail", line.startswith("config.impact_scale ") and line.endswith("— the package's default classes apply"), line)
    check_eq("O6: a complete map: no line", S.impact_scale_line(complete), "")
    check_eq("O6: absent, through compute(): exactly the key of K6a-4", sized({"sizing": {}}, "degraded")["reasoning"].count("config.impact_scale is absent — the package's default classes apply"), 1)

    # O5: architecture.md quotes by name.
    arch = (SCRIPTS.parent / "design" / "architecture.md").read_text(encoding="utf-8")
    breakage = [l for l in arch.splitlines() if l.startswith("- Breakage: commit 28fc7170")]
    check_eq("O5: the AR-22 Breakage line exists once", len(breakage), 1)
    check_in("O5: ... it names strategy_area_state", "strategy_area_state", breakage[0] if breakage else "")
    check("O5: ... and carries no ':478'", ":478" not in (breakage[0] if breakage else ":478"))
    return finish("test_sizing_impact_scale")


if __name__ == "__main__":
    sys.exit(main())
