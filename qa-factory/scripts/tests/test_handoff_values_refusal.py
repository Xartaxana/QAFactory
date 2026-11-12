#!/usr/bin/env python3
"""refusal: a part of test_handoff_values.py, split by tools/test_split.py (TD-11c). The shared helpers are in handoff_values_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as H  # noqa: E402
from handoff_values_common import (  # noqa: E402
    CONTRACT, _doc, _green_copy, _hc, _hc_stdin, _paths, _sha, _story,
)


# ------------------------------------------------------------------------------------- part A2: one refusal
S4 = "s4-case-critic-to-designer"


def _form4(art: Path, dispatch: str = "S4-qa-case-critic-1") -> Path:
    """A fresh S4 case-critic form - the role has NO Bash."""
    run_script("handoff_init.py", "--task", "QA-9", "--stage", "S4", "--role", "qa-case-critic",
               "--to", "qa-case-designer", "--dispatch", dispatch, "--task-root", str(art))
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


def _skeleton_of(report) -> list:
    return report["values_skeleton"].splitlines()


def one_refusal_block_one_command() -> None:
    """K-A12: three problems are ONE block with ONE command: all three paths in the skeleton, the allowed words of
    `header.verdict` inline, and not one `fix: --set` line (the 89-process failure was a command per field)."""
    root = temp_project("qa-values-a12-")
    try:
        art = _story(root)
        form = _green_copy(art, {"header.verdict": "<one of the above>", "scope[0].reason": "x" * 81,
                                 "scope[1].state": "contradiction"})
        code, report = _hc(art, form, "--json")
        paths = _paths(report["problems"])
        check_eq("K-A12: the three problems are the only ones", sorted(paths),
                 ["header.verdict", "scope[0].reason", "scope[1].state"])
        skeleton = _skeleton_of(report)
        names = [line.partition(":")[0].strip('"') for line in skeleton]
        check_eq("K-A12: the skeleton has a line for each of the three, in the order of the problems", sorted(names), sorted(paths))
        verdict = next(line for line in skeleton if line.startswith("header.verdict:"))
        check_eq("K-A12: the allowed words of header.verdict are inline",
                 [w for w in handoff.allowed("header_verdicts") if w in verdict], handoff.allowed("header_verdicts"))
        code, text = _hc(art, form)
        check_eq("K-A12: the text refusal exits 1", code, 1)
        check_eq("K-A12: ONE command in the block", text.count("--values -"), 1)
        check_eq("K-A12: and ONE heredoc", text.count("<<'EOF'"), 1)
        check_not_in("K-A12: no per-field `fix:` line", "\n      fix: ", text)
        check_not_in("K-A12: no per-field `--set` command", "--set", text)
        check_not_in("K-A12: no 'each fix below' preamble", "each fix below", text)
        check_in("K-A12: the skeleton is in the text verbatim", report["values_skeleton"], text)
        check_eq("K-A12: --json says nothing of the skeleton when the form is green",
                 _hc(art, _green_copy(art, None, "S2-green"), "--json")[1]["values_skeleton"], "")
        # nothing is cut: a long list of paths is printed whole, AT and BEYOND any count a person would pick
        for count in (1, 100, 101, 250):
            problems = [H.Problem(f"scope[{i}].id", "x") for i in range(count)]
            lines = H.values_skeleton(problems, CONTRACT, "qa-requirements-tester").splitlines()
            check_eq(f"K-A12: {count} paths give {count} lines, the last one whole", (len(lines), lines[-1].partition(":")[0]),
                     (count, f'"scope[{count - 1}].id"'))
    finally:
        cleanup(root)


def a_role_with_bash_is_shown_the_heredoc_and_the_file_door() -> None:
    """K-A12b: a heredoc is bash only, so the file door is ALWAYS beside it (any shell, or none)."""
    root = temp_project("qa-values-a12b-")
    try:
        art = _story(root)
        form = _green_copy(art, {"header.verdict": "<one of the above>"})
        code, text = _hc(art, form)
        sibling = H.sibling_values(form).as_posix()
        check_in("K-A12b: the heredoc command", "handoff_check.py\" --file", text)
        check_in("K-A12b: --fix --values - <<'EOF'", "--fix --values - <<'EOF'", text)
        check_in("K-A12b: the file door follows, in any shell or none",
                 f"or, in any shell or none: Write the same lines to {sibling} in one Write", text)
        check_in("K-A12b: the way out for what cannot be filled is the conductor's door", "handoff_help.py --file", text)
        check_not_in("K-A12b: and it is not the no-Bash role's sentence", "story_step finish applies them", text)
        check_not_in("K-A12b: no 'Rewrite' door while nothing was kept", "Rewrite", text)
    finally:
        cleanup(root)


def a_role_without_bash_is_shown_the_file_door_only() -> None:
    """K-A13: no command a role without Bash cannot run (FR-2): the file door, the skeleton, and `blocked` in the same file."""
    root = temp_project("qa-values-a13-")
    try:
        art = _story(root)
        form = _form4(art)
        code, text = _hc(art, form)
        check_eq("K-A13: a fresh S4 form is refused", code, 1)
        check_in("K-A13: the file door names the file", f"Write these lines to {H.sibling_values(form).as_posix()} in one Write; "
                 "story_step finish applies them", text)
        for banned in ("<<'EOF'", "--values -", "python \"", "handoff_help.py", "--set", "\n      fix: "):
            check_not_in(f"K-A13: no {banned!r} for a role without Bash", banned, text)
        check_in("K-A13: blocked is filled in the same values file", "fill blocked.field and blocked.problem in the same values file", text)
        report = _hc(art, form, "--json")[1]
        check_in("K-A13: the skeleton lines are in the text", report["values_skeleton"], text)
        # a role not named, or with no readable file, is shown both doors
        problems = [H.Problem("header.verdict", "x")]
        for role in ("", "qa-no-such-role"):
            both = H.refusal_text(form, S4, problems, role)
            check_in(f"K-A13: role {role!r} gets the command", "<<'EOF'", both)
            check_in(f"K-A13: role {role!r} gets the no-Bash sentence", "fill blocked.field and blocked.problem", both)
            check_in(f"K-A13: role {role!r} gets the conductor's door", "handoff_help.py", both)
    finally:
        cleanup(root)


class _NoJudge:
    asked = 0

    @staticmethod
    def active():
        return True

    @staticmethod
    def ask(*_a, **_k):
        _NoJudge.asked += 1
        raise AssertionError("the judge must never be asked by values_report")


def _tree_hashes(root: Path) -> dict:
    return {str(p.relative_to(root)): _sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def values_report_writes_nothing_and_never_asks_the_judge() -> None:
    """K-A17: the guard's question is PURE (FR-45) and costs no judge call: a word the judge would map is a problem."""
    root = temp_project("qa-values-a17-")
    try:
        art = _story(root)
        form = _green_copy(art)
        before = _tree_hashes(root)
        saved = H.judge
        H.judge = _NoJudge
        try:
            problems, role, kept = H.values_report(form, "header.verdict: contradiction\nscope[0].reason: fine\n")[:3]
        finally:
            H.judge = saved
        check_eq("K-A17: the judge was not asked", _NoJudge.asked, 0)
        check_eq("K-A17: the word outside the list is a problem, the good line is kept",
                 (_paths(problems), kept, role), (["header.verdict"], ["scope[0].reason: fine"], "qa-requirements-tester"))
        check_eq("K-A17: no file of the story changed, none was added", _tree_hashes(root), before)
        green = H.values_report(form, "scope[0].reason: fine\nheader.verdict: concerns\n")
        check_eq("K-A17: a green text has no problems, and all its lines are kept in the order they were applied (path order)",
                 (green[0], green[2]), ([], ["header.verdict: concerns", "scope[0].reason: fine"]))
    finally:
        cleanup(root)


def a_refused_values_text_keeps_its_good_lines_in_the_skeleton() -> None:
    """K-A19: M-4 - the guard refuses a text and the role REWRITES the file whole: its good lines must come back."""
    root = temp_project("qa-values-a19-")
    try:
        art = _story(root)
        form = _green_copy(art)
        good = ["scope[0].reason: first reason", "scope[1].reason: second reason", "scope[2].reason: third reason",
                "header.window: TP1-13877"]
        text = "\n".join(good[:2] + ["header.verdict: contradiction"] + good[2:]) + "\n"
        problems, role, kept = H.values_report(form, text)[:3]
        check_eq("K-A19: exactly the four good lines are kept, verbatim; the fifth is not", sorted(kept), sorted(good))
        refused = H.refusal_text(form, CONTRACT, problems, role, kept=kept)
        for line in good:
            check_in(f"K-A19: the good line `{line}` is in the refusal", "\n" + line + "\n", refused)
        verdict = handoff.allowed("header_verdicts")
        check_in("K-A19: and the fifth is a placeholder line with the allowed words", "header.verdict: <" + "|".join(verdict) + ">", refused)
        check_not_in("K-A19: the wrong word is not echoed back as a value", "header.verdict: contradiction", refused)
        check_in("K-A19: the door says to rewrite the file whole", "Rewrite", refused)
        check_in("K-A19: yours first, then the ones to fix", "yours that passed first, then the ones to fix", refused)
        skeleton = H.values_skeleton(problems, CONTRACT, role, kept=kept).splitlines()
        check_eq("K-A19: kept lines come before the lines to fix", skeleton[-1].startswith("header.verdict:"), True)
        # a text that does not PARSE: nothing is applied, every line that did parse is kept
        broken = "scope[0].reason: first\nthis line has no colon\nscope[1].reason: second\n"
        problems, role, kept = H.values_report(form, broken)[:3]
        check_eq("K-A19: a parse problem keeps the parsed lines", (kept, len(problems)),
                 (["scope[0].reason: first", "scope[1].reason: second"], 1))
        refused = H.refusal_text(form, CONTRACT, problems, role, kept=kept)
        check_in("K-A19: and gives them back", "\nscope[1].reason: second\n", refused)
        # no Bash: the file door says the lines are BELOW
        crit = H.refusal_text(art / "work" / "handoffs" / "x.yaml", S4, [H.Problem("header.verdict", "bad")],
                              "qa-case-critic", kept=["header.window: A, B"])
        check_in("K-A19: a role without Bash is told to rewrite the file whole with the lines below",
                 "Rewrite " + (art / "work" / "handoffs" / "x.values.yaml").as_posix() + " WHOLE with the lines below: "
                 "yours that passed first, then the ones to fix", crit)
        check("K-A19: its kept line stands before the line to fix",
              crit.index("header.window: A, B") < crit.index("header.verdict: <"))
        # the CLI: a values FILE with a bad line is refused with the good lines given back
        values = art / "work" / "v.txt"
        values.write_text(broken, encoding="utf-8")
        code, out = _hc(art, form, "--values", str(values))
        check_eq("K-A19: the CLI refuses it", code, 1)
        check_in("K-A19: and gives the good lines back", "\nscope[0].reason: first\nscope[1].reason: second\n", out)
        code, out = _hc_stdin(art, form, broken, "--values", "-")
        check_in("K-A19: the same through stdin", "\nscope[1].reason: second\n", out)
    finally:
        cleanup(root)


def a_blank_field_code_fills_is_not_refused_by_values_report() -> None:
    """K-A20: M-9 - the guard must not demand what only `--fix` can produce (FR-11): `review.findings_file` is derived
    from the findings file on disk, which a role without Bash cannot make a deriver find; `finish` checks it."""
    root = temp_project("qa-values-a20-")
    try:
        art = _story(root)
        form = _form4(art)
        doc = _doc(form)
        handoff.set_value(doc, "review.findings_file", "<fill>")
        form.write_text(doc.text(), encoding="utf-8")
        control = H.check(_doc(form), S4, H.Artifacts(art, dispatch=form.stem), fix=True, use_judge=False)[2]
        check_in("K-A20: the control - the same form IS refused for it by check(fix=True)",
                 "review.findings_file", _paths([p for p in control if p.kind == "blank"]))
        problems, role, kept = H.values_report(form, "header.verdict: ok\n")[:3]
        check_not_in("K-A20: values_report does not name it", "review.findings_file", _paths(problems))
        check_in("K-A20: but a blank field code does NOT fill still is a problem", "review.outcome", _paths(problems))
        check_eq("K-A20: and the good line is kept", kept, ["header.verdict: ok"])
        # the one answer
        yes = ["review.findings_file", "scope[3].case_version", "artifacts.tests[0]", "artifacts.tests[2]", "size.computed",
               "rounds[1].verify.witness", "claims." + next(iter(H.CLAIMS))]
        no = ["header.verdict", "scope[0].reason", "claims.never_heard_of_it", "artifacts.tests_other", "scope[0].id"]
        check_eq("K-A20: _code_fills says yes for what a deriver, a list deriver, a leaf or a verifier fills",
                 [H._code_fills(p) for p in yes], [True] * len(yes))
        check_eq("K-A20: and no for what only the role knows", [H._code_fills(p) for p in no], [False] * len(no))
        check("K-A20: a Problem says its kind structurally: 'not filled' is blank, a wrong word is not",
              {p.path: p.kind for p in control if p.path in ("review.findings_file", "review.outcome")}
              == {"review.findings_file": "blank", "review.outcome": "blank"}
              and H.Problem("a", "b").kind == "" and H.Problem("a", "b").also == ())
    finally:
        cleanup(root)


def a_blocked_row_puts_blocked_problem_into_the_skeleton() -> None:
    """K-A21: m-1 - the problem is on `scope[0].state`, its door is `blocked.problem`: the skeleton shows both paths."""
    root = temp_project("qa-values-a21-")
    try:
        art = _story(root)
        form = _green_copy(art, {"scope[0].state": "blocked"})
        code, report = _hc(art, form, "--json")
        row = [p for p in report["problems"] if p["path"] == "scope[0].state"]
        check_eq("K-A21: the blocked row is refused, and names its other door as data", [p["also"] for p in row], [["blocked.problem"]])
        names = [line.partition(":")[0] for line in _skeleton_of(report)]
        check_eq("K-A21: the skeleton has a line for the row AND for blocked.problem", (names.count("scope[0].state") + names.count('"scope[0].state"'),
                                                                                           names.count("blocked.problem")), (1, 1))
        problems, role, kept = H.values_report(form, "header.verdict: ok\n")[:3]
        check("K-A21: values_report keeps the same door (the guard shows it)", ("blocked.problem",) in [p.also for p in problems])
        check_in("K-A21: blocked.problem: in the refusal text", "\nblocked.problem: <", _hc(art, form)[1])
    finally:
        cleanup(root)


def a_skeleton_is_blank_for_every_field_of_every_contract() -> None:
    """A skeleton left unfilled must write NOTHING (FR-59: the line names what the role must supply, it does not
    invent a value): for every field of every contract, the placeholder line reads back as blank through the values
    parser, a list of values is one line `path: [<...>]`, and a list section expands to its first row."""
    contracts = [str(row.get("contract")) for row in handoff.index().get("handoffs", []) if row.get("contract")]
    bad, total = [], 0
    # `values_skeleton` reads the contract file again on every call; with one call per field that was ~57 s of file reads
    # (FR-31, t-1783). The schema is read-only here, so it is read once per contract for the whole loop.
    real_spec, memo = handoff.spec, {}
    handoff.spec = lambda cid: memo[cid] if cid in memo else memo.setdefault(cid, real_spec(cid))
    try:
        for contract in sorted(set(contracts)):
            spec = handoff.spec(contract)
            for generic in spec:
                if handoff.owned_by_contract(generic):
                    continue
                path = generic.replace("[]", "[0]")
                text = H.values_skeleton([H.Problem(path, "x")], contract, "")
                pairs, problems = H.parse_values(text)
                total += 1
                if problems or len(pairs) != 1 or not H._blank_value(pairs[0][1]):
                    bad.append((contract, path, text[:80]))
    finally:
        handoff.spec = real_spec
    check_eq(f"skeleton: all {total} fields of {len(set(contracts))} contracts read back blank", bad, [])
    lines = H.values_skeleton([H.Problem("blocked.tried[0]", "x")], CONTRACT, "qa-requirements-tester")
    check_eq("skeleton: a list of values is written whole on one line", lines.startswith("blocked.tried: [<"), True)
    rows = H.values_skeleton([H.Problem("scope", "no rows")], CONTRACT, "qa-requirements-tester").splitlines()
    check_eq("skeleton: a list section with no rows gets every field of its first row",
             [line.partition(":")[0].strip('"') for line in rows],
             [path.replace("[]", "[0]") for path in handoff.spec(CONTRACT) if path.startswith("scope[].")])
    notes = H.values_skeleton([H.Problem("claims.nothing_of_the_kind", "false", "repair the work")], CONTRACT, "")
    check_eq("skeleton: a problem on no field of the contract is a comment with its fix", notes,
             "# claims.nothing_of_the_kind: repair the work")
    again = H.values_skeleton([H.Problem("header.verdict", "x"), H.Problem("header.verdict", "y")], CONTRACT, "",
                              kept=["header.verdict: ok"])
    check_eq("skeleton: a path of kept is not repeated, nor a path of two problems", again, "header.verdict: ok")


def the_skeleton_cuts_nothing() -> None:
    """L2/L4: no limit is introduced - a closed list of 2000 words and a hint of 5000 characters are printed whole,
    and still read back blank."""
    words = [f"w{i:04d}" for i in range(2000)]
    spec = {"scope[].state": handoff.FieldSpec("scope[].state", [], False, 0, "text", "h" * 5000),
            "header.verdict": handoff.FieldSpec("header.verdict", [], False, 0, "text", "h" * 5000)}
    real_spec, real_options = handoff.spec, handoff.options_for_role
    handoff.spec = lambda _contract: spec
    handoff.options_for_role = lambda field, role, vocab=None: words if field.path.endswith(".state") else field.options
    try:
        text = H.values_skeleton([H.Problem("scope[0].state", "x"), H.Problem("header.verdict", "y")], CONTRACT, "r")
    finally:
        handoff.spec, handoff.options_for_role = real_spec, real_options
    state, verdict = text.splitlines()
    check_eq("cuts nothing: 2000 words in one line, all of them", all(w in state for w in words), True)
    check_eq("cuts nothing: a 5000-character hint is whole", verdict, "header.verdict: <" + "h" * 5000 + ">")
    check_eq("cuts nothing: both lines read back blank", [H._blank_value(v) for _p, v, _n, _r in H.parse_values(text)[0]], [True, True])


def a_skeleton_left_as_is_writes_nothing() -> None:
    """The refusal's own command, run as printed with no value filled, changes nothing and refuses again with the
    same problems - the placeholder never becomes a value."""
    root = temp_project("qa-values-a2-asis-")
    try:
        art = _story(root)
        form = _form4(art)
        report = _hc(art, form, "--json")[1]
        before = form.read_text(encoding="utf-8")
        code, out = _hc_stdin(art, form, report["values_skeleton"] + "\n", "--values", "-", "--json")
        again = json.loads(out)
        check_eq("as is: nothing applied", again["values_applied"], 0)
        check_eq("as is: the same problems", _paths(again["problems"]), _paths(report["problems"]))
        check_eq("as is: the form is what it was", form.read_text(encoding="utf-8"), before)
    finally:
        cleanup(root)


# ----------------------------------------------------------------------- HF8-7: the refusal names the indexed row form
S4C = "s4-case-critic-to-designer"        # the critic of round 2 of run 12586 met this contract


S4R = "s4-designer-to-runner"


GATE_A = "gate-a-to-automator"


def _problems(text: str, contract: str = S4C) -> list:
    return H.parse_values(text, contract=contract)[1]


def _skeleton(problems, contract: str = S4C, role: str = "qa-case-critic", kept=()) -> str:
    return H.values_skeleton(problems, contract, role, kept=kept)


def a_dotted_index_is_refused_with_the_indexed_row_form() -> None:
    """K1: the line the critic of round 2 wrote, `scope.0.id: TC-1`, is refused as before, and the text now names the form
    the writer takes - `"scope[0].id"` - on the contract's own list; the skeleton has the lines to fill. Protects AR-9, AR-10."""
    problems = _problems("scope.0.id: TC-1\nscope.0.state: approve\n")
    check_eq("K1: two problems, one per line", [p.path for p in problems], ["values line 1", "values line 2"])
    check_in("K1: line 1 names scope[0].id", '"scope[0].id"', problems[0].text)
    check_in("K1: line 2 names scope[0].state", '"scope[0].state"', problems[1].text)
    check_in("K1: the old part of the text stays", "is not a `path: value` line", problems[0].text)
    block = H.refusal_text("work/handoffs/S4-qa-case-critic-1.yaml", S4C, problems, "qa-case-critic")
    check_in("K1: the refusal block carries the indexed form", '"scope[0].id"', block)
    check_in("K1: and the skeleton the line of the finding", '"scope[0].state": <', _skeleton(problems))
    live = H._apply_text(handoff.template(S4C), S4C, "values", lambda: b"scope.0.id: x")[2][0].text   # the live path (M14)
    check_in("K1: the live path (--fix, --values, the waiting file) carries the contract too", '"scope[0].id"', live)


def a_list_of_objects_is_refused_with_the_first_row_lines() -> None:
    """K2: a JSON object with a list of objects, a JSON array, `scope: [{id: TC-1}]` and `findings: {id: F-1}` get the
    lines of the first row of THAT list; the field code fills (`case_version`) is not among them."""
    cases = [('{"scope": [{"id": "TC-1"}]}', "scope[0].id"), ('[{"id": "TC-1"}]', "scope[0].id"),
             ("scope: [{id: TC-1}]", "scope[0].id"), ("findings: {id: F-1}", "findings[0].id")]
    for text, want in cases:
        problems = _problems(text)
        sketch = _skeleton(problems)
        check_in(f"K2: {text!r} names {want}", f'"{want}"', problems[0].text)
        check_in(f"K2: {text!r} has the line to fill", f'"{want}": <', sketch)
        check_not_in(f"K2: {text!r}: no line for the field code fills", "case_version", sketch)
    filled = _problems("scope.0.case_version: x")[0]                # a dotted index on a field code fills (E4, FR-11)
    check_not_in("K2: a dotted code-filled field is not offered", "case_version", "".join(filled.also))
    check_not_in("K2: nor in the text as a form", '"scope[0].case_version"', filled.text)
    check_in("K2: it falls through to the rows of the list", '"scope[0].id"', filled.text)


def a_block_yaml_list_is_refused_with_the_headers_list() -> None:
    """K3: `findings:` then `- id: F-1` names `findings[0].id`; the bare `- id: x` names the first list of the contract."""
    problems = _problems("findings:\n  - id: F-1\n")
    check_eq("K3: one problem, on the item line", [p.path for p in problems], ["values line 2"])
    check_in("K3: the header's list", '"findings[0].id"', problems[0].text)
    pairs = H.parse_values("findings:\n  - id: F-1\n", contract=S4C)[0]
    check_eq("K3: the bare header stays a pair with no value (nothing is written)", [(p[0], p[1]) for p in pairs], [("findings", None)])
    check_in("K3: a bare item names the required list", '"scope[0].id"', _problems("- id: x\n")[0].text)
    two = _problems("findings:\n  - id: F-1\n    state: approve\n  - id: F-2\n    state: reject\n")
    check_eq("K3: both item lines are problems (line 5 is the repeated `state`)", [p.path for p in two][:2],
             ["values line 2", "values line 4"])
    check_in("K3: the second item still names the header's list", '"findings[0].id"', two[1].text)
    check_not_in("K3: and not the first list of the contract", "scope[0]", two[1].text)


def the_hint_never_changes_what_parse_values_decides() -> None:
    """K4: for every input of the battery the pairs and the PATHS of the problems are the same with and without the
    contract; the hint is text and `also` only, and nothing here calls `apply_values` (AR-28)."""
    saved = H.apply_values
    H.apply_values = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a hint applied values"))
    try:
        for text in _battery():
            plain, with_contract = H.parse_values(text), H.parse_values(text, contract=S4C)
            check_eq(f"K4: same pairs {text[:30]!r}", with_contract[0], plain[0])
            check_eq(f"K4: same problem paths {text[:30]!r}", [p.path for p in with_contract[1]], [p.path for p in plain[1]])
    finally:
        H.apply_values = saved


def a_list_that_is_not_a_list_of_rows_gets_no_row_hint() -> None:
    """K5: `blocked.tried` is a list of values and `inputs` has nothing the role writes: no row hint, no `[0].` path."""
    for text in ("blocked.tried: [{a: 1}]", "inputs: [{path: x}]"):
        problem = _problems(text)[0]
        check_not_in(f"K5: {text!r}: the text offers no row", "a row of a list", problem.text)
        check_eq(f"K5: {text!r}: no paths", problem.also, ())
        check_not_in(f"K5: {text!r}: the skeleton offers no row", "[0].",
                     "\n".join(l for l in _skeleton([problem]).splitlines() if not l.startswith("#")))


def an_unreadable_contract_gives_the_general_text() -> None:
    """K6: a contract that does not exist gives the general form `"<list>[0].<field>"`, no exception, the same number of
    problems (E1, E2)."""
    text = "scope.0.id: TC-1\nnot a line\n"
    plain, broken = _problems(text, ""), _problems(text, "no-such-contract")
    check_eq("K6: the same number of problems", (len(plain), len(broken)), (2, 2))
    check_in("K6: the general form", '"<list>[0].<field>"', broken[0].text)
    check_eq("K6: no paths", [p.also for p in broken], [(), ()])
    nested = _problems("blocked.tried: [{a: 1}]", "")[0]                 # no readable contract: the general sentence
    check_in("K6: a nested object without a contract carries the general form", '"<list>[0].<field>"', nested.text)
    check_eq("K6: and no paths", nested.also, ())
    # t-442 (canon part D): a nested value on a path that is ALSO given by an earlier line is ONE problem - its own shape; it is
    # not read as a pair, so it is not "given twice" as well (a line is refused once, for what is wrong with it)
    for contract in ("", S4C):
        once = _problems("blocked.tried: x\nblocked.tried: [{a: 1}]\n", contract)
        check_eq(f"K4 (t-442) [{contract or 'no contract'}] a repeated path with a nested value: exactly one problem",
                 [p.path for p in once], ["values line 2"])
        check_in(f"K4 (t-442) [{contract or 'no contract'}] ... it is the nested shape", "not a nested object", once[0].text)
        check_not_in(f"K4 (t-442) [{contract or 'no contract'}] ... and not 'given twice'", "given twice", once[0].text)
    twice = _problems("blocked.tried: x\nblocked.tried: y\n", "")
    check_eq("K4 (t-442) control: the same path twice with flat values IS 'given twice', once, naming both lines",
             [(p.path, "`blocked.tried` is given twice (lines 1 and 2)" in p.text) for p in twice], [("values line 2", True)])


def the_contract_is_read_once_and_only_when_a_line_is_bad() -> None:
    """K7: a clean text and an empty one never read the contract; a thousand bad lines read it once (AR-12, E5, E6, E8)."""
    real, calls = handoff.spec, []
    handoff.spec = lambda contract: calls.append(contract) or real(contract)
    try:
        H.parse_values("header.window: TC-1\nheader.verdict: ok\n", contract=S4C)
        H.parse_values("", contract=S4C)
        H.parse_values("# only a comment\n\n", contract=S4C)
        check_eq("K7: no bad line, no read", calls, [])
        H.parse_values("scope.0.id: x\n" * 1000, contract=S4C)
        check_eq("K7: a thousand bad lines, one read", len(calls), 1)
    finally:
        handoff.spec = real


def _scalar_paths(contract: str) -> list:
    return [p for p in H.row_form(handoff.spec(contract))[1] if not p.endswith("]")]


def the_row_form_of_every_contract_is_a_path_the_writer_takes() -> None:
    """K8: the door. For every contract of `handoffs/index.yaml` (and the escalation one) that has a list of rows, the
    first path the hint names is written by `apply_values` with a real value - one applied, no problem - and is neither
    the contract's own nor code's. A spec with no list of rows gives nothing (AR-1, AR-2, FR-2)."""
    index = handoff.index()
    contracts = [str(row["contract"]) for row in index.get("handoffs", [])] + [str(index["escalation"]["contract"])]
    seen = 0
    for contract in contracts:
        spec = handoff.spec(contract)
        name, paths = H.row_form(spec)
        if not paths:
            continue
        seen += 1
        first, later = H.row_pair(paths)
        check(f"K8 {contract}: a scalar path to show", bool(first) and bool(later) and first != later, f"{paths}")
        check(f"K8 {contract}: nothing owned by the contract or filled by code",
              not any(handoff.owned_by_contract(p) or H._code_fills(p) for p in paths), f"{paths}")
        doc, applied, problems, _notes = H.apply_values(handoff.template(contract), contract, [(first, "word", 1, "")])
        check_eq(f"K8 {contract}: `{first}` is written", (applied, [p.path for p in problems]), (1, []))
    check("K8: the contracts with a list of rows were really walked", seen >= 5, f"{seen}")
    check_eq("K8: a spec with no list of rows shows nothing", H.row_form({"header.verdict": None}), ("", []))
    check_eq("K8: and the sentence is the general one", H._row_sentence([]).count('"<list>[0].<field>"'), 1)
    check_eq("K8: gate A names its own list, not `scope`", H.row_form(handoff.spec(GATE_A))[0],
             "environment.preconditions_accepted_as_blocked")


def a_section_skeleton_writes_a_list_of_values_whole() -> None:
    """K9: a problem on the section `execution` of the runner contract gets `execution[0].preconditions: [<...>]` - the
    line the writer takes - and never `execution[0].preconditions[0]`, which `_apply_one` refuses; the filled lines
    apply without a problem. A field code fills is left out (M-9)."""
    sketch = _skeleton([H.Problem("execution", "no rows", "fix")], S4R, "qa-case-designer")
    check_in("K9: the list of values is one line", '"execution[0].preconditions": [<', sketch)
    check_not_in("K9: no index on the list of values", "preconditions[0]", sketch)
    filled = "\n".join(line.split(": ", 1)[0] + ": word" for line in sketch.splitlines() if not line.startswith("#"))
    filled = filled.replace('preconditions": word', 'preconditions": [word]').replace('data_and_accounts": word',
                                                                                    'data_and_accounts": [word]')
    pairs, bad = H.parse_values(filled)
    check_eq("K9: the filled skeleton parses", bad, [])
    _doc2, applied, problems, _n = H.apply_values(handoff.template(S4R), S4R, pairs)
    check_eq("K9: and applies with no problem", [p.path for p in problems], [])
    sections = _skeleton([H.Problem("scope", "no rows", "fix")], S4R, "qa-case-designer")
    check_not_in("K9: a field code fills is not in the section skeleton", "case_version", sections)
    _d3, got, bad, _n3 = H.apply_values(handoff.template(S4R), S4R, [("execution[0].precondition", "w", 1, "")])
    check_eq("K9: a near miss on a list of values is refused", (got, len(bad)), (0, 1))
    check_not_in("K9: `_near` does not teach the indexed leaf the writer refuses", "preconditions[0]", bad[0].text + bad[0].fix)
    check_in("K9: it names the whole list", "execution[0].preconditions", bad[0].fix)


def the_guard_block_carries_the_row_form_and_the_role_line_once() -> None:
    """K10: the text the pre-tool guard prints is `refusal_text` over `values_report`: with the contract passed in, a
    file with `scope[0].state: approve` and `scope.1.id: TC-2` is refused with `"scope[1].id"`, and the role's own line
    comes first and once."""
    root = temp_project("qa-values-hf87-")
    try:
        art = _story(root)
        form = _form4(art)
        problems, role, kept = H.values_report(form, "scope[0].state: approve\nscope.1.id: TC-2\n")[:3]
        check_in("K10: the problem names scope[1].id", '"scope[1].id"', problems[0].text)
        block = H.refusal_text(form, S4C, problems, role, kept=kept)
        check_in("K10: the block names scope[1].id", '"scope[1].id": <', block)
        check_eq("K10: the role's line is kept", kept, ["scope[0].state: approve"])
        check_eq("K10: and appears once", block.count("\nscope[0].state: approve\n"), 1)
        check_eq("K10: first among the lines", _skeleton(problems, kept=kept).splitlines()[0], "scope[0].state: approve")
    finally:
        cleanup(root)


def _old_door(form: Path, text: str) -> bool:
    """A COPY of the guard's own algorithm before SC2-13 (the second parse and the second read of the form): the door
    is open when the text parses and the form with every pair applied holds a filled `blocked.problem`. It is the
    control `blocked_said` is held to; it is not production code."""
    doc = handoff.parse(form.read_text(encoding="utf-8-sig", errors="replace"))
    contract = str(doc.get("contract") or "")
    pairs, unreadable = H.parse_values(text)
    if unreadable:
        return False
    merged = H.apply_values(doc, contract, pairs)[0]
    return not handoff.is_placeholder(merged.get("blocked.problem"))


def _with_blocked_problem(form: Path, word: str = "the findings file cannot be read: permission denied") -> Path:
    doc = _doc(form)
    assert handoff.set_value(doc, "blocked.problem", word)
    form.write_text(doc.text(), encoding="utf-8")
    return form


def blocked_said_is_the_old_guards_door_on_every_input() -> None:
    """K1/K4/K8 (SC2-13, AR-13, AR-28): `values_report.blocked_said` is the answer the guard used to compute with a
    second parse and a second read of the form; on every edge it is equal to a copy of that algorithm. A text that does
    not parse opens no door, whatever the form on disk says (E1); a placeholder is no word (E2, FR-59); a list is no word
    (E4); a form that already said it keeps its door (E3). The contract and the role are the ones the form names (K8)."""
    root = temp_project("qa-values-sc213-")
    try:
        art = _story(root)
        plain = _form4(art, "S4-qa-case-critic-1")
        said = _with_blocked_problem(_form4(art, "S4-qa-case-critic-2"))
        word = "blocked.field: review.outcome\nblocked.problem: the findings file cannot be read\n"
        bad = "header.verdict: contradiction\n"
        cases = {
            "E0 a word and a door": (plain, bad + word, True),
            "E0b a door and nothing wrong": (plain, word, True),
            "E1 unparseable text, form already said": (said, bad + "this line has no colon\n", False),
            "E1b unparseable text with the door in it": (plain, bad + word + "this line has no colon\n", False),
            "E2 template placeholder": (plain, bad + "blocked.problem: <what the role tried and what refused it, verbatim>\n", False),
            "E2b empty quotes": (plain, bad + 'blocked.problem: ""\n', False),
            "E2c <fill>": (plain, bad + "blocked.problem: <fill>\n", False),
            "E3 form already said, text has a bad word and no door": (said, bad, True),
            "E4 a list is not a word": (plain, bad + "blocked.problem: [a]\n", False),
            "E7 empty file": (plain, "", False),
            "E7b comments only": (said, "# only\n# comments\n", True),
            "E7c comments only, nothing said": (plain, "# only\n", False),
            "order: row 10 before row 2": (plain, "scope[10].reason: x\nscope[2].reason: y\n" + word, True),
        }
        for shown, (form, text, expected) in cases.items():
            report = H.values_report(form, text)
            check_eq(f"K1: {shown}: blocked_said", report.blocked_said, expected)
            check_eq(f"K1: {shown}: equal to the old guard's algorithm", report.blocked_said, _old_door(form, text))
        report = H.values_report(said, bad + "this line has no colon\n")
        check_eq("K4: a text that does not parse opens no door although the form on disk has one", report.blocked_said, False)
        check("K4: and the parse problem is what comes back", len(report.problems) == 1, str(report.problems))
        doc = _doc(plain)
        report = H.values_report(plain, bad)
        check_eq("K8: the contract is the form's own", report.contract, str(doc.get("contract")))
        check_eq("K8: the role is the form's own", report.role, str(doc.get("header.role")))
        check_eq("K8: the answer is a ValuesReport of five", (type(report).__name__, len(report)), ("ValuesReport", 5))
        check_eq("K8: the unparsed branch carries them too", (H.values_report(plain, "no colon").contract,
                                                              H.values_report(plain, "no colon").role), (report.contract, report.role))
    finally:
        cleanup(root)


def a_contract_without_the_door_field_has_no_door() -> None:
    """K6 (E5): a contract that names no `blocked.problem` field has no door: `blocked_said` is False and equals the old
    algorithm; the refusal keeps its general text (the guard refuses)."""
    root = temp_project("qa-values-sc213-e5-")
    try:
        art = _story(root)
        form = _form4(art)
        real = handoff.spec

        def without_door(contract):
            return {path: node for path, node in real(contract).items() if not path.startswith("blocked.")}

        text = "header.verdict: contradiction\nblocked.problem: the findings file cannot be read\n"
        handoff.spec = without_door
        try:
            kept_form = (H.values_report(form, text).blocked_said, _old_door(form, text))
            # a form of that contract has no `blocked:` section either: strip it, as an older form would lack it
            lines, skipping, stripped = form.read_text(encoding="utf-8").splitlines(), False, []
            for line in lines:
                if line.startswith("blocked:"):
                    skipping = True
                    continue
                if skipping and line[:1] in (" ", "\t", ""):
                    continue
                skipping = False
                stripped.append(line)
            form.write_text("\n".join(stripped) + "\n", encoding="utf-8")
            check_not_in("K6: the control - the stripped form holds no blocked.problem", "blocked.problem", form.read_text(encoding="utf-8"))
            report = H.values_report(form, text)
            old = _old_door(form, text)
        finally:
            handoff.spec = real
        check_eq("K6: no field in the contract and none in the form: no door", report.blocked_said, False)
        check_eq("K6: and the old algorithm said the same", old, False)
        check_eq("K6: a form that still holds the path is written with a note, as before: new equals old", kept_form[0], kept_form[1])
    finally:
        cleanup(root)


def a_derivation_of_fix_opens_no_door() -> None:
    """K7: `blocked_said` is read BEFORE `check(fix=True)`: a `check` that fills `blocked.problem` itself is not the role
    speaking, and the door stays shut (the position's invariant: the role's word opens it, code's derivation does not)."""
    root = temp_project("qa-values-sc213-k7-")
    try:
        art = _story(root)
        form = _form4(art)
        real = H.check

        def filling(doc, contract, art_, **kw):
            done = real(doc, contract, art_, **kw)
            handoff.set_value(done[0], "blocked.problem", "filled by the fix, not by the role")
            filled = handoff.parse(done[0].text())            # `set_value` writes the text; the reader sees a parsed document
            check_eq("K7: the control - the document `check` returns carries the filled door",
                     filled.get("blocked.problem"), "filled by the fix, not by the role")
            return (filled,) + tuple(done[1:])

        H.check = filling
        try:
            report = H.values_report(form, "header.verdict: contradiction\n")
        finally:
            H.check = real
        check_eq("K7: a derivation inside check(fix=True) opens no door", report.blocked_said, False)
        check("K7: and the problems are still returned", bool(report.problems))
    finally:
        cleanup(root)


def an_empty_list_and_a_flat_list_of_rows_are_taught_the_index() -> None:
    """K11: `scope: [a, b]` parses and the writer refuses it with `_near` while the skeleton unfolds the rows (E17, a pin);
    the fresh form with no rows says `no rows` and the indexed form."""
    pairs, bad = H.parse_values("scope: [a, b]", contract=S4C)
    check_eq("K11: the flat list parses", (len(pairs), bad), (1, []))
    _doc3, applied, problems, _n = H.apply_values(handoff.template(S4C), S4C, pairs)
    check_eq("K11: the writer refuses it", (applied, [p.path for p in problems]), (0, ["scope"]))
    check_in("K11: and the skeleton unfolds the rows", '"scope[0].id": <', _skeleton(problems))
    template = handoff.template(S4C).text()
    import re
    emptied = re.sub(r"(?ms)^scope:.*?(?=^\S)", "scope: []\n", template)
    doc = handoff.parse(emptied)
    problem = [p for p in H.check(doc, S4C, H.Artifacts(Path("."), dispatch="x"), fix=False, use_judge=False)[2]
               if p.path == "scope"]
    check("K11: the fresh form without rows is refused on scope", bool(problem), "")
    if problem:
        check_in("K11: `no rows` stays", "no rows", problem[0].text)
        check_in("K11: and it carries the indexed form", '"scope[0].id"', problem[0].text)


# r0107 t-439: the depth of the CLOSED deep scalar (`scope: [[[...]]]`). `handoff._scalar` cost ~44 s at 200000 on a
# box where 20000 costs ~3.3 s (the same on the base commit 8ce4ef3f, so the time is the input's size, not a release's
# slowdown); the guard under test (`except RecursionError` in `parse_values`) is live from the interpreter's own limit
# up (2000 levels already raise it, measured), so the depth is 20 times that limit, never a fixed number below it.
# The OPEN deep inputs (`"[" * 200000`, no closers) cost ~0.02 s and keep their size.
CLOSED_DEPTH = 20 * sys.getrecursionlimit()


def _battery() -> list:
    cyr, arabic = chr(0x438) + chr(0x434), chr(0x663)        # by code point: the package carries no Cyrillic (FR-30)
    return ["scope.0.id: x", "x" * 60 + " no colon", "x" * 61 + " no colon", "scope.99999.id: x", "scope.01.id: x",
            f"scope.{arabic}.id: x", "scope.0", "scope.0: {id: x}", "blocked.tried.0: x", "Scope.0.id: x",
            "scope: {\"id\": \"x\"}", "scope[0]: {id: x}", "inputs: [{path: x}]", "contract: x.0.y",
            "".join(f"bad line {n}\n" for n in range(2000)),
            "[" * 100 + "]" * 100, "[" * 200000, "scope: " + "[" * 200000, "scope: " + "[" * 100,
            "scope: " + "[" * CLOSED_DEPTH + "]" * CLOSED_DEPTH,
            "﻿scope.0.id: x\r\nscope.0.state: y\r\n", f"scope[0].{cyr}: x", "", "# only\n# comments\n",
            '{"scope": [{"id": "x"}]}', '{"scope.0.id": "x"}', '{"a": 1, "a": 2}', "{not json}",
            "scope[0].id: ok\nscope.1.id: x\n", "scope: [a, b]", "scope: x"]


def the_battery_never_raises_and_the_hint_names_only_real_paths() -> None:
    """K12: magnitude, nesting, encoding, empty and broken input (E7-E16): no exception; a path the hint names in `also`
    is a path of the contract the writer knows; the echo cuts at 60 as before; a deep file is an ordinary refusal."""
    s4_spec = handoff.spec(S4C)     # read once: the per-path `handoff.spec(S4C)` re-parsed the contract file tens of thousands of times (FR-31, t-1783)
    for text in _battery():
        try:
            pairs, problems = H.parse_values(text, contract=S4C)
        except Exception as exc:                                  # the failure is the test's finding, not a crash
            check(f"K12: no exception {text[:30]!r}", False, repr(exc))
            continue
        for problem in problems:
            for path in problem.also:
                generic = H.INDEXED.sub("[]", path)
                check(f"K12: {path} is a field of the contract", generic in s4_spec
                      and not handoff.owned_by_contract(path), path)
    two = {n: _problems(("x" * n) + " no colon")[0].text for n in (60, 61)}
    check_in("K12: 60 characters are shown whole", "x" * 60, two[60])
    check_not_in("K12: 61 are cut at 60 as before", "x" * 61, two[61])
    check_in("K12: an index past the rows is named, the writer refuses it", '"scope[99999].id"', _problems("scope.99999.id: x")[0].text)
    _d, applied, problems, _n = H.apply_values(handoff.template(S4C), S4C, [("scope[99999].id", "x", 1, "")])
    check_eq("K12: and opens nothing", applied, 0)
    check_in("K12: `the next row`", "the next row is", problems[0].text)
    check_in("K12: 01 reads as 1", '"scope[1].id"', _problems("scope.01.id: x")[0].text)
    check_not_in("K12: a non-ASCII digit is no index", '"scope[3].id"', _problems(f"scope.{chr(0x663)}.id: x")[0].text)
    check_not_in("K12: `scope.0` is no path of a row", 'scope[0]": <', _problems("scope.0")[0].text)
    check_not_in("K12: nor is a list of values a row", "blocked.tried[0].", _problems("blocked.tried.0: x")[0].text)
    check_eq("K12: a deep array is one ordinary problem", len(_problems("[" * 100 + "]" * 100)), 1)
    check_eq("K12: a too deep array is one problem too", len(_problems("[" * 200000)), 1)
    check_in("K12: with the usual text", "not valid JSON", _problems("[" * 200000)[0].text)
    deep = H.parse_values("scope: " + "[" * 200000)
    check_eq("K12: a too deep scalar is either one problem or one pair, never a crash", len(deep[0]) + len(deep[1]), 1)
    closed = H.parse_values("scope: " + "[" * CLOSED_DEPTH + "]" * CLOSED_DEPTH, contract=S4C)
    check_eq("K12: a closed too deep scalar is one problem and no pair (the RecursionError guard is live)",
             (len(closed[0]), len(closed[1])), (0, 1))
    check_in("K12: with the ordinary text", "is not a `path: value` line", closed[1][0].text)
    check_eq("K12: BOM and CRLF read", len(_problems("﻿scope.0.id: x\r\nscope.0.state: y\r\n")), 2)
    check_eq("K12: empty and comments have nothing", [_problems(t) for t in ("", "# only\n# comments\n")], [[], []])
    many = _problems("".join(f"bad line {n}\n" for n in range(10000)))
    check_eq("K12: ten thousand bad lines, ten thousand problems (nothing cut)", len(many), 10000)


def a_skeleton_of_every_refusal_reads_back_blank() -> None:
    """K13: the whole skeleton of each refusal of K1-K3 passes `parse_values` and every value in it is blank: left as
    it is, it writes nothing, and the comments stay comments (FILE_FIX is one line)."""
    check_eq("K13: FILE_FIX is one line", "\n" in H.FILE_FIX, False)
    for text in ("scope.0.id: TC-1\nscope.0.state: approve\n", '{"scope": [{"id": "TC-1"}]}', "findings: {id: F-1}",
                 "findings:\n  - id: F-1\n", "- id: x\n"):
        sketch = _skeleton(_problems(text))
        pairs, bad = H.parse_values(sketch)
        check_eq(f"K13: {text[:24]!r}: the skeleton parses", [p.text for p in bad], [])
        check(f"K13: {text[:24]!r}: every value is blank", all(H._blank_value(p[1]) for p in pairs), f"{pairs}")


# split: runner piece 1
if __name__ == "__main__":
    a_dotted_index_is_refused_with_the_indexed_row_form()
    a_list_of_objects_is_refused_with_the_first_row_lines()
    a_block_yaml_list_is_refused_with_the_headers_list()
    the_hint_never_changes_what_parse_values_decides()
    a_list_that_is_not_a_list_of_rows_gets_no_row_hint()
    an_unreadable_contract_gives_the_general_text()
    the_contract_is_read_once_and_only_when_a_line_is_bad()
    the_row_form_of_every_contract_is_a_path_the_writer_takes()
    a_section_skeleton_writes_a_list_of_values_whole()
    the_guard_block_carries_the_row_form_and_the_role_line_once()
    blocked_said_is_the_old_guards_door_on_every_input()
    a_contract_without_the_door_field_has_no_door()
    a_derivation_of_fix_opens_no_door()
    an_empty_list_and_a_flat_list_of_rows_are_taught_the_index()
    the_battery_never_raises_and_the_hint_names_only_real_paths()
    a_skeleton_of_every_refusal_reads_back_blank()
    one_refusal_block_one_command()
    a_role_with_bash_is_shown_the_heredoc_and_the_file_door()
    a_role_without_bash_is_shown_the_file_door_only()
    values_report_writes_nothing_and_never_asks_the_judge()
    a_refused_values_text_keeps_its_good_lines_in_the_skeleton()
    a_blank_field_code_fills_is_not_refused_by_values_report()
    a_blocked_row_puts_blocked_problem_into_the_skeleton()
    a_skeleton_is_blank_for_every_field_of_every_contract()
    the_skeleton_cuts_nothing()
    a_skeleton_left_as_is_writes_nothing()
    finish("test_handoff_values_refusal")
