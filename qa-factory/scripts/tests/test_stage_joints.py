#!/usr/bin/env python3
"""The stage-joints walk: the registry, its three directions, its pins and its negative controls (F6-51, FR-5, FR-38, FR-28).

`stage_joints.audit` walks the package (the error families of the exit gate, the blocking detectors of stages.json, the
gap kinds of the S5 window) against `references/stage-joints.json` and demands for each check a producer, a place the
role is told, and every demanded token in a file the role receives. A walker that walks nothing is green for the wrong
reason (t-317 F4), so the three walk sizes are pinned in BOTH directions, and every refusal below is shown on a
synthetic input or a deep copy next to the real tree passing. The real package is never mutated (FR-45).

Keys: K1 real tree green + the summary line, K2 pins AT, K3 pin -1/+1, K4 a check with no row, K5 stale row and two rows,
K6 each missing leg (and the informed gap, a gap on a complete leg, the `code:` site cases), K7 the reach rule, K8 direction
C, K9 unreadable shapes of the walk, K10 the data file, K11 the ratchet, K12 the joint census, K13 threshold(), K14 the CLI.
"""
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import null_outcomes as NO  # noqa: E402
import stage_joints as SJ  # noqa: E402

# The walk sizes. A change of any is a change of the factory's checks and the Lead's question: the walker is not adjusted
# to agree with the tree. exit: the 8 families of all_errors + main; detector: 9 tuples of stages.json minus the adviser
# sizing.py; window: 27 distinct gap kinds of validate_window (30 append sites, `expectation_change_gaps` from extend).
PINS = {"exit": 8, "detector": 8, "window": 27}
ENV = SJ.Env.real()
REAL, _WHY = NO.load_data(SJ.DATA)
UNI = SJ.universe()


def audit(data=None, uni=None, pins=None, env=None):
    return SJ.audit(copy.deepcopy(REAL) if data is None else data, UNI if uni is None else uni, pins, env or ENV)


def mutated(change, relax_ratchet: bool = True) -> dict:
    """A deep copy of the data with `change` applied; the ratchet follows the gaps unless the case is about the ratchet."""
    data = copy.deepcopy(REAL)
    change(data)
    if relax_ratchet:
        data["ratchet"][-1]["gaps"] = sum(1 for r in data["joints"] for p in r["producers"] if p.get("gap"))
    return data


def row_of(data: dict, check_key: str) -> dict:
    return next(r for r in data["joints"] if r["check"] == check_key)


def text_of(report) -> str:
    return " | ".join(report.problems)


def k1_real_tree() -> None:
    report = audit(pins=PINS)
    check_eq("K1: the real tree is green (every leg, every direction)", report.problems, [])
    print(report.line())
    check_in("K1: the summary line names the walk, the rows, the gaps by leg, the joints and the stages with no detector",
            "walked exit 8, detector 8, window 27 | rows 43, gaps ", report.line())
    check_in("K1/E5: a stage with no detector is reported, not invented",
             "stages with no detector: S0, S1, S6, S7, S9", report.line())
    check_eq("K1: no walk error on the real tree", UNI[1], [])
    check_in("K3/m-3: the line says the window rows with a code producer walk the code leg only", "role leg not walked (code-to-code rows): 26",
             report.line())
    check_eq("K3/m-3: every window row with a code producer says so in the data (window:quality has no producer: a gap, not code-to-code)",
             sorted(r["check"] for r in REAL["joints"] if r["check"].startswith("window:")
                    and all(p.get("role_leg") == "not walked" for p in r["producers"])),
             sorted(r["check"] for r in REAL["joints"] if r["check"].startswith("window:") and r["check"] != "window:quality"))
    check_in("K3/m-3: a role_leg value other than `not walked` is red", "`role_leg` is only `not walked`",
             text_of(audit(data=mutated(lambda d: [p.update(role_leg="walked") for r in d["joints"] if r["check"].startswith("window:")
                                                   for p in r["producers"]][:1], False))))
    check_in("K3/m-3: F6-51/5 is on the producer leg", "producer",
             json.dumps([p["gap"]["leg"] for r in REAL["joints"] for p in r["producers"] if (p.get("gap") or {}).get("ref") == "F6-51/5"]))
    check_eq("K1: the universe is exactly 8 + 8 + 27 keys", len(UNI[0]), 43)
    check_not_in("K1: the adviser sizing.py is not a blocking detector", "sizing.py", " ".join(UNI[0]))
    check_not_in("K1/X2-3: the form check left the stop (a stop no longer refuses the handover form; `finish` does)",
                 "exit:form_stop_errors", " ".join(UNI[0]))


def k2_k3_pins() -> None:
    check_eq("K2: the pins hold AT their values", audit(pins=PINS).problems, [])
    for kind, size in PINS.items():
        for pinned in (size - 1, size + 1):
            check_in(f"K3: {kind} pinned {pinned} (real {size}) is red, in both directions",
                     f"{kind} checks: {size}, pinned {pinned}", text_of(audit(pins={**PINS, kind: pinned})))
    stub = ({k: v for k, v in UNI[0].items() if k != "exit:digest_errors"}, [])
    check_in("K3: a stubbed universe one exit family short is red against the pin", "exit checks: 7, pinned 8",
             text_of(audit(uni=stub, pins=PINS)))


def k4_k5_directions() -> None:
    plus = ({**UNI[0], "exit:new_errors": "exit_gate.py::all_errors:1"}, [])
    out = text_of(audit(uni=plus))
    check_in("K4/E2: a check in code with no row is red, naming the key", "exit:new_errors is a check in code", out)
    check_in("K4: and saying what to add", "has no row in references/stage-joints.json", out)
    stale = text_of(audit(data=mutated(lambda d: d["joints"].append(
        {**copy.deepcopy(d["joints"][0]), "check": "exit:gone_errors"}))))
    check_in("K5/E3: a row whose check the walk does not meet is stale", "row exit:gone_errors: stale", stale)
    two = text_of(audit(data=mutated(lambda d: d["joints"].append(copy.deepcopy(d["joints"][0])))))
    check_in("K5/E4: two rows for one check", "exit:scoped_errors has two rows", two)


def k6_legs() -> None:
    quality = lambda d: row_of(d, "window:quality")["producers"][0]
    handback = lambda d: row_of(d, "exit:text_end_after_handback")["producers"][0]
    grounding = lambda d: row_of(d, "exit:grounding_errors")["producers"][0]
    check_in("K6/E1 producer: no writer and no gap is red",
             "the producer leg is missing and no gap is declared", text_of(audit(data=mutated(
                 lambda d: quality(d).pop("gap")))))
    check_in("K6/E1 told: no place and no gap is red", "the told leg is missing and no gap is declared",
             text_of(audit(data=mutated(lambda d: handback(d).pop("gap")))))
    check_in("K6/E1 demands: nothing demanded of a role and no gap is red",
             "the demands leg is missing for qa-requirements-tester",
             text_of(audit(data=mutated(lambda d: grounding(d).update(demands=[])))))
    gap = {"leg": "demands", "ref": "F6-51/9", "why": "a test gap on the demands leg of this role entry"}
    check_eq("K6: the same missing demands leg WITH a declared gap is green (an informed pass)",
             audit(data=mutated(lambda d: grounding(d).update(demands=[], gap=gap))).problems, [])
    check_in("K6: a gap declared on a complete leg is red, saying to remove it",
             "gap declared on a complete leg (demands) - remove it",
             text_of(audit(data=mutated(lambda d: grounding(d).update(gap=gap)))))
    check_in("K6: a gap whose ref points at nothing is red", "gap ref 'soon' is not",
             text_of(audit(data=mutated(lambda d: quality(d).update(gap={**quality(d)["gap"], "ref": "soon"})))))
    check_in("K6: a gap with a short reason is red", "gap `why` is shorter than 30",
             text_of(audit(data=mutated(lambda d: quality(d).update(gap={**quality(d)["gap"], "why": "later"})))))
    check_in("K6: a row with no producer entry is red", "`producers` is empty",
             text_of(audit(data=mutated(lambda d: row_of(d, "window:review").update(producers=[])))))
    check_in("K6: an unknown entry key is red", "has an unknown key `colour`",
             text_of(audit(data=mutated(lambda d: grounding(d).update(colour="red")))))
    check_in("K6: a role with no agent file is red", "role `qa-ghost` has no agents/qa-ghost.md",
             text_of(audit(data=mutated(lambda d: grounding(d).update(roles=["qa-ghost"])))))
    check_in("K6: a detector row at another stage than its key is red", "a detector row runs at the stage in its key",
             text_of(audit(data=mutated(lambda d: row_of(d, "detector:S5:qa-automator:s5_precheck.py").update(stages=["S4"])))))
    check_in("K6: a row that runs at no stage is red", "a check that runs at no stage",
             text_of(audit(data=mutated(lambda d: row_of(d, "window:review").update(stages=[])))))
    code_sites()


def code_sites() -> None:
    """The `code:` producer: a name only in a comment or a string, a line number, a missing file are all red."""
    tmp = temp_dir("qa-joints-code-")
    try:
        scripts = tmp / "scripts"
        scripts.mkdir()
        (scripts / "mod.py").write_text('def build():\n    """build()"""\n    return 1\n# build(2)\nX = "build(3)"\n'
                                        "# def ghost():\n" 'Y = "def ghost2():"\n', encoding="utf-8")
        env = copy.copy(ENV)
        env.plugin, env.scripts = tmp, scripts
        def entry(code_ref, told="scripts/mod.py"):
            return {"code": code_ref, "field": "a test field", "told": [{"path": told}], "demands": []}
        def problems(e):
            return SJ._entry_problems("window:x", 0, e, env)[0]
        check_in("K6 code: a name only in a comment is not a definition", "no function `ghost`", " | ".join(problems(entry("mod.py::ghost"))))
        check_in("K6 code: a name only in a string is not a definition", "no function `ghost2`", " | ".join(problems(entry("mod.py::ghost2"))))
        check_in("K6 code: a line number in the site is refused", "is not `<scripts file>.py::<function>`", " | ".join(problems(entry("mod.py:12"))))
        check_in("K6 code: a missing file is refused", "cannot be read", " | ".join(problems(entry("nofile.py::build"))))
        check_in("K6 code: a docstring, a comment and a string that spell `build(` are no call",
                 "no call of `build` outside its own definition", " | ".join(problems(entry("mod.py::build"))))
        (scripts / "mod.py").write_text('def build():\n    return 1\n\n\ndef run():\n    return build()\n', encoding="utf-8")
        env._texts.clear(), env._trees.clear()
        check_eq("K6 code (positive control): a real call outside the definition makes the producer called", problems(entry("mod.py::build")), [])
        check_in("K6 code: a told file outside scripts/ is refused", "called in a `scripts/*.py` file",
                 " | ".join(problems(entry("mod.py::build", told="scripts/tests/t.py"))))
        check_in("K6 code: an anchor means nothing for a code producer", "an anchor has no meaning",
                 " | ".join(problems({**entry("mod.py::build"), "told": [{"path": "scripts/mod.py", "anchor": "x"}]})))
    finally:
        cleanup(tmp)


def k7_reach() -> None:
    entry = {"roles": ["qa-automator"]}
    item = {"path": "agents/qa-runner.md", "anchor": "## Outputs"}
    check_in("K7/E15: another role's agent file is not read by this role", "is not read by qa-automator",
             " | ".join(SJ._reach_problems(entry, item, ENV)))
    check_eq("K7: a slice the injection map lists for the role is read by it",
             SJ._reach_problems(entry, {"path": "references/slices/qa-automator/artifact-contract-automation.md",
                                        "anchor": "automation"}, ENV), [])
    check_in("K7: an existing file that the map does not deliver to the role is not read by it", "is not read by qa-automator",
             " | ".join(SJ._reach_problems(entry, {"path": "references/slices/qa-runner/common-rules.md", "anchor": "x"}, ENV)))
    check_in("K7: an anchor absent from a file the role reads is red", "the anchor 'no such phrase here' is not in the file",
             " | ".join(SJ._reach_problems(entry, {"path": "agents/<role>.md", "anchor": "no such phrase here"}, ENV)))
    check_in("K7: a file that does not exist is red", "the file does not exist",
             " | ".join(SJ._reach_problems(entry, {"path": "references/slices/<role>/ghost.md", "anchor": "x"}, ENV)))
    check_in("K7: an entry with no anchor is red", "`anchor` is missing",
             " | ".join(SJ._reach_problems(entry, {"path": "agents/<role>.md"}, ENV)))
    check_eq("K7: `<role>` is expanded for each role of the entry",
             SJ._reach_problems({"roles": ["qa-scout", "qa-runner"]}, {"path": "agents/<role>.md", "anchor": "<!-- gen:digest contract_slices.py -->"}, ENV), [])


def k8_direction_c() -> None:
    base = {"roles": ["qa-requirements-tester"], "told": [{"path": "agents/<role>.md", "anchor": "## Outputs"}],
            "demands_from": None}
    check_in("K8: a demanded token absent from every told file is red", "qa-requirements-tester is not told `zz_not_a_token_zz`",
             " | ".join(SJ._demands_leg("exit:x", {**base, "demands": ["zz_not_a_token_zz"]}, ENV)))
    check_eq("K8: a token present in a told file is green", SJ._demands_leg("exit:x", {**base, "demands": ["derived"]}, ENV), [])
    check_in("K8: an unknown carrier is red", "`demands_from` 'my.table' is not one of",
             " | ".join(SJ._demands_leg("exit:x", {**base, "demands": [], "demands_from": "my.table"}, ENV)))
    tokens, why = SJ.demand_tokens("stages.json:required_outputs", "qa-scout", "exit:x", ENV)
    check_eq("K8: required_outputs are read through the stage model, by file name", (tokens, why),
             (["context-manifest.json", "context-bundle.json"], ""))
    check_eq("K8: PHASE_JSON_KEYS are read for the artifacts the role writes",
             SJ.demand_tokens("validate_artifacts.PHASE_JSON_KEYS", "qa-automator", "exit:x", ENV)[0], ["tests", "run_witness"])
    check_eq("K8: the detector scripts of a role exclude its advisers",
             SJ.demand_tokens("stages.json:detectors", "qa-requirements-tester", "exit:x", ENV)[0], ["branch_accounting.py"])
    check_in("K8: a carrier that yields nothing for a role is red (a stale entry, not a pass)",
             "the demands leg is missing for qa-retro-analyst",
             " | ".join(SJ._demands_leg("exit:x", {**base, "roles": ["qa-retro-analyst"], "demands": [],
                                                    "demands_from": "stages.json:detectors"}, ENV)))
    check_eq("K8/E16: direction C does not run on a code producer",
             SJ._demands_leg("window:x", {"code": "window_record.py::build", "told": [], "demands": ["zz"]}, ENV), [])


def k9_unreadable_shapes() -> None:
    members, errors = SJ.exit_members("def all_errors():\n    errors = a()\n    errors += self.x()\n"
                                      "def main():\n    errors = [e for e in errors]\n")
    check_eq("K9/E6: an attribute call in `errors` is a walk error, naming the line", len(errors), 1)
    check_in("K9: and the line", "exit_gate.py:3", errors[0])
    check_eq("K9: the family beside it is still a member", sorted(members), ["exit:a"])
    members, errors = SJ.exit_members("def all_errors():\n    errors = errors + list(x) + b() + (c if q else d)\n"
                                      "    if y:\n        errors += d()\n"
                                      "def main():\n    errors = [e for e in errors if e]\n    errors, passed = all_errors()\n")
    check_eq("K9: a name, a comprehension, `list`, the aggregator and a tuple target are no family, no error; a nested statement is walked",
             (sorted(members), errors), (["exit:b", "exit:d"], []))
    check_eq("K9: a file with neither function is a walk error", len(SJ.exit_members("x = 1")[1]), 2)
    check_eq("K9: a source that is not Python is a walk error", len(SJ.exit_members("def (")[1]), 1)
    src = ("def validate_window():\n    gaps.append(f(i))\n    gaps.append('a:' + x)\n    gaps.append(K if c else 'b:' + y)\n"
           "    gaps.extend(g for g in h(w))\n    gaps.extend(zz)\n")
    members, errors = SJ.window_members(src, {"K": "k:"})
    check_eq("K9/E6: gaps.append(f(i)) and gaps.extend(no call) are walk errors, each naming its line",
             sorted(e.split(" - ")[0] for e in errors), ["cannot read the check at acceptance.py:2", "cannot read the check at acceptance.py:6"])
    check_eq("K9: a constant, a module name and both branches of a conditional are members; extend adds the called name",
             sorted(members), ["window:a", "window:b", "window:h", "window:k"])
    check_eq("K9: a name that is no module text is a walk error, not skipped",
             len(SJ.window_members("def validate_window():\n    gaps.append(NOPE + ':')\n", {})[1]), 1)
    check_eq("K9: no validate_window is a walk error", len(SJ.window_members("x = 1", {})[1]), 1)


def k10_data_file() -> None:
    check_in("K10/E8: a reason string (file unreadable) is red, never an empty registry", "stage-joints.json cannot be read",
             text_of(SJ.audit("stage-joints.json cannot be read (OSError)", UNI, None, ENV)))
    check_in("K10: an unknown top key", "has an unknown key `extra`", text_of(audit(data=mutated(lambda d: d.update(extra=1)))))
    check_in("K10: a lost top key", "lacks `friction`", text_of(audit(data=mutated(lambda d: d.pop("friction")))))
    check_in("K10: schema 2", "schema_version is 2, this reader reads 1", text_of(audit(data=mutated(lambda d: d.update(schema_version=2)))))
    check_in("K10: an unknown row key", "unknown key `owner`", text_of(audit(data=mutated(lambda d: d["joints"][0].update(owner="x")))))
    check_in("K10: no joint rows is red", "has no joint rows", text_of(audit(data=mutated(lambda d: d.update(joints=[])))))
    check_in("K10: a short note is red", "`note` is shorter than 40", text_of(audit(data=mutated(lambda d: d.update(note="short")))))
    tmp = temp_dir("qa-joints-data-")
    try:
        for label, body in (("absent", None), ("malformed", "{not json"), ("an array", "[]")):
            path = tmp / f"{label.replace(' ', '-')}.json"
            if body is not None:
                path.write_text(body, encoding="utf-8")
            report = SJ.audit(path=path, uni=UNI, env=ENV)
            check(f"K10: a data file that is {label} is red with the file named", report.problems and "stage-joints" in report.problems[0]
                  and path.name in report.problems[0], str(report.problems))
    finally:
        cleanup(tmp)


def k11_ratchet() -> None:
    n = REAL["ratchet"][-1]["gaps"]
    check_eq("K11: the real ratchet equals the declared gaps", n, sum(1 for r in REAL["joints"] for p in r["producers"] if p.get("gap")))
    check_in("K11: a count that differs from the last entry is red", f"gaps has {n} declared gaps and the ratchet's last entry says {n + 1}",
             text_of(audit(data=mutated(lambda d: d["ratchet"].__setitem__(-1, {"node": "F6-51", "gaps": n + 1}), False))))
    check_in("K11: a history that rises is red, named as a raise", f"ratchet rises from {n} to {n + 2}",
             text_of(audit(data=mutated(lambda d: d["ratchet"].extend([{"node": "F6-51", "gaps": n + 2}]), False))))
    check_eq("K11: a history that falls to the count is green",
             audit(data=mutated(lambda d: d["ratchet"].insert(0, {"node": "F6-51", "gaps": n + 3}), False)).problems, [])
    check_in("K11: an empty ratchet is red", "ratchet is empty", text_of(audit(data=mutated(lambda d: d.update(ratchet=[]), False))))
    check_in("K11: a node that is not the node that keeps it is red", "is not F6-51",
             text_of(audit(data=mutated(lambda d: d["ratchet"][-1].update(node="N1"), False))))
    for node in ("F6-52", "F6-51a", "f6-51"):
        check_in(f"K2/m-2: a ratchet row under another node id ({node}) is refused - only F6-51 lowers it", "is not F6-51",
                 text_of(audit(data=mutated(lambda d, node=node: d["ratchet"].append({"node": node, "gaps": n - 1}), False))))
    check_in("K2/m-2: a gap ref of another node form is refused", "is not `B-<n>` or `F6-51/<n>`",
             text_of(audit(data=mutated(lambda d: [p["gap"].update(ref="F6-52/1") for r in d["joints"] for p in r["producers"] if p.get("gap")][:1], False))))
    check_in("K11: a key that is not a count is red", "`gaps` is not a count",
             text_of(audit(data=mutated(lambda d: d["ratchet"][-1].update(gaps=True), False))))


def k12_joint_census() -> None:
    test = "scripts/tests/test_stage_joints_12586.py"
    check_in("K12: a joint test that never mentions its fixture folder is red", "never mentions the fixture folder",
             text_of(audit(data=mutated(lambda d: row_of(d, "window:review").update(
                 joint={"test": test, "fixture": "scripts/tests/fixtures/run-12586-digest/"})))))
    both = text_of(audit(data=mutated(lambda d: row_of(d, "window:review").update(
        joint={"test": "scripts/tests/test_nowhere.py", "fixture": "scripts/tests/fixtures/nowhere/"}))))
    check_in("K12: a test that does not exist is red", "joint test scripts/tests/test_nowhere.py does not exist", both)
    check_in("K12: a fixture that does not exist is red", "joint fixture scripts/tests/fixtures/nowhere/ does not exist", both)
    check_eq("K12: a null joint is counted, never red", audit(data=mutated(lambda d: row_of(d, "exit:digest_errors").update(joint=None))).problems, [])
    held = [r["check"] for r in REAL["joints"] if r["joint"]]
    check_eq("K12: the rows that carry a recorded-run joint", sorted(held), sorted([
        "exit:scoped_errors", "exit:digest_errors", "detector:S3:qa-test-strategist:planning_contract.py", "window:quality"]))


def k13_threshold() -> None:
    check_eq("K13: threshold() reads friction.same_class_gate_blocks", SJ.threshold(), REAL["friction"]["same_class_gate_blocks"])
    tmp = temp_dir("qa-joints-thr-")
    try:
        for label, body, want in (("absent key", {"joints": []}, None), ("1 (below the floor)", {"friction": {SJ.KEY: 1}}, None),
                                  ("a bool", {"friction": {SJ.KEY: True}}, None), ("a text", {"friction": {SJ.KEY: "3"}}, None),
                                  ("2 (AT the floor)", {"friction": {SJ.KEY: 2}}, 2), ("5", {"friction": {SJ.KEY: 5}}, 5)):
            path = tmp / "d.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            check_eq(f"K13: {label}", SJ.threshold(path), want)
        check_eq("K13: a file that is not there gives None, not a default number", SJ.threshold(tmp / "nothing.json"), None)
    finally:
        cleanup(tmp)


def cli(*args) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = SJ.main(list(args))
    return code, out.getvalue()


def k14_cli() -> None:
    code, out = cli()
    check_eq("K14: the CLI exits 0 on the real tree and prints the line", (code, "stage joints: clean" in out), (0, True))
    done = run_script("stage_joints.py", "--check")
    check_eq("K14: the script itself exits 0 (--check)", done.returncode, 0)
    tmp = temp_dir("qa-joints-cli-")
    try:
        short = copy.deepcopy(REAL)
        short["joints"] = [r for r in short["joints"] if r["check"] != "exit:digest_errors"]
        path = tmp / "short.json"
        path.write_text(json.dumps(short), encoding="utf-8")
        code, out = cli("--data", str(path))
        check_eq("K14: a copy with one row removed exits 1 and prints the detector shape", (code, out.count("REJECT — 1 finding(s)")), (1, 1))
        check_in("K14: and names the check", "exit:digest_errors is a check in code", out)
        bad = tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        code, out = cli("--data", str(bad))
        check_eq("K14/m-1: a malformed data file exits 3 (the contract's EXIT_UNREADABLE) with the UNREADABLE line",
                 (code, out.startswith("UNREADABLE: ")), (3, True))
        code, out = cli("--data", str(tmp / "absent.json"))
        check_eq("K14/m-1: an absent data file exits 3", code, 3)
        check_eq("K14: --data with no file is a usage error, exit 2", cli("--data")[0], 2)
        import detector_verdict
        check_eq("K14/m-1: the exit is the contract's constant, not a copy", detector_verdict.EXIT_UNREADABLE, 3)
        check_eq("K14/m-1: the contract reads the CLI's own output as unreadable",
                 bool(detector_verdict.parse(code, out, "")["unreadable"]), True)
    finally:
        cleanup(tmp)


def main() -> None:
    k1_real_tree()
    k2_k3_pins()
    k4_k5_directions()
    k6_legs()
    k7_reach()
    k8_direction_c()
    k9_unreadable_shapes()
    k10_data_file()
    k11_ratchet()
    k12_joint_census()
    k13_threshold()
    k14_cli()
    finish("test_stage_joints")


if __name__ == "__main__":
    main()
