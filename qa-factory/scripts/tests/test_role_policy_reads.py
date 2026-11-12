#!/usr/bin/env python3
"""The read guard reads a quoted pattern as text, and one plain read command is all a role without Bash may run (CX1-5).

TP2-2406 S3-3, 15.10: the strategist (`tools: Read, Grep, Glob, Write, Edit`, no Bash) ran
`rg -n -A 8 -B 2 '"id":"TS-(1|2|3|4|8)"' <plan>` to read five rows of its plan. `host_adapter.role_policy` refused it
as "arbitrary shell execution" because a character search for `; & | ( )` ignored the quotes and hit the `|` of the
single-quoted regex; the role halted and its plan was never changed. The guard now reads the command with
`hooklib.command_segments` (the one shell tokenizer, SIBLING_MAP axis 11) in both shell dialects, and refuses whole every
form the shell reads differently from that tokenizer (`hooklib.SHELL_OPAQUE_BAN`, shared with the runner guard).

Expected verdicts come from the requirements (a quoted `|` is text, an unquoted one is an operator; the shell's own
forms the tokenizer does not model are refused), not from running the code (FR-58).

  K1  the commands of the diagnosis and of the review t-941, through the real `guard_pre_tool.py` as Codex PreToolUse
      events: the real refused read and `rg -n 'a;b'` PASS, every unquoted operator / substitution / redirect /
      hidden-quote / program launch is REFUSED in the role policy's own words, a Bash role's pipe is untouched.
      Mutation: restore the raw `[;&|...]` character search in `_read_refusal` -> the real-command case goes red
  K1b the predicate itself, in both dialects, with the adversarial battery (empty, huge, non-ASCII, nested, unbalanced
      quote, `--pre=`, `--pre-glob`), the boundary AT one segment (passes) and BEYOND it (refused), and the boundaries
      of the typographic-quote range (U+2017 passes, U+2018 refuses, U+201E refuses, U+201F passes)
  K1c the nine forms of the review t-941 G-1 (a launch hidden in a cut the tokenizer makes and the shell does not) in
      the read guard, with a read command in front: each is refused and the refusal says why and how to write it
  K5  the changelog fragment exists and names the change
"""
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import host_adapter  # noqa: E402
import role_replay as RR  # noqa: E402

TICKET = "TP2-2406"
PLAN = f"qa-factory/artifacts/{TICKET}/work/test-plan.json"
STRATEGIST = "qa-test-strategist"
BASH_ROLE = "qa-automator"
FRAGMENT = harness.PLUGIN_ROOT / "changelog.d" / "codex-1-cx1-5-one-tokenizer.md"
NOTE_MARKER = "The two command guards read a command with one tokenizer"  # the first words of this note in CHANGELOG.md
# Row 74 of the child rollout, decoded: the cmd of the refused exec_command, byte for byte.
REAL = f"""rg -n -A 8 -B 2 '"id":"TS-(1|2|3|4|8)"' '{PLAN}'"""

# (name, command, role, expected): "PASS" = the guard allows (exit 0), "REFUSED" = exit 2 from the role policy.
CASES = [
    ("REAL refused read (rollout row 74)", REAL, STRATEGIST, "PASS"),
    ("rg -e 'TS-1' -e 'TS-2' (control)", f"rg -n -e 'TS-1' -e 'TS-2' {PLAN}", STRATEGIST, "PASS"),
    ("rg -n 'a;b' <plan>", f"rg -n 'a;b' {PLAN}", STRATEGIST, "PASS"),
    ("rg \"a|b\" <plan>", f'rg -n "a|b" {PLAN}', STRATEGIST, "PASS"),
    ("OH3-32 rg \"a\\|b\" <plan> (a quoted backslash-pipe)", f'rg -n "a\\|b" {PLAN}', STRATEGIST, "PASS"),
    ("unquoted ; chaining", f"rg -n TS-1 {PLAN}; Remove-Item y", STRATEGIST, "REFUSED"),
    ("unquoted | pipe", f"rg -n TS-1 {PLAN} | sort", STRATEGIST, "REFUSED"),
    ("a quoted rg pattern, then a real pipeline into the runner", f"rg 'x' {PLAN} | python run_suite.py",
     STRATEGIST, "REFUSED"),
    # t-025 F-1: PowerShell reads these typographic quotes as quote delimiters, the ASCII tokenizer does not
    ("smart single quotes hide ;", f"rg 'x\u2019; Write-Output INJECTED; rg \u2018y' {PLAN}", STRATEGIST, "REFUSED"),
    ("&& chaining", f"rg -n TS-1 {PLAN} && Remove-Item y", STRATEGIST, "REFUSED"),
    ('"$(Remove-Item y)"', f'rg -n "$(Remove-Item y)" {PLAN}', STRATEGIST, "REFUSED"),
    ("redirect >", f"rg -n TS-1 {PLAN} > out.txt", STRATEGIST, "REFUSED"),
    ("backslash-quote hides ;", f"rg -n \\'; Remove-Item y; echo \\' {PLAN}", STRATEGIST, "REFUSED"),
    ("Get-Content (Remove-Item x)", "Get-Content (Remove-Item x)", STRATEGIST, "REFUSED"),
    ("python plan_row.py ...", "python plan_row.py --task T --row TS-1 --set a=b", STRATEGIST, "REFUSED"),
    ("rg --pre python x <plan>", f"rg --pre python x {PLAN}", STRATEGIST, "REFUSED"),
    ("newline inside quotes", f"rg -n 'a\nb' {PLAN}", STRATEGIST, "REFUSED"),
    ("an empty command", "", STRATEGIST, "REFUSED"),
    ("Bash role (qa-automator), ls | sort", "ls qa-factory | sort", BASH_ROLE, "PASS"),
]

# What a refusal of the shell's own forms says: the sequence, that the shell reads it differently, and the door.
DIFFERENTLY = "the shell reads differently from the guard"
OPAQUE_CASES = [
    ("a backslash before a quote", r"rg -n x \'; Remove-Item y; echo \' f.json", "backslash before `'`"),
    ("a backslash before ;", r"rg -n a\;b f.json", "backslash before `;`"),
    ("a typographic quote", "rg -n \u201cx f.json", "typographic quote U+201C"),
    ("a lone CR", "rg -n x f.json\rRemove-Item y", "lone carriage return"),
    ("the stop-parsing token", "rg --% a;cat f.json", "`--%`"),
    # t-947 F-1: bash keeps the `#` inside the word, so the text after it RUNS (the tokenizer reads a comment there)
    ("a backslash-escaped blank hides a second command in a 'comment'", "rg -n x f.json\\ # ; echo PWNED",
     "backslash-escaped blank before `#`"),
    ("a form feed hides a second command in a 'comment'", "rg -n x f.json\x0c# ; echo PWNED",
     "vertical tab or form feed"),
]

# The nine forms of t-941 G-1, each with a read command in front (the runner guard's battery has them with `python`).
G1_READ_FORMS = [
    ("backslash &", r"rg -X a\&cat f.json"),
    ("backslash (", r"rg -X a\(cat f.json"),
    ("$(true)cat", "rg -X $(true)cat f.json"),
    ("$((0))cat", "rg -X $((0))cat f.json"),
    ("<(true)cat", "rg -X <(true)cat f.json"),
    ("PowerShell (@())cat", "rg -X (@())cat f.json"),
    ("PowerShell $()cat", "rg -X $()cat f.json"),
    ("PowerShell block comment", "rg <# #> f.json"),
    ("PowerShell stop-parsing token", "rg --% -X a;cat f.json"),
]

# t-947 F-1: the comment members. Each is refused and the refusal names the sequence (the reader head is in front, as in K1c).
F1_COMMENT_FORMS = [
    ("$(true)#", "rg -X $(true)# f.json --task X", "`#` right after `)`"),
    ("$((0))#", "rg -X $((0))# f.json --task X", "`#` right after `)`"),
    ("<(true)#", "rg -X <(true)# f.json --task X", "`#` right after `)`"),
    ("backslash blank #", "rg -n x f.json\\ # ; echo PWNED", "backslash-escaped blank before `#`"),
    ("backslash TAB #", "rg -n x f.json\\\t# ; echo PWNED", "backslash-escaped blank before `#`"),
    ("form feed #", "rg -n x f.json\x0c# ; echo PWNED", "vertical tab or form feed"),
    ("vertical tab #", "rg -n x f.json\x0b# ; echo PWNED", "vertical tab or form feed"),
]


def bash_event(role: str, command: str, root: Path, n: int) -> dict:
    """The event the host sends for a nested `tools.exec_command`: tool_name Bash, command = the inner cmd."""
    return dict(RR.codex_event(role, "", root, n), tool_name="Bash", tool_input={"command": command})


def verdicts(root: Path, jobs: list, first_n: int) -> list:
    """The real guard's (exit code, stderr) for every (role, command), in order."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda item: RR.guard_verdict(item[1][0], "", root, item[0],
                                                           bash_event(item[1][0], item[1][1], root, item[0])),
                             [(first_n + n, job) for n, job in enumerate(jobs)]))


def the_cases_through_the_real_guard(root: Path) -> None:
    for (name, command, role, expected), (code, err) in zip(CASES, verdicts(root, [(c[2], c[1]) for c in CASES], 100)):
        got = "PASS" if code == 0 else "REFUSED"
        check_eq(f"K1 {name}: {expected} (exit {code}; {err[-160:]!r})", got, expected)
        if expected == "REFUSED":
            check_in(f"K1 {name}: by the role policy, in its own words", "FACTORY ROLE", err)
            check_in(f"K1 {name}: and the refusal says what a quoted pattern may hold", "quoted pattern", err)
            check_in(f"K1 {name}: and what is refused even quoted", "even quoted", err)
    jobs = [(STRATEGIST, command) for _name, command, _needle in OPAQUE_CASES]
    for (name, command, needle), (code, err) in zip(OPAQUE_CASES, verdicts(root, jobs, 200)):
        check_eq(f"K1 {name}: REFUSED (exit {code})", code, 2)
        check_in(f"K1 {name}: the refusal names the sequence", needle, err)
        check_in(f"K1 {name}: and says the shell reads it differently", DIFFERENTLY, err)
    # the same read as the nested exec_command the host really hooks (cmd, not command): the shape normalize reads
    code, err = RR.guard_verdict(STRATEGIST, REAL, root, 150)
    check_eq(f"K1 the real read as an exec_command event passes ({err[-120:]!r})", code, 0)


# --- the predicate itself: both dialects, the battery, the boundary ----------------------------------------------

ONE_READ = [
    ("a quoted | and ( ) in a regex", "rg -n 'TS-(1|2|3)' f.json"),
    ("a quoted ;", "rg -n 'a;b' f.json"),
    ("a double-quoted |", 'rg -n "a|b" f.json'),
    ("a quoted &", "rg -n 'a&b' f.json"),
    ("a single quote nested in a double-quoted pattern", "rg -n \"a 'b|c' d\" f.json"),
    ("Get-Content with a quoted ;", "Get-Content 'a;b.json'"),
    ("a quote that closes and reopens, in both readings", "Get-Content 'a''b;c'"),
    ("Select-String with a quoted |", "Select-String -Pattern 'x|y' -Path f.json"),
    ("Get-ChildItem", "Get-ChildItem -Recurse qa-factory"),
    ("non-ASCII in a pattern", "rg -n 'Za\u017c\xf3\u0142\u0107|g\u0119\u015bl\u0105' f.json"),
    ("a comment is not a second segment", "rg -n x f.json # ; Remove-Item y"),
    ("AT the boundary: exactly one segment", "ls qa-factory"),
    ("one background & is still one read", "rg x f.json &"),
    ("a huge quoted pattern stays one segment", "rg -n '" + "a|(" * 60000 + "' f.json"),
    ("--pre as the TEXT of a pattern", "rg -n 'x --pre y' f.json"),
    ("the door for a literal paren in a regex: a character class", "rg -n 'foo[(]' f.json"),
    ("a path with a space, quoted",r"Get-Content 'C:\Program Files\x\plan.json'"),
    ("a path with a space, bare: one read", r"Get-Content C:\Program Files\x"),
    ("a one-line here-string opens no block", "Get-Content @'x'@"),
    ("U+2017 just below the typographic-quote range", "rg -n 'a\u2017b' f.json"),
    ("U+201F just above the typographic-quote range", "rg -n 'a\u201fb' f.json"),
    # t-947 F-3: the door for a Windows path with a ( ) or & in it is forward slashes, and the form it sends is one read
    ("F-3 a Windows path with forward slashes and parentheses", "Get-Content 'C:/p/(1)/plan.json'"),
    ("F-3 ... and an ampersand", "rg -n x 'C:/p/&x/f.json'"),
    # t-947 F-1: only a backslash-blank, a paren and a VT/FF before # are banned; a real comment and a quoted # stay reads
    ("F-1 a # inside quotes is text", "rg -n '#tag' f.json"),
    ("F-1 a # after a real blank is a comment", "rg -n x f.json # a) #b"),
    ("F-1 a ) then a blank then # is a comment", "rg -n 'a)' f.json #b"),
    ("F-1 an escaped hash is a word, not a comment, and holds no second command", "rg -n x f.json\\#"),
    # OH3-32 (q15): a backslash before | ; & inside quotes is text in both readings: a regex alternation is one read
    ("OH3-32 q15 a double-quoted regex alternation", 'rg "a\\|b" f'),
    ("OH3-32 a single-quoted regex alternation", "rg -n 'a\\|b' f.json"),
    ("OH3-32 a quoted backslash-semicolon", "rg -n 'a\\;b' f.json"),
]
NOT_ONE_READ = [
    ("empty", ""),
    ("only blanks", "   \t "),
    ("BEYOND the boundary: two segments", "ls a; ls b"),
    ("a pipe", "rg x f.json | sort"),
    ("a real pipeline after a quoted pattern", "rg 'x' f.json | python run_suite.py"),
    ("a pipe in a pattern that is not quoted", 'rg "a "b|c" d" f.json'),
    ("&&", "rg x f.json && rg y f.json"),
    ("||", "rg x f.json || rg y f.json"),
    ("a background & between two commands", "rg x f.json & rg y f.json"),
    ("an unquoted ( )", "rg -n TS-(1|2) f.json"),
    ("a subshell paren", "Get-Content (Remove-Item x)"),
    ("a PowerShell subexpression", "Get-Content @(Remove-Item x)"),
    ("a $ anywhere", "rg -n 'a$' f.json"),
    ("a backtick", "rg -n `whoami` f.json"),
    ("a backtick pair around a pipe", "rg -n `a|b` f.json"),
    ("a PowerShell backtick escape", "Get-Content a`;Remove-Item"),
    ("a redirect >", "rg x f.json > o"),
    ("2>&1", "rg x f.json 2>&1"),
    ("a quoted > stays refused", "rg -n 'a>b' f.json"),
    ("a here-string <", "rg x f.json < o"),
    ("a here-doc", "cat <<EOF\nx\nEOF"),
    ("a multi-line here-string", "Get-Content @'\nx\n'@"),
    ("a CR", "rg x f.json\rRemove-Item y"),
    ("a CR LF (the read guard refuses every line end)", "rg x f.json\r\nRemove-Item y"),
    ("a LF", "rg x f.json\nRemove-Item y"),
    ("a newline inside quotes", "rg 'a\nb' f.json"),
    ("a backslash before a single quote", "rg x \\' ; Remove-Item y ; echo \\'"),
    ("a backslash before a double quote", 'rg "a\\"; Remove-Item y; \\"" f.json'),
    ("a path that ends in a backslash inside quotes", 'Get-Content "C:\\dir\\"'),
    ("smart single quotes hide a ; (rg)", "rg 'x\u2019; Write-Output INJECTED; rg \u2018y' f.json"),
    ("smart double quotes hide a ; (rg)", 'rg "x\u201d; Write-Output INJECTED; rg \u201cy" f.json'),
    ("smart quotes hide a ; (Get-Content)", "Get-Content 'x\u2019; Write-Output INJECTED; Get-Content \u2018y'"),
    ("U+201E at the top of the quote range", "rg \u201ex f.json"),
    ("U+2018 at the bottom of the quote range", "rg \u2018x f.json"),
    ("an unbalanced single quote does not hide a ;", "rg 'a ; Remove-Item y"),
    ("an unbalanced double quote does not hide a ;", 'rg "a ; Remove-Item y'),
    # OH3-32 (q16): the quoted alternation frees nothing behind it, and a quoted backslash-paren is still refused
    ("OH3-32 q16 a quoted alternation, then a second command", 'rg "a\\|b" f; x'),
    ("OH3-32 q16 a quoted alternation, then a redirect", 'rg "a\\|b" > f'),
    ("OH3-32 a quoted alternation, then an unquoted backslash-pipe", 'rg "a\\|b" f\\|g'),
    ("OH3-32 a quoted backslash before a paren stays refused", 'rg "a\\(b" f.json'),
    ("OH3-32 an unquoted backslash-pipe stays refused", "rg -n a\\|b f.json"),
    ("--pre", "rg --pre python x f.json"),
    ("--pre=", "rg --pre=python x f.json"),
    ("--pre-glob", "rg --pre-glob '*.json' x f.json"),
    ("--pre, quoted", "rg '--pre' python x f.json"),
    ("a head that is not a read", "python plan_row.py --row TS-1"),
    ("a read head glued to a path", "rgx -n a f.json"),
    ("a text headed `const` is no read (predicate only; the whole-cell refusal is CX1-1's normalize, pinned in its tests)",
     "const r = await tools.exec_command({});"),
    ("nesting far beyond one level", "rg " + "(" * 5000 + "x" + ")" * 5000 + " f.json"),
]


def the_predicate_and_its_battery() -> None:
    for name, command in ONE_READ:
        check(f"K1b one read: {name}", host_adapter._is_one_plain_read(command), command[:80])
    for name, command in NOT_ONE_READ:
        check(f"K1b not one read: {name}", not host_adapter._is_one_plain_read(command), command[:80])
    check("K1b a non-string is not a read", not host_adapter._is_one_plain_read(None))
    check_in("K1b the refusal of an empty command says so", "empty", host_adapter._read_refusal(""))
    check_eq("K1b a read has no refusal text", host_adapter._read_refusal("rg -n x f.json"), "")


def the_nine_forms_of_g1() -> None:
    for name, command in G1_READ_FORMS:
        why = host_adapter._read_refusal(command)
        check(f"K1c {name}: the read guard refuses it ({command[:60]!r})", bool(why), command[:80])
    for name, command in (("backslash &", G1_READ_FORMS[0][1]), ("backslash (", G1_READ_FORMS[1][1]),
                          ("stop-parsing token", G1_READ_FORMS[8][1])):
        check_in(f"K1c {name}: the refusal names the shell's reading", DIFFERENTLY, host_adapter._read_refusal(command))
    for name, command, needle in F1_COMMENT_FORMS:
        why = host_adapter._read_refusal(command)
        check_in(f"K1c F-1 {name}: refused, and the refusal names the sequence ({command[:50]!r})", needle, why)
        check_in(f"K1c F-1 {name}: and says the shell reads it differently, with the door", DIFFERENTLY, why)


def the_changelog_fragment_names_the_change() -> None:
    # a release folds the fragment into CHANGELOG.md (changelog_assemble.py): after it the text lives there, under the version
    try:
        text, why = harness.release_note(FRAGMENT, NOTE_MARKER), ""
    except ValueError as err:
        text, why = "", str(err)
    check("K5 the release note exists (the fragment, or its CHANGELOG.md block)", bool(text.strip()),
          why or f"neither {FRAGMENT.name} nor a CHANGELOG.md block carrying {NOTE_MARKER!r}")
    for needle in ("_is_one_plain_read", "hooklib.command_segments", "SHELL_OPAQUE_BAN", "TP2-2406", "FB-25",
                   "FB-40", "--pre"):
        check_in(f"K5 the fragment names {needle}", needle, text)
    check("K5 it holds no heading line", not re.search(r"(?m)^#{1,6}(\s|$)", text))
    check("K5 it is free of Cyrillic", not re.search("[\u0400-\u04ff]", text))


def main() -> None:
    the_predicate_and_its_battery()
    the_nine_forms_of_g1()
    root = temp_project("cx15-project-")
    try:
        (root / "qa-factory" / "artifacts" / TICKET / "work").mkdir(parents=True, exist_ok=True)
        the_cases_through_the_real_guard(root)
    finally:
        cleanup(root)
    the_changelog_fragment_names_the_change()
    finish("test_role_policy_reads")


if __name__ == "__main__":
    main()
