#!/usr/bin/env python3
"""The form lists its own allowed values, and a form written again never meets the words of the attempt before (SC1-2 part B1).

Two failures behind the keys. A role learned the allowed words of a field only from a refusal (RC1-9 (a): one round per
vocabulary field), because the form showed `<one of vocabulary.header_verdicts>` and nothing else; the owner's word of
26.10.2026 is that the form carries the words itself. And a `<dispatch>.values.yaml` written for one form was applied to
the next form of the same dispatch (`handoff_init --force`, a story started again), so the words of a dead attempt
filled a new one. Each test says the one behaviour it pins; the keys are the names K-B* of the spec (t-1243, part B1).
"""
import json
import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402
import handoff_check as H  # noqa: E402
import handoff_init  # noqa: E402

S5 = "S5-qa-code-critic-1"
S4 = "S4-qa-case-critic-1"
INLINE = re.compile(r"^<one of vocabulary\.([a-z_]+) - (\S+?)(, .*)?>$")


def _contracts() -> list:
    """(contract id, the role that fills it) of every row of the index, and the conductor's escalation contract."""
    rows = [(str(row["contract"]), str(row["from"])) for row in handoff.index().get("handoffs", [])]
    rows.append((str(handoff.index()["escalation"]["contract"]), "qa-scout"))
    return rows


def _form(contract: str, role: str) -> str:
    text = (handoff.CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8")
    return handoff_init.fill_head(text, task="QA-9", dispatch=f"X-{role}-1", role=role, stage="S5", scope="")


def _story(root: Path) -> Path:
    art = root / "artifacts" / "QA-9"
    (art / "work").mkdir(parents=True)
    return art


def _init(art: Path, stage: str, role: str, to: str, dispatch: str, *extra: str):
    return run_script("handoff_init.py", "--task", "QA-9", "--stage", stage, "--role", role, "--to", to,
                      "--dispatch", dispatch, "--task-root", str(art), *extra)


def _form_path(art: Path, dispatch: str) -> Path:
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


# ------------------------------------------------------------------------------------------------ K-B1, K-B3
def test_every_placeholder_lists_its_words() -> None:
    """K-B1: protects the role from learning a vocabulary field's words only from a refusal. After init NO contract
    keeps a bare `<one of vocabulary.X>`, and every one carries `- a|b|c` read from the vocabulary (the tail, such as
    `, or a dash when ...`, and the line's own comment stay)."""
    seen, bare, wrong, above = 0, [], [], []
    for contract, role in _contracts():
        template = handoff.template(contract)
        form = handoff.parse(_form(contract, role))
        for path, node in template.nodes.items():
            if not isinstance(node.value, str) or not handoff.VOCAB_REF.search(node.value):
                continue
            seen += 1
            shown = form.get(path)
            found = INLINE.match(str(shown or "").strip())
            if not found:
                bare.append(f"{contract}:{path} = {shown!r}")
                continue
            leaf_state = path.rsplit(".", 1)[-1] == "state"
            field = handoff.spec_of(template)[re.sub(r"\[\d+\]", "[]", path)]
            words = handoff.options_for_role(field, role) if leaf_state else handoff.allowed(found.group(1))
            if found.group(2).split("|") != words:
                wrong.append(f"{contract}:{path} lists {found.group(2)!r}, wants {'|'.join(words)!r}")
            inner = node.value.strip()[1:-1]
            tail = inner[handoff_init.VOCAB_LIST.search(inner).end():]
            if (found.group(3) or "") != tail:
                wrong.append(f"{contract}:{path} tail {found.group(3)!r} != {tail!r}")
        for line in _form(contract, role).splitlines():
            if "one of the above" in line:
                above.append(f"{contract}: {line.strip()}")
    check(f"K-B1 {seen} vocabulary placeholders over {len(_contracts())} contracts were read", seen >= 60, str(seen))
    check_eq("K-B1 no placeholder of any contract is left without its list", bare, [])
    check_eq("K-B1 every list is the vocabulary's own (the role's own for a row's state), every tail kept", wrong, [])
    check_eq("K-B1 `<one of the above>` is gone from every contract (F5)", above, [])
    s5 = handoff.parse(_form("s5-automator-to-runner", "qa-automator"))
    check_eq("K-B1 a known line, whole: freshness",
             s5.get("scope[0].freshness"), "<one of vocabulary.freshness_states - fresh|stale|never_run>")
    check_eq("K-B1 a known line, whole: the tail stays",
             s5.get("scope[0].stale_because"),
             "<one of vocabulary.staleness_causes - source|test|runtime|environment|build|provenance, or a dash when freshness is fresh>")
    critic = _form("s5-critic-to-automator", "qa-code-critic")
    check_in("K-B1 a line's own comment stays after the list", "wrong_location>   # incomplete: the tool could not read the run", critic)


def test_state_list_is_the_roles_own() -> None:
    """K-B2: a row's `state` carries the words THIS role may write (`options_for_role`, what a refusal prints), not the
    fifty-two words of the vocabulary: a list nobody reads is no list. The two critics whose `state` was `<one of the
    above>` (F5) get theirs from the vocabulary too."""
    whole = handoff.allowed("row_states")
    mine = {}
    for contract, role in (("s5-critic-to-automator", "qa-code-critic"), ("s4-case-critic-to-designer", "qa-case-critic"),
                           ("s1-scout-to-tester", "qa-scout")):
        value = handoff.parse(_form(contract, role)).get("scope[0].state")
        found = INLINE.match(str(value))
        words = found.group(2).split("|") if found else []
        mine[role] = words
        field = handoff.spec(contract)["scope[].state"]
        check_eq(f"K-B2 {role}: the state list is options_for_role", words, handoff.options_for_role(field, role))
        check(f"K-B2 {role}: the state list is shorter than the vocabulary's {len(whole)} words", 0 < len(words) < len(whole), str(len(words)))
    check("K-B2 the critic's list and the scout's list differ", mine["qa-code-critic"] != mine["qa-scout"])
    check_in("K-B2 the code critic may write review_skipped", "review_skipped", mine["qa-code-critic"])


def test_hand_list_is_replaced() -> None:
    """K-B3: protects against two lists for one field. A hand-written list after the name is replaced by the
    vocabulary's; a tail and a comment after it stay."""
    text = ("a:\n"
            "  verdict: <one of vocabulary.critic_verdicts - old|list>   # keep this\n"
            "  cause: <one of vocabulary.repair_causes, or a dash when it never ran>\n"
            "  bare: <one of vocabulary.staleness_causes>\n")
    out = handoff.parse(handoff_init.inline_values(text, "qa-scout"))
    check_eq("K-B3 the hand list is the vocabulary's list",
             out.get("a.verdict"), "<one of vocabulary.critic_verdicts - approved|approved_with_fixes|rejected|unverified>")
    check_in("K-B3 the comment stays", "   # keep this", handoff_init.inline_values(text, "qa-scout"))
    check_eq("K-B3 the tail stays", out.get("a.cause"),
             "<one of vocabulary.repair_causes - test_defect|mechanical|environment|tooling|reviewer_error, or a dash when it never ran>")
    check_eq("K-B3 a bare name gets its list", out.get("a.bare"),
             "<one of vocabulary.staleness_causes - source|test|runtime|environment|build|provenance>")
    again = handoff_init.inline_values(handoff_init.inline_values(text, "qa-scout"), "qa-scout")
    check_eq("K-B3 doing it twice changes nothing", again, handoff_init.inline_values(text, "qa-scout"))
    check_eq("K-B3 a line that is not a vocabulary placeholder is untouched",
             handoff_init.inline_values("x: <= 80 characters>\ny: some words one of vocabulary.row_states\n", "r"),
             "x: <= 80 characters>\ny: some words one of vocabulary.row_states\n")


# ------------------------------------------------------------------------------------------------ K-B4
def test_empty_list_is_declared() -> None:
    """K-B4: protects against a blank list that reads as "any word" (FR-41). An empty or unreadable vocabulary list is
    written `NONE READABLE`, never as nothing, and the form is still written."""
    text = "h:\n  verdict: <one of vocabulary.header_verdicts>\n"
    with mock.patch.object(handoff, "allowed", lambda name: []):
        empty = handoff.parse(handoff_init.inline_values(text, "qa-scout")).get("h.verdict")
    check_eq("K-B4 an empty list is declared", empty, "<one of vocabulary.header_verdicts - NONE READABLE>")

    def broken(name):
        raise OSError("the vocabulary cannot be read")

    with mock.patch.object(handoff, "allowed", broken):
        unreadable = handoff.parse(handoff_init.inline_values(text, "qa-scout")).get("h.verdict")
    check_eq("K-B4 an unreadable list is declared", unreadable, "<one of vocabulary.header_verdicts - NONE READABLE>")
    state = "rows:\n  - state: <one of vocabulary.row_states>\n"
    with mock.patch.object(handoff, "allowed", lambda name: []):
        lone = handoff.parse(handoff_init.inline_values(state, "qa-code-critic")).get("rows[0].state")
    check_eq("K-B4 an empty list of a row's state is declared too", lone, "<one of vocabulary.row_states - NONE READABLE>")


# ------------------------------------------------------------------------------------------------ K-B5
def test_check_reads_the_template() -> None:
    """K-B5: protects every verdict of the check from the form's own text. The schema comes from the contract's
    template, so a form with the lists inline and one without give the same spec for every contract, and the same
    check output on an empty form."""
    moved = []
    for contract, role in _contracts():
        text = (handoff.CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8")
        before, after = handoff.spec_of(handoff.parse(text)), handoff.spec_of(handoff.parse(handoff_init.inline_values(text, role)))
        # the hint is the placeholder's own text and so shows the list; every verdict reads options, optional, max_len, kind
        flat = lambda spec: {p: (f.options, f.optional, f.max_len, f.kind) for p, f in spec.items()}  # noqa: E731
        if flat(before) != flat(after):
            moved.append(contract)
    check_eq("K-B5 the spec of a contract is the same with the lists inline", moved, [])

    root = temp_project()
    try:
        art = _story(root)
        _init(art, "S5", "qa-code-critic", "qa-automator", S5)
        inline = _form_path(art, S5)
        raw_art = root / "artifacts" / "QA-8"
        (raw_art / "work").mkdir(parents=True)
        with mock.patch.object(handoff_init, "inline_values", lambda text, role: text):
            text = (handoff.CONTRACTS / "s5-critic-to-automator.yaml").read_text(encoding="utf-8")
            raw = _form_path(raw_art, S5)
            raw.parent.mkdir(parents=True)
            # the control differs from the real form ONLY in the inline lists: the real init also empties the optional
            # `findings` list of this contract (EMPTIED, F1 (b)), so the control is emptied the same way
            raw.write_text(handoff_init.empty_optional_lists(
                handoff_init.fill_head(text, task="QA-9", dispatch=S5, role="qa-code-critic", stage="S5", scope=""),
                "s5-critic-to-automator"), encoding="utf-8")
        check_not_in("K-B5 the control form has no list inline", " - concerns|", raw.read_text(encoding="utf-8"))
        check_in("K-B5 the form under test has", " - concerns|", inline.read_text(encoding="utf-8"))
        out = []
        for path, art_root in ((inline, art), (raw, raw_art)):
            run = run_script("handoff_check.py", "--file", str(path), "--task", "QA-9", "--task-root", str(art_root), "--json")
            out.append(run.stdout)
        check("K-B5 the control run produced a JSON verdict", out[1].lstrip().startswith("{"), out[1][:200])
        check_eq("K-B5 the check says the same on both forms", json.loads(out[0]), json.loads(out[1]))
    finally:
        cleanup(root)


# ------------------------------------------------------------------------------------------------ the head line
def test_head_line_follows_the_roles_tools() -> None:
    """The form's head line names the door the role has: a role with Bash is told the stdin call as well, a role
    without it only the file (a text never names a command the guard would refuse it)."""
    scout = _form("s1-scout-to-tester", "qa-scout")
    designer = _form("s4-designer-to-case-critic", "qa-case-designer")
    critic = _form("s4-case-critic-to-designer", "qa-case-critic")
    check_in("head: a role with Bash is told the stdin call", "--fix --values - (Bash)", scout)
    check_not_in("head: a role without Bash is not", "--values -", critic)
    check_in("head: a role without Bash is told the file", "to work/handoffs/X-qa-case-critic-1.values.yaml in one Write; a Write over this form is refused", critic)
    check_not_in("head: an unknown role has no shell either", "(Bash)", _form("s1-scout-to-tester", "qa-nobody"))
    check_in("head: the line is a comment before the first key", "\n# Fill: ", scout)
    check("head: the line sits before schema_version",
          scout.index("# Fill: ") < scout.index("schema_version:") and designer.count("# Fill: ") == 1)
    check_eq("head: the form still parses as the contract does (same sections)",
             handoff.sections_of(handoff.parse(scout)).keys(), handoff.sections("s1-scout-to-tester").keys())


def test_head_line_names_the_row_form_of_its_own_contract() -> None:
    """K14 (HF8-7, AR-1, AR-10, FR-37): the head line of a form with a list of rows ends with how a row is written by its
    index, on THAT contract's list; a contract with another list names it, not `scope`; an unreadable contract gives the
    line as it was; there is still one `# Fill:` line and its old text is whole."""
    sentence = 'A row of a list, one line per key: "scope[0].id": <value>, the next row "scope[1].id".'
    critic = _form("s4-case-critic-to-designer", "qa-case-critic")
    line = [row for row in critic.splitlines() if row.startswith("# Fill:")]
    check_eq("K14: one Fill line", len(line), 1)
    check("K14: the old text is whole and the row form follows it", line[0].endswith("an Edit here is refused too. " + sentence), line[0][-160:])
    gate = _form("gate-a-to-automator", "qa-test-strategist")
    check_in("K14: gate A names its own list", '"environment.preconditions_accepted_as_blocked[0].case": <value>', gate)
    check_not_in("K14: and not scope", '"scope[0]', gate)
    saved = handoff.spec_of
    handoff.spec_of = lambda doc: (_ for _ in ()).throw(ValueError("unreadable"))
    try:
        broken = _form("s4-case-critic-to-designer", "qa-case-critic")
    finally:
        handoff.spec_of = saved
    broken_line = [row for row in broken.splitlines() if row.startswith("# Fill:")][0]
    check("K14: an unreadable contract: the line as before, no row form",
          broken_line.endswith("an Edit here is refused too.") and "A row of a list" not in broken_line, broken_line[-80:])
    designer = _form("s4-designer-to-case-critic", "qa-case-designer")
    check_in("K14: the designer's form names its list too", "A row of a list, one line per key:", designer)


# ------------------------------------------------------------------------------------------------ K-B16
def test_form_written_again_leaves_the_old_values_stale() -> None:
    """K-B16: protects a new form from the words of the attempt before. `handoff_init` that WRITES a form (a new one,
    or `--force`) first moves a waiting `<stem>.values.yaml` to `<stem>.values.stale.yaml`, which nothing applies; the
    path 'a form is already there' (no `--force`) is the same form and leaves its file alone, byte for byte."""
    words = "header.verdict: halt\nblocked.field: scope[0].state\nblocked.problem: the stand is down\n"
    root = temp_project()
    try:
        art = _story(root)
        form = _form_path(art, S5)
        waiting = H.sibling_values(form)
        stale = form.with_name(f"{S5}.values.stale.yaml")

        run = _init(art, "S5", "qa-code-critic", "qa-automator", S5)
        check_eq("K-B16 no neighbour: the form is written", (run.returncode, form.is_file()), (0, True))
        check_eq("K-B16 no neighbour: nothing extra is created", sorted(p.name for p in form.parent.iterdir()), [form.name])
        check_not_in("K-B16 no neighbour: nothing is said about one", "values", run.stdout.replace(".values.yaml in one", ""))

        waiting.write_text(words, encoding="utf-8")
        before = waiting.read_bytes()
        run = _init(art, "S5", "qa-code-critic", "qa-automator", S5)
        check_eq("K-B16 form already there, no --force: the neighbour stays, byte for byte",
                 (run.returncode, waiting.read_bytes(), stale.exists()), (0, before, False))

        run = _init(art, "S5", "qa-code-critic", "qa-automator", S5, "--force")
        check_eq("K-B16 --force: the neighbour became the stale file, unchanged",
                 (waiting.exists(), stale.read_bytes()), (False, before))
        check_in("K-B16 --force: the stale file is named in the output", f"{S5}.values.stale.yaml", run.stdout)
        fix = run_script("handoff_check.py", "--file", str(form), "--task", "QA-9", "--task-root", str(art), "--fix", "--json")
        report = json.loads(fix.stdout)
        check_eq("K-B16 --force: the next --fix applies nothing of it", (report["values_applied"], report["values_pending"]), (0, ""))
        check_eq("K-B16 --force: the new form's verdict is still a placeholder",
                 handoff.parse(form.read_text(encoding="utf-8")).get("header.verdict") in (None, "") or
                 handoff.is_placeholder(handoff.parse(form.read_text(encoding="utf-8")).get("header.verdict")), True)
        check_eq("K-B16 --force: the stale file is not renamed .applied", (form.with_name(f"{S5}.values.applied.yaml").exists(),), (False,))

        # the stale file of an earlier round is replaced by the next, and an orphan meets a NEW form
        form.unlink()
        waiting.write_text("header.verdict: ok\n", encoding="utf-8")
        run = _init(art, "S5", "qa-code-critic", "qa-automator", S5)
        check_eq("K-B16 a new form beside an orphan: the orphan became stale, replacing the one before",
                 (waiting.exists(), stale.read_text(encoding="utf-8")), (False, "header.verdict: ok\n"))
        check_eq("K-B16 a new form beside an orphan: the form is written", form.is_file(), True)
    finally:
        cleanup(root)


def test_old_values_that_cannot_be_moved() -> None:
    """K-B16 (F11 (b)): the form is ALWAYS written (a form that is not there is a form nobody checks, FR-4). When the old
    file cannot be moved aside it is deleted; when it cannot be deleted either, the form is written and the output says,
    in one loud line, that the old words will meet it."""
    root = temp_project()
    try:
        art = _story(root)
        form = _form_path(art, S5)
        form.parent.mkdir(parents=True)
        waiting = H.sibling_values(form)
        stale = form.with_name(f"{S5}.values.stale.yaml")

        waiting.write_text("header.verdict: halt\n", encoding="utf-8")
        with mock.patch("os.replace", side_effect=PermissionError("locked")):
            said = handoff_init._stale_values(form)
        check_eq("K-B16 move impossible, delete possible: the file is gone, nothing is left to apply",
                 (waiting.exists(), stale.exists()), (False, False))
        check_in("K-B16 move impossible, delete possible: the line says it was deleted and never applied",
                 "was deleted and never applied", said)

        waiting.write_text("header.verdict: halt\n", encoding="utf-8")
        with mock.patch("os.replace", side_effect=PermissionError("locked")), \
                mock.patch.object(Path, "unlink", side_effect=PermissionError("locked")):
            said = handoff_init._stale_values(form)
        check_eq("K-B16 neither possible: the file stays, loudly", (waiting.exists(), stale.exists()), (True, False))
        check_in("K-B16 neither possible: the line names the file", f"{S5}.values.yaml could not be moved aside (PermissionError)", said)
        check_in("K-B16 neither possible: the line says what happens and what to do",
                 "it will be applied to this new form at the next check - remove it before the role starts", said)

        # and through main(): the form is written either way
        argv = ["handoff_init.py", "--task", "QA-9", "--stage", "S5", "--role", "qa-code-critic", "--to", "qa-automator",
                "--dispatch", S5, "--task-root", str(art), "--force"]
        with mock.patch("os.replace", side_effect=PermissionError("locked")), \
                mock.patch.object(Path, "unlink", side_effect=PermissionError("locked")), \
                mock.patch.object(sys, "argv", argv), mock.patch("builtins.print") as printed:
            code = handoff_init.main()
        lines = [" ".join(str(a) for a in call.args) for call in printed.call_args_list]
        check_eq("K-B16 neither possible, through main: exit 0 and the form is written", (code, form.is_file()), (0, True))
        check("K-B16 neither possible, through main: the loud line is printed before the form is named",
              any("could not be moved aside" in line for line in lines) and
              [i for i, line in enumerate(lines) if "could not be moved aside" in line][0] <
              [i for i, line in enumerate(lines) if line.startswith("handoff form:")][0], str(lines))

        # a values file that is a nothing: no neighbour at all, no line
        waiting.unlink()
        check_eq("K-B16 no neighbour: no line", handoff_init._stale_values(form), "")
    finally:
        cleanup(root)


def test_fill_line_names_the_form_where_it_was_written() -> None:
    """K-B1b (B1-1, FR-37): the head line names the file of the words beside the form that was WRITTEN, `--out` honoured
    (relative and nested), by the one rule `handoff_check.sibling_values`; without `--out` it is the dispatch's default place.
    KILLS: a line that spells `work/handoffs/<dispatch>.values.yaml` whatever `--out` says."""
    root = temp_project()
    try:
        art = _story(root)
        _init(art, "S5", "qa-code-critic", "qa-automator", S5)
        line = lambda text: [row for row in text.splitlines() if row.startswith("# Fill: ")][0]
        default = line(_form_path(art, S5).read_text(encoding="utf-8"))
        check_in("K-B1b no --out: the default place", f"to work/handoffs/{S5}.values.yaml in one Write", default)
        for out in ("cases/F.yaml", "a/b/c/G.yaml"):
            run = run_script("handoff_init.py", "--task", "QA-9", "--stage", "S1", "--role", "qa-scout",
                             "--to", "qa-requirements-tester", "--dispatch", "S1-qa-scout-1",
                             "--task-root", str(art), "--out", out, cwd=root)
            written = root / out
            check_eq(f"K-B1b --out {out}: the form is written there", (run.returncode, written.is_file()), (0, True))
            head = line(written.read_text(encoding="utf-8"))
            named = re.search(r" to (\S+) in one Write", head).group(1)
            check_eq(f"K-B1b --out {out}: the line names the file beside it", named, H.sibling_values(out).as_posix())
            check_not_in(f"K-B1b --out {out}: not the default place", "work/handoffs/", head)
            check_in(f"K-B1b --out {out}: the shell door names the form that was written", f"--file {out} --fix --values -", head)
    finally:
        cleanup(root)


def test_the_loud_line_of_handoff_init_reaches_the_conductor() -> None:
    """K-B16b (B1-2, F11 (b)): `story_step._handoff_form` returns the loud line of `handoff_init` (an old values file that
    could not be moved aside will meet the new form) as its note when the form is written; a line that only reports a
    file moved aside, and an output with nothing extra, give no note. KILLS: `return rel, ""` on success."""
    import story_step
    root = temp_project()
    try:
        art = _story(root)
        form = _form_path(art, S5)
        form.parent.mkdir(parents=True)
        form.write_text("contract: x\n", encoding="utf-8")
        loud = (f"handoff_init: {S5}.values.yaml could not be moved aside (PermissionError); it will be applied to this new "
                "form at the next check - remove it before the role starts")
        aside = f"handoff_init: {S5}.values.yaml belonged to the form written before; kept as {S5}.values.stale.yaml and never applied"
        tail = f"handoff form: {form}\ncontract: c (a -> b)\nfill it, then: handoff_check.py --file {form}\n"
        rel_expected = f"qa-factory/artifacts/QA-9/work/handoffs/{S5}.yaml"
        for label, output, note in (("loud line", loud + "\n" + tail, loud), ("moved aside", aside + "\n" + tail, ""),
                                    ("nothing extra", tail, "")):
            with mock.patch.object(story_step, "_run", lambda *a, **k: (0, output)):
                got = story_step._handoff_form("QA-9", "S5", "qa-code-critic", S5, art, "")
            check_eq(f"K-B16b {label}", got, (rel_expected, note))
        with mock.patch.object(story_step, "_run", lambda *a, **k: (2, "handoff_init: no contract for x\nmore\n")):
            got = story_step._handoff_form("QA-9", "S5", "qa-code-critic", S5, art, "")
        check_eq("K-B16b a refusal of handoff_init is the note as before", got, ("", "handoff_init: no contract for x"))
        form.unlink()
        got = story_step._handoff_form("QA-9", "S5", "qa-code-critic", S5, art, "")
        check_eq("K-B16b the real handoff_init, nothing extra: the form and no note", got, (rel_expected, ""))
    finally:
        cleanup(root)


def test_form_begun_on_the_old_version() -> None:
    """M-7: a form begun on 0.10.2 (no lists inline, no head line, a critic's `<one of the above>`) still passes the
    check: the lists in the form are for the role to read, the check never reads them."""
    root = temp_project()
    try:
        art = _story(root)
        dispatch = "S5-qa-code-critic-9"
        text = (handoff.CONTRACTS / "s5-critic-to-automator.yaml").read_text(encoding="utf-8").replace(
            "state: <one of vocabulary.row_states>", "state: <one of the above>")
        with mock.patch.object(handoff_init, "inline_values", lambda t, r: t):
            form = handoff_init.fill_head(text, task="QA-9", dispatch=dispatch, role="qa-code-critic", stage="S5", scope="")
        form = "\n".join(line for line in form.splitlines() if not line.startswith("# Fill: ")) + "\n"
        path = _form_path(art, dispatch)
        path.parent.mkdir(parents=True)
        path.write_text(form, encoding="utf-8")
        run = run_script("handoff_check.py", "--file", str(path), "--task", "QA-9", "--task-root", str(art), "--json")
        report = json.loads(run.stdout)
        check_in("M-7 a 0.10.2 form is read as before (the check runs, its problems are the ordinary ones)",
                 "scope", [p["path"] for p in report["problems"]])
        check_eq("M-7 nothing in it is refused for lacking the new head line or lists",
                 [p["path"] for p in report["problems"] if "Fill" in p["problem"] or "inline" in p["problem"]], [])
    finally:
        cleanup(root)


test_every_placeholder_lists_its_words()
test_state_list_is_the_roles_own()
test_hand_list_is_replaced()
test_empty_list_is_declared()
test_check_reads_the_template()
test_head_line_follows_the_roles_tools()
test_head_line_names_the_row_form_of_its_own_contract()
test_form_written_again_leaves_the_old_values_stale()
test_old_values_that_cannot_be_moved()
test_fill_line_names_the_form_where_it_was_written()
test_the_loud_line_of_handoff_init_reaches_the_conductor()
test_form_begun_on_the_old_version()
finish("handoff inline values")
