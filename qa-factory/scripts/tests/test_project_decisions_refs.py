"""project_decisions.py `_refs()`: a Git Bash (MSYS) argument survives.

TP1-15045: `project_decisions.py add --field-ref "/gate_a/design_reviews"` run from Git
Bash came back "C:/Program Files/Git/gate_a/design_reviews" — MSYS rewrites any argv token
that starts with a bare `/` into an absolute Windows path rooted at the Git install dir,
because it looks like a POSIX path. `_refs()` used to require every ref to start with `/` and
raised "field_refs must contain JSON pointers", so the orchestrator's two attempts both failed
and three factory findings never reached a registry.

Runnable on its own: `python -B scripts/tests/test_project_decisions_refs.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_decisions as PD  # noqa: E402


def test_msys_rewritten_pointer_is_recovered() -> None:
    mangled = "C:/Program Files/Git/gate_a/design_reviews"
    check_eq("MSYS-mangled arg recovers the original pointer", PD._refs(mangled),
             ["/gate_a/design_reviews"])


def test_msys_rewritten_pointer_with_backslashes_is_recovered() -> None:
    mangled = r"C:\Program Files\Git\gate_a\design_reviews"
    check_eq("backslash MSYS path recovers the original pointer", PD._refs(mangled),
             ["/gate_a/design_reviews"])


def test_bare_pointer_without_leading_slash_is_accepted() -> None:
    check_eq("a pointer typed without its leading `/` still normalizes",
             PD._refs("gate_a/design_reviews"), ["/gate_a/design_reviews"])


def test_already_correct_pointer_is_unchanged() -> None:
    check_eq("a normal JSON pointer passes through unchanged",
             PD._refs("/gate_a/design_reviews"), ["/gate_a/design_reviews"])


def test_list_input_mixes_forms() -> None:
    check_eq("a list of refs normalizes every entry",
             PD._refs(["/a/b", "c/d", "C:/Program Files/Git/e/f"]),
             ["/a/b", "/c/d", "/e/f"])


def test_empty_refs_still_reject() -> None:
    threw = False
    try:
        PD._refs("")
    except ValueError:
        threw = True
    check("an empty ref list is still refused", threw)


def test_cli_add_accepts_the_exact_mangled_argument() -> None:
    """End to end: the literal argv value Git Bash produced now records a decision."""
    root = temp_project("qa-factory-project-decisions-")
    try:
        row = PD.upsert(root, field_refs=["C:/Program Files/Git/gate_a/design_reviews"],
                         essence="scope on a historical S4 dispatch", asked="owner, 2026-09-20",
                         scope="local-urgent", owner="story owner")
        check_eq("the recorded row carries the clean pointer",
                 row["field_refs"], "/gate_a/design_reviews")
        proc = run_script("project_decisions.py", "--root", root, "add",
                           "--field-ref", "C:/Program Files/Git/gate_b/other",
                           "--essence", "second finding", "--asked", "owner, 2026-09-21",
                           "--scope", "local-urgent", "--owner", "story owner")
        check("the CLI itself exits clean on a mangled --field-ref", proc.returncode == 0,
              proc.stdout + proc.stderr)
    finally:
        cleanup(root)


def test_add_finding_needs_no_field_ref() -> None:
    """`add-finding` (factory findings) never took `--field-ref` — regression guard for the
    part the CLI already had right, so a later change cannot quietly require one."""
    root = temp_project("qa-factory-project-decisions-")
    try:
        proc = run_script("project_decisions.py", "--root", root, "add-finding",
                           "--essence", "Git Bash mangles a leading-`/` argument",
                           "--scope", "local-urgent", "--witness", "TP1-15045",
                           "--idempotency-key", "test-key-1")
        check("add-finding succeeds with no --field-ref at all", proc.returncode == 0,
              proc.stdout + proc.stderr)
    finally:
        cleanup(root)


# --- t-299 (B-253 b): the scope of a finding is one of three words, and a refusal says which ---------------
#
# TP1-15045, 02.10: the conductor ran `add-finding --scope "handoff.py REQUIRED_LISTS / handoff_check.py /
# driver S7 entry"`, met a bare `ValueError: invalid finding scope` traceback with no word named, and stopped:
# the finding that the factory's own S7 form had no legal answer was never recorded.

REAL_BAD_SCOPE = "handoff.py REQUIRED_LISTS / handoff_check.py / driver S7 entry"   # the conductor's own
WORDS = ("local-urgent", "local-calibration", "upstream-candidate")


def add_finding_cli(root, scope, key="k", essence="the S7 form has no empty answer", witness="TP1-15045 S7"):
    return run_script("project_decisions.py", "--root", root, "add-finding", "--essence", essence,
                      "--scope", scope, "--witness", witness, "--idempotency-key", key)


def backlog_rows(root):
    path = root / "qa-factory" / "factory-backlog.md"
    return PD.parse_findings(path.read_text(encoding="utf-8")) if path.exists() else []


def test_the_scope_words_are_listed_and_each_writes_a_row() -> None:
    """K4: `--help` lists the three words; each valid word writes one FB row; the three are the template's."""
    root = temp_project("qa-factory-project-decisions-")
    try:
        helped = run_script("project_decisions.py", "add-finding", "--help")
        check("add-finding --help exits 0", helped.returncode == 0, helped.stderr)
        for word in WORDS:
            check(f"--help lists `{word}`", word in " ".join(helped.stdout.split()), helped.stdout)
        check_eq("the writer's constant holds exactly the three words, in this order", tuple(PD.FINDING_SCOPES), WORDS)
        for number, word in enumerate(WORDS, start=1):
            done = add_finding_cli(root, word, key=f"key-{number}")
            check(f"`--scope {word}` writes", done.returncode == 0, done.stdout + done.stderr)
        rows = backlog_rows(root)
        check_eq("three FB rows, one per word, each with its scope", [(r["id"], r["scope"]) for r in rows],
                 [("FB-1", WORDS[0]), ("FB-2", WORDS[1]), ("FB-3", WORDS[2])])
        # the same key and the same content is the same row, not a fourth
        again = add_finding_cli(root, WORDS[0], key="key-1")
        check_eq("a retry with the same key and content writes nothing new", (again.returncode, len(backlog_rows(root))), (0, 3))
        # the template's own words: the three words and the meaning each refusal prints are the file's
        template_file = Path(PD.__file__).resolve().parents[1] / "references" / "templates" / "factory-backlog.md"
        template = " ".join(template_file.read_text(encoding="utf-8").split())
        for word, meaning in PD.FINDING_SCOPES.items():
            check(f"the template names `{word}`", f"`{word}`" in template)
            lead = " ".join(meaning.replace(";", ":").replace("(", ":").split(":")[0].split())
            check(f"and the meaning printed for `{word}` is its words ({lead!r})", lead in template, template[:300])
    finally:
        cleanup(root)


def test_an_invalid_scope_is_refused_with_the_three_words() -> None:
    """K4 / S5: the real value, an empty string, another letter case, padding and magnitude: exit 2, the three
    words and their meanings, no traceback, and not one row written."""
    root = temp_project("qa-factory-project-decisions-")
    try:
        cap = PD.SCOPE_SHOWN
        cases = (("the conductor's own value", REAL_BAD_SCOPE), ("an empty string", ""),
                 ("another letter case", "Local-Urgent"), ("upper case", "LOCAL-URGENT"),
                 ("padding", " local-urgent"), ("a trailing space", "local-urgent "),
                 ("a word that is not one", "urgent"), ("AT the cap", "x" * cap), ("BEYOND the cap", "x" * (cap + 1)),
                 ("a magnitude", "x" * 20000), ("a newline and quotes", "local\n\"urgent'"),
                 ("non-ASCII", "déploiement-urgent"))
        for label, scope in cases:
            done = add_finding_cli(root, scope)
            err = done.stderr
            check_eq(f"S5 ({label}): exit 2", done.returncode, 2)
            check_not_in_text(f"S5 ({label}): no traceback", "Traceback", err)
            for word in WORDS:
                check(f"S5 ({label}): the refusal names `{word}`", f"`{word}`" in err, err[-600:])
            check("S5 ({}): and what the first one means".format(label), "breaks runs here and now" in err, err[-600:])
            check(f"S5 ({label}): nothing was written", backlog_rows(root) == [] and not (root / "qa-factory"
                  / "factory-backlog.md").exists(), "a row or the file exists")
        # the echo of a refused word is cut, with an ellipsis, BEYOND the cap and whole AT it
        at = add_finding_cli(root, "x" * cap).stderr
        beyond = add_finding_cli(root, "x" * (cap + 1)).stderr
        check("AT the cap the word is echoed whole", "'" + "x" * cap + "'" in at, at[-300:])
        check("BEYOND the cap it is cut with an ellipsis", "'" + "x" * cap + "...'" in beyond, beyond[-300:])
        check("a 20 KB word does not become a 20 KB refusal", len(add_finding_cli(root, "x" * 20000).stderr) < 2000)
    finally:
        cleanup(root)


def check_not_in_text(name, needle, text) -> None:
    check(name, needle not in text, text[-400:])


def test_a_direct_call_still_raises_and_other_refusals_are_one_line() -> None:
    """S5: the guard calls `add_finding()` and relies on the ValueError; the CLI turns the refusals of add-finding
    - the scope and every other ValueError of it - into one stderr line and exit 2."""
    root = temp_project("qa-factory-project-decisions-")
    try:
        for scope in (REAL_BAD_SCOPE, "", "Local-Urgent"):
            raised = ""
            try:
                PD.add_finding(root, essence="e", scope=scope, witness="w", idempotency_key="k")
            except ValueError as exc:
                raised = str(exc)
            check(f"a direct add_finding({scope[:20]!r}) raises ValueError naming the three words",
                  all(f"`{w}`" in raised for w in WORDS), raised)
        done = add_finding_cli(root, "local-urgent", essence="  ")
        check_eq("an empty essence: exit 2", done.returncode, 2)
        check_eq("...one stderr line, no traceback", (len(done.stderr.strip().splitlines()), "Traceback" in done.stderr), (1, False))
        check_in_text("...naming what was refused", "essence, witness and idempotency_key are required", done.stderr)
        check("a valid word still writes", add_finding_cli(root, "local-calibration", key="a").returncode == 0)
        clash = add_finding_cli(root, "local-calibration", key="a", essence="another essence")
        check_eq("the same key with other content: its OWN exit code (3, C1-7a: the finding is recorded), one line",
                 (clash.returncode, len(clash.stderr.strip().splitlines())), (PD.RECORDED_EARLIER_EXIT, 1))
        check_eq("...and that code is 3, distinct from every other refusal's 2", (PD.RECORDED_EARLIER_EXIT, done.returncode), (3, 2))
        check_in_text("...naming the clash", "idempotency key reused with different finding content", clash.stderr)
        other = add_finding_cli(root, "local-calibration", key="b", essence="another essence")
        check_eq("control: another key with that other content is a NEW row, exit 0", other.returncode, 0)
        try:
            PD.add_finding(root, essence="third essence", scope="local-calibration", witness="w", idempotency_key="a")
            raised_type = None
        except ValueError as exc:
            raised_type = type(exc).__name__
        check_eq("a direct call raises the ValueError subclass the CLI maps (the guard relies on a ValueError)", raised_type, "FindingRecordedEarlier")
    finally:
        cleanup(root)


def check_in_text(name, needle, text) -> None:
    check(name, needle in text, text[-400:])


def test_the_dashboard_reads_the_writers_words() -> None:
    """Q6 (i): ONE constant. The dashboard imports it, and a word it has no colour for is drawn grey, not dropped."""
    import factory_dashboard as FD
    check("the dashboard's constant IS the writer's", FD.FINDING_SCOPES is PD.FINDING_SCOPES)
    check_eq("every word of the writer has a colour of its own in the dashboard", sorted(FD.SCOPE_COLOR), sorted(PD.FINDING_SCOPES))
    check("and the table has no word the writer lacks", set(FD.SCOPE_COLOR) <= set(PD.FINDING_SCOPES))


if __name__ == "__main__":
    test_the_scope_words_are_listed_and_each_writes_a_row()
    test_an_invalid_scope_is_refused_with_the_three_words()
    test_a_direct_call_still_raises_and_other_refusals_are_one_line()
    test_the_dashboard_reads_the_writers_words()
    test_msys_rewritten_pointer_is_recovered()
    test_msys_rewritten_pointer_with_backslashes_is_recovered()
    test_bare_pointer_without_leading_slash_is_accepted()
    test_already_correct_pointer_is_unchanged()
    test_list_input_mixes_forms()
    test_empty_refs_still_reject()
    test_cli_add_accepts_the_exact_mangled_argument()
    test_add_finding_needs_no_field_ref()
    finish("project_decisions_refs")
