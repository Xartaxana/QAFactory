"""gate_registry.py — A26 (FR-59): the registry matches the shipped sources, and no verdict comparison
sits outside a registered gate.

The audit is worth only as much as its scanner, so this file first checks the scanner on synthetic
packages (a planted comparison nobody registered is caught; a stale site, a stale allow prefix and every
schema rule are caught; the inputs that must stay silent stay silent) and then runs it against the real
package, which is the regression that matters: a literal verdict comparison added to a script without a
row fails here before it fails a live story.

Keys K-T1.1 .. K-T1.14 are those of docs/tasks/specs/t-302-T1T2-gate-registry-and-template.md; the t-360
fix pass (critic t-359 F1-F6, F8) is `part_fix_pass`.

FR-45 ("a validator writes nothing") is checked in its WEAKER form: an AST read of gate_registry.py for a write
call (`write_calls`), not a before/after of the package tree's mtimes over a run.
"""
import ast
import contextlib
import copy
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, \
    run_script, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import gate_registry as GR  # noqa: E402

REGISTRY_PATH = PLUGIN_ROOT / "references" / "gate-registry.json"
F_A = "is in no registered gate"
CYRILLIC_A = chr(0x0430)          # spelled by code point: no Cyrillic in the package (FR-30)
ARABIC_FIVE = chr(0x0665)

# The 22 rows of the node spec plus the one Q6-A adds (source_freshness): 23.
EXPECTED_IDS = [
    "stand_identity", "provenance_acceptance", "request_shape", "inputs_unchanged", "test_identity",
    "collected_ids", "executor_present", "live_check_demand", "s5_coverage", "s5_window", "delivery",
    "manual_evidence_shape", "case_preconditions", "environment_preparation", "baseline_identity",
    "witness_backstop", "equivalence_metric", "then_oracle",
    "exploratory_oracle",   # MR !10 W4 (t-1594): the exploratory findings oracle that accepts person_confirmed (F2(a)); unknown branch debt
    "stand_login_gate", "stand_check",
    "s5_stand_limits", "reporter_rehearsal_identity", "environment_property_cover", "source_freshness",
    "probe_verdict",      # B-373 (c) adds the probe verdict (t-531, integration batch 0.9)
    "finish_exit_gate",   # GW1-8 (t-1264): `story_step finish` re-runs the stage's exit gate; unknown branch refuse_with_door
    "branch_accounting",  # TQ1-20 / G2-11 (S6.01): the S2 exit detector of branch accounting; unknown branch refuse_with_door
    "s3_grounding",       # G1-5: the S3 exit gate of the grounding table. ALREADY in the registry at 121bb203 and missing from this pin there (F-8, t-612)
    "regression_on_main",  # RG1-1 (t-609): a regression item must be on the main branch; unknown main branch is silent, never a refusal
    "s5_open_oracle_asserted",  # TQ1-1 (t-684): S5 exit - a Then the one resolver reads open/invalid is not bound to an asserting instance without an expectation_unconfirmed row; unknown branch refuse_with_door
    "env_block_evidence",  # RH2-9 (t-691): a blocked_by_env row stands only on a run that shows the stand; unknown branch refuse_with_door
    "plan_target_on_base"]  # TQ1-21: S3 exit - the test a plan row's extend/param/reuse builds on is a file of the working tree; unknown base is a WARN, never a refusal
# The Lead's debt-ref table (Q9-A), from the node spec - the oracle for the live data (FR-58).
EXPECTED_DEBT = {
    "stand_identity": "B-257", "provenance_acceptance": "B-255", "test_identity": "B-217",
    "collected_ids": "B-278", "live_check_demand": "B-279", "s5_coverage": "B-221", "s5_window": "B-179",
    "delivery": "B-061", "case_preconditions": "B-280", "environment_preparation": "B-255",
    "baseline_identity": "B-281", "s5_stand_limits": "B-282", "reporter_rehearsal_identity": "B-283",
    "environment_property_cover": "B-283"}      # B-414 adds the row; its verdict words convert with the reporter row's (B-283)
EXPECTED_EXEMPT = ["request_shape", "executor_present", "manual_evidence_shape", "witness_backstop",
                   "equivalence_metric", "source_freshness"]
EXPECTED_CONVERTED = ["inputs_unchanged", "then_oracle", "stand_login_gate", "stand_check", "probe_verdict",
                      "finish_exit_gate", "exploratory_oracle", "branch_accounting", "s3_grounding", "regression_on_main",
                      "s5_open_oracle_asserted", "env_block_evidence", "plan_target_on_base"]
BLIND_STEM = "a gate that compares only non-anchor words, outside any registered site, is not seen"
CONVERTED_TEST = "scripts/tests/test_gate_registry.py"


# --- helpers ----------------------------------------------------------------------------------------

def live_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def row(rid="g_one", status="debt", sites=None, **over) -> dict:
    """A valid row of the given status; `over` replaces fields."""
    out = {
        "id": rid, "inventory": "G1", "decides": "is the thing valid", "sites": sites or [], "field": "result",
        "words": ["matched", "unknown"],
        "verdict_map": {"matched": {"class": "matched"}, "unknown": {"class": "unknown", "owner": "environment"}},
        "accepts": {}, "promotable": False, "unknown_branch": "rerun", "on_no_answer": "rerun",
        "waits_at": None, "closed_by": [], "addressee": ["code_routes"], "person_subject": None,
        "policy_file": None, "scope_keys": [], "binding_keys": [], "question_kind": None,
        "vocabulary": "code" if status == "converted" else "target",
        "test": CONVERTED_TEST if status == "converted" else None, "status": status,
        "debt_ref": "B-100" if status == "debt" else "",
        "exempt_reason": "not a validity gate" if status == "exempt" else ""}
    out.update(over)
    return out


def site(file="f.py", function="f", role="accept", **over) -> dict:
    out = {"file": file, "function": function, "role": role}
    out.update(over)
    return out


def reg(*rows) -> dict:
    return {"schema_version": 1, "rows": list(rows)}


def fake_package(files: dict) -> Path:
    """A throwaway <root>/scripts/*.py (and the one test file a converted row may name)."""
    root = temp_dir("qa-factory-gates-")
    (root / "scripts" / "tests").mkdir(parents=True)
    (root / "references").mkdir()
    (root / CONVERTED_TEST).write_text("", encoding="utf-8")
    for name, body in files.items():
        (root / "scripts" / name).write_text(body, encoding="utf-8")
    return root


def audit(files: dict, *rows, registry=None) -> dict:
    """Analyse a fake package against the given rows (a dummy exempt row keeps the registry non-empty)."""
    root = fake_package(files)
    try:
        return GR.analyse(root, registry if registry is not None else reg(row("other", "exempt"), *rows))
    finally:
        cleanup(root)


def a_findings(result: dict) -> list:
    return [f for f in result["findings"] if F_A in f]


def called_names(path: Path, function: str) -> set:
    """The names called anywhere inside the module-level def `function` of a source file (an AST read: `f(...)` is `f`,
    `m.f(...)` is `f`)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function:
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    callee = call.func
                    out.add(callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", ""))
    return out


def write_calls(tree: ast.AST) -> list:
    """The calls in `tree` that write: open() with a w/a/x/+ mode, write_text/write_bytes/write/writelines/
    mkdir/touch/unlink/rmdir, os.replace/rename/remove/unlink/makedirs/mkdir, anything of shutil."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
        base = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
        if name in ("write_text", "write_bytes", "write", "writelines", "mkdir", "touch", "unlink", "rmdir") \
                and base != "os":
            out.append(f"{name} at line {node.lineno}")
        if base == "os" and name in ("replace", "rename", "remove", "unlink", "makedirs", "mkdir"):
            out.append(f"os.{name} at line {node.lineno}")
        if base == "shutil":
            out.append(f"shutil.{name} at line {node.lineno}")
        if name == "open":
            modes = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)] + \
                    [k.value.value for k in node.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
            if any(set(str(m)) & set("wax+") for m in modes):
                out.append(f"open(..., {modes}) at line {node.lineno}")
    return out


def cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = GR.main(list(argv))
    return code, buf.getvalue()


def mutated(registry: dict, rid: str, **over) -> dict:
    out = copy.deepcopy(registry)
    for r in out["rows"]:
        if r["id"] == rid:
            r.update(over)
    return out


# --- K-T1.1, K-T1.2, K-T1.14: the live registry against the live package ----------------------------

def part_live_registry() -> None:
    registry = live_registry()
    ids = [r["id"] for r in registry["rows"]]
    check_eq("K-T1.1 the live registry has the 22 ids of the node spec plus source_freshness (Q6-A)", ids, EXPECTED_IDS)
    check_eq("K-T1.1 every id is unique", len(set(ids)), len(ids))
    check_eq("the classes are the five", registry["classes"],
             ["matched", "mismatched", "unknown", "not_applicable", "person_confirmed"])
    check_eq("the anchor words are the three that are never anything but a verdict", registry["anchor_words"],
             ["matched", "mismatched", "person_confirmed"])
    by_id = {r["id"]: r for r in registry["rows"]}
    check_eq("the debt rows are the Lead's table, ref for ref",
             {r["id"]: r["debt_ref"] for r in registry["rows"] if r["status"] == "debt"}, EXPECTED_DEBT)
    check_eq("the exempt rows are the six the node spec names",
             [r["id"] for r in registry["rows"] if r["status"] == "exempt"], EXPECTED_EXEMPT)
    check_eq("the converted rows are then_oracle, stand_login_gate, stand_check, inputs_unchanged and the probe verdict",
             sorted(r["id"] for r in registry["rows"] if r["status"] == "converted"), sorted(EXPECTED_CONVERTED))
    for r in registry["rows"]:
        if r["status"] == "converted":
            check(f"K-T1.1 converted {r['id']} names a test that exists",
                  (PLUGIN_ROOT / str(r["test"])).is_file(), str(r["test"]))
        if r["status"] == "debt":
            check(f"K-T1.1 debt {r['id']} has an ASCII B-nnn debt_ref",
                  GR.DEBT_REF_RE.fullmatch(str(r["debt_ref"])) is not None, str(r["debt_ref"]))
        if r["status"] == "exempt":
            check(f"exempt {r['id']} says why", bool(str(r["exempt_reason"]).strip()))
    # the Q5-A and Q6-A decisions, as data
    sites = {(s["file"], s["function"]): (r["id"], s["role"]) for r in registry["rows"] for s in r["sites"]}
    check_eq("Q5-A: gate_preflight._derive_probe is a dispatch site of stand_identity",
             sites[("gate_preflight.py", "_derive_probe")], ("stand_identity", "dispatch"))
    check_eq("Q6-A: source_preflight.assess_freshness is an exempt row's site",
             by_id["source_freshness"]["status"], "exempt")

    result = GR.analyse(PLUGIN_ROOT)
    check_eq("K-T1.1 the live registry is clean against the live package", result["findings"], [])
    scans = GR.scan_package(PLUGIN_ROOT)
    for (fname, function) in sorted(sites):
        ok = fname in scans and (function == GR.MODULE or function in scans[fname]["outer"])
        check(f"K-T1.1 site {fname}:{function} exists", ok)

    # NEG: one site's function renamed in a copy of the registry -> F-c names it
    renamed = copy.deepcopy(registry)
    for r in renamed["rows"]:
        for s in r["sites"]:
            if (s["file"], s["function"]) == ("execution_fingerprint.py", "build"):
                s["function"] = "build_renamed_away"
    got = GR.analyse(PLUGIN_ROOT, renamed)["findings"]
    check("K-T1.1 NEG: a renamed site function is a stale-site finding naming it",
          any("build_renamed_away" in f and "is stale" in f and "provenance_acceptance" in f for f in got), "\n".join(got))
    gone = copy.deepcopy(registry)
    gone["rows"][1]["sites"][2]["file"] = "no_such_script.py"
    got = GR.analyse(PLUGIN_ROOT, gone)["findings"]
    check("K-T1.1 NEG: a site whose file is gone is a stale-site finding too",
          any("no_such_script.py" in f and "is gone" in f for f in got), "\n".join(got))

    # K-T1.2: the CLI on the live package, and every G7 comparison attributed
    p = run_script("gate_registry.py", "--check")
    check("K-T1.2 gate_registry.py --check exits 0 on the live package", p.returncode == 0, (p.stdout + p.stderr)[-800:])
    lines = p.stdout.splitlines()
    check_eq("K-T1.2 its first line", lines[0] if lines else "", "A26 gate registry: no violations")
    check_in("K-T1.2 the second header line states the blind spot", BLIND_STEM, lines[1] if len(lines) > 1 else "")
    check_in("K-T1.2 it lists the debt, decided and not forgotten", "14 gate(s) left as debt:", p.stdout)
    check_in("K-T1.2 and the exempt gates", "6 gate(s) exempt:", p.stdout)

    code, out = cli("--sites")
    check_eq("K-T1.2 --sites exits 0", code, 0)
    check_not_in("K-T1.2 --sites: nothing is UNREGISTERED", "UNREGISTERED", out)
    shown = {(s["file"], s["function"]): s for s in result["items"]}
    # t-300 N2: S1 (run_suite.probe_runtime), S8 (probe_by_code.probe_runtime) and S9 (manual_capture.stand_probe) no longer SHOW a
    # literal comparison - they go through `acceptable_provenance` (or, S8, through S1) - so they leave this list; the sites
    # that still compare (the local_source and fingerprint bare `not_applicable`, the baseline, the equivalence measure, ...) stay.
    g7 = [("execution_request.py", "validate_request"), ("execution_fingerprint.py", "build"),
          ("manual_evidence.py", "_provenance_errors"), ("manual_evidence.py", "_other_profile_errors"),
          ("manual_evidence.py", "validate_baseline_record"),
          ("coverage_contract.py", "validate_manual_current"), ("environment_preparation.py", "_run_step"),
          ("source_preflight.py", "assess_freshness"), ("run_suite.py", "build_run_block"),
          ("gate_preflight.py", "_derive_probe")]
    for key in g7:
        item = shown.get(key)
        check(f"K-T1.2 --sites lists the G7 comparison in {key[0]}:{key[1]}, attributed to a row",
              bool(item) and bool(item["rows"]) and item["allowed"], str(item))
    # K-N2.12: each site that no longer compares CALLS the one predicate (an AST read of the live file, not a literal search)
    for (fname, function), callee in ((("run_suite.py", "probe_runtime"), "acceptable_provenance"),
                                      (("manual_capture.py", "stand_probe"), "acceptable_provenance"),
                                      (("execution_request.py", "rehearsal_probe"), "acceptable_provenance"),
                                      (("execution_request.py", "validate_request"), "acceptable_provenance"),
                                      (("execution_fingerprint.py", "build"), "acceptable_provenance"),
                                      (("manual_evidence.py", "_provenance_errors"), "acceptable_provenance"),
                                      # the wiring pin of the split (HF8-19 F1): `validate` reaches the predicate only through it
                                      (("manual_evidence.py", "validate"), "_provenance_errors"),
                                      (("manual_evidence.py", "validate"), "_other_profile_errors"),
                                      (("manual_evidence.py", "_other_profile_errors"), "_provenance_errors"),
                                      (("coverage_contract.py", "validate_manual_current"), "acceptable_provenance"),
                                      (("probe_by_code.py", "probe_runtime"), "probe_runtime")):
        check(f"K-N2.12 {fname}:{function} calls `{callee}` (the one predicate; S8 delegates to the strict reader)",
              callee in called_names(PLUGIN_ROOT / "scripts" / fname, function))
    check("K-N2.12 positive control: the same AST read finds a call known to be in profile_contract.acceptable_provenance",
          "validate_runtime_provenance" in called_names(PLUGIN_ROOT / "scripts" / "profile_contract.py", "acceptable_provenance"))
    check("K-N2.12 S8 holds no validator call of its own (B-255 a: the copy is gone)",
          "validate_runtime_provenance" not in called_names(PLUGIN_ROOT / "scripts" / "probe_by_code.py", "probe_runtime"))
    # K-N2.12 NEG: a person's word added to the BASELINE consumer of an in-memory copy is exactly one finding, naming it
    worded = copy.deepcopy(registry)
    next(r for r in worded["rows"] if r["id"] == "baseline_identity")["accepts"]["provenance.baseline"].append("person_confirmed")
    got = GR.analyse(PLUGIN_ROOT, worded)["findings"]
    check_eq("K-N2.12 NEG: `person_confirmed` added to provenance.baseline: exactly one finding",
             len(got), 1, )
    check("K-N2.12 NEG: and it names the consumer and the word", "provenance.baseline" in "".join(got) and "person_confirmed" in "".join(got),
          "\n".join(got))
    check("K-T1.2 every comparison the scan counts is attributed", all(i["rows"] and i["allowed"] for i in result["items"]))
    # S1 keeps its non-acceptance comparison as an `allow`, and the allow matches (K-T1.3 on the live data)
    allow = [e for r in registry["rows"] for s in r["sites"] for e in s.get("allow", [])]
    check_eq("S1's data-seed shape check is the one allow entry today, the WHOLE comparison (F3)",
             [e["compare"] for e in allow], ['seed.get("result") not in {"matched", "mismatched", "unknown"}'])

    # NEG: the registry minus provenance_acceptance, in memory -> F-a findings naming the S-sites
    minus = copy.deepcopy(registry)
    minus["rows"] = [r for r in minus["rows"] if r["id"] != "provenance_acceptance"]
    got = [f for f in GR.analyse(PLUGIN_ROOT, minus)["findings"] if F_A in f]
    # t-300 N2: pinned to the sites that still compare an anchor word (the local_source and data-seed literals of
    # validate_request, the baseline's person_confirmed branch, the deploy step, gate A's identity read): the ones that moved
    # to the predicate hold no anchor literal now, so nothing of theirs is left for the scan to flag
    for fname, function in (("execution_request.py", "validate_request"), ("manual_evidence.py", "validate_baseline_record"),
                            ("environment_preparation.py", "_run_step"), ("gate_preflight.py", "_observed_identity")):
        check(f"K-T1.2 NEG: without provenance_acceptance, {fname}:{function} is F-a",
              any(f.startswith(fname + ":") and f"({function})" in f for f in got), f"{len(got)} F-a findings")
    # and the empty registry: valid as data, and every live site is F-a
    got = GR.analyse(PLUGIN_ROOT, reg())["findings"]
    check("K-T1.8 `rows: []` is a finding of its own", any("holds no rows" in f for f in got))
    check("K-T1.8 and every live site is F-a (more than forty, naming execution_request.py)",
          len([f for f in got if F_A in f]) > 40 and any("execution_request.py" in f and F_A in f for f in got))

    # K-T1.14: the --json contract
    code, out = cli("--json")
    check_eq("K-T1.14 --json exits 0 on the live package", code, 0)
    data = json.loads(out)
    check_eq("K-T1.14 --json keys are findings, debt, exempt", sorted(data), ["debt", "exempt", "findings"])
    check_eq("K-T1.14 findings is empty", data["findings"], [])
    check_eq("K-T1.14 debt lists the 13 ids of the node spec and B-414's environment_property_cover", [d["id"] for d in data["debt"]], list(EXPECTED_DEBT))
    check_eq("K-T1.14 a debt item has id, decides, debt_ref", sorted(data["debt"][0]), ["debt_ref", "decides", "id"])
    check_eq("K-T1.14 exempt lists the six", [d["id"] for d in data["exempt"]], EXPECTED_EXEMPT)
    check_eq("K-T1.14 an exempt item has id, decides, exempt_reason", sorted(data["exempt"][0]),
             ["decides", "exempt_reason", "id"])
    # the document against a shape built INDEPENDENTLY, straight from the registry file (t-359: comparing
    # --check --json with itself proved nothing): counts per status, the debt ids with their refs, the exempt ids
    raw_rows = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))["rows"]
    raw = {s: [r for r in raw_rows if r["status"] == s] for s in ("converted", "debt", "exempt")}
    # AR-20, TQ1-1 (t-684): converted 10 -> 11 - the row `s5_open_oracle_asserted` joined; RH2-9 (t-691): 11 -> 12, `env_block_evidence`; TQ1-21: 12 -> 13, `plan_target_on_base`; debt and exempt are unchanged
    check_eq("K-T1.14 the registry file's rows split 13 converted / 14 debt / 6 exempt (s3_grounding, regression_on_main, s5_open_oracle_asserted, env_block_evidence and plan_target_on_base joined the 8)",
             {s: len(v) for s, v in raw.items()}, {"converted": 13, "debt": 14, "exempt": 6})
    check_eq("K-T1.14 --json debt = the file's debt rows (id, decides, debt_ref), in order",
             data["debt"], [{"id": r["id"], "decides": r["decides"], "debt_ref": r["debt_ref"]} for r in raw["debt"]])
    check_eq("K-T1.14 --json exempt = the file's exempt rows (id, decides, exempt_reason), in order",
             data["exempt"], [{"id": r["id"], "decides": r["decides"], "exempt_reason": r["exempt_reason"]}
                              for r in raw["exempt"]])
    check_eq("K-T1.14 debt + exempt + converted = every row of the file",
             len(data["debt"]) + len(data["exempt"]) + len(raw["converted"]), len(raw_rows))
    code, out = cli("--check", "--json")
    check_eq("K-T1.14 --check --json prints the same keys as --json", sorted(json.loads(out)), sorted(data))
    code, out = cli("--sites", "--json")
    listed = json.loads(out)
    check_eq("K-T1.14 --sites --json keys", sorted(listed[0]),
             ["allowed", "file", "function", "line", "rows", "source"])
    check_eq("K-T1.14 --sites --json holds every counted comparison", len(listed), len(result["items"]))
    # a package with no registry says so, rather than passing
    root = fake_package({})
    try:
        found = GR.analyse(root)
        check("a package with no registry file is F-g, not an empty pass",
              any("references/gate-registry.json cannot be read" in f for f in found["findings"]))
    finally:
        cleanup(root)


# --- K-T1.3, K-T1.6: the scanner on synthetic packages ----------------------------------------------

FLAGGED = [
    ("a module-level ACCEPTED used later", 'ACCEPTED = {"matched", "not_applicable"}\n\ndef f(r):\n    return r in ACCEPTED\n',
     "r in ACCEPTED"),
    ("a function-level set used later", 'def f(r):\n    ok = {"matched"}\n    return r in ok\n', "r in ok"),
    ("an annotated module-level set", 'ACC: set = {"matched"}\n\ndef f(r):\n    return r in ACC\n', "r in ACC"),
    ("a name bound to the word", 'M = "matched"\n\ndef f(r):\n    return r == M\n', "r == M"),
    ("a lambda inside a function", 'def f(rs):\n    return list(filter(lambda r: r == "matched", rs))\n', "r == 'matched'"),
    ("an != chain", 'def f(r):\n    return r != "matched" and r != "not_applicable"\n', "r != 'matched'"),
    ("the .get(result) ==", 'def f(rec):\n    return rec.get("result") == "matched"\n', "rec.get('result') == 'matched'"),
    ("a tuple in", 'def f(r):\n    return r in ("matched", "not_applicable")\n', "r in ('matched', 'not_applicable')"),
    ("a negated membership", 'def f(r):\n    return r not in ("matched",)\n', "r not in ('matched',)"),
    ("a reversed compare", 'def f(r):\n    return "matched" == r\n', "'matched' == r"),
    ("a frozenset inside a compare", 'def f(r):\n    return r in frozenset({"matched"})\n', "r in frozenset({'matched'})"),
    ("a bare frozenset", 'X = frozenset({"matched"})\n', "frozenset({'matched'})"),
    ("a match statement", 'def f(r):\n    match r:\n        case "matched":\n            return 1\n', "case 'matched'"),
    ("an is", 'def f(r):\n    return r is "matched"\n', "r is 'matched'"),
    ("a comparison at module level", 'r = 1\nif r == "matched":\n    pass\n', "r == 'matched'"),
    ("a hidden token set as a keyword", 'def f(g):\n    return g(accepts=("matched", "person_confirmed"))\n',
     "('matched', 'person_confirmed')"),
    ("a conditional operand", 'def f(r, c):\n    return r == ("matched" if c else "other")\n', "r == ('matched' if c else 'other')"),
    ("a dict-key membership", 'def f(r):\n    return r in {"matched": 1}\n', "r in {'matched': 1}"),
    ("a method of a class", 'class C:\n    def go(self, r):\n        return r == "mismatched"\n', "r == 'mismatched'"),
]
SILENT = [
    ("a dict KEY", 'D = {"matched": 1}\n'),
    ("a .get argument", 'def f(r):\n    return r.get("matched")\n'),
    ("a plain assignment", 'x = "matched"\n'),
    ("a print", 'def f():\n    print("matched")\n'),
    ("a docstring that names the comparison", 'def f():\n    """is r == "matched" ? the docstring says so"""\n    return 1\n'),
    ("an f-string", 'def f(r):\n    return f"result == matched: {r}"\n'),
    ("a log line", 'import logging\n\ndef f(r):\n    logging.info("verdict matched for %s", r)\n'),
    ("a subscript index", 'def f(r):\n    return r["matched"]\n'),
    ("a call argument", 'def f(r, g):\n    return g("matched")\n'),
    ("a comment", 'def f(r):\n    return r  # r == "matched" would be wrong here\n'),
    ("a non-anchor word outside any site (the stated blind spot)", 'def f(r):\n    return r == "not_applicable"\n'),
]


def part_scanner() -> None:
    # K-T1.3: a planted literal in a fake package
    body = 'def f(rec):\n    return rec["result"] == "matched"\n'
    got = audit({"f.py": body})
    found = a_findings(got)
    check_eq("K-T1.3 a planted unregistered comparison is exactly one F-a", len(found), 1)
    check("K-T1.3 and it names file:line (function) and the source",
          bool(found) and found[0].startswith("f.py:2 (f): the verdict comparison `rec['result'] == 'matched'`"), "\n".join(found))
    check_in("K-T1.3 and the door: the registry path", "references/gate-registry.json", found)
    check_eq("K-T1.3 CONTROL: the same line in a registered debt accept site is no finding",
             audit({"f.py": body}, row("g_debt", "debt", [site()]))["findings"], [])
    check_eq("K-T1.3 CONTROL: in an exempt accept site, none",
             audit({"f.py": body}, row("g_ex", "exempt", [site()]))["findings"], [])
    for role in ("produce", "validate", "dispatch", "measure", "vocabulary", "library"):
        check_eq(f"K-T1.3 CONTROL: a `{role}` site allows it",
                 audit({"f.py": body}, row("g_role", "debt", [site(role=role)]))["findings"], [])
    got = audit({"f.py": body}, row("g_conv", "converted", [site()]))
    check("K-T1.3 inside a converted accept site, the comparison is F-a", len(a_findings(got)) == 1, "\n".join(got["findings"]))
    with_call = 'def f(rec):\n    acceptable(rec, "x.y")\n    return rec["result"] == "matched"\n'
    allow = [{"compare": 'rec["result"] == "matched"', "why": "not an acceptance: a shape check"}]
    check_eq("K-T1.3 with the allow entry equal to the whole comparison (double quotes) and the acceptable() call, none",
             audit({"f.py": with_call}, row("g_conv", "converted", [site(allow=allow)]))["findings"], [])
    got = audit({"f.py": with_call}, row("g_conv", "converted",
                                         [site(allow=allow + [{"compare": "nothing like this", "why": "stale"}])]))
    check("K-T1.3 a stale allow entry is F-d naming it",
          any("nothing like this" in f and "matches no comparison" in f for f in got["findings"]), "\n".join(got["findings"]))
    check_eq("K-T1.3 and only that", len(got["findings"]), 1)
    # the row's own words count inside its own sites (Q3-A)
    own = 'def f(r):\n    acceptable(r, "x.y")\n    return r == "not_applicable"\n'
    check("K-T1.3 a non-anchor word of the row's `words` counts inside the row's converted site",
          len(a_findings(audit({"f.py": own}, row("g_conv", "converted", [site()],
                                                  words=["matched", "not_applicable"],
                                                  verdict_map={"matched": {"class": "matched"},
                                                               "not_applicable": {"class": "not_applicable"}})))) == 1)
    check_eq("K-T1.3 ... and the same line is nothing in a debt site",
             audit({"f.py": own}, row("g_debt", "debt", [site()], words=["matched", "not_applicable"],
                                      verdict_map={"matched": {"class": "matched"},
                                                   "not_applicable": {"class": "not_applicable"}}))["findings"], [])

    # K-T1.6: the adversarial list. Each flagged input is exactly ONE finding, carrying the comparison's own text
    for label, source, text in FLAGGED:
        got = audit({"f.py": source})
        found = a_findings(got)
        check(f"K-T1.6 flagged, once: {label}", len(found) == 1 and len(got["findings"]) == 1, "\n".join(got["findings"]) or "no finding")
        check_in(f"K-T1.6 flagged as the comparison itself: {label}", text, found)
    for label, source in SILENT:
        check_eq(f"K-T1.6 silent: {label}", audit({"f.py": source})["findings"], [])
    # a package whose script does not parse is a finding, not a silence
    got = audit({"f.py": "def broken(:\n"})
    check("a script that does not parse is a finding naming it",
          any("scripts/f.py does not parse" in f for f in got["findings"]), "\n".join(got["findings"]))
    root = fake_package({"f.py": "x = 1\n"})
    try:
        (root / "scripts" / "tests" / "test_planted.py").write_text('def t(r):\n    return r == "matched"\n', encoding="utf-8")
        check_eq("scripts/tests/** is not scanned (a planted comparison there is no finding)",
                 GR.analyse(root, reg(row("other", "exempt")))["findings"], [])
    finally:
        cleanup(root)


# --- K-T1.4, K-T1.5, K-T1.9, K-T1.10: the schema rules -----------------------------------------------

def named(result: dict, rid: str, field: str) -> bool:
    return any(f.startswith(f"{rid}.{field}:") for f in result["findings"])


def part_schema() -> None:
    def run(*rows, registry=None):
        return audit({"f.py": "x = 1\n"}, *rows, registry=registry)

    check_eq("a valid debt, converted and exempt row make a clean registry",
             run(row("a", "debt"), row("b", "converted"), row("c", "exempt"))["findings"], [])
    # K-T1.4
    check("K-T1.4 unknown_branch `pass` is a finding naming the row and the field",
          named(run(row("a", unknown_branch="pass")), "a", "unknown_branch"))
    check("K-T1.4 on_no_answer `pass` is a finding", named(run(row("a", on_no_answer="pass")), "a", "on_no_answer"))
    check("K-T1.4 waits_at `stage_exit` is a finding",
          named(run(row("a", on_no_answer="wait", waits_at="stage_exit", closed_by=["person"])), "a", "waits_at"))
    check("K-T1.4 `wait` with no waits_at is a finding", named(run(row("a", on_no_answer="wait", closed_by=["person"])), "a", "waits_at"))
    check("K-T1.4 `wait` with no closed_by is a finding", named(run(row("a", on_no_answer="wait", waits_at="gate_a")), "a", "closed_by"))
    check_eq("K-T1.4 CONTROL: a well-formed wait row is clean",
             run(row("a", on_no_answer="wait", waits_at="gate_a", closed_by=["person"]))["findings"], [])
    # K-T1.5
    check("K-T1.5 a debt row without debt_ref is a finding", named(run(row("a", "debt", debt_ref="")), "a", "debt_ref"))
    check("K-T1.5 a Cyrillic debt_ref is a finding",
          named(run(row("a", "debt", debt_ref="B-255" + CYRILLIC_A)), "a", "debt_ref"))
    check("K-T1.5 a debt_ref with another script's digits is a finding",
          named(run(row("a", "debt", debt_ref="B-" + ARABIC_FIVE * 3)), "a", "debt_ref"))
    check("K-T1.5 a debt_ref that is not B-nnn is a finding", named(run(row("a", "debt", debt_ref="t-302")), "a", "debt_ref"))
    check("K-T1.5 a four-digit debt_ref is a finding", named(run(row("a", "debt", debt_ref="B-2555")), "a", "debt_ref"))
    check("K-T1.5 a debt_ref with a trailing newline is a finding", named(run(row("a", "debt", debt_ref="B-255\n")), "a", "debt_ref"))
    check("K-T1.5 an exempt row without a reason is a finding", named(run(row("a", "exempt", exempt_reason="")), "a", "exempt_reason"))
    check("K-T1.5 an exempt row with a blank reason is a finding", named(run(row("a", "exempt", exempt_reason="  ")), "a", "exempt_reason"))
    check("a bad status is a finding", named(run(row("a", status="done")), "a", "status"))
    check("a converted row with no test is a finding", named(run(row("a", "converted", test=None)), "a", "test"))
    check("a test that does not exist is a finding", named(run(row("a", test="scripts/tests/test_nope.py")), "a", "test"))
    check("an exempt row with a test is a finding", named(run(row("a", "exempt", test=CONVERTED_TEST)), "a", "test"))
    # K-T1.9
    for token in ("unknown", "mismatched", "unknown:image", "mismatched:x", "bogus", "matched:why", "person_confirmed:x",
                  "not_applicable:Bad Code", ""):
        check(f"K-T1.9 an accepts token {token!r} is a finding",
              named(run(row("a", accepts={"gate.consumer": [token]})), "a", "accepts"))
    check_eq("K-T1.9 CONTROL: the whole grammar is clean",
             run(row("a", promotable=True, accepts={"gate.one": ["matched", "person_confirmed", "not_applicable",
                                                                  "not_applicable:no_changed_file",
                                                                  "not_applicable:local_source"]}))["findings"], [])
    check("K-T1.9 promotable false with person_confirmed accepted is a finding",
          named(run(row("a", promotable=False, accepts={"gate.one": ["person_confirmed"]})), "a", "promotable"))
    check("K-T1.9 a consumer id without a gate is a finding", named(run(row("a", accepts={"consumer": ["matched"]})), "a", "accepts"))
    got = run(row("a", accepts={"gate.one": ["matched"]}), row("b", accepts={"gate.one": ["matched"]}))
    check("a consumer id used by two rows is a finding", any("gate.one" in f and "already used" in f for f in got["findings"]))
    # K-T1.10
    check("K-T1.10 closed_by naming a role without person is a finding (F10)",
          named(run(row("a", on_no_answer="wait", waits_at="gate_a", closed_by=["role:qa-code-critic"])), "a", "closed_by"))
    check("K-T1.10 person in addressee without person_subject is a finding",
          named(run(row("a", addressee=["code_routes", "person"])), "a", "person_subject"))
    check_eq("K-T1.10 CONTROL: with person_subject it is clean",
             run(row("a", addressee=["code_routes", "person"], person_subject="world"))["findings"], [])
    check("a gate whose only unknown owner is factory has no person (FR-3)",
          named(run(row("a", addressee=["person"], person_subject="world",
                        verdict_map={"matched": {"class": "matched"},
                                     "unknown": {"class": "unknown", "owner": "factory"}})), "a", "addressee"))
    check("an addressee outside the vocabulary is a finding", named(run(row("a", addressee=["everyone"])), "a", "addressee"))
    # the rest of the schema
    check("a word with no verdict_map entry is a finding naming the word",
          any("`unknown` has no entry" in f for f in run(row("a", verdict_map={"matched": {"class": "matched"}}))["findings"]))
    check("a verdict_map key that is not a word is a finding",
          named(run(row("a", verdict_map={"matched": {"class": "matched"}, "unknown": {"class": "unknown"},
                                          "extra": {"class": "matched"}})), "a", "verdict_map"))
    check("a class outside the classes is a finding",
          named(run(row("a", verdict_map={"matched": {"class": "passed"}, "unknown": {"class": "unknown"}})), "a", "verdict_map"))
    check("an owner outside the vocabulary is a finding",
          named(run(row("a", verdict_map={"matched": {"class": "matched"},
                                          "unknown": {"class": "unknown", "owner": "nobody"}})), "a", "verdict_map"))
    check("a non-exempt row with no words is a finding", named(run(row("a", words=[], verdict_map={})), "a", "words"))
    check_eq("an exempt row may have no words", run(row("a", "exempt", words=[], verdict_map={}))["findings"], [])
    check("a row id outside [a-z][a-z0-9_]* is a finding", named(run(row("Bad-Id")), "Bad-Id", "id"))
    got = run(row("a"), row("a"))
    check("a duplicate row id is a finding naming it", any(f.startswith("a: the row id is used twice") for f in got["findings"]))
    check("an unknown row key is a finding (the schema is strict)",
          any("unknown key `surprise`" in f for f in run(row("a", surprise=1))["findings"]))
    check("an unknown top-level key is a finding",
          any("unknown top-level key `surprise`" in f for f in run(registry={"schema_version": 1, "rows": [row("a")], "surprise": 1})["findings"]))
    check("a missing required field is a finding", any("a.promotable: required" in f for f in
                                                        run({k: v for k, v in row("a").items() if k != "promotable"})["findings"]))
    check("a site with a bad role is a finding", named(run(row("a", sites=[site(role="judge")])), "a", "sites"))
    check("a site naming a path is a finding", named(run(row("a", sites=[site(file="tests/f.py")])), "a", "sites"))
    check("an allow with no reason is a finding",
          named(run(row("a", "converted", [site(allow=[{"compare": "x", "why": ""}])])), "a", "sites"))
    check("a site registered twice in one row is a finding",
          any("registered twice" in f for f in run(row("a", sites=[site(), site()]))["findings"]))
    check("a registry whose anchor_words drops `matched` is a finding",
          any("must keep `matched`" in f for f in run(registry={"schema_version": 1, "rows": [row("a")],
                                                                "anchor_words": ["mismatched", "person_confirmed"]})["findings"]))
    check("an anchor word outside the classes is a finding",
          any("`passed` is not one of the classes" in f for f in run(registry={"schema_version": 1, "rows": [row("a")],
                                                                                "anchor_words": list(GR.ANCHOR_FLOOR) + ["passed"]})["findings"]))
    # the floor: a registry with no anchor_words still scans for the three
    check("a registry that names no anchors still flags `matched` (the floor is code)",
          len(a_findings(audit({"f.py": 'def f(r):\n    return r == "matched"\n'}, registry=reg(row("a", "exempt"))))) == 1)
    check("an added anchor word widens the scan",
          len(a_findings(audit({"f.py": 'def f(r):\n    return r == "unknown"\n'},
                               registry={"schema_version": 1, "rows": [row("a", "exempt")],
                                         "anchor_words": list(GR.ANCHOR_FLOOR) + ["unknown"]}))) == 1)


# --- K-T1.7, K-T1.11 and the site rules ---------------------------------------------------------------

def part_sites() -> None:
    plain = 'def f(rec):\n    return rec["result"] == "matched"\n'
    called = 'def f(rec):\n    acceptable(rec, "x.y")\n    return rec["result"] == "matched"\n'
    called_attr = 'def f(rec):\n    gate_template.acceptable(rec, "x.y")\n    return rec["result"] == "matched"\n'
    allow = [{"compare": "rec['result'] == 'matched'", "why": "shape"}]
    conv = lambda body, **kw: audit({"f.py": body}, row("g_conv", "converted", [site(allow=allow)]), **kw)  # noqa: E731
    got = conv(plain)
    check("K-T1.7 a converted accept site with no acceptable() call is F-b",
          any("converted accept site f.py:f calls no acceptable()" in f for f in got["findings"]), "\n".join(got["findings"]))
    check_eq("K-T1.7 CONTROL: with the call (a Name), no finding", conv(called)["findings"], [])
    check_eq("K-T1.7 CONTROL: with the call (an Attribute), no finding", conv(called_attr)["findings"], [])
    check("K-T1.7 a call to acceptable_provenance is NOT the predicate",
          any("calls no acceptable()" in f for f in conv(
              'def f(rec):\n    acceptable_provenance(rec)\n    return rec["result"] == "matched"\n')["findings"]))
    check("K-T1.7 a converted row on a produce site needs no call (F-b is for accept sites)",
          not any("calls no acceptable()" in f for f in audit({"f.py": plain}, row("g_conv", "converted", [site(role="produce")]))["findings"]))
    # F-c
    got = audit({"f.py": plain}, row("g_a", "debt", [site(function="gone")]))
    check("F-c a site whose function is gone is stale, naming row, file and function",
          any(f.startswith("g_a: site f.py:gone is stale") for f in got["findings"]), "\n".join(got["findings"]))
    check("F-c a site whose function is only NESTED is stale (the owner is the outermost def)",
          any("is stale" in f for f in audit({"f.py": "def outer():\n    def inner():\n        return 1\n    return inner\n"},
                                             row("g_a", "debt", [site(function="inner")]))["findings"]))
    check("F-c a site whose file is gone is stale",
          any("scripts/nowhere.py is gone" in f for f in audit({"f.py": plain}, row("g_a", "debt", [site(file="nowhere.py")]))["findings"]))
    check_eq("<module> is always a legal site name for an existing file",
             audit({"f.py": 'if x == "matched":\n    pass\n'}, row("g_a", "debt", [site(function="<module>")]))["findings"], [])
    # F-e (K-T1.11)
    twice = 'def f(rec):\n    return rec["result"] == "matched"\n\nclass C:\n    def f(self, rec):\n        return 1\n'
    got = audit({"f.py": twice}, row("g_a", "debt", [site()]))
    check("K-T1.11 a function name defined twice in the file is F-e, naming the count",
          any("is ambiguous - 2 defs named `f`" in f for f in got["findings"]), "\n".join(got["findings"]))
    check_eq("K-T1.11 CONTROL: defined once, no finding",
             audit({"f.py": plain}, row("g_a", "debt", [site()]))["findings"], [])
    # masking: a converted accept site's function shared with another row would hide a literal
    got = audit({"f.py": called}, row("g_conv", "converted", [site(allow=allow)]), row("g_other", "exempt", [site(role="validate")]))
    check("a function shared by a converted accept site and another row is a finding (the role would mask)",
          any("registered more than once" in f and "g_conv" in f and "g_other" in f for f in got["findings"]), "\n".join(got["findings"]))
    # a comparison in a file with no row at all stays F-a even beside registered ones
    got = audit({"f.py": plain, "h.py": 'def g(r):\n    return r == "mismatched"\n'}, row("g_a", "debt", [site()]))
    check("a registered file does not cover another file's comparison",
          len(a_findings(got)) == 1 and a_findings(got)[0].startswith("h.py:"), "\n".join(got["findings"]))
    # --sites output on a fake package: attributed vs UNREGISTERED
    root = fake_package({"f.py": plain, "h.py": 'def g(r):\n    return r == "mismatched"\n'})
    try:
        items = GR.sites(root, reg(row("g_a", "debt", [site()])))
        check_eq("--sites attributes the registered comparison and leaves the other unregistered",
                 sorted((i["file"], i["rows"], i["allowed"]) for i in items),
                 [("f.py", ["g_a"], True), ("h.py", [], False)])
    finally:
        cleanup(root)


# --- the t-360 fix pass (critic t-359 F1-F6, F8) ------------------------------------------------------

def part_fix_pass() -> None:
    registry = live_registry()
    by_id = {r["id"]: r for r in registry["rows"]}
    page = {"f.py": "x = 1\n"}

    # F1: the consumers live under the rows whose promotable guards them, and a consumer inherits the
    # promotable of the row its <gate> prefix names
    home = {c: r["id"] for r in registry["rows"] for c in r["accepts"]}
    check_eq("F1 provenance.baseline lives under baseline_identity", home["provenance.baseline"], "baseline_identity")
    check_eq("F1 provenance.environment_preparation lives under environment_preparation",
             home["provenance.environment_preparation"], "environment_preparation")
    check_eq("F1 the other five consumers stay under provenance_acceptance",
             sorted(c for c, r in home.items() if r == "provenance_acceptance"),
             ["provenance.automation", "provenance.fingerprint", "provenance.manual", "provenance.manual_capture",
              "provenance.rehearsal"])
    check_eq("F1 both guarding rows are promotable false",
             (by_id["baseline_identity"]["promotable"], by_id["environment_preparation"]["promotable"]), (False, False))
    for consumer, rid in (("provenance.baseline", "baseline_identity"),
                          ("provenance.environment_preparation", "environment_preparation")):
        probe = copy.deepcopy(registry)
        for r in probe["rows"]:
            if consumer in r["accepts"]:
                r["accepts"][consumer].append("person_confirmed")
        got = GR.analyse(PLUGIN_ROOT, probe)["findings"]
        check(f"F1 person_confirmed added to {consumer}: exactly one finding, naming the consumer and the row",
              len(got) == 1 and consumer in got[0] and rid in got[0], "\n".join(got) or "0 findings")
    gate = row("gate_a", promotable=False)
    got = audit(page, gate, row("other_a", promotable=True, accepts={"gate_a.consumer": ["matched", "person_confirmed"]}))
    check("F1 a consumer on a promotable row inherits the false of the row its prefix names: one finding naming both",
          len(got["findings"]) == 1 and "gate_a.consumer" in got["findings"][0] and "`gate_a`" in got["findings"][0],
          "\n".join(got["findings"]))
    check_eq("F1 CONTROL: a prefix that names no row inherits nothing (the live `provenance.*` ids)",
             audit(page, row("other_a", promotable=True, accepts={"nowhere.consumer": ["person_confirmed"]}))["findings"], [])
    check_eq("F1 CONTROL: a prefix that names a promotable row is clean",
             audit(page, row("gate_t", promotable=True),
                   row("other_a", promotable=True, accepts={"gate_t.consumer": ["person_confirmed"]}))["findings"], [])
    got = audit(page, row("gate_b", promotable=False, accepts={"gate_b.consumer": ["person_confirmed"]}))
    check_eq("F1 a consumer under its own false row is ONE finding, not two", len(got["findings"]), 1)

    # F2: a name-bound token set is left to its comparisons only when EVERY read is a comparison
    head = 'ACCEPTS = ("matched", "person_confirmed")\n\n\ndef h(r):\n    return r in ACCEPTS\n\n\n'
    reg_h = row("g_one", "debt", [site(function="h")])
    uses = [("a call argument", 'def g(f):\n    return f(accepts=ACCEPTS)\n'),
            ("a return value", 'def g():\n    return ACCEPTS\n'),
            ("an attribute base", 'def g():\n    return ACCEPTS.count("matched")\n'),
            ("a default parameter", 'def g(accepts=ACCEPTS):\n    return accepts\n'),
            ("an iteration", 'def g():\n    return [t for t in ACCEPTS]\n'),
            ("a positional argument of a call", 'def g(f):\n    return f(ACCEPTS)\n')]
    for label, extra in uses:
        got = audit({"f.py": head + extra}, reg_h)
        check(f"F2 a set read as {label} besides its comparison: one finding, at the binding line",
              len(got["findings"]) == 1 and got["findings"][0].startswith("f.py:1 (<module>): the verdict token set"),
              "\n".join(got["findings"]) or "0 findings")
    check_eq("F2 CONTROL: every read is the registered comparison - nothing reported",
             audit({"f.py": head}, reg_h)["findings"], [])
    two = head + 'def k(r):\n    return r not in ACCEPTS\n'
    check_eq("F2 CONTROL: two comparisons, both in registered sites - nothing reported",
             audit({"f.py": two}, row("g_one", "debt", [site(function="h"), site(function="k")]))["findings"], [])
    got = audit({"f.py": two}, reg_h)
    check("F2 a second comparison in an UNREGISTERED function is the finding (at that comparison), once",
          len(got["findings"]) == 1 and "r not in ACCEPTS" in got["findings"][0], "\n".join(got["findings"]))
    check("F2 a set bound and never read is reported",
          len(audit({"f.py": 'ACCEPTS = ("matched",)\n\n\ndef h(r):\n    return r\n'}, reg_h)["findings"]) == 1)
    check_eq("F2 registered as a vocabulary site of the module, the argument use is no finding",
             audit({"f.py": head + uses[0][1]}, row("g_one", "debt", [site(function="h"),
                                                                       site(function="<module>", role="vocabulary")]))["findings"], [])
    voc = [(s["file"], s["role"]) for s in by_id["provenance_acceptance"]["sites"] if s["function"] == "<module>"]
    check_in("F2 the live registry registers profile_contract.py:<module> as a vocabulary site of provenance_acceptance",
             "('profile_contract.py', 'vocabulary')", [str(v) for v in voc])
    GR.analyse(PLUGIN_ROOT)
    check("F2 and --sites lists profile_contract.ACCEPTS (a set the old scan hid), attributed",
          any(i["file"] == "profile_contract.py" and i["function"] == "<module>" and "person_confirmed" in i["source"]
              and "not_applicable:no_changed_file" in i["source"] and i["rows"] == ["provenance_acceptance"]
              for i in GR.analyse(PLUGIN_ROOT)["items"]))

    # F3: an allow entry is the WHOLE comparison
    body = 'def f(rec):\n    acceptable(rec, "x.y")\n    return rec["result"] == "matched"\n'
    conv = lambda allow: audit({"f.py": body}, row("g_conv", "converted", [site(allow=allow)]))  # noqa: E731
    got = conv([{"compare": "rec['result'] ==", "why": "w"}])
    check("F3 a PREFIX entry is one finding: allow must be the whole comparison, naming the entry and the comparison",
          len(got["findings"]) == 1 and "allow must be the whole comparison: `rec['result'] ==`" in got["findings"][0]
          and "rec['result'] == 'matched'" in got["findings"][0], "\n".join(got["findings"]))
    check_eq("F3 and the comparison a prefix points at is NOT allowed (the prefix whitelists nothing)",
             [i["allowed"] for i in conv([{"compare": "rec['result'] ==", "why": "w"}])["items"]], [False])
    check_eq("F3 the exact text whitelists its line", conv([{"compare": 'rec["result"] == "matched"', "why": "w"}])["findings"], [])
    check_eq("F3 and marks it allowed",
             [i["allowed"] for i in conv([{"compare": 'rec["result"] == "matched"', "why": "w"}])["items"]], [True])
    check_eq("F3 whitespace and quote style do not matter",
             conv([{"compare": "rec['result']   ==   'matched'", "why": "w"}])["findings"], [])
    check("F3 an empty allow list changes nothing: the literal is F-a", len(a_findings(conv([]))) == 1)
    got = conv([{"compare": "something else entirely", "why": "w"}])
    check("F3 an entry that matches nothing is the stale finding, and the line stays F-a",
          len(a_findings(got)) == 1 and any("matches no comparison" in f for f in got["findings"]))
    two_lines = ('def f(rec):\n    acceptable(rec, "x.y")\n    a = rec["result"] == "matched"\n'
                 '    b = rec["state"] == "matched"\n    return a, b\n')
    got = audit({"f.py": two_lines}, row("g_conv", "converted", [site(allow=[{"compare": 'rec["result"] == "matched"', "why": "w"}])]))
    check("F3 the exact text whitelists exactly its line: the other comparison stays F-a",
          len(got["findings"]) == 1 and "rec['state'] == 'matched'" in got["findings"][0], "\n".join(got["findings"]))
    twice = ('def f(rec):\n    acceptable(rec, "x.y")\n    a = rec["result"] == "unknown"\n'
             '    b = rec["result"] == "unknown"\n    return a, b\n')
    check_eq("F3 two comparisons of IDENTICAL text in one site are both covered by one entry (the stated limit)",
             audit({"f.py": twice}, row("g_conv", "converted", [site(allow=[{"compare": 'rec["result"] == "unknown"', "why": "w"}])]))["findings"], [])
    got = conv([{"compare": 'rec["result"] == "matched"', "why": "w"}, {"compare": "rec['result'] ==", "why": "w"}])
    check("F3 a prefix entry beside an exact one is still its own finding",
          len(got["findings"]) == 1 and "allow must be the whole comparison" in got["findings"][0], "\n".join(got["findings"]))

    # F4: vocabulary target | code
    check_eq("F4 every live row says target or code",
             sorted({r["vocabulary"] for r in registry["rows"]}), ["code", "target"])
    check_eq("F4 `code` is the gate's own words: the D9 list, inputs_unchanged, the two converted story_run gates and the "
             "probe verdict (its words are vocabulary.yaml's probe_verdicts)",
             sorted(r["id"] for r in registry["rows"] if r["vocabulary"] == "code"),
             sorted(["case_preconditions", "test_identity", "then_oracle", "live_check_demand", "inputs_unchanged",
                     "stand_login_gate", "stand_check", "probe_verdict", "finish_exit_gate", "exploratory_oracle", "branch_accounting",
                     "s3_grounding", "regression_on_main", "s5_open_oracle_asserted", "env_block_evidence", "plan_target_on_base"]))
    check("F4 no live converted row says target",
          not [r["id"] for r in registry["rows"] if r["status"] == "converted" and r["vocabulary"] == "target"])
    missing = row("a")
    del missing["vocabulary"]
    check("F4 a row with no `vocabulary` is a finding", any(f.startswith("a.vocabulary: required") for f in audit(page, missing)["findings"]))
    check("F4 a value other than target|code is a finding", named(audit(page, row("a", vocabulary="stand-in")), "a", "vocabulary"))
    check("F4 a converted row that says target is a finding naming the row and the key",
          named(audit(page, row("a", "converted", vocabulary="target")), "a", "vocabulary"))
    for status in ("debt", "exempt", "converted"):
        check_eq(f"F4 CONTROL: a {status} row that says code is clean", audit(page, row("a", status, vocabulary="code"))["findings"], [])
    for status in ("debt", "exempt"):
        check_eq(f"F4 CONTROL: a {status} row that says target is clean", audit(page, row("a", status, vocabulary="target"))["findings"], [])
    flipped = mutated(registry, "s5_coverage", status="converted", test="scripts/tests/test_s5_precheck.py", debt_ref="")
    check("F4 flipping a live `target` row to converted names the row and the key",
          any(f.startswith("s5_coverage.vocabulary:") for f in GR.analyse(PLUGIN_ROOT, flipped)["findings"]))

    # F5: the forms the scan does not see are in the scope text, one line each
    for form in ("x == V.OK", 'def f(ok="matched")', "operator.eq(x", ".split()", '.startswith("match")',
                 "d.get(word)", "comprehension filter"):
        check_in(f"F5 the scope text names the invisible form {form!r}", form, GR.__doc__)

    # F6: --sites labels, three forms
    root = fake_package({
        "f.py": 'def f(rec):\n    acceptable(rec, "x.y")\n    return rec["result"] == "matched"\n',
        "h.py": 'def g(r):\n    return r == "mismatched"\n',
        "k.py": 'def k(r):\n    return r == "matched"\n'})
    try:
        rows = reg(row("g_conv", "converted", [site(file="f.py", function="f")]),
                   row("g_debt", "debt", [site(file="k.py", function="k")]))
        (root / "references" / "gate-registry.json").write_text(json.dumps(rows), encoding="utf-8")
        saved_root = GR.PLUGIN_ROOT
        GR.PLUGIN_ROOT = root
        try:
            code, out = cli("--sites")
            code_json, out_json = cli("--sites", "--json")
        finally:
            GR.PLUGIN_ROOT = saved_root
        lines = {line.split("  ")[0]: line for line in out.splitlines()}
        check_in("F6 a registered row: [<row>]", "  [g_debt]", lines["k.py:2"])
        check_in("F6 a converted accept site outside its allow list: [<row> NOT ALLOWED], not UNREGISTERED",
                 "  [g_conv NOT ALLOWED]", lines["f.py:3"])
        check_in("F6 a site in no row: [UNREGISTERED]", "  [UNREGISTERED]", lines["h.py:2"])
        check_not_in("F6 and only that one is called UNREGISTERED", "UNREGISTERED", lines["f.py:3"] + lines["k.py:2"])
        listed = {i["file"]: i for i in json.loads(out_json)}
        check_eq("F6 JSON: unregistered = no rows", (listed["h.py"]["rows"], listed["h.py"]["allowed"]), ([], False))
        check_eq("F6 JSON: not allowed = rows set, allowed false", (listed["f.py"]["rows"], listed["f.py"]["allowed"]),
                 (["g_conv"], False))
        check_eq("F6 JSON: registered = rows set, allowed true", (listed["k.py"]["rows"], listed["k.py"]["allowed"]),
                 (["g_debt"], True))
    finally:
        cleanup(root)

    # F8: the source_freshness reason names its backlog row
    reason = by_id["source_freshness"]["exempt_reason"]
    check_in("F8 source_freshness.exempt_reason names B-290", "B-290", reason)
    check_not_in("F8 and no longer says the line is pending", "pending", reason)


# --- K-T1.8: the registry file itself -----------------------------------------------------------------

def part_registry_file() -> None:
    cannot = "references/gate-registry.json cannot be read"
    cases = [("absent", None), ("0 bytes", b""), ("{}", b"{}"), ("[]", b"[]"), ("not JSON", b"{nope"),
             ("duplicate keys", b'{"schema_version": 1, "rows": [], "rows": []}'),
             ("a duplicate key inside a row", b'{"schema_version": 1, "rows": [{"id": "a", "id": "b"}]}'),
             ("invalid UTF-8", b'{"schema_version": 1, "rows": [], "note": "\xff\xfe"}'),
             ("rows is not a list", b'{"schema_version": 1, "rows": {}}'),
             ("a string", b'"gate registry"')]
    for label, content in cases:
        root = fake_package({"f.py": 'def f(r):\n    return r == "matched"\n'})
        try:
            if content is not None:
                (root / "references" / "gate-registry.json").write_bytes(content)
            got = GR.analyse(root)["findings"]
            check(f"K-T1.8 {label}: exactly one finding, F-g, naming references/gate-registry.json",
                  len(got) == 1 and cannot in got[0], "\n".join(got))
        finally:
            cleanup(root)
    root = fake_package({"f.py": 'def f(r):\n    return r == "matched"\n'})
    try:
        (root / "references" / "gate-registry.json").write_text(json.dumps(reg(row("a", "exempt"))), encoding="utf-8")
        got = GR.analyse(root)["findings"]
        check("K-T1.8 a registry file read from disk is analysed (F-a for the unregistered line)",
              len(got) == 1 and F_A in got[0], "\n".join(got))
    finally:
        cleanup(root)


# --- K-T1.12, K-T1.13: A26 is not in the doctor, and is live for A1 ------------------------------------

def part_wiring() -> None:
    tree = ast.parse((SCRIPTS / "audit_factory.py").read_text(encoding="utf-8"))
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {c.func.id for c in ast.walk(main) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    check("K-T1.12 POSITIVE CONTROL: the same AST read finds a24_refusal_registry() in main()", "a24_refusal_registry" in called, str(sorted(called)))
    check("K-T1.12 audit_factory.main() calls nothing named gate_registry or A26",
          not [c for c in called if "gate_registry" in c or "a26" in c.lower()], str(sorted(called)))
    imported = [alias.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for alias in n.names] + [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    check("K-T1.12 audit_factory imports no gate_registry at all", "gate_registry" not in imported, str(imported))

    sandbox = temp_project("qa-factory-gates-a1-")
    try:
        use_project(sandbox)
        import audit_factory as A
        found = A.a1_findings(PLUGIN_ROOT)
        check_not_in("K-T1.13 A1 does not name gate_registry.py", "gate_registry", found or ["-"])
        check_in("K-T1.13 the CLI_SCRIPTS line is there", "gate_registry", sorted(A.CLI_SCRIPTS))
        saved = set(A.CLI_SCRIPTS)
        A.CLI_SCRIPTS.discard("gate_registry")
        try:
            found = A.a1_findings(PLUGIN_ROOT)
        finally:
            A.CLI_SCRIPTS.clear()
            A.CLI_SCRIPTS.update(saved)
        check_in("K-T1.13 NEG: CLI_SCRIPTS without it names gate_registry.py as dead code", "gate_registry.py", found)
    finally:
        cleanup(sandbox)


# --- the scope statement, the text rules ---------------------------------------------------------------

def part_text() -> None:
    check_in("the blind spot of Q3-A is stated in the module's scope text", "BLIND SPOT: " + BLIND_STEM, GR.__doc__)
    check_in("and in the header of --check", BLIND_STEM, GR.BLIND_SPOT)
    code, out = cli("--check")
    check_in("the printed header carries it", BLIND_STEM, out.splitlines()[1])
    check_in("the scope text says A26 is never in the project doctor", "NEVER wired into audit_factory.main()", GR.__doc__)
    check_in("the scope text says the package cannot see a closed debt row", "cannot read plans/", GR.__doc__)
    check_in("the scope text documents the --json contract", '{"findings": [str, ...]', GR.__doc__)
    # a violation prints the A24 header shape, owner and all, and --check exits 1
    root = fake_package({"f.py": 'def f(r):\n    return r == "matched"\n'})
    try:
        (root / "references" / "gate-registry.json").write_text(json.dumps(reg(row("a", "exempt"))), encoding="utf-8")
        saved_root = GR.PLUGIN_ROOT
        GR.PLUGIN_ROOT = root
        try:
            code, out = cli("--check")
            code_json, out_json = cli("--json")
        finally:
            GR.PLUGIN_ROOT = saved_root
        check_eq("--check exits 1 on a finding", code, 1)
        check_eq("the violation header is A24's shape",
                 out.splitlines()[0], "A26 gate registry: VIOLATIONS (1)  owner: factory \u2014 nothing wanted from you")
        check_in("the finding line follows", "  - f.py:2 (f): the verdict comparison", out)
        check_eq("--json exits 1 on a finding too", code_json, 1)
        check_eq("--json carries the finding and nothing else on stdout", len(json.loads(out_json)["findings"]), 1)
    finally:
        cleanup(root)
    # FR-29, FR-30: no control byte, no Cyrillic in what this node ships
    for path in (REGISTRY_PATH, SCRIPTS / "gate_registry.py", Path(__file__)):
        raw = path.read_bytes()
        check(f"FR-29 {path.name} carries no control byte", not any(b in raw for b in (7, 8, 11, 12)))
        text = raw.decode("utf-8")
        check(f"FR-30 {path.name} carries no Cyrillic", not any(0x0400 <= ord(ch) <= 0x04FF for ch in text))
    check("the registry file is ASCII", REGISTRY_PATH.read_bytes().isascii())
    # FR-45, the WEAKER form (t-359): an AST read of gate_registry.py for a write call, not a before/after
    # of the package tree over a run. open() with a w/a/x/+ mode, write_text, write_bytes, os.replace/rename/
    # remove/unlink, anything of shutil, mkdir/touch: none may appear.
    check_eq("A26 writes nothing (FR-45, AST form): no write call in gate_registry.py",
             write_calls(ast.parse((SCRIPTS / "gate_registry.py").read_text(encoding="utf-8"))), [])
    planted = ('import os, shutil\nfrom pathlib import Path\nPath("x").write_text("y")\nopen("z", "w")\n'
               'open("z", mode="a")\nos.replace("a", "b")\nshutil.copy("a", "b")\nopen("r").read()\n')
    check_eq("FR-45 CONTROL: the same read sees the five planted writes and not the read",
             len(write_calls(ast.parse(planted))), 5)


# --- t-683 D13 (G13): the attribution of every counted comparison to a (file, function, row), pinned -------------------------------
# `--sites` counted 126 comparisons on 10.10.2026 and nothing said WHICH functions they sit in: a split that moved a comparison out
# of a registered site (or a registry edit that dropped a site) was seen only as a smaller count. These are the triples, with no line
# numbers (a moved line never breaks the pin). An addition or a removal here is a decision, taken in the diff that makes it.
D13_TRIPLES = [
    ("check_delivery.py", "assess", "delivery"),
    ("contract.py", "resolve_then_oracle", "then_oracle"),
    ("contract.py", "then_oracle_errors", "then_oracle"),
    ("coverage_contract.py", "validate_manual_current", "provenance_acceptance"),
    ("delivery_verdict.py", "decide", "delivery"),
    ("driver_stage_build.py", "build_outcome", "stand_identity"),
    ("environment_preparation.py", "_facts", "environment_preparation"),
    ("environment_preparation.py", "_run_step", "provenance_acceptance"),
    ("execution_fingerprint.py", "build", "provenance_acceptance"),
    ("execution_request.py", "validate_request", "provenance_acceptance"),
    ("exploratory_findings.py", "<module>", "exploratory_oracle"),
    ("exploratory_findings.py", "append", "exploratory_oracle"),
    ("gate_preflight.py", "_case_question", "case_preconditions"),
    ("gate_preflight.py", "_check_one_precondition", "case_preconditions"),
    ("gate_preflight.py", "_derive_probe", "stand_identity"),
    ("gate_preflight.py", "_observed_identity", "provenance_acceptance"),
    ("gate_preflight.py", "_sort_items", "case_preconditions"),
    # EP1-24 F3 (t-335-2, 454b370e): `named_container_said` has ONE comparison, `result == 'matched'`: the probe's verdict, not the
    # answered container's identity (stand_identity row, a site it registers). t-430/t-435 AR-20, the count 131 -> 134 row by row:
    # +1 `named_container_said` (this triple), +2 the two `('uncheckable', ...)` tuples of `_check_one_precondition` (case_preconditions,
    # a triple already in the set; 732f5a81, GW1-27). Two more items were reworded (gone and re-added: no net change).
    ("gate_preflight.py", "named_container_said", "stand_identity"),
    ("gate_registry.py", "<module>", "provenance_acceptance"),
    ("gate_registry.py", "_check_registry", "provenance_acceptance"),
    ("gate_registry.py", "_check_row", "provenance_acceptance"),
    ("gate_registry.py", "_token_problem", "provenance_acceptance"),
    # HF8-19 N1a: the two acceptance comparisons of `validate` moved to `_provenance_errors` (one function for a record's own
    # pair and each joined profile's), and the joined pair's revision bypass is a third comparison in `_other_profile_errors`
    ("manual_evidence.py", "_other_profile_errors", "provenance_acceptance"),
    ("manual_evidence.py", "_provenance_errors", "provenance_acceptance"),
    ("manual_evidence.py", "person_sentences", "provenance_acceptance"),
    ("manual_evidence.py", "validate_baseline_record", "provenance_acceptance"),
    ("planning_contract.py", "_unmet_preconditions", "case_preconditions"),
    ("probe_by_code.py", "_judge_rows", "probe_verdict"),
    ("profile_contract.py", "<module>", "provenance_acceptance"),
    ("profile_contract.py", "acceptable_provenance", "provenance_acceptance"),
    ("profile_contract.py", "image_identity", "provenance_acceptance"),
    ("profile_contract.py", "no_changed_file", "provenance_acceptance"),
    ("profile_contract.py", "person_confirmed", "provenance_acceptance"),
    ("profile_contract.py", "refusal_text", "provenance_acceptance"),
    ("profile_contract.py", "rehearsal_view", "provenance_acceptance"),
    ("profile_contract.py", "stand_runs_other_build", "provenance_acceptance"),
    ("profile_contract.py", "validate_runtime_provenance", "provenance_acceptance"),
    ("proof_level.py", "already_probed", "test_identity"),
    ("proof_level.py", "novelty_of", "live_check_demand"),
    ("run_suite.py", "build_run_block", "equivalence_metric"),
    ("run_suite.py", "selection_line", "equivalence_metric"),
    ("runtime_probe.py", "conclude", "stand_identity"),
    ("runtime_probe.py", "finish", "stand_identity"),
    # TQ1-1 (t-684): the four row-word comparisons of the S5 exit gate (`== 'settled'` twice, `== 'invalid'`, `== 'open'`) - one new site
    ("s5_precheck.py", "check_open_oracle_asserted", "s5_open_oracle_asserted"),
    ("source_preflight.py", "assess_freshness", "source_freshness"),
    # RH1-5 (t-1433, 0b53cc33): `finish` splits an exit-gate record of kind `unreadable` from the refusals - two comparisons
    # (`kind == 'unreadable'` and `kind != 'unreadable'`) at the site finish_exit_gate already registers; no new site, no new row.
    ("story_step.py", "_finish_gate", "finish_exit_gate"),
]
# The total is pinned beside the set: two comparisons of one triple are one entry above, and the count is what notices one of them go.
# 134 -> 135 (t-598, F-7 of t-596): EP1-36's `record.get("verdict") == "incomplete"` stands in `_judge_rows` (a site of the
# `probe_verdict` row, already in the set above); it was a helper `_tooling_gap_if_incomplete` only so that this comparison was not
# counted here. The raise is the decision, taken in the diff that makes it; the set of triples is unchanged.
# 135 -> 139 (TQ1-1, t-684, AR-20): the four comparisons of `check_open_oracle_asserted` (`state == 'settled'` twice, `'invalid'`, `'open'`),
# the site of the new row `s5_open_oracle_asserted`; no existing site changed. The raise is the decision, taken in the diff that makes it.
# 139 -> 140 (EP1-4, 9c2f084e, AR-20): one comparison the batch brought, red on the merged tree before RH2-9's row; the new row
# `env_block_evidence` adds none. The raise is the decision, taken in the diff that makes it.
# 140 -> 141 (D3-B1, t-1710): `run_suite.selection_line` (the console count line over report_scope.selection_count) is registered
# under `equivalence_metric` (G17) as a `measure` site; an inventory step of registered sites, not a quality ratchet.
# 141 -> 142 (t-1968 N1/N4/N2): `probe_by_code._judge_rows` gained `record.get('verdict') == 'intended_failure'`, attributed to
# the existing row `probe_verdict` (same triple as before, so D13_TRIPLES is unchanged); an inventory step, not a quality ratchet.
# 142 -> 137 (t-2064 N3b, t-2132): `probe_by_code.verdict_of` (Python's own row judge) is removed, and its site with it;
# the count fell by what the scan attributed to it (measured with `GR.analyse` before and after: 142, 137). A removal of a registered
# site, not a quality ratchet; D13_TRIPLES lost the `verdict_of` triple.
D13_ITEM_COUNT = 137


def part_site_attribution() -> None:
    result = GR.analyse(PLUGIN_ROOT)
    triples = sorted({(i["file"], i["function"], row) for i in result["items"] for row in i["rows"]})
    check_eq("D13: the set of (file, function, row) the scan attributes its comparisons to", triples, D13_TRIPLES)
    check_eq("D13: and the number of comparisons it counts", len(result["items"]), D13_ITEM_COUNT)
    # B-283: the row below has no triple on purpose, and the pin says so, so the move that gives it one changes this line too
    # (the row's real consumers are the R7 callers - `_card_items` via `_environment_cover`, `_reporter_card`; B-283 moves them here
    # and updates this pin).
    check_eq("D13: no counted comparison is attributed to environment_property_cover (B-283 moves its R7 callers here)",
             [t for t in triples if t[2] == "environment_property_cover"], [])
    # NEG: a copy of the registry without one site (a function that compares only non-anchor words, so the scan raises no finding
    # for it - the count is what drops) is a DIFFERENT set, and the difference names the triple
    registry, why = GR.load_registry(PLUGIN_ROOT)
    check_eq("D13: the registry reads (no reason it cannot)", why, None)
    cut = copy.deepcopy(registry)
    row = next(r for r in cut["rows"] if r["id"] == "case_preconditions")
    row["sites"] = [s for s in row["sites"] if (s["file"], s["function"]) != ("gate_preflight.py", "_case_question")]
    reduced = GR.analyse(PLUGIN_ROOT, cut)
    seen = sorted({(i["file"], i["function"], rw) for i in reduced["items"] for rw in i["rows"]})
    check_eq("D13 NEG: without the site, the set differs by exactly the triple of that site",
             sorted(set(triples) - set(seen)), [("gate_preflight.py", "_case_question", "case_preconditions")])
    check("D13 NEG: ... and so does the count", len(reduced["items"]) < D13_ITEM_COUNT, str(len(reduced["items"])))
    check_eq("D13 NEG: ... with no registry finding at all (the count and the set are the only witnesses)", reduced["findings"], [])


def main() -> None:
    part_scanner()
    part_schema()
    part_sites()
    part_fix_pass()
    part_registry_file()
    part_live_registry()
    part_site_attribution()
    part_wiring()
    part_text()
    finish("test_gate_registry")


if __name__ == "__main__":
    main()
