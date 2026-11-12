"""form_selftest.py — importable now (build_fixture()/case_*(fx) instead of module-level
mkdtemp + a big try/finally + sys.exit), so a handful of its case groups can run in-process
here instead of paying for the whole ~24-case, ~15-20 s script every time a change nearby is
tested. `python form_selftest.py` still runs the whole thing and is the CLI contract
--selftest-scripts and install_smoke.py actually invoke; at that duration it does not belong
in a sub-10 s unit test and is deliberately NOT re-run as a child here (a full-script child
stays only when it measures under 10 s)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import form_selftest as F  # noqa: E402


def outcomes(results: list) -> dict:
    return {name: ok for ok, name, rc, tail in results}


def main() -> None:
    # 0. Importing the module runs nothing — no mkdtemp, no subprocess, no printed transcript.
    #    (If it did, this file's own import above would already have paid for it.)
    check("import form_selftest has no side effects (module has build_fixture, not globals "
          "PROJ/ART/STATE/TMP/results)",
          hasattr(F, "build_fixture") and not hasattr(F, "PROJ") and not hasattr(F, "results"))

    fx = F.build_fixture()
    try:
        # 1. The register group, on its own — build_fixture() already seeded a passing
        #    register + plan, so a case group needs nothing run before it.
        reg = outcomes(F.case_register(fx))
        check("register: a valid register passes", reg.get("register ok") is True)
        check("register: derived-without-derived_from is caught",
              reg.get("register bad: derived without derived_from, ok without ref") is True)
        # the group restores requirements-register.md to the passing form before returning —
        # a later group in the SAME fixture must not inherit the forgery it just wrote.
        check("register: restores the register to the passing form after its bad case",
              (fx.art / "requirements-register.md").read_text(encoding="utf-8") == F.REGISTER_OK)

        # 2. The bug group, in the SAME fixture — proves a fixture composes across groups
        #    without re-seeding (bug validation reads the register the fixture already has).
        bug = outcomes(F.case_bug(fx))
        check("bug: a valid new bug passes", bug.get("bug new ok") is True)
        check("bug: severity/oracle/missing-section forgery is caught",
              bug.get("bug new bad: severity != impact, violates is not an oracle, no section")
              is True)
        check("bug: an old bug (before the cutoff date) passes unchanged",
              bug.get("bug old ok (before cutoff)") is True)

        # 3. The escape-ledger group — a different artifact kind (JSONL under state/, not
        #    artifacts/), proving the fixture's `state` path is wired too.
        ledger = outcomes(F.case_ledger(fx))
        check("ledger: a valid escape-ledger line passes", ledger.get("escape ledger ok") is True)
        check("ledger: an 'unknown' stage with no reason is caught",
              ledger.get("escape ledger bad: unknown without reason") is True)
    finally:
        F.cleanup_fixture(fx)
    check("cleanup_fixture removes the synthetic project", not fx.proj.exists())
    check("cleanup_fixture removes the scratch dir", not fx.tmp.exists())

    # 4. A case group run on a FRESH fixture, without register/plan/bug/ledger run first —
    #    the independence build_fixture()'s docstring promises.
    fx2 = F.build_fixture()
    try:
        charter = outcomes(F.case_charter(fx2))
        check_eq("charter: a valid charter passes on a fresh fixture, no prior group needed",
                 charter.get("charter ok"), True)
        check_eq("charter: a self-verdict with empty seams is caught",
                 charter.get("charter bad: status ok, seams empty"), True)
    finally:
        F.cleanup_fixture(fx2)

    finish("test_form_selftest")


if __name__ == "__main__":
    main()
