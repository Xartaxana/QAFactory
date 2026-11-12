"""run_history.py and the one "same test" comparison (RH1-9 N3; AR-13, AR-28).

`_compare_shas` decides code/raw through `proof_level.compare_identity` (the record's words and shas stay as they were);
`_job_contract` takes a contract by the bare function name only when it cannot be a stranger's (E5). Keys: K-R1 the
results of `_compare_shas` over every combination equal the pre-change ones, K-R2 E5, K-R3 twin classes, K-R4 the forms of
a parametrized id, K-R5 the comparator is the one asked.
"""
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import proof_level as PL  # noqa: E402
import run_history as RH  # noqa: E402


def before_rh1_9(red: dict, green: dict) -> tuple:
    """The body of `_compare_shas` as it was before RH1-9: the first basis present on BOTH sides decides."""
    for basis in ("code", "raw", "file"):
        if red[basis] and green[basis]:
            return ("same" if red[basis] == green[basis] else "changed"), basis, red[basis], green[basis]
    return "unknown", "unknown", RH._first_sha(red), RH._first_sha(green)


def k_r1_results_equal_the_old_ones() -> None:
    values = ("", "a", "b")
    bad = []
    total = 0
    for rc, rr, rf, gc, gr, gf in itertools.product(values, repeat=6):
        red, green = {"code": rc, "raw": rr, "file": rf}, {"code": gc, "raw": gr, "file": gf}
        total += 1
        if RH._compare_shas(dict(red), dict(green)) != before_rh1_9(red, green):
            bad.append((red, green))
    check_eq(f"K-R1: _compare_shas equals the pre-change answer on all {total} combinations", bad, [])
    check_eq("K-R1: code equal, raw equal -> the record's basis is `code` (the rule that decided)",
             RH._compare_shas({"code": "k", "raw": "r", "file": "f"}, {"code": "k", "raw": "r", "file": "f"}),
             ("same", "code", "k", "k"))
    check_eq("K-R1 (E2): code differs, raw equal -> changed on code",
             RH._compare_shas({"code": "k1", "raw": "r", "file": ""}, {"code": "k2", "raw": "r", "file": ""}),
             ("changed", "code", "k1", "k2"))
    check_eq("K-R1: no code on one side, raw differs -> changed on raw",
             RH._compare_shas({"code": "", "raw": "r1", "file": ""}, {"code": "k", "raw": "r2", "file": ""}),
             ("changed", "raw", "r1", "r2"))
    check_eq("K-R1: nothing but the file sha on both sides -> the file decides",
             RH._compare_shas({"code": "", "raw": "", "file": "f1"}, {"code": "", "raw": "", "file": "f2"}),
             ("changed", "file", "f1", "f2"))
    check_eq("K-R1: no sha on either side -> unknown, never same",
             RH._compare_shas({"code": "", "raw": "", "file": ""}, {"code": "", "raw": "", "file": ""})[:2],
             ("unknown", "unknown"))


def job(contracts: dict) -> dict:
    return {"job_id": "j", "request": {"instance_contracts": contracts}}


def k_r2_the_bare_name_fallback() -> None:
    a = {"instance_code_sha": "k1", "instance_content_sha": "c1"}
    b = {"instance_code_sha": "k2", "instance_content_sha": "c2"}
    check_eq("K-R2: the exact id wins", RH._job_contract(job({"t.py::FN[x]": a, "t.py::FN[y]": b}), "t.py::FN[x]"), a)
    check_eq("K-R2 (E5): no contract of that function -> {}", RH._job_contract(job({"t.py::OTHER[x]": a}), "t.py::FN[p]"), {})
    check_eq("K-R2 (E5): exactly one contract of the function by the bare name -> it (the boundary, as before)",
             RH._job_contract(job({"t.py::FN[P-old]": a}), "t.py::FN[P-new]"), a)
    check_eq("K-R2 (E5): two contracts with DIFFERENT shas -> {} (a stranger's sha never decides)",
             RH._job_contract(job({"t.py::FN[P-old1]": a, "t.py::FN[P-old2]": b}), "t.py::FN[P-new]"), {})
    check_eq("K-R2 (E5): same code sha, different content sha -> {}",
             RH._job_contract(job({"t.py::FN[P-old1]": a, "t.py::FN[P-old2]": dict(a, instance_content_sha="c9")}),
                              "t.py::FN[P-new]"), {})
    same = dict(a, instance_content_scope="function")
    check_eq("K-R2: two parameter contracts of ONE function, equal shas (the 13797 rename shape) -> the first",
             RH._job_contract(job({"t.py::FN[P-old1]": same, "t.py::FN[P-old2]": dict(same)}), "t.py::FN[P-new]"), same)
    check_eq("K-R2: two contracts of equal but EMPTY shas -> {}",
             RH._job_contract(job({"t.py::FN[P-old1]": {}, "t.py::FN[P-old2]": {}}), "t.py::FN[P-new]"), {})
    check_eq("K-R2: no request / no contracts -> {}", (RH._job_contract({}, "x"), RH._job_contract(None, "x")), ({}, {}))
    check_eq("K-R2: an empty function name finds nothing", RH._job_contract(job({"t.py::FN[x]": a}), ""), {})


def k_r3_twin_classes() -> None:
    a = {"instance_code_sha": "k1", "instance_content_sha": "c1"}
    b = {"instance_code_sha": "k2", "instance_content_sha": "c2"}
    check_eq("K-R3: TestA::test_x and TestB::test_x are two keys",
             RH.function_key("tests/t.py::TestA::test_x[p]") == RH.function_key("tests/t.py::TestB::test_x[p]"), False)
    check_eq("K-R3: the bare-name search of the twins, with different shas -> {}",
             RH._job_contract(job({"tests/t.py::TestA::test_x": a, "tests/t.py::TestB::test_x": b}), "test_x"), {})


def k_r4_parametrized_forms() -> None:
    keys = {RH.function_key(f"tests/t.py::test_x[{p}]") for p in ("a/b-1", "a::b", "[n]", "plain")}
    check_eq("K-R4: `[a/b-1]`, `[a::b]`, `[[n]]` and a plain parameter give ONE function key", keys, {"t.test_x"})
    check_eq("K-R4: a class-qualified nested bracket", RH.function_key("tests/t.py::TestC::test_x[[n]]"), "t.TestC.test_x")


def k_r5_the_comparator_is_the_one_asked() -> None:
    red = {"code": "k", "raw": "r", "file": "f"}
    real = PL.compare_identity
    PL.compare_identity = lambda a, b: ("different", "code")
    try:
        got = RH._compare_shas(dict(red), dict(red))
    finally:
        PL.compare_identity = real
    check_eq("K-R5: a comparator answering `different` makes equal shas `changed`", got[0], "changed")
    check_eq("K-R5 control: restored, the same shas are `same`", RH._compare_shas(dict(red), dict(red))[0], "same")


def k_r6_job_contract_asks_the_one_comparator() -> None:
    """m2 (AR-13, AR-28): `_job_contract` decides "the same function" through `compare_identity`; an unknown is no match."""
    one = {"instance_code_sha": "k1", "instance_content_sha": "c1"}
    contracts = job({"t.py::FN[P-old1]": dict(one), "t.py::FN[P-old2]": dict(one)})
    real = PL.compare_identity
    try:
        for answer in (("unknown", ""), ("different", "code"), ("same", "code")):
            PL.compare_identity = lambda a, b, answer=answer: answer
            check_eq(f"K-R6: a comparator answering {answer} -> {{}} (only ('same', 'content') matches)",
                     RH._job_contract(contracts, "t.py::FN[P-new]"), {})
        PL.compare_identity = lambda a, b: ("same", "content")
        check_eq("K-R6: a comparator answering ('same', 'content') -> the first",
                 RH._job_contract(contracts, "t.py::FN[P-new]"), one)
    finally:
        PL.compare_identity = real
    check_eq("K-R6 control: restored, equal shas keep the first", RH._job_contract(contracts, "t.py::FN[P-new]"), one)
    check_eq("K-R6 (m2): one side without a content sha is unknown/code-only -> {}",
             RH._job_contract(job({"t.py::FN[P-old1]": {"instance_code_sha": "k1"},
                                   "t.py::FN[P-old2]": {"instance_code_sha": "k1"}}), "t.py::FN[P-new]"), {})
    check_eq("K-R6 (m2): a non-dict contract is not a candidate (one candidate left -> it, as before)",
             RH._job_contract(job({"t.py::FN[P-old1]": dict(one), "t.py::FN[P-old2]": "junk"}), "t.py::FN[P-new]"), one)


def main() -> None:
    k_r6_job_contract_asks_the_one_comparator()
    k_r1_results_equal_the_old_ones()
    k_r2_the_bare_name_fallback()
    k_r3_twin_classes()
    k_r4_parametrized_forms()
    k_r5_the_comparator_is_the_one_asked()
    check("the comparator lives in proof_level", callable(PL.compare_identity))
    finish("test_run_history_identity")


if __name__ == "__main__":
    main()
