"""The case field `alternatives` (TQ1-25, t-739 + t-750): the one reader, the one validator, the validator path, the texts.

Pure contract functions (K1-K8d) and the validator on a temp case file (K9, with its date cutoff). The doc keys K-T1..K-T5
and B-1 (the role-text phrases) moved to design/role-rules.json.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check_eq, check_in, finish, temp_dir  # noqa: E402

import contract as C  # noqa: E402
import validate_artifacts as V  # noqa: E402

GOOD = '[{"id": "ALT-1", "then": 2, "reading": "the stamp is taken at completion", "ref": "R-2"}]'
THENS = [1, 2]


def errs(raw, thens=THENS, **kw) -> list:
    return C.alternatives_errors("TC-1.md", raw, thens, **kw)


def only(label: str, raw, field: str, **kw) -> None:
    found = errs(raw, **kw)
    check_eq(f"{label}: exactly one error", len(found), 1)
    check_in(f"{label}: the error starts `TC-1.md: FORM - ` and names `{field}`", f"TC-1.md: FORM - alternatives `{field}`"
             if field != "key" else "TC-1.md: FORM - `alternatives` must be ONE line", found[0] if found else "")


def item(**over) -> str:
    base = {"id": "ALT-1", "then": 2, "reading": "the stamp is taken at completion", "ref": "R-2"}
    base.update(over)
    base = {k: v for k, v in base.items() if v is not ...}
    import json
    return json.dumps([base])


def contract_functions() -> None:
    check_eq("K1 absent -> []", errs(None), [])
    check_eq("K2 `[]` -> []", errs("[]"), [])
    check_eq("K3 well-formed -> []", errs(GOOD), [])
    only("K4 id not ALT-n", item(id="A-1"), "id")
    only("K4 id repeated", '[{"id": "ALT-1", "then": 2, "reading": "a", "ref": "R-2"}, '
         '{"id": "ALT-1", "then": 1, "reading": "b", "ref": "R-2"}]', "id")
    only("K4 then not an int", item(then="2"), "then")
    only("K4 reading empty after strip", item(reading="   "), "reading")
    only("K4 reading not a string", item(reading=5), "reading")
    only("K4 ref absent", item(ref=...), "ref")
    only("K4 ref not R-n or Qn", item(ref="X-1"), "ref")
    found = errs('[{"id": "ALT-1", "then": 2, "reading": "a  b", "ref": "R-2"}, '
                 '{"id": "ALT-2", "then": 2, "reading": "a b", "ref": "R-2"}]')
    check_eq("K4 two items with the same then and the same reading (whitespace folded): one error", len(found), 1)
    check_eq("K5 reading of 300 characters is ok", errs(item(reading="r" * 300)), [])
    only("K5 reading of 301 characters", item(reading="r" * 301), "reading")
    found = errs(item(then=5))
    check_in("K6 a then past the list: the error lists the numbers present", "(this case has 1, 2)", found[0] if found else "")
    check_eq("K7 ALT-999 ok", errs(item(id="ALT-999")), [])
    only("K7 ALT-1000", item(id="ALT-1000"), "id")
    only("K7 ALT-0 (the form says 1..999)", item(id="ALT-0"), "id")
    only("K7 alt-1 (case matters)", item(id="alt-1"), "id")
    for raw in ("not json", "", "{}", "[1]", '[{"id": "ALT-1"'):
        found = errs(raw)
        check_eq(f"K8 {raw!r}: ONE error, never an exception", len(found), 1)
        check_in(f"K8 {raw!r}: it names the shape", "ONE line of JSON", found[0])
    only("K8b `then: true` is not an int", item(then=True), "then")
    only("K8c `ref: Q-1`", item(ref="Q-1"), "ref")
    check_eq("K8c `ref: Q7` is ok", errs(item(ref="Q7")), [])
    only("K8d R-9 with known_r {R-1}", item(ref="R-9"), "ref", known_r={"R-1"})
    check_eq("K8d R-9 with known_r None -> ok (shape only)", errs(item(ref="R-9"), known_r=None), [])
    only("K8d Q9 with questions {Q7}", item(ref="Q9"), "ref", questions={"Q7": {}})
    check_eq("K8d Q7 with questions {Q7} -> ok", errs(item(ref="Q7"), questions={"Q7": {}}), [])
    # the reader: absent / empty / well-formed
    check_eq("reader: absent key", C.alternatives_from_text("---\nid: x\n---\n# x\n"), (None, ""))
    items, problem = C.alternatives_from_text(f"---\nid: x\nalternatives: {GOOD}\n---\n# x\n")
    check_eq("reader: well-formed", (len(items or []), problem), (1, ""))
    check_eq("reader: an empty value is a problem, not an absence", C.alternatives_from_text("---\nalternatives:\n---\n")[1],
             "the value is empty")


def the_validator_path() -> None:
    directory = temp_dir("qa-case-alt-")
    path = directory / "TC-1.md"

    def case(updated: str, alternatives=None) -> list:
        line = f"alternatives: {alternatives}\n" if alternatives is not None else ""
        path.write_text(
            "---\nid: TC-1\ntitle: t\nupdated: " + updated + "\n"
            'then_oracles: [{"then": 1, "source": "requirement", "ref": "R-1"}, {"then": 2, "source": "requirement", "ref": "R-2"}]\n'
            + line + "---\n# TC-1\n\n## Then\n1. a\n2. b\n", encoding="utf-8")
        errors: list = []
        V.check_case(path, errors)
        return [e for e in errors if "alternatives" in e]

    bad = item(then=7)
    found = case("2026-11-02", bad)
    check_eq("K9 a bad `then` on a dated case: the FORM line", len(found), 1)
    check_in("K9 ... naming the field", "FORM - alternatives `then`", found[0] if found else "")
    check_eq("K9 the same file without the key: no alternatives line", case("2026-11-02"), [])
    check_eq("K9 a well-formed key: no line", case("2026-11-02", GOOD), [])
    check_eq("K9 the same bad file dated before ORACLE_CUTOFF (2026-10-02): no alternatives line (the cutoff, pinned)",
             case("2026-09-01", bad), [])


def main() -> None:
    contract_functions()
    the_validator_path()
    finish("test_case_alternatives")


if __name__ == "__main__":
    main()
