"""S5: every test function of the dispatch against the rubric dimensions a judge can read.

`s5_precheck.py` already counts what is mechanical — a Then with no assertion, a manifest row
that disagrees with a run block, a `sleep`. What it cannot do is read meaning, and on
TP1-15045 that is where the code critic's two rounds went: sixteen S5 dispatches, and the
findings that mattered were "this assertion does not check what the Then says", "this fixture
builds a second account the case never asked for", "this locator is a position in the DOM".
Here the loop is code, so no test function is skipped, and each one is one small state — the
function's own source plus the Then clauses of the cases it covers.

The critic reads `work/judge-code-<its dispatch>.json` first (`report_rel`; `work/judge-code.json` when run with no dispatch):
  needs_critic   a dimension failed or the judge was not sure -> full review, as without a judge
  clean          every judged dimension passed -> the critic checks only what the judge does not
                 read (the roll-call, the red probe, over-mocking, shared module state, an
                 ungrounded expected value) and still owns the verdict.
In `shadow` mode the file is a comparison record and the critic reviews everything.

`--cause` answers the other question the orchestrator was guessing: which `repair_cause` a
rework round carries. Only `test_defect` spends the repair cap (`controller.REPAIR_CAUSES`),
and on the live run two rounds of every window were spent on manifest bookkeeping and an env
file — rounds the cap should never have counted.

Nothing here prints a credential value: a `code_hardcoded_credential` answer is reported as
the test's file and line and the verdict, never the literal it found.

Calibrated 2026-09-23 against TP1-15045's own manifest, cases and harness tests: 19 test
functions, 19 requests, 39k input tokens, $0.0017 and about 11 seconds for the whole story;
2 clean, 17 to the critic, 4 carrying a decided fail, and two consecutive runs produced
identical verdicts on all 128 answers. What it is worth today is the ORDER of the critic's
attention and the four it names, not a shorter review - the per-judgment numbers and the two
rejected questions are in `references/judgments.d/code.json`.

  judge_code.py --task-root qa-factory/artifacts/<T> [--dispatch D] [--json]
  judge_code.py --cause --finding "<text>" [--test <path>] [--task-root <T>] [--json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assertion_detectors as AD  # noqa: E402
import grammar as G  # noqa: E402
import hooklib  # noqa: E402
import judge  # noqa: E402
import s5_precheck as P  # noqa: E402

try:  # the closed list lives with the role that spends the cap, not in contract.py
    # The REVIEWERS' causes, not the controller's whole list: `ticket_changed` is the driver's word (B-364), and a
    # judge that wrote it for a test's defect would spend no cap - so it reads as `test_defect`, the safe side.
    from controller import REVIEWER_CAUSES
except Exception:  # pragma: no cover - a controller that cannot be imported is not a halt
    REVIEWER_CAUSES = ("test_defect", "mechanical", "environment", "tooling", "reviewer_error")

# name -> (judgment id, the value that means "this dimension passed", rubric dimension)
DIMENSIONS = {
    "assert_matches_then": ("code_assert_matches_then", True, 1),
    "sleep_justified": ("code_sleep_justified", True, 3),
    "locator_fragile": ("code_locator_fragile", False, 5),
    "fixture_unneeded": ("code_fixture_unneeded", False, 5),
    "owns_its_data": ("code_owns_its_data", True, 4),
    "dead_code": ("code_dead_code", False, 6),
    "narrow_negative": ("code_narrow_negative", True, 2),
    "hardcoded_credential": ("code_hardcoded_credential", False, 6),
    "asserts_trigger_return": ("code_asserts_trigger_return", False, 2),
}
# Questions that are only worth asking when the shape they are about is in the code. A judge
# asked "is this sleep justified" about a test with no sleep answers about the surroundings.
# The shapes are data (FR-13, B-407 C): `references/detectors.json` keys `sleep`, `locator` + `locator_words`
# (a locator CALL and the wider words around one) and `negative_code`, read through
# `assertion_detectors.shape_patterns`. The negative shape IN THE CODE is `pytest.raises`, a 4xx/5xx asserted,
# an error payload read. Code is not prose - this is the shape the question is about. Whether the CASE is
# negative is a field, and `grammar.negative_case` answers it: until 0.7.19 this same list ran over the case's
# Then as well, so a negative case worded otherwise lost the dimension that exists for it, and nothing said so
# (FR-12).
SLEEP_KEYS = ("sleep",)
LOCATOR_KEYS = ("locator", "locator_words")
NEGATIVE_KEYS = ("negative_code",)
# One function is one state. 7000 characters is about four screens of test code - longer than
# any test of the sample story, and far inside the model's 32k tokens for the whole request.
CODE_CHARS = 7000
THEN_CHARS = 2400


def _trim(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "\n# ... trimmed"


def shape_in(code: str, keys: tuple) -> bool:
    """Is the shape of these `detectors.json` keys in the code - or is that unknown?

    More questions mean fewer `clean` results, so this may only err toward asking (E-C5): a key that is absent,
    unreadable, malformed or holds a pattern that does not compile means the question is asked of EVERY test.
    Nothing becomes `clean` because a table was missing."""
    for key in keys:
        try:
            patterns = AD.shape_patterns(key)
            if any(re.search(pattern, code) for pattern in patterns):
                return True
        except Exception:
            return True
    return False


def fixture_args(node) -> list:
    """The setup one test asks for: its parameters, minus pytest's own and `self`."""
    names = [a.arg for a in getattr(node.args, "args", [])]
    return [n for n in names if n not in ("self", "cls", "request")]


def bound_clauses(manifest: dict, case: str, function: str) -> set:
    """The Then numbers `then_bindings` gives THIS function, empty when it names none.

    Calibration, 2026-09-23: without this the state was one function and the question was
    about every clause of its case, so every case split over several functions answered
    `fail` — TC-014's four clauses live in three tests, and all three read as contradicting
    the case. A function is judged against the clauses the manifest says it proves."""
    numbers = set()
    for row in P.bindings_of_case(manifest, case):
        if P.C.function_name(row.get("instance_id")) != function:
            continue
        numbers.add(P.C.then_number(row.get("then")))
    return {n for n in numbers if n}


def case_text(task_root: Path, case: str, texts: dict) -> str:
    text = texts.get(case)
    if text is None:
        path = P.find_case_file(task_root, case)
        text = path.read_text(encoding="utf-8", errors="replace") if path else ""
        texts[case] = text
    return text


def case_is_negative(task_root: Path, case: str, texts: dict) -> bool:
    """Does this case assert a refusal, by the fields it carries — its `defect_class` and the
    status its Then fixes? `narrow_negative` is asked of the test when the code has the shape OR
    the case says so; what it may not do is read the case's wording for a synonym (FR-12)."""
    text = case_text(task_root, case, texts)
    front = hooklib.parse_frontmatter(text) or {}
    then = "\n".join(clause for _number, clause in P.then_clauses(text))
    return bool(G.negative_case(front.get("defect_class"), then))


def then_lines(task_root: Path, case: str, numbers: set, texts: dict) -> list:
    """`numbers` empty means the manifest bound nothing to this function: the whole Then is
    the only honest state, and the answer then says the function does not prove the case."""
    out = []
    for number, clause in P.then_clauses(case_text(task_root, case, texts)):
        if not numbers or number in numbers:
            out.append(f"{case} Then {number}: {clause}")
    return out


def targets(task_root: Path, dispatch_id: str | None) -> tuple:
    """Every test function of the dispatch's cases, keyed `<file>::<function>`.

    A consolidated test proves several cases (0.7.7), so the same function is reached from
    each of them; its state then carries the Then clauses of all of them, which is what the
    critic would read too."""
    manifest = P._load(P.C.artifact(task_root, "automation-manifest.json"))
    cases = P.scope_cases(task_root, manifest, dispatch_id)
    found: dict = {}
    notes: list = []
    skipped: list = []   # non-Python test files, once each: nothing here reads them, the critic does
    texts: dict = {}
    for case in cases:
        entries = P.instances_of_case(manifest, case)
        files, seen = [], set()
        for entry in entries:
            resolved = P.resolve_test_file(task_root, str(entry.get("file") or ""))
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            if resolved.suffix != ".py":
                notes.append(f"{case}: {resolved.name} is not a Python test file; it was not judged")
                if resolved.name not in skipped:
                    skipped.append(resolved.name)
                continue
            parsed, problem = P.read_python(resolved)
            if problem:
                notes.append(f"{case}: {problem}")
            if parsed:
                files.append(parsed)
        for pyfile, name, node in P.functions_of_case(files, P.case_aliases(case, entries),
                                                      P.case_functions(entries)):
            key = f"{pyfile.path.name}::{name}"
            row = found.setdefault(key, {"file": pyfile.path.name, "function": name,
                                         "cases": [], "then": [], "bound": True,
                                         "pyfile": pyfile, "node": node})
            if case in row["cases"]:
                continue
            row["cases"].append(case)
            numbers = bound_clauses(manifest, case, name)
            row["bound"] = row["bound"] and bool(numbers)
            row["then"] += then_lines(task_root, case, numbers, texts)
            row["negative"] = bool(row.get("negative")) or case_is_negative(task_root, case, texts)
    return found, cases, notes, skipped


JUDGE_TEST_DATA_KEYS = ("accounts_by_role", "seeds", "generators", "shared_records")   # where the data comes FROM; not masking or cleanup
JUDGE_TEST_DATA_CHARS = 300
NOT_RECORDED = "not recorded"


def test_data_for_judge(task_root):
    """The project's recorded approach to test data as the judge reads it: the `recorded` ones of JUDGE_TEST_DATA_KEYS as
    `key: value` lines (a list joined by ", "), each value cut to JUDGE_TEST_DATA_CHARS. The reader is
    `config_contract.test_data_states` (AR-13). Error direction (AR-28): no key, no block, a config that cannot be read, any
    exception - the word "not recorded", which asks the question as it was before; the judge never gets a softer one."""
    try:
        import config_contract
        import runtime_paths
        got = config_contract.test_data_states(
            config_contract.read_config_file(runtime_paths.project_for_task(task_root)))
        lines = []
        for key in JUDGE_TEST_DATA_KEYS:
            if key not in got["values"]:
                continue
            value = got["values"][key]
            text = ", ".join(str(v) for v in value) if isinstance(value, list) else json.dumps(value) if isinstance(value, dict) else str(value)
            lines.append(f"{key}: {_trim(text, JUDGE_TEST_DATA_CHARS)}")
        return "\n".join(lines) or NOT_RECORDED
    except Exception:
        return NOT_RECORDED


def state_of(row: dict, approach: str | None = None) -> dict:
    code = row["pyfile"].source(row["node"])
    return {"test": {"file": row["file"], "function": row["function"],
                     "fixtures": fixture_args(row["node"]),
                     "code": _trim(code, CODE_CHARS)},
            "case": {"ids": row["cases"], "then": _trim("\n".join(row["then"]), THEN_CHARS),
                     "negative": bool(row.get("negative"))},
            "project": {"test_data": approach if approach is not None else NOT_RECORDED}}


def _tests_row(key: str, row: dict, scores: dict, asked) -> dict:
    return {"file": row["file"], "function": row["function"], "cases": row["cases"],
            "then_scope": "bindings" if row.get("bound") else "whole case",
            "asked": list(asked), "scores": scores,
            # `fails` is what the judge is sure about and `flagged` is where it is not: the
            # critic starts with the first list and still reads the second.
            "fails": [n for n, s in scores.items() if s["verdict"] == "fail"],
            "flagged": [n for n, s in scores.items() if s["verdict"] != "pass"]}


def questions_for(state: dict, cfg: dict | None = None) -> dict:
    """The dimensions worth asking of THIS function. A question whose shape is not in the
    code is not asked at all: a judge asked "is this sleep justified" about a test with no
    sleep answers from the surroundings. A dimension a calibration rejected, or the project
    disabled, is dropped here too — otherwise it comes back unanswered and every test is
    flagged for a question nobody meant to ask."""
    code = state["test"]["code"]
    asked = ["assert_matches_then", "owns_its_data", "dead_code", "hardcoded_credential",
             "asserts_trigger_return"]
    if shape_in(code, SLEEP_KEYS):
        asked.append("sleep_justified")
    if shape_in(code, LOCATOR_KEYS):
        asked.append("locator_fragile")
    if state["test"]["fixtures"]:
        asked.append("fixture_unneeded")
    if state["case"].get("negative") or shape_in(code, NEGATIVE_KEYS):
        asked.append("narrow_negative")
    return {name: {"judgment": DIMENSIONS[name][0]} for name in asked
            if judge.active(cfg, DIMENSIONS[name][0])}


def report_rel(dispatch_id=None) -> str:
    """The task-relative file the judge of the critic `dispatch_id` writes and that critic reads (TR3-15, the ONE spelling: one file per
    critic dispatch, so a window's critic never reads another window's screening). No dispatch (a manual run): `work/judge-code.json`."""
    ident = str(dispatch_id or "").strip()
    return f"work/judge-code-{ident}.json" if ident else "work/judge-code.json"


def run(task_root, dispatch_id: str | None = None) -> dict:
    task_root = Path(task_root)
    cfg = judge.settings(task_root)
    report = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok",
              "dispatch": dispatch_id}
    if not judge.active(cfg):
        return dict(report, status="off")
    found, cases, notes, skipped = targets(task_root, dispatch_id)
    report["cases"] = cases
    report["notes"] = notes
    report["skipped_files"] = skipped
    if not found:
        return dict(report, status="not_ready",
                    reason="no Python test function of this scope could be read")
    keys = list(found)
    requests = []
    approach = test_data_for_judge(task_root)
    for key in keys:
        state = state_of(found[key], approach)
        requests.append((state, questions_for(state, cfg)))
    replies = judge.ask_many(requests, workers=8, ticket=task_root.name, stage="S5",
                             project_root=task_root, cfg=cfg)
    failed = next((r for r in replies if r["status"] != "ok"), None)
    if failed:
        return dict(report, status=failed["status"], reason=failed.get("reason"))
    tests, needs, clean = {}, [], []
    for key, (_state, asked), reply in zip(keys, requests, replies):
        row = found[key]
        scores = {}
        for name in asked:
            answer = reply["answers"].get(name) or {}
            _jid, passing, dimension = DIMENSIONS[name]
            value = answer.get("value")
            verdict = "undecided" if value is None else "pass" if value is passing else "fail"
            scores[name] = {"dimension": dimension, "verdict": verdict,
                            "probability": answer.get("probability")}
        tests[key] = _tests_row(key, row, scores, asked)
        (needs if tests[key]["flagged"] else clean).append(key)
    report.update(tests=tests, needs_critic=needs, clean=clean,
                  decided_fails=[k for k in keys if tests[k]["fails"]],
                  judged_dimensions=sorted({d for _j, _p, d in DIMENSIONS.values()}),
                  critic_only=["roll-call (7)", "red probe", "masking (8)", "self_fixes (9)",
                               "over-mocking", "shared state", "ungrounded expected value"],
                  advisory=replies[0]["advisory"] if replies else True,
                  input_tokens=sum(r.get("input_tokens") or 0 for r in replies))
    path = task_root / report_rel(dispatch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def cause(finding: str, test_path: str | None = None, project_root=None) -> dict:
    """Which `repair_cause` a rework round opened from this finding carries."""
    cfg = judge.settings(project_root)
    out = {"provider": cfg["provider"], "mode": cfg["mode"], "status": "ok",
           "repair_cause": "test_defect", "confidence": None, "decided": False}
    if not judge.active(cfg, "code_repair_cause"):
        return dict(out, status="off")
    code = ""
    if test_path:
        try:
            code = _trim(Path(test_path).read_text(encoding="utf-8", errors="replace"), CODE_CHARS)
        except OSError:
            code = ""
    state = {"finding": _trim(finding, 4000), "test": {"path": str(test_path or ""), "code": code}}
    decision = judge.ask_one(state, "code_repair_cause", stage="S5", project_root=project_root,
                             cfg=cfg)
    if decision is None:
        return dict(out, status="unavailable", reason="the judge could not answer")
    value = decision.get("value")
    return dict(out, repair_cause=value if value in REVIEWER_CAUSES else "test_defect",
                leaning=decision.get("leaning"), confidence=decision.get("confidence"),
                decided=bool(decision.get("decided")), advisory=decision.get("advisory", True))


def render(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_code: {report['status']} - {report.get('reason') or 'judge.provider is none'}; "
                "review every test as usual")
    skipped = len(report.get("skipped_files") or [])
    left = (f"{skipped} non-Python file(s) skipped (the critic reviews them in full)" if skipped
            else "none skipped")
    lines = [f"judge_code: mode={report['mode']} {len(report['tests'])} test function(s) judged, "
             f"{left} - {len(report['clean'])} clean, {len(report['needs_critic'])} need the "
             f"critic ({len(report['decided_fails'])} with a decided fail) -> {report_rel(report.get('dispatch'))}"]
    for key in report["needs_critic"]:
        item = report["tests"][key]
        detail = ", ".join(f"{n}={item['scores'][n]['verdict']}({item['scores'][n]['probability']})"
                           for n in item["flagged"])
        lines.append(f"  {key} [{', '.join(item['cases'])}]: {detail}")
    return "\n".join(lines)


def render_cause(report: dict) -> str:
    if report["status"] != "ok":
        return (f"judge_code --cause: {report['status']} - "
                f"{report.get('reason') or 'judge.provider is none'}; "
                "the round carries `test_defect` unless the role says otherwise")
    word = "decided" if report["decided"] else "leaning (undecided, `test_defect` stands)"
    return (f"judge_code --cause: repair_cause={report['repair_cause']} {word} "
            f"confidence={report['confidence']} leaning={report.get('leaning')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--task-root", help="qa-factory/artifacts/<TICKET>")
    parser.add_argument("--dispatch", help="limit the scope to this dispatch's cases")
    parser.add_argument("--cause", action="store_true", help="classify one review finding")
    parser.add_argument("--finding", help="the critic finding's text (with --cause)")
    parser.add_argument("--test", help="the test file the finding is about (with --cause)")
    parser.add_argument("--json", action="store_true")
    args = hooklib.exact_options(parser).parse_args()
    if args.task_root is not None:      # a GIVEN root names an existing story, even when the judge is off (E-4)
        hooklib.story_cli("judge_code.py", root=args.task_root, key_flag=None)
    if args.cause:
        if not args.finding:
            parser.error("--cause needs --finding")
        report = cause(args.finding, args.test, args.task_root)
        print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render_cause(report))
        return 0 if report["status"] in ("ok", "off") else 3
    if not args.task_root:
        parser.error("--task-root is required (or use --cause --finding)")
    report = run(Path(args.task_root).resolve(), args.dispatch)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 0 if report["status"] in ("ok", "off") else 3


if __name__ == "__main__":
    sys.exit(main())
