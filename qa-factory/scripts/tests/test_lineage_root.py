#!/usr/bin/env python3
"""P2 M3 controller helpers: `lineage_root` (K-M3-27), `s7_part_of` (K-S7P) and the word `investigation` in `PURPOSES` (K-PURP)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import controller as CT  # noqa: E402

K = ("parent_retry", "relaunch_of")


def k_m3_27():
    cyc = {"A": {"parent_retry": "B"}, "B": {"parent_retry": "A"}}
    check_eq("K-M3-27a cycle A<->B: A -> A", CT.lineage_root(cyc, "A", ("parent_retry",)), "A")
    check_eq("K-M3-27a cycle A<->B: B -> B", CT.lineage_root(cyc, "B", ("parent_retry",)), "B")
    check_eq("K-M3-27b no key -> identity", CT.lineage_root({"A": {}}, "A", K), "A")
    check_eq("K-M3-27b unknown identifier unchanged", CT.lineage_root({"A": {}}, "Z", K), "Z")
    check_eq("K-M3-27b key naming an unknown record stops", CT.lineage_root({"A": {"parent_retry": "Q"}}, "A", K), "A")
    check_eq("K-M3-27b non-dict record stops", CT.lineage_root({"A": {"parent_retry": "B"}, "B": "x"}, "A", K), "B")
    rel = {"A": {}, "B": {"relaunch_of": "A"}}
    check_eq("K-M3-27c relaunch_of followed when in keys", CT.lineage_root(rel, "B", K), "A")
    check_eq("K-M3-27c relaunch_of ignored when not in keys", CT.lineage_root(rel, "B", ("parent_retry",)), "B")
    chain = {"R": {}, "P": {"relaunch_of": "R"}, "C": {"parent_retry": "P"}}
    check_eq("K-M3-27d parent_retry then relaunch_of -> root", CT.lineage_root(chain, "C", K), "R")


def k_s7p():
    inv = "investigation"
    check_eq("K-S7P-1 {} -> ''", CT.s7_part_of({}), "")
    check_eq("K-S7P-1 None / non-dict -> ''", (CT.s7_part_of(None), CT.s7_part_of("S7"), CT.s7_part_of([1])), ("", "", ""))
    check_eq("K-S7P-2 non-S7 with investigation -> ''",
             CT.s7_part_of({"stage": "S5", "request_binding": {"purpose": inv}}), "")
    check_eq("K-S7P-3 binding wins over top-level",
             CT.s7_part_of({"stage": "S7", "request_binding": {"purpose": inv}, "purpose": "diagnostic"}), inv)
    check_eq("K-S7P-3 binding says other, top says investigation -> ''",
             CT.s7_part_of({"stage": "S7", "request_binding": {"purpose": "diagnostic"}, "purpose": inv}), "")
    check_eq("K-S7P-4 top-level purpose used when no binding key", CT.s7_part_of({"stage": "S7", "purpose": inv}), inv)
    check_eq("K-S7P-5 crooked binding -> ''", CT.s7_part_of({"stage": "S7", "request_binding": ["x"], "purpose": inv}), "")


def k_purp():
    check("K-PURP investigation in PURPOSES", "investigation" in CT.PURPOSES)
    check("K-PURP old words kept", {"initial", "s5_plan", "s3_labelling"} <= set(CT.PURPOSES))


def k_cls():
    """P2 w5 B-1: `_closes_stage` exempts an S7 investigation dispatch, as it does the S5 plan one (the rule reads no state here)."""
    ctl = CT.Controller.__new__(CT.Controller)
    state = {"stages": {"S7": {"status": "running"}}}
    s7 = {"stage": "S7", "role": "qa-failure-analyst", "scope": []}
    check_eq("K-CLS-1 S7 record with binding purpose investigation -> False",
             ctl._closes_stage(dict(s7, request_binding={"purpose": "investigation"}), state), False)
    check_eq("K-CLS-1 binding wins over a top-level purpose triage -> False",
             ctl._closes_stage(dict(s7, request_binding={"purpose": "investigation"}, purpose="triage"), state), False)
    check_eq("K-CLS-2 control: the same record without the purpose -> today's value (True)",
             ctl._closes_stage(dict(s7, request_binding={}), state), True)
    check_eq("K-CLS-2 control: a crooked binding (a list) -> today's value (True), no raise",
             ctl._closes_stage(dict(s7, request_binding=["investigation"]), state), True)
    plan = {"stage": "S5", "role": "qa-code-critic", "scope": ["TC-001"], "request_binding": {"purpose": "s5_plan"}}
    check_eq("K-CLS-3 an S5 plan record -> unchanged (False)", ctl._closes_stage(plan, state), False)
    check_eq("K-CLS-3 a non-closing S7 role with the purpose -> False as before",
             ctl._closes_stage({"stage": "S7", "role": "qa-automator", "request_binding": {"purpose": "investigation"}}, state), False)


k_m3_27()
k_s7p()
k_purp()
k_cls()
finish("test_lineage_root")
