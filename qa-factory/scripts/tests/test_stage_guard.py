"""stage_guard.py — the four rules, the stage model, and the fail-open contract.

The rules themselves are exercised against a synthetic project by `stage_guard.py --selftest`
(which this file runs as a subprocess, so a broken guard fails here too); what this file adds
is the shape of stages.json, the role map against the twelve v0 roles, and the promise that a
repository with no story is never touched.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, \
    finish, reader_patched, run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import adapter_forms as AF  # noqa: E402
import hooklib  # noqa: E402
import inject_context as IC  # noqa: E402
import runtime_paths as RP  # noqa: E402
import stage_guard as SG  # noqa: E402

V0_ROLES = [
    "qa-scout", "qa-requirements-tester", "qa-test-strategist", "qa-case-designer",
    "qa-case-critic", "qa-automator", "qa-code-critic", "qa-runner", "qa-failure-analyst",
    "qa-doc-scribe", "qa-bug-reporter", "qa-retro-analyst",
]


# The commands the typed-runner rule actually refused on TP1-15045, copied out of the
# subagent transcripts of session 57cf578c (42 guard refusals over six S5 windows). Nothing
# below could have launched a test outside the typed interface, and four of the six are the
# role LOOKING UP the runner — three of them because the previous refusal had just told it
# the interface had changed.
LIVE_REFUSALS_THAT_RAN_NOTHING = [
    ('python "$R/scripts/run_suite.py" --help 2>&1 | grep -i detail',
     "--help, asked because the refusal said the interface had changed"),
    ('python "$R/scripts/run_suite.py" --task TP1-15045 --detail '
     '"tests.workflow.test_workflow_validate_api::test_validate_by_non_owner_is_rejected"',
     "--detail, which reads the junitxml and never re-runs"),
    ('python $R/scripts/run_suite.py --task TP1-15045 --reparse-block block.json '
     '--mapping map.json',
     "--reparse-block, the remedy execution-lifecycle.md itself prescribes"),
    ("find / -name run_suite.py -not -path '*/node_modules/*' 2>/dev/null | head -3",
     "looking for the runner on disk"),
    ('grep -n "report_test_id" $R/scripts/run_suite.py | head -20',
     "reading the runner's source"),
    ('R=/c/plugins/0.7.6; ls $R/references | head -40; python $R/scripts/run_suite.py --help',
     "a compound command whose only runner call is --help"),
    ('python "$R/scripts/run_suite.py" --template request',
     "--template, which prints the request skeleton and launches nothing"),
]


def part_typed_runner_tax(event: dict) -> None:
    """the guard stops taxing calls that cannot run a test, and a scope of case ids
    stops refusing the instances of those cases."""
    open_dispatch = {"dispatches": {"d-1": {"id": "d-1", "status": "running",
                                            "scope": ["TC-012", "TC-013"]}}}
    for command, why in LIVE_REFUSALS_THAT_RAN_NOTHING:
        check_eq(f"typed runner: {why} is not refused",
                 SG.rule_typed_runner(command, event, "X", open_dispatch), "")
    check("typed runner: an untyped run that DOES launch tests is still refused",
          bool(SG.rule_typed_runner("cd /repo && python run_suite.py --task X --label all",
                                    event, "X", open_dispatch)))

    request = PLUGIN_ROOT / ".stage-guard-scope-request.json"
    try:
        # The five "selected instances exceed the active dispatch scope" refusals: the
        # controller's stage-scope hands out case ids, a RunRequest names instances.
        request.write_text(json.dumps({"dispatch_id": "d-1", "selected_instance_ids": [
            "TC-012::test_validate_per_partition[missing-assistant]",
            "TC-013--test_version_history--deleted-workflow", "TC-012"]}), encoding="utf-8")
        check_eq("typed runner: instances of cases in scope are in scope, in either shape",
                 SG.rule_typed_runner(f'python run_suite.py --request "{request}"',
                                      event, "X", open_dispatch), "")
        request.write_text(json.dumps({"dispatch_id": "d-1",
                                       "selected_instance_ids": ["TC-099::test_other[x]"]}),
                           encoding="utf-8")
        check_in("typed runner: an instance of a case outside the scope still is",
                 "TC-099", SG.rule_typed_runner(f'python run_suite.py --request "{request}"',
                                                event, "X", open_dispatch))
    finally:
        request.unlink(missing_ok=True)

    # The 11 "typed run request is unreadable: FileNotFoundError" refusals: a PreToolUse hook
    # reads the path before the shell writes it. Every role rediscovered this from scratch.
    notes: list = []
    same_command = ('cd /repo && cp "$S/probe-req.json" work/requests/redprobe-1.json && '
                    'python $S/run_suite.py --request work/requests/redprobe-1.json')
    check_eq("typed runner: a request written by the same command is not a refusal",
             SG.rule_typed_runner(same_command, event, "X", open_dispatch, notes), "")
    check("typed runner: it passes with a note instead", bool(notes))
    missing = SG.rule_typed_runner("python run_suite.py --request work/requests/nothing.json",
                                   event, "X", open_dispatch)
    check_in("typed runner: a path nothing writes is still refused", "FileNotFoundError", missing)
    check_in("typed runner: and the refusal names the shape that works", SG.SAME_COMMAND_FIX,
             missing)


RUN = "C:/p/run_suite.py"
LAUNCH = f"python {RUN} --task X"
PARENS = "parentheses around the runner's words"      # the refusal of a command cut at a BARE parenthesis of bash says this
DOOR = "a substitution or a group in its arguments"   # CX1-20: the refusal of a runner launch whose arguments hold a region
DIFFERENTLY = "reads differently from this guard"      # the refusal of a form in SHELL_OPAQUE_BAN says this

# (what the command is, the command, "pass" = "" or "refuse", a phrase the refusal must hold). The expectations are
# the requirements', not the code's (FR-58): FB-25 - a quote makes a `|` text; FB-40 - a flag frees only its own
# command; t-941 G-1 - a cut the shell does not make must never hide a launch (the last column of its table is what
# bash/PowerShell really build: `python -X a\&cat run_suite.py` is ONE command, python's argv holds run_suite.py).
RUNNER_ROWS = [
    ("R1 a quoted | in a reader's pattern is text (single quotes)", f"rg -n 'classname|report_test_id' {RUN}", "pass", ""),
    ("R1 ... in double quotes", f'rg -n "classname|report_test_id" {RUN}', "pass", ""),
    ("R1 ... after an environment assignment", f'$env:PYTHONUTF8="1"; rg -n \'classname|report_test_id\' {RUN}', "pass", ""),
    ("R2 a quoted | then a real ;", f"rg -n 'a|b' {RUN}; {LAUNCH}", "refuse", ""),
    ("R2 ... a real |", f"rg -n 'a|b' {RUN} | {LAUNCH}", "refuse", ""),
    ("R2 ... a real &&", f"rg -n 'a|b' {RUN} && {LAUNCH}", "refuse", ""),
    ("R2 ... a real line end", f"rg -n 'a|b' {RUN}\n{LAUNCH}", "refuse", ""),
    ("R3 a launch through python -c", """python -c "import runpy; runpy.run_path('run_suite.py')" """, "refuse", ""),
    ("R4 a flag frees its own command: --template;", f"python {RUN} --template; Get-Content x", "pass", ""),
    ("R5 ... and not the next one", f"python {RUN} --template req; python {RUN}", "refuse", ""),
    ("R6 --help of an echo frees nothing", f"echo --help; python {RUN}", "refuse", ""),
    ("R7 a flag before a trailing separator", f"python {RUN} --help;", "pass", ""),
    ("R7 no flag before a trailing separator", f"python {RUN};", "refuse", ""),
    ("R9 a single quote nested in a double-quoted reader pattern", f"""rg "a 'b|c' {RUN}" f""", "pass", ""),
    ("R10 an unbalanced quote hides nothing", f"rg 'a|python {RUN} --task X", "refuse", ""),
    ("R11 a backtick pair is cut at its |", f"rg -n `x|y` {RUN}", "refuse", ""),
    ("R12 a here-document is cut at its line ends", f"cat <<EOF\n{{\"run\": \"{RUN}\"}}\nEOF\n{LAUNCH}", "refuse", ""),
    ("R14 an empty command launches nothing", "", "pass", ""),
    ("R18 a flag in a comment frees nothing", f"{LAUNCH} # --help", "refuse", ""),
    ("R18 ... and a comment holding the runner is not run", f"rg -n x f # {LAUNCH}", "pass", ""),
    ("R17 a launch inside a substitution: the walker judges the region as its own slice (CX1-20; was a cut at its parentheses)", f"echo $({LAUNCH})", "refuse", "run_suite.py --request FILE"),
    ("R19 a parenthesized path: refused, with the door", "python (Join-Path $S run_suite.py) --request r.json", "refuse",
     "Join-Path"),
    ("R21 an untyped launch after cd", f"cd /repo && {LAUNCH} --label all", "refuse", ""),
    # t-941 G-1: the nine forms of a launch hidden in a cut the shell does not make
    ("G-1 a\\&cat (bash)", f"python -X a\\&cat {RUN} --task X", "refuse", "backslash before `&`"),
    ("G-1 a\\(cat (bash)", f"python -X a\\(cat {RUN} --task X", "refuse", "backslash before `(`"),
    ("G-1 $(true)cat (bash)", f"python -X $(true)cat {RUN} --task X", "refuse", DOOR),
    ("G-1 $((0))cat (bash)", f"python -X $((0))cat {RUN} --task X", "refuse", DOOR),
    ("G-1 <(true)cat (bash)", f"python -X <(true)cat {RUN} --task X", "refuse", DOOR),
    ("G-1 (@())cat (PowerShell)", f"python -X (@())cat {RUN} --task X", "refuse", PARENS),
    ("G-1 $()cat (PowerShell)", f"python -X $()cat {RUN} --task X", "refuse", DOOR),
    ("G-1 a block comment (PowerShell)", f"python <# #> {RUN} --task X", "refuse", "`<#`"),
    ("G-1 the stop-parsing token (PowerShell)", f"python --% -X a;cat {RUN} --task X", "refuse", "`--%`"),
    ("G-1 control: a real ; is a real separator", f"python -X a;cat {RUN} --task X", "pass", ""),
    ("a lone ( is a parenthesis boundary", f"python -X a(cat {RUN} --task X", "refuse", PARENS),
    ("a lone ) is a parenthesis boundary", f"python -X a)cat {RUN} --task X", "refuse", PARENS),
    # either dialect's refusal is the answer: each reading quotes a ; the other one cuts (the backtick is PowerShell's
    # escape and, in bash, a substitution the tokenizer does not follow)
    ("PowerShell cuts where bash quotes", f"rg a`\"; {LAUNCH}; `\"", "refuse", ""),
    ("bash cuts where PowerShell quotes", f"rg \"a`\" ; {LAUNCH} ; \"`", "refuse", ""),
    # t-936 F-1 and the rest of the class the tokenizer cannot see
    ("F-1 a backslash-quote outside quotes (single)", f"rg \\';{LAUNCH};\\' f", "refuse", "backslash before `'`"),
    ("F-1 a backslash-quote outside quotes (double)", f'rg \\";{LAUNCH};\\" f', "refuse", 'backslash before `"`'),
    ("R15 a backslash-quote inside quotes", f'rg "a\\";{LAUNCH};"', "refuse", 'backslash before `"`'),
    ("a path ending in a backslash, quoted", f'python {RUN} --request "C:\\p\\"', "refuse", 'backslash before `"`'),
    ("a backslash before a line end", f"python -X a\\\ncat {RUN} --task X", "refuse", "a line end"),
    ("a backslash before CR LF", f"python -X a\\\r\ncat {RUN} --task X", "refuse", "a line end"),
    ("a lone CR is a line end to PowerShell and a blank to the tokenizer", f"rg -n x {RUN}\r{LAUNCH}", "refuse",
     "lone carriage return"),
    ("CR LF is an ordinary line end", f"rg -n x {RUN}\r\n", "pass", ""),
    ("CR LF is cut where the shell cuts: the launch behind it is judged", f"rg -n x {RUN}\r\n{LAUNCH}", "refuse", ""),
    ("R16 typographic quotes hide a ;", f"rg \"a\u201d; {LAUNCH}; \"\u201d", "refuse", "typographic quote U+201D"),
    ("U+2017 (below the range) is an ordinary character", f"rg -n 'a\u2017b' {RUN}", "pass", ""),
    ("U+2018 (the bottom of the range)", f"rg -n 'a\u2018b' {RUN}", "refuse", "typographic quote U+2018"),
    ("U+201E (the top of the range)", f"rg -n 'a\u201eb' {RUN}", "refuse", "typographic quote U+201E"),
    ("U+201F (above the range) is an ordinary character", f"rg -n 'a\u201fb' {RUN}", "pass", ""),
    # t-947 F-1: bash keeps a `#` inside a word after `)` that closes a substitution, after a backslash-escaped blank,
    # and after a vertical tab or form feed (not bash blanks) - the tokenizer reads a comment there and cuts the launch
    ("F-1 $(true)# (bash)", f"python -X $(true)# {RUN} --task X", "refuse", "`#` right after `)`"),
    ("F-1 $((0))# (bash)", f"python -X $((0))# {RUN} --task X", "refuse", "`#` right after `)`"),
    ("F-1 <(true)# (bash)", f"python -X <(true)# {RUN} --task X", "refuse", "`#` right after `)`"),
    ("F-1 a backslash-escaped blank before # (bash)", f"python -X a\\ # {RUN} --task X", "refuse",
     "backslash-escaped blank before `#`"),
    ("F-1 a backslash-escaped TAB before # (bash)", f"python -X a\\\t# {RUN} --task X", "refuse",
     "backslash-escaped blank before `#`"),
    ("F-1 a form feed before # (bash)", f"python -X a\x0c# {RUN} --task X", "refuse", "vertical tab or form feed"),
    ("F-1 a vertical tab before # (bash)", f"python -X a\x0b# {RUN} --task X", "refuse", "vertical tab or form feed"),
    ("F-1 control: a real blank before # is a comment, nothing runs after it", f"rg -n x f #{LAUNCH}", "pass", ""),
    ("F-1 control: a # inside quotes is text", f"rg -n '#tag' {RUN}", "pass", ""),
    ("a ban beats a flag", f"python {RUN} --help \u201c", "refuse", DIFFERENTLY),
    ("a ban beats a reader head", f"rg -n \u201c {RUN}", "refuse", DIFFERENTLY),
]

# SHELL_OPAQUE_BAN member by member: the sequence in a sample is found and NAMED (the contract of
# `hooklib.shell_opaque_found`, FR-14), and the sequences that look alike but are ordinary text are not found.
BAN_MEMBERS = [(f"a\\{c}b", f"backslash before `{c}`") for c in ";&|()'\""] + [
    ("a\\\nb", "a backslash before a line end"), ("a\\\r\nb", "a backslash before a line end"),
    ("a <# b #> c", "`<#`"), ("a --% b", "`--%`"),
    ("a\u2018b", "typographic quote U+2018"), ("a\u201cb", "typographic quote U+201C"),
    ("a\u201eb", "typographic quote U+201E"), ("a\rb", "lone carriage return"),
    ("a\\ #b", "a backslash-escaped blank before `#`"), ("a\\\t#b", "a backslash-escaped blank before `#`"),
    ("$(true)#b", "`#` right after `)`"), ("a)#b", "`#` right after `)`"),
    ("a\x0bb", "a vertical tab or form feed"), ("a\x0cb", "a vertical tab or form feed")]
BAN_ORDINARY = ["a;b", "a|b & c (d)", "'a;b' \"a|b\"", r"C:\p\run_suite.py", "a\r\nb", "a\u2017b", "a\u201fb", "a - b -- c %",
                "a < b # c", "a #b", "a) #b", "'#tag'", "a\\#b", "a\\ b", "a(#b", "a\tb c",
                # OH3-32: a backslash before | ; & inside quotes (both readings) is text
                'grep "a\\|b" f', "grep -o 'a\\|b' f", 'echo "a\\\\|b"', "echo 'a\\;b' \"c\\&d\""]


def _nest(levels: int, inner: str) -> str:
    return "echo $(" * levels + inner + ")" * levels


def part_cx20_walker(event: dict) -> None:
    """CX1-20 (t-995 section 6 with L-2/L-3): the battery of the one walker, the answer PER READER. R4 `refuse`/`pass` is
    `rule_typed_runner`; R2 is `_delivery_match`, R3 `_is_commit_shape` (both labels, the dialects are read both). The
    expectations come from the shell's rules and the reviews' verdicts (FR-58), not from a run."""
    import time
    dispatch = {"dispatches": {"d-1": {"id": "d-1", "status": "running", "scope": ["TC-012"]}}}
    L = LAUNCH
    commit = "git commit -m x tests/test_a.py"
    r4 = [  # (row, command, refuse?, needle)
        ("4: four levels around a launch", _nest(4, L), True, ""),
        ("10: a substitution in the arguments of a launch", f"{L} $(true --help >/dev/null)", True, DOOR),
        ("10: ... --mine in a substitution", f"{L} $(true --mine X)", True, DOOR),
        ("10: ... --request built by a substitution", f"python {RUN} $(echo --request r.json)", True, DOOR),
        ("10: ... the request path built by a substitution", f"python {RUN} --request $(echo r.json)", True, DOOR),
        ("11: a quoted substitution in the arguments (main passed; B-433)", f'{L} "$(true --help >/dev/null)"', True, DOOR),
        ("13: a reader inside a substitution is a mention (relief)", f"echo $(rg -n x {RUN})", False, ""),
        ("13: ... and a substitution among the arguments of a reader", f"rg -n x {RUN} $(echo f)", False, ""),
        ("14: a quoted substitution that launches (closed)", f'echo "$({L})"', True, ""),
        ("14: ... a backtick pair that launches (closed)", f"echo `{L}`", True, ""),
        ("15: a quoted reader in a quoted substitution", 'echo "$(rg -n x run_suite.py)"', False, ""),
        ("16: a backtick region cut at its |", f"rg -n `x|y` {RUN}", True, ""),
        ("19: the name built by a substitution", "python C:/p/run_sui$(true)te.py --task X", True, DOOR),
        ("19: ... by an empty quoted run", 'python C:/p/run_sui""te.py --task X', True, ""),
        ("19: ... by a backslash", "python C:/p/run_sui\\te.py --task X", True, ""),
        ("20: find -exec of a launch", f"find . -name x -exec {L} {{}} +", True, ""),
        ("20: find -execdir", f"find . -name x -execdir {L} {{}} +", True, ""),
        ("20: find -ok", f"find . -name x -ok {L} {{}} +", True, ""),
        ("20: find -okdir (L-2 M-5)", f"find . -name x -okdir {L} {{}} +", True, ""),
        ("20: xargs is no reader (= main)", f"find . -name x | xargs {L}", True, ""),
        ("20: a program built by a substitution", f"$(echo python) {RUN} --task X", True, DOOR),
        ("20: control: find -exec of a READER runs nothing", "find . -name run_suite.py -exec grep -n def {} +", False, ""),
        ("20: awk system() runs a program", f"awk 'BEGIN {{ system(\"x\") }}' {RUN}", True, ""),
        ("20: control: awk without system()", f"awk 'NR<20' {RUN}", False, ""),
        ("20: control: sed -n with a range", f"sed -n 1,40p {RUN}", False, ""),
        ("20: control: rg -e is a pattern, not a program", f"rg -n -e foo {RUN}", False, ""),
        ("20: rg --pre runs a program", f"rg --pre python x {RUN}", True, ""),
        ("23: a name found by a quoted substitution", 'python "$(find . -name run_suite.py | head -1)" --task X', True, DOOR),
        ("23: ... unquoted", "python $(find . -name run_suite.py) --task X", True, DOOR),
        ("23: ... echoed", f"python $(echo {RUN}) --task X", True, DOOR),
        ("28: a flag frees the slice before the region rule", f"python {RUN} --help $(true)", False, ""),
        ("NM-3: a quoted mention in a search is no launch", 'git log --grep "run_suite" -n 5', False, ""),
        ("NM-3: ... git grep", 'git grep "run_suite" scripts', False, ""),
        ("34: an unpaired $( runs to the end", f"echo $({L}", True, ""),
        ("34: ... $((", f"echo $(( {L}", True, ""),
        ("34: ... <(", f"echo <({L}", True, ""),
        ("35: a region across a cut", f"echo $(rg x f; {L}", True, ""),
        ("35: a comment in a region closes it early (the safe side)", f"echo $(true # )\n{L})", True, ""),
        ("36: a backtick pair in double quotes", f'echo "`{L}`"', True, ""),
        ("36: a CRLF in a region", f"echo $(rg x f\r\n{L})", True, ""),
        ("37: PowerShell quoted subexpression", f'Write-Output "$({L})"', True, ""),
        ("37: single quotes hold no region", f"rg -n '$({L})' f", False, ""),
        ("38: bash -c in bash -c", f"bash -c \"bash -c '{L}'\"", True, ""),
        ("40: empty and blank commands", "", False, ""),
        ("40: ... blanks only", "   ", False, ""),
        ("G-1: PowerShell group", f"python -X (@())cat {RUN} --task X", True, ""),
        ("17: single parentheses keep the door", f"({L})", True, ""),
        ("17: ... a reader before them", f"rg -n x ({L})", True, ""),
    ]
    for name, command, refuse, needle in r4:
        message = SG.rule_typed_runner(command, event, "X", dispatch)
        check_eq(f"CX1-20 R4 {name}", bool(message), refuse)
        if needle and message:
            check_in(f"CX1-20 R4 {name}: the refusal names the door", needle, message)
    check_eq("CX1-20 R4 the region refusal names the literal way (FR-1)", "run_suite.py --request FILE" in SG.REGION_REFUSAL
             and "Join-Path" in SG.REGION_REFUSAL, True)
    for text in ("", "   ", None):
        check_eq(f"CX1-20 R4 no command: {text!r}", SG.rule_typed_runner(text, event, "X", dispatch), "")
    # magnitude and the 1 MB command: no exception, linear (the ratio of 10x the input is far under 25x the time)
    def took(text: str) -> float:
        started = time.perf_counter()
        message = SG.rule_typed_runner(text, event, "X", dispatch)
        return time.perf_counter() - started, bool(message)
    (t_small, hit_small), (t_big, hit_big) = took("$(" * 20000 + L), took("$(" * 200000 + L)
    check_eq("CX1-20 33: 200 000 openers then a launch: refused, no exception", (hit_small, hit_big), (True, True))
    check("CX1-20 33: ... and 10x the input costs under 25x the time", t_big / max(t_small, 1e-6) < 25, f"{t_big:.2f}s / {t_small:.2f}s")
    check_eq("CX1-20 33: bare openers, no launch: no exception", [took("<(" * 200000)[1], took("$(" * 200000)[1]], [False, False])
    check_eq("CX1-20 39: ~1 MB of commands then a launch is refused", took("rg x f; " * 125000 + L)[1], True)
    # R2 and R3: the answer per reader
    def delivery(text: str) -> bool:
        return SG._delivery_match(text, None) is not None

    def commits(text: str, tool: str = "Bash") -> bool:
        return SG._is_commit_shape(text, {}, {"tool_name": tool})
    gh = "gh pr create --fill"
    rows = [  # (row, command, R2 delivery?, R3 commit?)
        ("3/32: four levels", _nest(4, gh), True, False), ("3: four levels around a commit", _nest(4, commit), False, True),
        ("7/32: PowerShell group", f"Write-Output ({gh})", True, False),
        ("7: PowerShell group around a commit", f"Write-Output ({commit})", False, True),
        ("27: a glued PowerShell group", f"Write-Output x({commit})", False, True),
        # M12 (review t-1071): the BASH reading joins `\(` into the word (no cut, no commit in it), so only the PowerShell
        # group `x\(...)` shows the commit - a PowerShell reader that stopped opening a glued group would lose this row
        ("27: ... behind a backslash (bash joins it, only the group shows the commit)", f"Write-Output x\\({commit})", False, True),
        ("32: a quoted substitution", f'echo "$({gh})"', True, False),
        ("22: a Windows path ending in a backslash, then a commit", f"git status C:\\p\\\n{commit}", False, True),
        ("29: a substitution among the arguments of a commit", "git commit -m $(cat msg) tests/test_a.py", False, True),
        ("31: a block comment first", f"<# x #> {gh}", True, False), ("31: ... before a commit", f"<# x #> {commit}", False, True),
        ("B-1: a substitution as the program", "$(echo gh) pr create --fill", True, False),
        ("B-1: a backtick pair as the program", "`echo gh` pr create --fill", True, False),
        ("B-1: ... holding the program and a word", "`echo gh pr` create --fill", True, False),
        ("B-1: ... holding printf", "`printf g; printf h` pr create --fill", True, False),
        ("B-1: a substitution between git and the verb", "git $(true) commit -m x tests/test_a.py", False, True),
        # R2 is True here too, on purpose (I-SAFE): `$(a)` may print `glab mr` and `$(b)` `create` - a delivery to bash
        ("B-1: a run of them", "git $(a) $(b) commit -m x tests/test_a.py", True, True),
        ("NM-4: a substitution as a subcommand", "gh $(echo pr) create --fill", True, False),
        ("NM-4: a substitution as git", f"$(echo git) {commit[4:]}", False, True),
        ("NM-4: a substitution as the verb", "git $(echo commit) -m x tests/test_a.py", False, True),
        ("M-4: a name built by a substitution (R2)", "gh pr cre$(true)ate --fill", True, False),
        ("M-4: ... (R3)", "git com$(true)mit -m x tests/test_a.py", False, True),
        ("control: a date substitution", "echo $(date) done", False, False), ("control: git $(true) status", "git $(true) status", False, False),
        ("control: gh pr view with a substitution", "gh pr view $(gh pr list -q .x) --web", False, False),
        ("control: glab mr list --author=$(whoami)", "glab mr list --author=$(whoami)", False, False),
        ("t-1000 row 6: bash joins the escaped quotes", "echo a\\' ; gh pr create ; echo b\\'", True, False),
        ("t-1000 row 7: an escaped blank keeps the #", "echo a\\ #; git commit -m x tests/test_a.py", False, True),
        ("control: empty", "", False, False), ("control: blanks", "   ", False, False),
    ]
    for name, command, want_delivery, want_commit in rows:
        check_eq(f"CX1-20 R2 {name}", delivery(command), want_delivery)
        check_eq(f"CX1-20 R3 {name} (Bash label)", commits(command), want_commit)
        check_eq(f"CX1-20 R3 {name} (PowerShell label: the label decides nothing)", commits(command, "PowerShell"), want_commit)
    check_eq("CX1-20 R2/R3: None", (delivery(None), commits(None)), (False, False))
    # Q-5 (FR-1): the refusal names the command the ROLE wrote - never `glab mr create` for a `gh` command
    check_eq("CX1-20 Q-5: the delivery a refusal names is the one written",
             [SG._delivery_match(c, None)[0] for c in ("gh pr create --fill", "gh $(x) create --fill", "gh pr $(echo create) --fill",
                                                      "gh pr cre$(true)ate --fill", "`echo gh pr` create --fill",
                                                      "$(echo glab) mr create --fill")],
             ["gh pr create", "gh ...", "gh ...", "gh pr create", "`echo gh pr` create --fill", "$(echo glab) mr create --fill"])
    check_eq("CX1-20 R2 the gate: a text with a mark is admitted whole (the cleaned view), without it needs the words",
             (AF.could_be_in("gh pr create", "gh pr cre$(true)ate", "gh pr cre$(true)ate"), AF.could_be_in("gh pr create", "ls"),
              AF.could_be_in("gh pr create", "$(echo gh) pr create", "$(echo gh) pr create")), (True, False, True))
    # the hook path (F-1): a LIVE `guard_pre_tool.stage_check`. `stage_guard.check` is replaced by a recorder that judges the
    # RAW command the way `check_command` does (R2/R3 shapes and the typed-runner rule); `needs_stage_guard` by a wrapper
    # that records what the hook hands the gate. The gate must be handed the command as the role wrote it - not the output
    # of `command_text_parts`, which cuts `$(` into `$` + LF (B-434, queued) - so a glue row reaches the check and is blocked.
    import guard_pre_tool as G
    gate_saw, check_saw = [], []

    def recorder(ev: dict) -> int:
        raw = ev["tool_input"]["command"]
        raw = " ".join(raw) if isinstance(raw, list) else raw
        check_saw.append(raw)
        return 2 if SG.command_shapes(raw, {}, ev) or SG.rule_typed_runner(raw, event, "X", dispatch) else 0

    def gate(command: str, cfg=None) -> bool:
        gate_saw.append(command)
        return real_gate(command, cfg)

    def through_the_hook(command, tool: str = "Bash") -> tuple:
        gate_saw.clear(), check_saw.clear()
        blocked = G._blocked(G.stage_check, {"tool_name": tool, "tool_input": {"command": command}}, {}) is not None
        return (len(gate_saw), len(check_saw), blocked)

    real_check, real_gate = SG.check, SG.needs_stage_guard
    SG.check, SG.needs_stage_guard = recorder, gate
    try:
        for name, command in (("git com$(true)mit", "git com$(true)mit -m x tests/test_a.py"),
                              ("git $(true) commit", "git $(true) commit -m x tests/test_a.py"),
                              ("run_sui$(true)te.py", "python C:/p/run_sui$(true)te.py --task X"),
                              ("run_sui\"\"te.py", 'python C:/p/run_sui""te.py --task X'),
                              ("run_sui\\te.py", "python C:/p/run_sui\\te.py --task X"),
                              ("a backtick as gh", "`printf g; printf h` pr create --fill"),
                              ("git (echo commit)", "git (echo commit) -m x tests/test_a.py")):
            check_eq(f"CX1-20 hook path: `{name}` reaches the check through the live stage_check and is blocked",
                     through_the_hook(command), (1, 1, True))
            check_eq(f"CX1-20 hook path: ... the gate and the check were handed the RAW command ({name})",
                     (gate_saw, check_saw), ([command], [command]))
        check_eq("CX1-20 hook path: an ordinary command reads nothing (gate asked, check never reached)",
                 [through_the_hook(c) for c in ("ls -la", "git status")], [(1, 0, False), (1, 0, False)])
        # the GATE only: this recorder joins a list itself, so it says nothing of what the real check reads - that is
        # `part_cx20_round3`'s pin, on the real `check` (Q-9 of review t-1082)
        check_eq("CX1-20 hook path: a Codex argv list is joined into the one line the GATE reads",
                 (through_the_hook(["git", "commit", "-m", "x", "tests/test_a.py"]), gate_saw),
                 ((1, 1, True), ["git commit -m x tests/test_a.py"]))
        check_eq("CX1-20 hook path: a tool that is no shell is not the hook's business",
                 through_the_hook("git commit -m x tests/test_a.py", "Read"), (0, 0, False))
    finally:
        SG.check, SG.needs_stage_guard = real_check, real_gate
    check_eq("CX1-20 hook path: the wrappers are gone", (SG.check is real_check, SG.needs_stage_guard is real_gate), (True, True))
    check_eq("CX1-20 hook path: needs_stage_guard itself is True for the cutter's text and False for an ordinary command",
             [SG.needs_stage_guard(G.command_text_parts("git com$(true)mit -m x tests/test_a.py")["exec"], {}), SG.needs_stage_guard("ls -la", {})],
             [True, False])


def part_cx20_round3() -> None:
    """Review t-1082 (the re-check of the CX1-20 fix round): N-1 - a backtick pair inside an unclosed `"` whose partner is
    an escaped LAST character left a stale limit after the E8 rewind, a `#` of the re-read ended there and the walker
    raised; `check` swallowed it as "fail-open". Q-9 - `check_command` read `str(list)` for an argv list. The expected
    values are the shell's: after the rewind the text reads as the text without the dropped quote (E8), so `#` starts a
    comment and what stands before it is a command; an argv list is the line the host's shell runs."""
    import guard_pre_tool as G
    tick, bs = chr(96), chr(92)
    tail = " #" + tick + " " + bs + tick
    for name, text in (("a quoted heredoc delimiter, an odd quote in the body", "cat <<'EOF'\n\"\nEOF\n{X}" + tail),
                       ("an unquoted delimiter, ${HOME} and an odd quote in the body", 'cat <<EOF\n${HOME} "\nEOF\n{X}' + tail)):
        check_eq(f"N-1 R3: {name}, a commit before the comment: a commit, no exception",
                 SG._is_commit_shape(text.replace("{X}", "git commit -m x tests/test_a.py"), {}, {"tool_name": "Bash"}), True)
        check_eq(f"N-1 R3 control: {name}, `git status` there: no commit",
                 SG._is_commit_shape(text.replace("{X}", "git status"), {}, {"tool_name": "Bash"}), False)
    # a walker that raises: the real `check` DENIES with the door (never the fail-open of an ordinary crash)
    err = io.StringIO()

    def boom(self, *args, **kwargs):
        raise IndexError("synthetic walker failure")

    # SC1-5b: `reader_patched` reads from an empty cache (a text read earlier is a cache hit that never reaches the patched reader)
    with reader_patched("_code", lambda real: boom) as real_code:
        with contextlib.redirect_stderr(err):
            code = SG.check({"tool_name": "Bash", "cwd": str(PLUGIN_ROOT), "tool_input": {"command": "git commit -m x tests/test_a.py"}})
    check_eq("N-1 a walker exception inside check is a DENY (2), not the fail-open 0", code, 2)
    check_in("N-1 ... the door names the guard's failure and the way on", "could not read this command (IndexError: synthetic walker failure)",
             err.getvalue())
    check_in("N-1 ... and says what to do", "split it into several simpler commands", err.getvalue())
    check_not_in("N-1 ... never `fail-open`", "fail-open", err.getvalue())
    check_eq("N-1 the walker is restored", hooklib._Reader._code is real_code, True)
    # Q-9: what the REAL check reads for a Codex argv list - recorded at `command_shapes`, the first reader of the words
    seen, real_shapes = [], SG.command_shapes

    def shapes(command, cfg=None, event=None):
        seen.append(command)
        return real_shapes(command, cfg, event)

    SG.command_shapes = shapes
    try:
        argv = ["git", "commit", "-m", "x", "tests/test_a.py"]
        with contextlib.redirect_stderr(io.StringIO()):
            SG.check({"tool_name": "Bash", "cwd": str(PLUGIN_ROOT), "tool_input": {"command": argv}})
            handed_direct = list(seen)
            seen.clear()
            G._blocked(G.stage_check, {"tool_name": "Bash", "cwd": str(PLUGIN_ROOT), "tool_input": {"command": argv}}, {})
            handed_hook = list(seen)
    finally:
        SG.command_shapes = real_shapes
    line = "git commit -m x tests/test_a.py"
    check_eq("Q-9 the real check reads an argv list as its joined line (never str(list)), direct and through the hook",
             (handed_direct, handed_hook), ([line], [line]))
    check_eq("Q-9 ... and that line is a commit (str(list) is none)", (SG.command_shapes(line, {}, {}), SG.command_shapes(str(argv), {}, {})),
             (["commit"], []))


def part_one_tokenizer(event: dict) -> None:
    """The runner guard reads the command with the one tokenizer, both dialects, and refuses whole what the tokenizer
    cannot see as the shell does (CX1-5). The battery is the requirements' (FB-25, FB-40, t-936 F-1, t-941 G-1)."""
    dispatch = {"dispatches": {"d-1": {"id": "d-1", "status": "running", "scope": ["TC-012"]}}}
    for name, command, verdict, needle in RUNNER_ROWS:
        message = SG.rule_typed_runner(command, event, "X", dispatch)
        check_eq(f"one tokenizer: {name}: {verdict}", "refuse" if message else "pass", verdict)
        if needle:
            check_in(f"one tokenizer: {name}: the refusal says why and how", needle, message)
    check_in("one tokenizer: a refusal of the ban names the runner's own form as the door", "run_suite.py --request FILE",
             SG.rule_typed_runner(f"rg \u201c {RUN}", event, "X", dispatch))
    # the `spans` view of the tokenizer (FR-14): the first two members are today's answer, the slices run 1:1 with the
    # segments, in order, never overlapping, and hold neither a separator nor a comment
    for name, command, _verdict, _needle in RUNNER_ROWS:
        for dialect in ("bash", "powershell"):
            segments, regions, spans = hooklib.command_segments(command, dialect, spans=True)
            check_eq(f"spans: {name} [{dialect}]: the first two members equal the plain answer",
                     (segments, regions), hooklib.command_segments(command, dialect))
            check_eq(f"spans: {name} [{dialect}]: slices run 1:1 with segments", len(spans), len(segments))
            check(f"spans: {name} [{dialect}]: slices are ordered and disjoint",
                  all(a[1] <= b[0] for a, b in zip(spans, spans[1:])) and all(0 <= s <= e <= len(command) for s, e in spans))
            check(f"spans: {name} [{dialect}]: a slice holds no comment start",
                  all(not command[s:e].lstrip().startswith("#") for s, e in spans))
    check_eq("spans: a comment ends its slice", [c[s:e] for c in ["rg x # (y) ; z"] for s, e in
                                                 hooklib.command_segments(c, "bash", spans=True)[2]], ["rg x "])
    check_eq("spans: an empty text has no slices", hooklib.command_segments("", "bash", spans=True), ([], [], []))
    for sample, needle in BAN_MEMBERS:
        what, door = hooklib.shell_opaque_found(sample)
        check_in(f"ban member {sample!r} is found and named", needle, what)
        check(f"ban member {sample!r} comes with a door", bool(door), door)
    # t-947 F-3: the door of a backslash names forward slashes for a Windows path, and the form it sends passes
    check_in("ban: the backslash door names forward slashes for a Windows path", "forward slashes (C:/p/(1)/x)",
             hooklib.shell_opaque_found("Get-Content 'C:\\p\\(1)\\plan.json'")[1])
    check_eq("ban: ... and the path the door sends is ordinary", hooklib.shell_opaque_found("Get-Content 'C:/p/(1)/plan.json'"),
             ("", ""))
    for sample in BAN_ORDINARY:
        check_eq(f"ban: {sample!r} is ordinary text, not found", hooklib.shell_opaque_found(sample), ("", ""))
    for sample in ("", None):
        check_eq(f"ban: {sample!r} holds nothing", hooklib.shell_opaque_found(sample), ("", ""))
    # position: no open dispatch means no reading and no refusal, even of a banned form (R22)
    for quiet in ({}, {"dispatches": {"d-1": {"id": "d-1", "status": "done"}}}):
        check_eq("one tokenizer: R22 without a running dispatch a banned command is not touched",
                 SG.rule_typed_runner(f"{LAUNCH} \u201c", event, "X", quiet), "")
    # the request written in an early slice and used in a later one (R8), one note even though both dialects read it
    notes: list = []
    check_eq("one tokenizer: R8 a request written by an earlier slice is a note, not a refusal",
             SG.rule_typed_runner(f"cp $S/probe.json work/requests/r8.json; python {RUN} --request work/requests/r8.json",
                                  event, "X", dispatch, notes), "")
    check_eq("one tokenizer: R8 ... and the note is said once", len(notes), 1)
    # the controller is read once for a command of three slices (R22 position)
    reads: list = []
    real_read = SG.read_json
    SG.read_json = lambda path: reads.append(path) or dispatch
    try:
        SG.rule_typed_runner(f"rg a f; rg b f; {LAUNCH}", event, "X")
    finally:
        SG.read_json = real_read
    check_eq("one tokenizer: R22 controller.json is read once for a command of three slices", len(reads), 1)
    check("one tokenizer: _segments, the regex splitter, is gone", not hasattr(SG, "_segments"))


def desktop_dispatch(task_name: str, **extra) -> dict:
    """What Codex 0.155.1 desktop actually sends (TP2-2556, 23.09, raw event):
    `spawn_agent` with `task_name`, `fork_turns` and a `message` that is an encrypted
    `gAAAA…` string. The factory has always known those messages are opaque
    (native_context.py); what it did not know is that the task name is then the ONLY
    readable carrier of the ticket, and that its slug spelling is not `TICKET-1234`."""
    opaque = "gAAAAABo" + "x" * 64
    return dict({"tool_name": "Agent",
                 "tool_input": {"subagent_type": "qa-automator", "task_name": task_name,
                                "prompt": opaque},
                 "_qa_host": {"name": "collaboration.spawn_agent",
                              "input": {"task_name": task_name, "fork_turns": "none",
                                        "message": opaque}}}, **extra)


CLOSED_AT = "2026-09-21T10:00:00+00:00"


def part_resume_ids() -> None:
    """Rule 6 reads the agent id wherever the factory learns it (TP2-2553).

    A role stopped, the orchestrator tried to resume it, and this rule refused: only
    `stage_done.py --agent-id` ever wrote an agent_id into pipeline.json and nobody called it.
    The id the host's task notification returns is now kept on the controller's dispatch
    record the moment it is known, and a stage's last one is projected into pipeline.json
    afterwards — so both places answer, and the refusal that is left names `recover`.
    """
    root = temp_project("qa-factory-resume-")
    task_root = root / "qa-factory" / "artifacts" / "TP2-2553"
    (task_root / "state").mkdir(parents=True, exist_ok=True)

    def resume(target: str) -> int:
        return SG.check_resume({"tool_name": "SendMessage", "cwd": str(root),
                                "tool_input": {"to": target, "task_id": "TP2-2553"}})

    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            (task_root / "pipeline.json").write_text(json.dumps(
                {"ticket": "TP2-2553", "stages": {"S5": {"status": "running"}}}),
                encoding="utf-8")
            check_eq("resume: no id anywhere is refused", resume("agent-77"), 2)
            check_in("resume: and the refusal says where the id comes from",
                     "task notification", SG.LAST_DENIAL["message"])
            check_in("resume: and how to go on without one",
                     "--operation recover", SG.LAST_DENIAL["message"])

            # The controller holds it before pipeline.json projects it — which is the whole
            # window in which a stopped role has to be resumed.
            (task_root / "state" / "controller.json").write_text(json.dumps(
                {"dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1",
                                                      "status": "blocked",
                                                      "agent_id": "agent-77"}}}), encoding="utf-8")
            check_eq("resume: an id the controller's dispatch record carries is resumable",
                     resume("agent-77"), 0)
            check_eq("resume: an id nobody ran is still refused", resume("agent-99"), 2)
            check_in("resume: and the refusal lists what the story does know",
                     "agent-77", SG.LAST_DENIAL["message"])
    finally:
        cleanup(root)


def part_resume_no_recipient() -> None:
    """A SendMessage that addresses no agent is not a resume (M13).

    The Codex host's send_input / followup_task shapes (and a send_message to anyone but /root) are normalized to SendMessage with
    `recipient` = id or target or "", so a message with no addressee reached `check_resume` and
    was refused as "resuming '(no id)'" whenever a story was identifiable. The allow is concluded
    only after every alias was read: a recipient named under ANY alias that this story never ran
    is still a refusal."""
    root = temp_project("qa-factory-resume-none-")
    task_root = root / "qa-factory" / "artifacts" / "TP2-2553"
    (task_root / "state").mkdir(parents=True, exist_ok=True)

    def send(tool_input: dict, raw_input: dict | None = None) -> int:
        event = {"tool_name": "SendMessage", "cwd": str(root),
                 "tool_input": dict(tool_input, task_id="TP2-2553")}
        if raw_input is not None:
            event["_qa_host"] = {"name": "collaboration.send_message", "input": raw_input,
                                 "codex": True}
        return SG.check_resume(event)

    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            (task_root / "pipeline.json").write_text(json.dumps(
                {"ticket": "TP2-2553", "stages": {"S5": {"status": "running"}}}),
                encoding="utf-8")
            (task_root / "state" / "controller.json").write_text(json.dumps(
                {"dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1",
                                                      "status": "blocked",
                                                      "agent_id": "agent-77"}}}), encoding="utf-8")
            check_eq("resume: a message that names no recipient is allowed",
                     send({"content": "ping"}), 0)
            check_eq("resume: the Codex shape with an empty normalized recipient is allowed",
                     send({"recipient": "", "content": "ping"}, {"message": "ping"}), 0)
            check_eq("resume: a whitespace-only recipient is no recipient",
                     send({"to": "   ", "recipient": "\t"}), 0)
            check_eq("resume: a recorded recipient is still allowed",
                     send({"to": "agent-77"}), 0)
            check_eq("resume: an unknown recipient in `to` is still refused",
                     send({"to": "agent-99"}), 2)
            check_in("resume: and the refusal names it", "agent-99", SG.LAST_DENIAL["message"])
            check_eq("resume: an unknown recipient in `recipient` is still refused",
                     send({"recipient": "agent-98"}), 2)
            check_eq("resume: an unknown recipient in `agent_id` is still refused",
                     send({"agent_id": "agent-97"}), 2)
            check_eq("resume: an unknown recipient only in the raw host `id` is still refused",
                     send({"content": "ping"}, {"id": "agent-96", "message": "ping"}), 2)
            check_in("resume: and the refusal names the raw id", "agent-96",
                     SG.LAST_DENIAL["message"])
            check_eq("resume: an unknown recipient only in the raw host `target` is still refused",
                     send({}, {"target": "agent-95"}), 2)
            check_eq("resume: a recorded recipient only in the raw host `id` is allowed",
                     send({}, {"id": "agent-77"}), 0)

            # Every alias is a recipient: no ordering of them may hide an unrecorded one.
            (task_root / "state" / "controller.json").write_text(json.dumps(
                {"dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1",
                                                      "status": "blocked",
                                                      "agent_id": "agent-77"},
                                "S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1",
                                                        "status": "blocked",
                                                        "agent_id": "agent-78"}}}),
                encoding="utf-8")
            check_eq("resume: raw `id` unknown beside a recorded `to` is refused",
                     send({"to": "agent-77", "recipient": "agent-77"},
                          {"id": "agent-99", "to": "agent-77"}), 2)
            check_in("resume: and the refusal names the unknown one", "agent-99",
                     SG.LAST_DENIAL["message"])
            check_eq("resume: an unknown `to` beside a recorded raw `id` is refused",
                     send({"to": "agent-99"}, {"id": "agent-77"}), 2)
            check_eq("resume: an unknown `agent_id` beside a recorded `to` is refused",
                     send({"to": "agent-77", "agent_id": "agent-94"}), 2)
            check_eq("resume: the same recorded value under two aliases is allowed",
                     send({"to": "agent-77", "recipient": "agent-77"}), 0)
            check_eq("resume: two different recorded agents are both allowed",
                     send({"to": "agent-77"}, {"id": "agent-78"}), 0)
            check_eq("resume: all-blank aliases are no recipient",
                     send({"to": " ", "recipient": "", "agent_id": "\n"},
                          {"id": "  ", "target": ""}), 0)

            (task_root / "state" / "controller.json").unlink()
            check_eq("resume: with nothing recorded, two recipients keep the 'no agent_id' refusal",
                     send({"to": "agent-77"}, {"id": "agent-78"}), 2)
            check_in("resume: and it is that refusal", "no agent_id is recorded",
                     SG.LAST_DENIAL["message"])
            check_eq("resume: with nothing recorded, a recipient keeps the 'no agent_id' refusal",
                     send({"to": "agent-99"}), 2)
            check_in("resume: and it is that refusal", "no agent_id is recorded",
                     SG.LAST_DENIAL["message"])
            check_eq("resume: with nothing recorded, a message with no recipient is allowed",
                     send({"content": "ping"}), 0)
    finally:
        cleanup(root)


def part_story_identity() -> None:
    """which story a dispatch is about when the host cannot put an id in its text, and what
    the refusal says when none of the five answers works (I-90)."""
    root = temp_project("qa-factory-identity-")
    arts = root / "qa-factory" / "artifacts"

    def story(name: str, archived: bool = False, closed: bool = False) -> None:
        folder = arts / name
        folder.mkdir(parents=True, exist_ok=True)
        data = {"ticket": name, "stages": {"S1": {"status": "running"}}}
        if archived:
            data["archived"] = True
        if closed:
            # By hand, not through Package D's writers: a reader must cope with a story
            # written by any version that ever shipped, and with the ghost tail 2534 had —
            # S8 done and gate B approved with a stage still `running` beside them.
            data["stages"]["S8"] = {"status": "done", "finished": CLOSED_AT}
            data["gates"] = {"A": {"decision": "approve"},
                             "B": {"decision": "approve", "at": CLOSED_AT}}
            data["closed_at"] = CLOSED_AT
        (folder / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")

    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            story("TP2-2534")
            story("TP2-2556")
            check_eq("identity: the desktop task name picks the story it names",
                     SG.requested_ticket(desktop_dispatch("qa_automator__tp2_2556_s5_11")),
                     "TP2-2556")
            check_eq("identity: a task name matching no story leaves it ambiguous",
                     SG.requested_ticket(desktop_dispatch("qa_scout__something_else")), "")

            # The unblock the plan had to reach for by hand: 2534 was finished and still
            # `running`, so the "single running story" fallback saw two.
            story("TP2-2534", archived=True)
            check_eq("identity: an archived story is not a candidate",
                     SG.requested_ticket(desktop_dispatch("qa_scout__something_else")),
                     "TP2-2556")
            story("TP2-2534")

            os.environ["QA_FACTORY_TASK"] = "TP2-2556"
            try:
                check_eq("identity: a person's word in QA_FACTORY_TASK names the story",
                         SG.requested_ticket(desktop_dispatch("qa_scout__something_else")),
                         "TP2-2556")
                os.environ["QA_FACTORY_TASK"] = "TP2-9999"
                check_eq("identity: and never invents one that has no artifacts",
                         SG.requested_ticket(desktop_dispatch("qa_scout__something_else")), "")
            finally:
                os.environ.pop("QA_FACTORY_TASK", None)

            # An id the person DID pass cannot be answered with "pass the explicit task_id".
            named = desktop_dispatch("qa_automator__x", task_id="TP2-9999",
                                     host_binding=str(root / "binding.json"))
            check_eq("identity: an explicit id with no story here is refused", SG.check(named), 2)
            message = SG.LAST_DENIAL["message"]
            check_in("identity: and the refusal says exactly that",
                     "the explicit task id names no story", message)
            check_not_in("identity: not 'pass the explicit task_id'", "pass the explicit", message)
            check_in("identity: it names where the id came from", "host binding", message)
            check_in("identity: and the root it looked under", str(arts.resolve()), message)

            # The ticketless denial — the only one whose diagnosis lives entirely in the
            # event, and the only one 0.7.11 never wrote down.
            nameless = desktop_dispatch("qa_scout__something_else")
            nameless["cwd"] = str(root)
            check_eq("identity: an unidentifiable dispatch is refused", SG.check(nameless), 2)
            IC.note_denial(nameless, "", "S5", "qa-automator", SG.LAST_DENIAL["message"])
            denials = root / "qa-factory" / "state" / "dispatch-denials.jsonl"
            check("identity: and written to the project-level denials file", denials.is_file())
            row = json.loads(denials.read_text(encoding="utf-8").splitlines()[-1])
            check_eq("identity: with no ticket", row.get("ticket"), None)
            check_eq("identity: with the host's own argument keys", row.get("host_input_keys"),
                     ["fork_turns", "message", "task_name"])
            check_eq("identity: and the normalized ones", row.get("tool_input_keys"),
                     ["prompt", "subagent_type", "task_name"])
            check_eq("identity: and the task name", row.get("task_name"),
                     "qa_scout__something_else")
            check_not_in("identity: never the message body, which may be opaque or huge",
                         "gAAAAABo", denials.read_text(encoding="utf-8"))
            check_in("identity: with the reason", "task identity is missing or ambiguous",
                     row.get("reason") or "")

            part_closed_story(root, arts, story)
    finally:
        cleanup(root)


def part_closed_story(root, arts, story) -> None:
    """The ghost tail of a closed story (I-92), against the two stories of the incident.

    TP2-2534 went S1-S8 with both gates, its MR merged and the suite green, and one
    stage left `running` made it "the second running story" for two days: every Codex
    desktop dispatch of the live 2556 was refused as ambiguous. Closure removes a story
    from the GUESS only — a dispatch that names it still resolves, which is what keeps S9
    working on a closed story.
    """
    story("TP2-2534", closed=True)   # closed, and still carrying S1 running
    story("TP2-2556")                # the live one
    nameless = desktop_dispatch("qa_scout__something_else")
    check_eq("closed: a closed story with a ghost running stage is not a candidate",
             SG.requested_ticket(nameless), "TP2-2556")
    facts = SG.resolve_ticket(nameless)[1]
    check_eq("closed: it is listed as closed, not silently dropped",
             facts.get("closed"), ["TP2-2534"])
    check_not_in("closed: and no longer counted among the running",
                 "TP2-2534", facts.get("running") or [])
    check_in("closed: the refusal text prints the closed line", "closed (not candidates)",
             SG.identity_facts(facts))
    check_eq("closed: a dispatch naming it by slug still resolves to it — S9 must pass",
             SG.requested_ticket(desktop_dispatch("qa_retro_analyst__tp2_2534_s9")),
             "TP2-2534")

    lines = {}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        SG.stories()
    for line in buf.getvalue().splitlines():
        if line.strip():
            lines[line.split()[0]] = line
    ghost = lines.get("TP2-2534", "")
    check_in("stories: the closed story says the word, with the date", "closed 2026-09-21", ghost)
    check_in("stories: its running stage is still shown, not swallowed", "S1 running", ghost)
    check_in("stories: and the line ends in the one next action", SG.STALE_AFTER_CLOSURE, ghost)
    check_in("stories: which is recover, on this story's own task root",
             f"--task-root {(arts / 'TP2-2534').resolve()} --operation recover", ghost)
    live = lines.get("TP2-2556", "")
    check_not_in("stories: an open story is never called closed", "closed", live)
    check_not_in("stories: nor accused of a stale state", SG.STALE_AFTER_CLOSURE, live)

    # A closed story with nothing left running is just closed: no accusation, no command.
    settled = arts / "TP2-2534" / "pipeline.json"
    data = json.loads(settled.read_text(encoding="utf-8"))
    data["stages"]["S1"] = {"status": "done"}
    settled.write_text(json.dumps(data), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        SG.stories()
    line = next((r for r in buf.getvalue().splitlines()
                 if r.startswith("TP2-2534")), "")
    check_in("stories: a settled closed story reads `active: closed <date>`",
             "active: closed 2026-09-21", line)
    check_not_in("stories: with no stale-state line to answer", SG.STALE_AFTER_CLOSURE, line)

    # `reopened_at` is a person's word, and it puts the story back in the running.
    data["reopened_at"] = "2026-09-22T09:00:00+00:00"
    data["reopened_by_words"] = "the fix needs one more regression pass"
    data["stages"]["S6"] = {"status": "running"}
    settled.write_text(json.dumps(data), encoding="utf-8")
    facts = SG.resolve_ticket(desktop_dispatch("qa_scout__something_else"))[1]
    check_in("closed: a person's word reopens it, and it counts again",
             "TP2-2534", facts.get("running") or [])
    check_eq("closed: so the single-story guess is ambiguous again, as it should be",
             facts.get("closed"), [])


def part_held_for_code() -> None:
    """t-2181 PC-6 (C13) / t-2277 J-C8: a story held for code is not let into a stage from `held_from` (S6 for the default cause
    `s5_absent_side`, S3 for `first_look_stop`); the stages below it are open (a rework runs inside the hold); a person's recorded
    word passes the refusal and the pass is a `gate_override`; `stories` (the doctor) prints the hold and the stop."""
    root = temp_project("qa-guard-held-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-8"
        (art / "work").mkdir(parents=True)
        (art / "state").mkdir()
        use_project(root)
        model = SG.stage_model()
        empty = {"tests": [], "unresolved": []}

        def story(stage: str, hold=None, overrides=None) -> None:
            """The story at `stage` (every earlier one done, gate A approved, a readable empty manifest) with `hold` as pipeline.awaiting."""
            (art / "work" / MANIFEST).write_text(json.dumps(empty), encoding="utf-8")
            stages = {s["id"]: {"status": "done" if int(s["id"][1:]) < int(stage[1:]) else "pending"} for s in model["stages"]}
            data = {"ticket": "QA-8", "gates": {"A": {"decision": "approved"}}, "stages": stages}
            if hold is not None:
                data["awaiting"] = hold
            if overrides:
                data["stage_overrides"] = overrides
            (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")

        def dispatch(role: str) -> tuple:
            with contextlib.redirect_stderr(io.StringIO()):
                code = SG.check_dispatch({"tool_name": "Task", "cwd": str(root), "tool_input": {"subagent_type": role, "task_id": "QA-8"}})
            return code, SG.LAST_DENIAL.get("message", "") if code else ""

        def word(stage: str, revoked: bool = False) -> list:
            row = {"stage": stage, "match": "is held for code", "decision": "go on, the code is on its way", "at": "2026-11-01T10:00:00"}
            if revoked:
                row["revoked_at"] = "2026-11-01T11:00:00"
            return [row]

        record = {"since": "2026-11-01T10:00:00+00:00", "sides": {"backend": {"reality": "absent"}}, "packet": None}
        story("S6")
        check_eq("no hold: an S6 role is let in (today's pass)", dispatch("qa-runner")[0], 0)
        story("S6", record)
        code, said = dispatch("qa-runner")
        check_eq("s6_role_refused_while_awaiting", code, 2)
        for needle in ("held for code (s5_absent_side) from S6", "the code this story delivers is not there yet", "--block \"is held for code\"",
                       "stop_waiting"):
            check_in(f"... the refusal says `{needle}`", needle, said)
        story("S5", record)
        check_eq("a stage BELOW the hold (S5) is open: a rework runs inside the hold", dispatch("qa-automator")[0], 0)
        story("S6", dict(record, held_from="stage six"))
        check_eq("an unreadable `held_from` reads as the default stage: S6 is refused", dispatch("qa-runner")[0], 2)
        story("S6", dict(record, stopped={"at": "2026-11-02T09:00:00+00:00", "words": "stop"}))
        code, said = dispatch("qa-runner")
        check_eq("a STOPPED story refuses S6 as well", code, 2)
        check_in("... and says the person stopped the wait", "the person stopped the wait", said)

        first_look = dict(record, cause="first_look_stop", held_from="S3", s5_dispatch=None)
        story("S3", first_look)
        code, said = dispatch("qa-test-strategist")
        check_eq("s3_role_refused_while_first_look_held", code, 2)
        check_in("... naming the cause and the stage", "held for code (first_look_stop) from S3", said)
        story("S2", first_look)
        check_eq("a stage below the first-look hold (S2) is open", dispatch("qa-requirements-tester")[0], 0)
        story("S4", first_look)
        check_eq("a later stage (S4) is held too", dispatch("qa-case-designer")[0], 2)

        story("S3", first_look)
        RP.record(root, "journal.jsonl").unlink(missing_ok=True)
        story("S3", first_look, overrides=word("S3"))
        check_eq("a person's recorded word passes the hold", dispatch("qa-test-strategist")[0], 0)
        check_eq("... and the pass is journaled as a gate_override",
                 any(r.get("event") == "gate_override" for r in SG.journal_lines({"cwd": str(root)})), True)
        story("S3", first_look, overrides=word("S3", revoked=True))
        check_eq("a revoked word refuses again", dispatch("qa-test-strategist")[0], 2)
        story("S3", first_look, overrides=word("S6"))
        check_eq("a word for another stage passes nothing", dispatch("qa-test-strategist")[0], 2)

        def doctor() -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                SG.stories({"cwd": str(root)})
            return buf.getvalue()

        story("S6", record)
        check_in("stories prints `awaiting code since <date> (<sides>)`", "awaiting code since 2026-11-01 (backend)", doctor())
        story("S3", first_look)
        check_in("stories names the first-look hold", "held after the first look since 2026-11-01", doctor())
        story("S6", dict(record, stopped={"at": "2026-11-02T09:00:00+00:00", "words": "stop"}))
        check_in("stories prints `stopped waiting <date>`", "stopped waiting 2026-11-02", doctor())
        story("S6")
        check_not_in("a story that waits for nothing prints neither", "waiting", doctor())
    finally:
        cleanup(root)


def part_third_verdict() -> None:
    """K-N8.15 (t-305 N8, Q3, F8): rule 4 opens on `yes` and on `after_checks` - the person's checks are theirs to finish - and
    refuses `no`, an unknown word and an absent ledger; a TMS publish is no delivery shape (it happens at S4), the MR commands
    still are."""
    root = temp_project("qa-guard-third-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-3"
        (art / "work").mkdir(parents=True)
        use_project(root)
        for ledger, opens in (({"delivery_verdict": "yes", "delivery_ready": True}, True),
                              ({"delivery_verdict": "after_checks", "delivery_ready": False}, True),
                              ({"delivery_ready": True}, True),
                              ({"delivery_verdict": "no", "delivery_ready": False}, False),
                              ({"delivery_ready": False}, False),
                              ({"delivery_ready": "no"}, False),
                              ({"delivery_verdict": "yes", "delivery_ready": False}, False),
                              ({"delivery_verdict": "maybe", "delivery_ready": False}, False)):
            (art / "work" / "ledger.json").write_text(json.dumps(dict(ledger, rows=[], reasons=["x"])), encoding="utf-8")
            said = SG.rule_delivery("QA-3", "dispatching qa-bug-reporter")
            check_eq(f"K-N8.15 rule 4 on {ledger}: {'opens' if opens else 'refuses'}", said is None, opens)
        (art / "work" / "ledger.json").unlink()
        check("K-N8.15 an absent ledger refuses", SG.rule_delivery("QA-3", "dispatching qa-bug-reporter") is not None)
        for command in ("tms publish --story QA-3", "python cases.py --publish-cases", "python external_writes.py QA-3 --publish-cases --yes"):
            check_eq(f"K-N8.15 `{command}` is no delivery shape", SG.command_shape(command), "")
        for command in ("glab mr create --fill", "gh pr create --draft"):
            check_eq(f"K-N8.15 `{command}` is still one", SG.command_shape(command), "delivery")
        check("K-N8.15 the delivery forms (B-406: data, no longer a literal tuple of the guard) name no TMS publish",
              not any("publish" in form for form, _source in AF.delivery_forms({})), str(AF.delivery_forms({})))
    finally:
        cleanup(root)


MANIFEST_ROLES = (("S6", "qa-runner"), ("S7", "qa-failure-analyst"), ("S8", "qa-doc-scribe"))
MANIFEST = "automation-manifest.json"
S5_RAN = "done"
S5_SKIPPED = "skipped"


def part_manifest_not_read() -> None:
    """t-910 (C4-1, F-7; fix round t-912): at S6-S8 a manifest that is absent or unreadable is a refusal that names the
    file, what was expected and the door - not "no open items". Three worlds (read with zero items / absent / broken) at
    each stage; the S5 policy skip (pipeline.json records S5 as skipped: no manifest is expected) leaves rule 3 silent; the
    file is found where the registry puts it (work/) as well as under the legacy flat name, and an existing work/ file
    is THE manifest whatever a stale flat copy says; the refusal is one of the dispatch guard's list, so a person's
    recorded word passes it (P13) and the pass is a gate_override record; the commit of test code keeps today's pass."""
    root = temp_project("qa-guard-manifest-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-9"
        (art / "work").mkdir(parents=True)
        (art / "state").mkdir()
        use_project(root)
        model = SG.stage_model()

        def story(stage: str, s5: str, manifest=None, where="work/", overrides=None, flat=None) -> None:
            """The story at `stage` (every earlier one done, gate A approved) with S5 recorded as `s5` in pipeline.json,
            its manifest under `where` (a dict, a raw text, or None for no file), a second copy at the flat name when
            `flat` is given, and the person's recorded words `overrides` (stage_overrides[] rows)."""
            for leftover in (art / "work" / MANIFEST, art / MANIFEST):
                leftover.unlink(missing_ok=True)
            done = [s["id"] for s in model["stages"] if int(s["id"][1:]) < int(stage[1:])]
            stages = {s["id"]: {"status": "done" if s["id"] in done else "pending"} for s in model["stages"]}
            if "S5" in done:
                stages["S5"] = {"status": s5}
            data = {"ticket": "QA-9", "gates": {"A": {"decision": "approved"}}, "stages": stages}
            if overrides:
                data["stage_overrides"] = overrides
            (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")
            for target, content in ((art / where / MANIFEST, manifest), (art / MANIFEST, flat)):
                if content is not None:
                    target.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")

        def word(stage: str, match: str, revoked: bool = False) -> list:
            row = {"stage": stage, "match": match, "decision": "go on without it", "at": "2026-10-17T10:00:00"}
            if revoked:
                row["revoked_at"] = "2026-10-17T11:00:00"
            return [row]

        def dispatch(stage: str, role: str) -> tuple:
            with contextlib.redirect_stderr(io.StringIO()):
                code = SG.check_dispatch({"tool_name": "Task", "cwd": str(root),
                                          "tool_input": {"subagent_type": role, "task_id": "QA-9"}})
            return code, SG.LAST_DENIAL.get("message", "") if code else ""

        empty = {"tests": [], "unresolved": []}
        for stage, role in MANIFEST_ROLES:
            tag = f"{stage} {role}"
            story(stage, S5_RAN, empty)
            check_eq(f"manifest[{tag}] read, zero items: today's pass", dispatch(stage, role)[0], 0)
            story(stage, S5_RAN, empty, where="")
            check_eq(f"manifest[{tag}] read from the legacy flat name, zero items: pass", dispatch(stage, role)[0], 0)

            story(stage, S5_RAN, None)
            code, said = dispatch(stage, role)
            check_eq(f"manifest[{tag}] absent, S5 ran: refused", code, 2)
            check_in(f"manifest[{tag}] absent: names the file", "work/automation-manifest.json is absent", said)
            check_in(f"manifest[{tag}] absent: names the door (the writer)", "manifest_put.py", said)
            check_not_in(f"manifest[{tag}] absent: is not the unreadable text", "could not be read", said)

            for label, raw in (("not JSON", "{oops"), ("empty file", ""), ("a JSON list", "[1, 2]"), ("JSON null", "null")):
                story(stage, S5_RAN, raw)
                code, said = dispatch(stage, role)
                check_eq(f"manifest[{tag}] broken ({label}): refused", code, 2)
                check_in(f"manifest[{tag}] broken ({label}): names the file and 'could not be read'",
                         "work/automation-manifest.json could not be read", said)
                check_not_in(f"manifest[{tag}] broken ({label}): is not the absent text", "is absent", said)
            story(stage, S5_SKIPPED, "{oops")
            code, said = dispatch(stage, role)
            check_eq(f"manifest[{tag}] broken, S5 skipped: still refused (a file is there and it is not readable)",
                     code, 2)
            check_in(f"manifest[{tag}] broken, S5 skipped: names the file", "work/automation-manifest.json could not be read", said)
            check_in(f"manifest[{tag}] broken, S5 skipped: the repair is removing or repairing the file",
                     "remove the file, or repair it", said)
            check_not_in(f"manifest[{tag}] broken, S5 skipped: no qa-automator re-dispatch (the policy forbids it)",
                         "manifest_put.py", said)

            story(stage, S5_SKIPPED, None)
            code, said = dispatch(stage, role)
            check_not_in(f"manifest[{tag}] absent, S5 skipped by a policy: no manifest is expected, rule 3 is silent",
                         "automation-manifest", said)
            check_eq(f"manifest[{tag}] absent, S5 skipped by a policy: the dispatch result (rule 1 refuses S6 only)",
                     code, 2 if stage == "S6" else 0)
            story(stage, S5_RAN, empty)
            check_eq(f"manifest[{tag}] read: pass", dispatch(stage, role)[0], 0)

            # F-1: the refusal is a line of the dispatch guard's list, so a person's word passes it (P13), the pass is
            # the standard gate_override record, a revoked word refuses again
            for what, manifest, match, text in (
                    ("absent", None, "is absent", "is absent"),
                    ("unreadable", "{oops", "could not be read", "could not be read"),
                    ("an open row", {"tests": [], "unresolved": [{"case": "TC-4", "reason": "because"}]},
                     "unresolved cases without a reason", "unresolved cases without a reason")):
                story(stage, S5_RAN, manifest)
                code, said = dispatch(stage, role)
                check_in(f"manifest[{tag}] {what}: the refusal carries the person's door with its block",
                         f'--block "{match}"', said)
                check_in(f"manifest[{tag}] {what}: ...and the text", text, said)
                RP.record(root, "journal.jsonl").unlink(missing_ok=True)
                story(stage, S5_RAN, manifest, overrides=word(stage, match))
                code, said = dispatch(stage, role)
                check_eq(f"manifest[{tag}] {what}: a recorded word passes it", code, 0)
                check_eq(f"manifest[{tag}] {what}: ...journaled as a gate_override",
                         any(r.get("event") == "gate_override" for r in SG.journal_lines({"cwd": str(root)})), True)
                story(stage, S5_RAN, manifest, overrides=word(stage, match, revoked=True))
                check_eq(f"manifest[{tag}] {what}: a revoked word refuses again", dispatch(stage, role)[0], 2)
                story(stage, S5_RAN, manifest, overrides=word("S1", match))
                check_eq(f"manifest[{tag}] {what}: a word for another stage passes nothing", dispatch(stage, role)[0], 2)
            story(stage, S5_RAN, None)
            import waiver
            check_in(f"manifest[{tag}] the waiver's own re-check of the guard sees the line (`block_standing`)",
                     "is absent", "\n".join(waiver._guard_lines(json.loads((art / "pipeline.json").read_text(
                         encoding="utf-8")), stage)))

            # F-2: an existing work/ file is THE manifest; the flat copy is read only when work/ holds none
            story(stage, S5_RAN, {"tests": [], "unresolved": [{"case": "TC-4", "reason": "because"}]}, flat=empty)
            code, said = dispatch(stage, role)
            check_eq(f"manifest[{tag}] work/ with an open row + a stale flat copy without one: refused", code, 2)
            check_in(f"manifest[{tag}] ...the open row is seen", "TC-4 (because)", said)
            story(stage, S5_RAN, "{oops", flat=empty)
            code, said = dispatch(stage, role)
            check_eq(f"manifest[{tag}] work/ broken + a flat copy that reads: refused (work/ wins)", code, 2)
            check_in(f"manifest[{tag}] ...'could not be read'", "work/automation-manifest.json could not be read", said)
            story(stage, S5_RAN, None, flat=empty)
            check_eq(f"manifest[{tag}] work/ absent + a flat copy that reads: the flat copy is the manifest",
                     dispatch(stage, role)[0], 0)

            bad = {"tests": [], "unresolved": [{"case": "TC-4", "reason": "because"}]}
            for where in ("work/", ""):
                story(stage, S5_RAN, bad, where=where)
                code, said = dispatch(stage, role)
                check_eq(f"manifest[{tag}] an open unresolved row under {where or 'the flat name'}: refused", code, 2)
                check_in(f"manifest[{tag}] ...naming the case ({where or 'flat'})", "TC-4 (because)", said)

        # F-3: the scope rule asks the SAME resolver (`manifest_path`): the work/ manifest's `covers`, not a stale flat copy's
        story("S6", S5_RAN, {"tests": [{"instance_id": "test_x[eu]", "covers": ["TC-12"]}], "unresolved": []},
              flat={"tests": [], "unresolved": []})
        covered = SG._manifest_covers("QA-9", {"cwd": str(root)})
        check("manifest resolver: `_manifest_covers` reads the work/ manifest, not a stale flat copy",
              any("TC-12" in cases for cases in covered.values()), str(covered))

        # the controller's `--task-root` is THE story (t-910 round 2b): the manifest is read there, and a same-named story
        # in the cwd project neither supplies nor hides it
        elsewhere = temp_project("qa-guard-taskroot-")
        try:
            other_root = elsewhere / "stories" / "QA-9"
            (other_root / "work").mkdir(parents=True)

            def manifest_lines(pipe: dict, **kw) -> list:
                return [m for m in SG.dispatch_errors(pipe, "S6", journal=False, **kw) if "automation-manifest" in m]

            story("S6", S5_RAN, None)                                  # cwd project: QA-9 has NO manifest
            pipe = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
            (other_root / "work" / MANIFEST).write_text(json.dumps(empty), encoding="utf-8")
            check_eq("task_root outside the cwd project: its own manifest is found (nothing refused)",
                     manifest_lines(pipe, task_root=other_root), [])
            check_in("...while the hook path (no task_root) still reads the cwd project and refuses",
                     "is absent", "".join(manifest_lines(pipe)))
            story("S6", S5_RAN, empty)                                 # cwd project HAS a manifest, the task root does not
            (other_root / "work" / MANIFEST).unlink()
            check_in("a same-named story in the cwd project does not satisfy the task root",
                     "is absent", "".join(manifest_lines(pipe, task_root=other_root)))
        finally:
            cleanup(elsewhere)

        # POSITION invariants. The unreadable pipeline keeps its single text and comes first; the order reason and the
        # manifest reason are items of ONE refusal (F-2); the commit of test code (S5 writes tests BEFORE the manifest)
        # and S1-S5 are untouched.
        story("S6", S5_RAN, None)
        (art / "pipeline.json").write_text("{oops", encoding="utf-8")
        code, said = dispatch("S6", "qa-runner")
        check_eq("manifest position: an unreadable pipeline.json is the single registered text",
                 (code, said.endswith("QA-9: unreadable pipeline; recover task state before dispatch")), (2, True))
        story("S6", S5_RAN, None)
        data = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        data["stages"]["S5"]["status"] = "pending"
        (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")
        code, said = dispatch("S6", "qa-runner")
        check_in("manifest position: with the order reason it is one more item of the same refusal",
                 "2 problems", said)
        check_in("...whole: the manifest item", "work/automation-manifest.json is absent", said)
        check_eq("manifest edge: the commit rule (default) finds no open item in an absent manifest",
                 SG.rule_manifest("QA-9", "committing test code"), None)
        check_in("manifest edge: `explain` (--ticket/--stage) shows the refusal too",
                 "work/automation-manifest.json is absent", "\n".join(_explained("QA-9", "S6")))
        story("S5", S5_RAN, None)
        check_eq("manifest edge: S5 has no manifest rule: qa-automator passes without a manifest",
                 dispatch("S5", "qa-automator")[0], 0)
        # X7-2 (E-3): the route word is checked before anything else, the role's words go after the `:`, an empty reason is refused.
        real_read = SG.read_manifest
        try:
            def refusal_for(reasons) -> str | None:
                rows = [{"case": f"TC-{i}", "reason": reason} for i, reason in enumerate(reasons, start=1)]
                SG.read_manifest = lambda ticket, event=None, task_root=None: ({"unresolved": rows}, "read", Path("m.json"))
                return SG.rule_manifest("QA-9", "committing test code")
            check_eq("route rule (3): `<route>: <words>` and a bare route word pass",
                     refusal_for(["blocked_by_env: the stand has no non-owner account", "impossible", "deferred_by_decision:gate-a"]), None)
            bare = refusal_for(["env blocker"]) or ""
            check_in("route rule (3): bare words are refused", "TC-1 (env blocker)", bare)
            check_in("route rule (4): ... with the expected list (a typo of a route word is refused with the closed list)",
                     " | ".join(SG.closed_unresolved_reasons()), refusal_for(["blocked_by_envv: typo"]) or "")
            check_in("route rule (3): an empty reason is refused and says so", "no reason", refusal_for([""]) or "")
        finally:
            SG.read_manifest = real_read
    finally:
        cleanup(root)


def _explained(ticket: str, stage: str) -> list:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        SG.explain(ticket, stage)
    return out.getvalue().splitlines()


def part_adapter_forms() -> None:
    """B-405 / B-406: the story a dispatch names is read in the PROJECT's ticket-key form, and the delivery commands
    the gate stops are data (references/adapter-forms.json plus `adapters.vcs.delivery_commands`), read by their words
    (the critic's t-528 F-F: `glab  mr create` and `glab --repo x/y mr create` passed a substring test)."""
    root = temp_project("qa-factory-forms-")
    arts = root / "qa-factory" / "artifacts"
    cfg_path = root / "qa-factory" / "config.json"
    base_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    def configure(ticket: dict | None = None, vcs: dict | None = None) -> dict:
        cfg = json.loads(json.dumps(base_cfg))
        cfg["adapters"]["ticket"].update(ticket or {})
        cfg["adapters"]["vcs"].update(vcs or {})
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg

    def story(name: str, verdict: str | None = None) -> None:
        folder = arts / name
        (folder / "work").mkdir(parents=True, exist_ok=True)
        (folder / "pipeline.json").write_text(json.dumps({"ticket": name, "stages": {"S1": {"status": "running"}}}),
                                              encoding="utf-8")
        if verdict:
            (folder / "work" / "ledger.json").write_text(json.dumps(
                {"delivery_verdict": verdict, "delivery_ready": verdict == "yes", "rows": [], "reasons": ["x"]}),
                encoding="utf-8")

    def named(prompt: str, **extra) -> str:
        return SG.requested_ticket({"tool_name": "Agent", "cwd": str(root), **extra,
                                    "tool_input": {"subagent_type": "qa-scout", "prompt": prompt}})

    def shapes(command: str, cfg: dict | None = None) -> list:
        return SG.command_shapes(command, cfg)

    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            # --- key acceptance 2: a GitHub-config project resolves `123` from `Ticket: 123` ONLY ---
            configure(ticket={"name": "github"})
            story("123")
            story("7")
            check_eq("forms/gh: `Ticket: 123` names story 123", named("You are qa-scout. Ticket: 123. Dispatch: d1."), "123")
            check_eq("forms/gh: `#123` names no story (the single-story guess does not apply to two running)",
                     named("work on #123 please"), "")
            check_eq("forms/gh edge 7: `Fixes #1` in a PR title never resolves story 1",
                     named("gh pr create --title 'Fixes #7'"), "")
            check_eq("forms/gh edge 6: a bare 123 names no story", named("look at 123 and 7"), "")
            check_eq("forms/gh edge 22: `Step #7 ... Ticket: 123` is 123 - only the label names a story",
                     named("Step #7: do the work. Ticket: 123. Dispatch: d1."), "123")
            check_eq("forms/gh: two labelled stories name none (the error direction is no story)",
                     named("Ticket: 123 and Ticket: 7"), "")
            check_eq("forms/gh: an explicit id is never overruled by the text",
                     named("Ticket: 123", task_id="7"), "7")
            nameless = {"tool_name": "Agent", "cwd": str(root),
                        "tool_input": {"subagent_type": "qa-scout", "prompt": "no id here"}}
            check_eq("forms/gh: and the identity refusal comes", SG.check(nameless), 2)
            check_in("forms/gh: ... naming the form the guard read", "ticket key form: a ticket key like #123",
                     SG.LAST_DENIAL["message"])
            # edge 9: a window suffix never names a numeric story; only the first word of the tail does
            check_eq("forms/gh edge 9: `qa_automator__tp3c_s5_7` is not story 7",
                     SG.requested_ticket(desktop_dispatch("qa_automator__tp3c_s5_7")), "")
            check_eq("forms/gh edge 9: `qa_automator__7_s5_3` is story 7 (the slug starts the tail)",
                     SG.requested_ticket(desktop_dispatch("qa_automator__7_s5_3")), "7")
            check_eq("forms/gh edge 9: the slug helper, anchored and not",
                     (SG.slug_in_task_name("7", "qa_automator__tp3c_s5_7", True),
                      SG.slug_in_task_name("7", "qa_automator__tp3c_s5_7", False),
                      SG.slug_in_task_name("7", "qa_automator__7_s5", True)), (False, True, True))

            # --- key acceptance 3, edge 23, F19 (b): two candidates name none, the Ticket: line settles ---
            configure()
            story("TP2-2534")
            story("TP2-2556")
            story("TP1-15045")
            story("MY_PROJ-12")
            check_eq("forms/jira: two existing stories named without the label name none",
                     named("compare TP2-2534 with TP2-2556"), "")
            check_in("forms/jira: ... and the refusal lists both names", "TP2-2534, TP2-2556",
                     SG.identity_facts(SG.resolve_ticket({"tool_name": "Agent", "cwd": str(root), "tool_input": {
                         "subagent_type": "qa-scout", "prompt": "compare TP2-2534 with TP2-2556"}})[1]))
            check_eq("forms/jira edge 23 (F19 b): `Ticket: 2556` with 2534 also named answers 2556",
                     named("You are qa-scout. Ticket: TP2-2556. Compare with TP2-2534."), "TP2-2556")
            check_eq("forms/jira: the label naming TWO existing stories settles nothing",
                     named("Ticket: TP2-2556 Ticket: TP2-2534"), "")
            check_eq("forms/jira: a dispatch that names one story is unchanged",
                     named("dispatch qa-scout for TP2-2556"), "TP2-2556")
            check_eq("forms/jira edge 10: MY_PROJ-12 is ONE key (the old shape named PROJ-12)",
                     named("dispatch for MY_PROJ-12"), "MY_PROJ-12")
            check_eq("forms/jira edge 10: a case id with the story's key in it names the story (the lookahead delta)",
                     named("TP1-15045_TC_001 ... Ticket: TP1-15045"), "TP1-15045")
            check_eq("forms/jira edge 10: ... and with the label naming ANOTHER story, the label wins over the case id",
                     named("TP1-15045_TC_001 checks the work of Ticket: TP2-2556"), "TP2-2556")
            check_eq("forms/jira edge 10: fooTP1-15045 and TP1-15045a name nothing",
                     named("fooTP1-15045 TP1-15045a"), "")
            check_eq("forms/jira: a slug in the task name still resolves (Jira slugs are unanchored)",
                     SG.requested_ticket(desktop_dispatch("qa_automator__tp2_2556_s5_11")), "TP2-2556")

            # --- B4: the shared signatures and command_shape == the first of command_shapes ---
            import inspect
            check_eq("forms/B4: command_shapes(command, cfg=None, event=None)",
                     list(inspect.signature(SG.command_shapes).parameters), ["command", "cfg", "event"])
            check_eq("forms/B4: _is_commit_shape(command, cfg=None, event=None)",
                     list(inspect.signature(SG._is_commit_shape).parameters), ["command", "cfg", "event"])
            check_eq("forms/B4: needs_stage_guard(command, cfg=None)",
                     list(inspect.signature(SG.needs_stage_guard).parameters), ["command", "cfg"])
            for command in ("glab mr create", "git commit -m x tests/t.py", "git stash push -u", "ls",
                            "gh pr create && git stash", "git commit -m x tests/t.py && glab mr create"):
                got = SG.command_shapes(command)
                check_eq(f"forms/B4: command_shape == the first of command_shapes for `{command}`",
                         SG.command_shape(command), got[0] if got else "")

            # --- key acceptance 4: the forms in force, read by their words ---
            gitlab_bb = configure(vcs={"name": "gitlab", "delivery_commands": ["bb pr create"]})
            deliveries = ("bb pr create", "gh pr create", "glab mr create", "glab mr create --fill", "gh pr create --draft",
                          "glab  mr create", "gh   pr    create", "glab --repo x/y mr create", "gh -R o/r pr create",
                          "glab --hostname=h.example mr create", "sudo gh pr create", "env GH_TOKEN=x gh pr create",
                          "cd app && glab mr create", "git push -o merge_request.create", "git push origin x -o merge_request.create",
                          "git push --push-option=merge_request.create", 'bash -c "gh pr create --fill"',
                          "pwsh -NoProfile -Command \"glab mr create\"", "echo $(gh pr create)", "hub pull-request -m x",
                          "/usr/bin/glab mr create", "glab.exe mr create", "bb  --workspace w pr create")
            for command in deliveries:
                check_eq(f"forms/delivery: `{command}` is a delivery", "delivery" in shapes(command, gitlab_bb), True)
            not_deliveries = ("gh pr list", "glab mr view 5", "glab mr list", "gh pr view create", "gh pr list create",
                              "bb pr list", "gh issue create", 'echo "glab mr create"', "git commit -m 'gh pr create' README.md",
                              'grep -rn "gh pr create" docs', "echo 'bb pr create'", 'echo "merge_request.create"',
                              "git push origin main", "ls -la", "glab", "gh pr", "gh create pr")
            for command in not_deliveries:
                check_eq(f"forms/delivery: `{command}` is not a delivery", "delivery" in shapes(command, gitlab_bb), False)
            # --- critic t-549 F1: recognition is never narrower than the substring it replaced (FR-59) ---
            floor_cases = ('eval "gh pr create"', 'python -c "os.system(\'gh pr create\')"', "git -c alias.x='!gh pr create' x",
                           "gh=gh; $gh pr create", "${tool} pr create --fill", 'ssh host "gh pr create"', "bash -lc 'gh pr create'",
                           'FOO=1 eval "glab mr create"', 'sudo ssh host \'cd x && glab  mr create\'')
            for command in floor_cases:
                check_eq(f"forms/F1: `{command}` is a delivery (the quoted argument of a non-mention command is a command)",
                         "delivery" in shapes(command, gitlab_bb), True)
            for command in ('echo "glab mr create"', "git commit -m 'gh pr create'", 'grep -rn "gh pr create" docs', "gh pr list",
                            'printf "%s" "gh pr create"', 'git -C app commit -m "gh pr create"', 'echo "$gh pr create"',
                            "$gh pr list", 'git tag -a v1 -m "gh pr create"', 'FOO=1 echo "gh pr create"'):
                check_eq(f"forms/F1: `{command}` stays a mention / no delivery", "delivery" in shapes(command, gitlab_bb), False)
            check_eq("forms/F1 (a): `eval` is a row of the shell table (launch-causes.json): its quoted argument is a command, bash dialect",
                     hooklib.run_forms()["shells"].get("eval"), ("none", "bash"))
            check_eq("forms/F1 (a): ...which is also what makes B-404's matcher see `eval \"pytest -q\"` as a test launch",
                     hooklib.direct_test_form('eval "pytest -q"') is not None, True)
            # --- critic t-549 F2: the cost is linear in the command (rule 11 battery, AT and BEYOND a size) ---
            import time
            tokens_of = lambda text: len(text.split())  # noqa: E731
            measured = {}
            for label, command in (("8 KB", "gh --x " * 1100 + "pr list && echo create"), ("64 KB", "gh --x " * 9300 + "pr list && echo create"),
                                   ("128 KB", "gh --x " * 18600 + "pr list && echo create")):
                AF.STEPS[0] = 0
                started = time.perf_counter()
                got = shapes(command, gitlab_bb)
                elapsed = time.perf_counter() - started
                measured[label] = AF.STEPS[0]
                check_eq(f"forms/F2 {label}: `gh --x ... pr list && echo create` is no delivery", got, [])
                check(f"forms/F2 {label}: the matcher visited at most 4 cells per token per word ({AF.STEPS[0]} steps for {tokens_of(command)} tokens)",
                      AF.STEPS[0] <= 4 * tokens_of(command) * 3, str(AF.STEPS[0]))
                # A wall-clock bound is load-sensitive (FR-31), so the STEP COUNT above is the assertion; this one is only a
                # generous margin against the old quadratic walk (22 s at 28 KB): seconds, not 200 ms.
                check(f"forms/F2 {label}: and it returns in seconds, not minutes ({elapsed:.2f} s)", elapsed < 10.0)
            check("forms/F2: doubling the command about doubles the steps (linear, not quadratic)",
                  measured["128 KB"] < 2.5 * measured["64 KB"] and measured["64 KB"] < 9 * measured["8 KB"], str(measured))
            started = time.perf_counter()
            check_eq("forms/F2: 8000 quoted arguments and a mention at the end are no delivery",
                     shapes('"a" ' * 8000 + '; echo "gh pr create"', gitlab_bb), [])
            check("forms/F2: ...in seconds (quoted arguments are re-read one level down, each once)", time.perf_counter() - started < 10.0)
            check_eq("forms/F2: and a delivery after a long run of options is still found",
                     "delivery" in shapes("gh --x " * 9000 + "pr create", gitlab_bb), True)
            check_eq("forms/delivery: `echo gh pr create` with the words bare IS read as a delivery (the gate errs toward refusing)",
                     "delivery" in shapes("echo gh pr create"), True)
            check_eq("forms/delivery: the project's own command is not known without its config",
                     ("delivery" in shapes("bb pr create"), "delivery" in shapes("bb pr create", gitlab_bb)), (False, True))
            check_eq("forms/delivery: config only WIDENS - the other host's commands are gated whatever the host is",
                     ["delivery" in shapes(c, gitlab_bb) for c in ("gh pr create", "glab mr create")], [True, True])
            bad = configure(vcs={"delivery_commands": ["git", "", 5, None, "bb pr"]})
            check_eq("forms/delivery: invalid entries are ignored (git, empty, 5, None: `git push` is no delivery), "
                     "`bb pr` is AT the limit and valid - it gates `bb pr` and `bb pr create`, not `bb issue`",
                     ["delivery" in shapes(c, bad) for c in ("git push", "bb pr create", "bb pr", "bb issue", "gh pr create")],
                     [False, True, True, False, True])
            check_eq("forms/delivery: needs_stage_guard sees the same",
                     [SG.needs_stage_guard(c, gitlab_bb) for c in ("bb pr create", 'echo "bb pr create"', "ls")],
                     [True, False, False])
            # a table that cannot be read: the declared floor, never a pass
            saved_path = AF.TABLE_PATH
            AF.TABLE_PATH = root / "no-such-table.json"
            try:
                check_eq("forms/floor: with the table unreadable `glab mr create` and `gh pr create` are still gated, `hub pull-request` is not",
                         ["delivery" in shapes(c) for c in ("glab mr create", "gh --repo x pr create", "hub pull-request")],
                         [True, True, False])
            finally:
                AF.TABLE_PATH = saved_path

            # --- key acceptance 5, edge 14: every shape the command has runs its rule ---
            configure()
            story("QA-3", verdict="yes")
            event = {"tool_name": "Bash", "cwd": str(root), "task_id": "QA-3", "tool_input": {"command": ""}}

            def verdict_of(command: str) -> int:
                event["tool_input"]["command"] = command
                return SG.check(event)

            check_eq("forms/F15: `git commit -a -m x tests/t.py && gh pr create` is a delivery AND a commit",
                     shapes("git commit -a -m x tests/t.py && gh pr create"), ["delivery", "commit"])
            check_eq("forms/F15: under a `yes` verdict it is refused by rule 5 (the delivery form is no way past it)",
                     verdict_of("git commit -a -m x tests/t.py && gh pr create"), 2)
            check_in("forms/F15: ... and the refusal is rule 5's", "-a/--all", SG.LAST_DENIAL["message"])
            check_eq("forms/F15 control: the same delivery with a pathspec commit is allowed under `yes`",
                     verdict_of("git commit -m x -- tests/t.py && gh pr create"), 0)
            check_eq("forms/F15 control: `gh pr create` alone under `yes` is allowed", verdict_of("gh pr create --fill"), 0)
            check_eq("forms/F15: a stash that sweeps the tree, in one command with a delivery, meets rule 7",
                     (shapes("git stash push -u && gh pr create"), verdict_of("git stash push -u && gh pr create")),
                     (["delivery", "stash"], 2))
            check_eq("forms/edge 14 -> E-A10 (B-407 A): a delivery whose body MENTIONS a test-file commit is a delivery and "
                     "no commit (the quoted body is one token of a non-git segment); the mutation 'scan the raw command' "
                     "is killed here", shapes('gh pr create --body "git commit -m x tests/x.py"'), ["delivery"])
            story("QA-3", verdict="no")
            check_eq("forms/delivery: under a `no` verdict every form is refused, the refusal names the form and its source",
                     [verdict_of(c) for c in ("glab  mr create", "gh -R o/r pr create")], [2, 2])
            check_eq("forms/F1: under a `no` verdict the five commands the substring caught are refused through the guard",
                     [verdict_of(c) for c in ('eval "gh pr create"', 'python -c "os.system(\'gh pr create\')"',
                                              "git -c alias.x='!gh pr create' x", "gh=gh; $gh pr create", 'ssh host "gh pr create"')],
                     [2] * 5)
            check_eq("forms/F1: ...and the mentions pass",
                     [verdict_of(c) for c in ('echo "glab mr create"', "git commit -m 'gh pr create'", 'grep -rn "gh pr create" docs',
                                              "gh pr list")], [0] * 4)
            verdict_of("gh -R o/r pr create")        # RH1-5: `check` clears LAST_DENIAL on entry, so read it right after the refusal
            check_in("forms/delivery: ... naming the matched form and where it comes from",
                     "`gh pr create`, from references/adapter-forms.json (github)", SG.LAST_DENIAL["message"])
            check_in("forms/delivery: rule_delivery names a configured form and its source",
                     "`bb pr create`, from adapters.vcs.delivery_commands",
                     SG.rule_delivery("QA-3", "this delivery command", None, ("bb pr create", "adapters.vcs.delivery_commands")))
            check_eq("forms/delivery: rule_delivery with no match is the old sentence (a role dispatch)",
                     "from " in (SG.rule_delivery("QA-3", "dispatching qa-bug-reporter") or ""), False)
    finally:
        cleanup(root)


K8_COMMAND = ('run(){ python "$P/scripts/question_register.py" --task T --answer $1 ${2:+--reading $2} '
              '--words-file $W/s2-$(echo $1|tr Q q).txt --register-hash $3; }')
GATE_B_TODAY = ("this delivery command (`gh pr create`, from references/adapter-forms.json (github)) is blocked — the delivery "
                "verdict for QA-3 is `no`; it opens at yes or after_checks, or with a deliver_with_risks line in the journal: x. "
                "Either close the gaps, or have the human say 'deliver with known gaps' at gate B (with a "
                "reason) so the journal carries a deliver_with_risks event.")


def part_cx2_27_matcher() -> None:
    """CX2-27 (K1, t-220 N1): the guard reads as a delivery what the shell would run - a bare `$var` or a substitution
    with no sign of the form in the segment is an argument. Error direction: toward refusal (a form word written anywhere in
    the segment still refuses). Each row is `SG._delivery_match(c, None)`; the mutation that each row kills is named in the
    node's report."""
    def hit(command: str):
        return SG._delivery_match(command, None)

    for key, command in (("k1", "$a $(f)"), ("k2", "python x.py --n $a --f b-$(f).txt"), ("k3", "echo $a $(f)"),
                         ("k4", "$a $(f) $(g)"), ("k5", "python x.py --n $a --f b.txt"),
                         ("k6", "python x.py --f b-$(f).txt --n $a"), ("k8", K8_COMMAND), ("k11a", "echo $(a) $(b)"),
                         ("k11b", "for f in $(a) $(b)"), ("k11c", "foreach ($x in $(a) $(b)) { $x }"),
                         ("k11d", "FOO=1 echo $(a) $(b)")):
        check_eq(f"CX2-27 {key}: `{command[:50]}` is no delivery", hit(command), None)
    found = hit("gh=gh; $gh pr create")
    check_eq("CX2-27 k7: `gh=gh; $gh pr create` stays a delivery, of github", (found is not None and found[1]),
             "references/adapter-forms.json (github)")
    for command in ("$gh pr $(echo create)", "$gh $(echo pr) create", "$gh $(echo pr create)", "${tool} pr create",
                    "$P/gh pr create", "$gh pr create --fill", "gh $(echo pr create)", "$a pr $(f)"):
        check("CX2-27 k9: `" + command + "` stays a delivery", hit(command) is not None)
    for command in ("$(a) $(b)", "git $(a) $(b) commit -m x tests/test_a.py", "$(echo gh) pr create", "gh $(x) create"):
        check("CX2-27 k10: `" + command + "` stays a delivery (pin B-1, I-SAFE)", hit(command) is not None)
    for command in ('echo "$(gh pr create)"', "for f in $(gh pr create); do x; done", 'for c in "gh pr create"; do $c; done',
                    "echo gh pr create", "for f in gh pr create; do x; done"):
        check("CX2-27 k12: `" + command + "` stays a delivery (a region is read on its own; the quoted words of a loop "
              "head are commands)", hit(command) is not None)
    check_eq("CX2-27 edge: no command, blanks: no shape", [hit(None), hit(""), hit("   ")], [None, None, None])
    check_eq("CX2-27 edge: the shown form of a variable program is still the form (the refusal's own words are a question "
             "for Lead, see the report)", hit("$gh pr create --fill")[0], "gh pr create")
    # magnitude (S3.8): 10x the starts costs under 25x the time, and the verdict does not move
    import time

    def took(count: int) -> tuple:
        began = time.perf_counter()
        return hit("$a " * count + "$(f)"), time.perf_counter() - began
    (small_hit, small), (big_hit, big) = took(20000), took(200000)
    check_eq("CX2-27 magnitude: 200 000 `$a ` then `$(f)` is no delivery", (small_hit, big_hit), (None, None))
    check("CX2-27 magnitude: ... and 10x the input costs under 25x the time", big / max(small, 1e-6) < 25, f"{big:.2f}s / {small:.2f}s")
    check_eq("CX2-27 magnitude: ... with a written form at the end it is refused", hit("$a " * 200000 + "$gh pr create") is not None, True)
    # the table is data (AR-1): a damaged one releases nothing - the loop head keeps today's reading, never a pass
    saved = AF.TABLE_PATH
    AF.TABLE_PATH = Path(SCRIPTS) / "no-such-table.json"
    try:
        check_eq("CX2-27 damage: with the table unreadable a loop head releases nothing (the floor refuses as before)",
                 [hit(c) is not None for c in ("for f in $(a) $(b)", "echo $(a) $(b)")], [True, False])
    finally:
        AF.TABLE_PATH = saved


def part_cx2_27_door() -> None:
    """CX2-27 (b), K1 d1..d5: before gate B the refusal of a delivery shape names no door of gate B; the verdict is the same."""
    root = temp_project("qa-factory-gate-b-door-")
    art = root / "qa-factory" / "artifacts" / "QA-3"
    event = {"tool_name": "Bash", "cwd": str(root), "task_id": "QA-3", "tool_input": {"command": ""}}

    def story(stages) -> dict:
        (art / "work").mkdir(parents=True, exist_ok=True)
        pipeline = {"ticket": "QA-3", "stages": stages}
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        (art / "work" / "ledger.json").write_text(json.dumps(
            {"delivery_verdict": "no", "delivery_ready": False, "rows": [], "reasons": ["x"]}), encoding="utf-8")
        return pipeline

    def said(command: str) -> tuple:
        event["tool_input"]["command"] = command
        verdict = SG.check(event)
        return verdict, SG.LAST_DENIAL.get("message", "") if verdict else ""

    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            story({"S7": {"status": "done"}, "S8": {"status": "running"}})
            verdict, message = said("gh pr create --fill")
            check_eq("CX2-27 d1: S8 not done, a delivery: refused", verdict, 2)
            for needle in ("gh pr create", "gate B comes after S8, which is running", "Write tool"):
                check_in(f"CX2-27 d1: the message holds `{needle}`", needle, message)
            for needle in ("deliver with known gaps", "check_delivery"):
                check_not_in(f"CX2-27 d1: ... and no door of gate B (`{needle}`)", needle, message)
            story({"S7": {"status": "done"}})
            check_in("CX2-27 d1: no S8 record reads as pending", "which is pending", said("gh pr create")[1])
            story({"S8": {"status": "done"}})
            verdict, message = said("gh pr create --fill")
            check_eq("CX2-27 d2: S8 done, the same command: refused", verdict, 2)
            check_in("CX2-27 d2: ... with today's sentence, door of gate B included", "deliver with known gaps", message)
            check_not_in("CX2-27 d2: ... and not the new one", "gate B comes after", message)
            check_eq("CX2-27 d2: rule_delivery is byte-equal to today's sentence",
                     SG.rule_delivery("QA-3", "this delivery command", None, ("gh pr create", "references/adapter-forms.json (github)"),
                                      {"stages": {"S8": {"status": "done"}}}), GATE_B_TODAY)
            check_eq("CX2-27 d2: no pipeline handed over (a caller that has none) is today's sentence too",
                     SG.rule_delivery("QA-3", "this delivery command", None, ("gh pr create", "references/adapter-forms.json (github)")),
                     GATE_B_TODAY)
            # RD1-4 K10/K11 (B-1, B-2): the head names every opener and never states a word for a ledger that is not there
            check_in("RD1-4 K10: the head names all three openers", "opens at yes or after_checks, or with a deliver_with_risks line",
                     GATE_B_TODAY)
            check_not_in("RD1-4 K10: and never the old `delivery_ready is not yes`", "delivery_ready is not yes", GATE_B_TODAY)
            ledger_file = art / "work" / "ledger.json"
            saved_ledger = ledger_file.read_text(encoding="utf-8")
            ledger_file.unlink()
            absent = SG.rule_delivery("QA-3", "this delivery command", None, None, {"stages": {"S8": {"status": "done"}}}) or ""
            check_in("RD1-4 K11: no ledger: the verdict was never computed", "the delivery verdict for QA-3 was never computed", absent)
            check_in("RD1-4 K11: and it names the door", "run check_delivery.py", absent)
            check_not_in("RD1-4 K11: and never a word `no` for a ledger that is not there", "is `no`", absent)
            check_not_in("RD1-4 K11: nor `unknown` as a word", "is `unknown`", absent)
            ledger_file.write_text(json.dumps({"delivery_verdict": "no", "delivery_ready": False, "rows": [], "reasons": []}),
                                   encoding="utf-8")
            empty = SG.rule_delivery("QA-3", "this delivery command", None, None, {"stages": {"S8": {"status": "done"}}}) or ""
            check_in("RD1-4 K11: a ledger with no reasons says it records none", "the ledger records no reason", empty)
            check_in("RD1-4 K11: and its verdict word", "is `no`", empty)
            for word in ("yes", "after_checks"):
                ledger_file.write_text(json.dumps({"delivery_verdict": word, "delivery_ready": word == "yes", "rows": [],
                                                   "reasons": []}), encoding="utf-8")
                check_eq(f"RD1-4 K11: `{word}` still opens it (None)",
                         SG.rule_delivery("QA-3", "this delivery command", None, None, {"stages": {"S8": {"status": "done"}}}), None)
            ledger_file.write_text(saved_ledger, encoding="utf-8")
            check_eq("CX2-27 d2: a role dispatch (no match) is today's sentence",
                     "gate B comes after" in (SG.rule_delivery("QA-3", "dispatching qa-bug-reporter", None, None,
                                                               {"stages": {"S8": {"status": "pending"}}}) or ""), False)
            for label, stages in (("a string", "S8"), ("a list", ["S8"]), ("S8 a string", {"S8": "done"}), ("S8 with no status", {"S8": {}}),
                                  ("S8 status None", {"S8": {"status": None}})):
                story(stages)
                verdict, message = said("gh pr create --fill")
                check_eq(f"CX2-27 d3: `stages` is {label}: refused with the new sentence, never today's door",
                         (verdict, "gate B comes after S8" in message, "deliver with known gaps" in message), (2, True, False))
            story({"S8": {"status": "running"}})
            journal = RP.record(root, "journal.jsonl")
            journal.parent.mkdir(parents=True, exist_ok=True)
            journal.write_text(json.dumps({"event": "deliver_with_risks", "task": "QA-3", "reason": "release window"}) + "\n",
                               encoding="utf-8")
            check_eq("CX2-27 d4: S8 not done with a recorded deliver_with_risks: allowed (the verdict is not the sentence's)",
                     said("gh pr create --fill")[0], 0)
            journal.unlink()
            check_eq("CX2-27 d4 control: the same command without the line: refused",
                     said("gh pr create --fill")[0], 2)
            # d5: the door the sentence names opens - the same words moved to a file, the command split
            Path(root / "words.txt").write_text("gh pr create\n", encoding="utf-8")
            check_eq("CX2-27 d5: the words in a file and the command split pass",
                     [said(c)[0] for c in ("python scripts/x.py --words-file words.txt", "echo ok", "cat words.txt")], [0, 0, 0])
            check_eq("CX2-27 d5: the finding's own command (a function writing the answers) passes before gate B",
                     said(K8_COMMAND)[0], 0)
            check_eq("CX2-27 d5 control: `$gh pr create` before gate B is still refused", said("gh=gh; $gh pr create")[0], 2)
    finally:
        cleanup(root)


_BS, _PIPE, _FORM = chr(92), "|", "gh pr create"
# OH3-22 (K2, t-229 N2): what the shell only STORES is text to the gate (want None), what it RUNS stays a delivery (want a
# match). Newlines are real; the pipe is spelled by a name so the table reads in a markdown-free file.
OH3_22_TEXT = {
    "b1": "cat > answers.txt <<'EOF'\nok, gh pr create later\nEOF",
    "b2": "python story_run.py answer --words-file - <<'EOF'\nyes, then glab mr create the fix\nEOF",
    "b3": 'python story_run.py answer --text "yes; glab mr create"',
    "b5": "cat >> conftest.py <<'EOF'\nsource, target = project(), project()  # mr create\nEOF",
    "b6": "def log(a): foo(b), create_mr()",
    "b7": "$x = @'\ngh pr create\n'@",
    "b8": 'cat <<< "gh pr create"',
    "b9": "cat > answers.txt <<'EOF'\n" + chr(0x434) + chr(0x430) + ", gh pr create " + chr(0x43f) + chr(0x43e) + "\nEOF",
    "b10": "cat > a <<'E'\nit's\nE\ncat > b <<'E'\ngh pr create\nE",
    "b11": "cat > a.md <<E\nplain gh pr create text\nE\ntee b.md <<'E'\nglab mr create\nE",
    # round 2 controls: the same shapes with the blank, the quote or the line the shell reads as the scan does stay text
    "o2 c1 plain": "cat <<'E'\n" + _FORM + "\nE",
    "o2 c2 redirect": "cat > n.txt <<'E'\n" + _FORM + "\nE",
    "o2 c3 tab before": "cat\t<<'E'\n" + _FORM + "\nE",
    "o2 c4 earlier plain line": "echo hi\ncat <<'E'\n" + _FORM + "\nE",
    "o2 c5 earlier closed quotes": 'echo "it\'s" \'a "b"\'\ncat > n.md <<\'E\'\n' + _FORM + "\nE",
    "o2 c6 earlier substitution": "x=$(echo a)\ncat > n.md <<'E'\n" + _FORM + "\nE",
    "k12b": "python x.py --a $(f) --b $(g)",
    "run-py": "run-py x.py --words-file - <<'E'\ngh pr create\nE",
}
OH3_22_RUNS = {
    "r1": 'bash -c "gh pr create"',
    "r2a": "python - <<'EOF'\ngh pr create\nEOF",
    "r2b": "python <<'EOF'\ngh pr create\nEOF",
    "r2c": "python -X utf8 - <<'EOF'\ngh pr create\nEOF",
    "r2d": "python /dev/stdin <<'E'\nimport os; os.system(\"gh pr create\")\nE",
    "g0 continuation": "cat <<'E' " + _BS + "\n" + _PIPE + " sh\ngh pr create\nE",
    "g0 continuation and": "cat <<'E' " + _BS + "\n&& gh pr create\nE",
    "g0 region over the line": "cat <<'E' $(\ntrue\n) " + _PIPE + " sh\ngh pr create\nE",
    "g0 ansi-c quote": "echo $'a" + _BS + "' <<E '\ngh pr create\nE",
    "g0 backtick": "cat `<<E`\ngh pr create\nE",
    "g0 dq with backslash": 'echo "' + _BS + '" x" <<E "\ngh pr create\nE',
    "g0 stop-parsing": "cat --% <<E\ngh pr create\nE",
    "g0 pipe at line end": "cat <<'E' " + _PIPE + "\ngh pr create\nE\nsh",
    "g0 pipe-and": "cat <<'E' " + _PIPE + "& sh\ngh pr create\nE",
    "g1 comment": "# <<'X'\ngh pr create\nX",
    "g1 arithmetic": "$((1<<X))\ngh pr create\nX",
    "g1 region": "eval $(cat <<'E'\ngh pr create\nE\n)",
    "g2 crlf": "cat <<'E'\r\nx\r\nE\r\ngh pr create",
    "g2 unterminated": "cat <<'E'\ngh pr create",
    "g3 quoted separator": "bash \"a;b\" <<'E'\ngh pr create\nE",
    "g3 python option": "python -X \"a;b\" <<'E'\ngh pr create\nE",
    "g3 ssh": "ssh host <<'E'\ngh pr create\nE",
    "g3 sudo sh": "sudo sh <<'E'\ngh pr create\nE",
    "g3 source": "source /dev/stdin <<'E'\ngh pr create\nE",
    "g3 dot": ". /dev/stdin <<'E'\ngh pr create\nE",
    "g3 while read": "while read l; do $l; done <<'E'\ngh pr create\nE",
    "g3 docker": "docker exec -i c sh <<'E'\ngh pr create\nE",
    "g3 arithmetic program": "((1<<X))\ngh pr create\nX",
    "g4 sh": "cat <<'E' " + _PIPE + " sh\ngh pr create\nE",
    "g4 tee python": "cat <<'E' " + _PIPE + " tee f " + _PIPE + " python\ngh pr create\nE",
    "g4 group": "( cat <<'E'\ngh pr create\nE\n) " + _PIPE + " sh",
    "g4 braces": "{ cat <<'E'\ngh pr create\nE\n} " + _PIPE + " bash",
    "g4 xargs": "cat <<'E' " + _PIPE + " xargs -I{} sh -c {}\ngh pr create\nE",
    "g4 braces pipe-and": "{ cat <<'E'\ngh pr create\nE\n} " + _PIPE + "& sh",
    "g5 tee": "tee >(sh) <<'E'\ngh pr create\nE",
    "g5 redirect": "cat <<'E' > >(sh)\ngh pr create\nE",
    "g5 exec": "exec 3> >(sh); cat <<'E' >&3\ngh pr create\nE",
    "g5 group": "{ cat <<'E'\ngh pr create\nE\n} > >(sh)",
    "g6 unquoted delimiter": "cat <<E\n$(gh pr create)\nE",
    # round 2 (t-229-2): each row below was RUN by a real shell (Git Bash 5.2.37, Windows PowerShell 5.1) with a `gh` function
    # that prints a marker, and the line after the operator ran. PowerShell 7 is not measured.
    "o2 f1 escaped op echo": "echo " + _BS + "<<E\n" + _FORM + "\nE",
    "o2 f1 escaped op cat": "cat " + _BS + "<<E\n" + _FORM + "\nE",
    "o2 f2 arithmetic bracket": "echo $[1<<E]\n" + _FORM + "\nE",
    "o2 f2 substring offset": "x=abc; echo ${x:1<<E}\n" + _FORM + "\nE",
    "o2 f2 array index": "echo ${a[1<<E]}\n" + _FORM + "\nE",
    "o2 f2 nested dq inline": 'echo "${x:-"<<E"}"\n' + _FORM + "\nE",
    "o2 f2 nested dq split": 'echo "${x:-" <<E\n"}"; ' + _FORM + "\nE",
    "o2 f2 arithmetic expansion": "echo $((1<<E))\n" + _FORM + "\nE",
    "o2 f2 arithmetic command": "((1<<E))\n" + _FORM + "\nE",
    "o2 f3 ansi-c on an earlier line": "echo $'a" + _BS + "'\ncat <<E\n'; " + _FORM + "\nE",
    "o2 f3 ansi-c quoted delimiter": "echo $'a" + _BS + "'\ncat <<'E'\n'; " + _FORM + "\nE",
    "o2 f3 nested dq on an earlier line": 'echo "${x:-"\ncat <<E\n"}"; ' + _FORM + "\nE",
    "o2 f3 escaped dq on an earlier line": "echo " + _BS + '" "\ncat <<E\n"; ' + _FORM + "\nE",
    "o2 f3b continuation joins the closer": "cat <<E\nE" + _BS + "\n\n" + _FORM + "\nE",
    "o2 f3b continuation joins the closer crlf": "cat <<E\r\nE" + _BS + "\r\n\r\n" + _FORM + "\r\nE",
    "o2 f4 glued word": "cat a<<E\n" + _FORM + "\nE",
    "o2 f4 glued word quoted": "cat a<<'E'\n" + _FORM + "\nE",
    "o2 f4 glued after redirect": "cat >f<<'E'\n" + _FORM + "\nE",
    "o2 f4 glued after file": "cat > n.txt<<'E'\n" + _FORM + "\nE",
    "o2 f4 glued after script": "python x.py a<<'E'\n" + _FORM + "\nE",
    "o2 f4 glued after flag": "cat -n<<E\n" + _FORM + "\nE",
    "o2 f4 glued after path": "cat /x<<E\n" + _FORM + "\nE",
    "o2 f4 glued after variable": "echo $x<<E\n" + _FORM + "\nE",
    "o2 f4 glued after assignment": "echo a=<<E\n" + _FORM + "\nE",
    "o2 f4 glued after quoted word": 'echo "x"#<<E\n' + _FORM + "\nE",
    "h pipe iex": "@'\ngh pr create\n'@ " + _PIPE + " iex",
    "h iex": "iex @'\ngh pr create\n'@",
    "h variable iex": "$c = @'\ngh pr create\n'@; iex $c",
    "h comment": "# @'\ngh pr create\n'@",
    "h sh -c": "sh -c @'\ngh pr create\n'@",
    "h eval": "eval @'\ngh pr create\n'@",
    "r4": "@'\nit's\ngh pr create\n'@",
    "r5a": "python -c \"os.system('gh pr create')\"",
    "r5b": 'python -m x "gh pr create"',
    "r5c": 'python - "gh pr create"',
    "r5d": 'python "-c" "gh pr create"',
    "r5e": 'python $S "gh pr create"',
    "r5f": 'python $(x) "gh pr create"',
    "r5g": 'python x.py bash -c "gh pr create"',
    "r6a": 'eval "gh pr create"',
    "r6b": "git -c alias.x='!gh pr create' x",
    "r6c": 'ssh host "gh pr create"',
    "r7": "cat <<'E' && gh pr create\nbody\nE",
    "r8a": "GH$(x) pr create",
    "r8b": "/usr/bin/$(x) pr create",
    "r8c": "C:" + _BS + "t" + _BS + "$(x).exe pr create",
    "r8d": "$(x).exe pr create",
    "r8e": "gh --repo=$(r) pr create",
    "r8f": "g$(x) pr create",
}


def part_oh3_22_bodies() -> None:
    """OH3-22 (K2): `SG._delivery_match(c, None)` with a body only stored, with a body run, and the rules that read the
    executable text (commit, stash, typed runner). Error direction: a body the shell may run stays a refusal."""
    for key, command in OH3_22_TEXT.items():
        check_eq(f"OH3-22 {key}: a stored body or an argument is no delivery", SG._delivery_match(command, None), None)
    for key, command in OH3_22_RUNS.items():
        check(f"OH3-22 {key}: what the shell runs is still a delivery", SG._delivery_match(command, None) is not None, command)
    check_eq("OH3-22 shown form: a here-string body that the shell runs names the form",
             SG._delivery_match(OH3_22_RUNS["r4"], None)[0], "gh pr create")
    # r9: a damaged table takes nothing out (the floor has no receiver): b1 is a delivery again
    work = temp_project()
    saved = AF.TABLE_PATH
    try:
        bad = Path(work) / "adapter-forms.json"
        bad.write_text("{not json", encoding="utf-8")
        AF.TABLE_PATH = bad
        check("OH3-22 r9: a damaged table takes no body out", SG._delivery_match(OH3_22_TEXT["b1"], None) is not None)
        check_eq("OH3-22 r9: ...and the receivers read as none", (AF.text_receivers(), AF.script_runners(), AF.script_plain_flags()),
                 ((), (), ()))
    finally:
        AF.TABLE_PATH = saved
        cleanup(work)
    check_eq("OH3-22 r9: with the table back the body comes out again", SG._delivery_match(OH3_22_TEXT["b1"], None), None)
    # commit and stash: a body that holds the words is no commit and no stash; a body a shell runs still is
    check_eq("OH3-22 commit: `git commit` in a stored body", SG.command_shapes("cat > n.md <<'E'\ngit commit -m x tests/a.py\nE"), [])
    check_eq("OH3-22 stash: `git stash` in a stored body", SG.command_shapes("cat > n.md <<'E'\ngit stash\nE"), [])
    check_eq("OH3-22 commit: -F - from stdin is a commit", SG.command_shapes("git commit -F - tests/a.py <<'E'\nmsg\nE"), ["commit"])
    check_eq("OH3-22 commit: bash <<E runs its body", SG.command_shapes("bash <<'E'\ngit commit -m x tests/a.py\nE"), ["commit"])
    # typed runner: the body is text, the launch is not
    event = {"cwd": str(PLUGIN_ROOT), "tool_input": {}}
    active = {"dispatches": {"d-1": {"id": "d-1", "status": "running", "scope": ["i-1"]}}}
    check_eq("OH3-22 runner: a stored body naming the runner is no launch",
             SG.rule_typed_runner(SG._executable_text("cat > n.md <<'E'\nrun_suite.py --task X\nE", "bash"), event, "X", active), "")
    check("OH3-22 runner: a bare launch is still refused",
          SG.rule_typed_runner(SG._executable_text("python run_suite.py --task X --label all", "bash"), event, "X", active) != "")
    check("OH3-22 runner: an interpreter's body is still a launch",
          SG.rule_typed_runner(SG._executable_text("python - <<'E'\nrun_suite.py --task X\nE", "bash"), event, "X", active) != "")
    # round 2 (F1): an escaped operator opens no body, so the commit, the stash and the runner shapes read the next line too
    check_eq("OH3-22 o2 commit: `\\<<E` is a redirect, the next line runs",
             SG.command_shapes("cat " + _BS + "<<E\ngit commit -m x tests/a.py\nE"), ["commit"])
    check_eq("OH3-22 o2 stash: `\\<<E` is a redirect, the next line runs", SG.command_shapes("cat " + _BS + "<<E\ngit stash\nE"), ["stash"])
    check("OH3-22 o2 runner: `\\<<E` is a redirect, the next line launches",
          SG.rule_typed_runner(SG._executable_text("cat " + _BS + "<<E\nrun_suite.py --task X\nE", "bash"), event, "X", active) != "")
    # round 2 (F4): in PowerShell 5.1 a `<<` glued to a word is a plain token, so the body is taken out in bash only
    glued = "cat > n.txt<<'E'\nx\nE"
    check_eq("OH3-22 o2 glued: bash takes the stored body out", SG._executable_text(glued, "bash"), "cat > n.txt<<'E'")
    check_eq("OH3-22 o2 glued: PowerShell keeps the text whole", SG._executable_text(glued, "powershell"), glued)
    check_eq("OH3-22 o2 blank before: PowerShell takes the body out",
             SG._executable_text("cat > n.txt <<'E'\nx\nE", "powershell"), "cat > n.txt <<'E'")
    check_eq("OH3-22 o2 tab before: PowerShell takes the body out",
             SG._executable_text("cat\t<<'E'\nx\nE", "powershell"), "cat\t<<'E'")
    # the view of the text: nothing taken is the same string; the body is gone from a stored one only
    check_eq("OH3-22 a command with no body is itself", SG._executable_text("git status", "bash"), "git status")
    check_eq("OH3-22 None and empty are no body", (SG._executable_text(None, "bash"), SG._executable_text("", "powershell")), ("", ""))
    check_eq("OH3-22 the operator's line stays, the body and the closer go",
             SG._executable_text("cat > a <<'E'\nx\nE", "bash"), "cat > a <<'E'")
    check_eq("OH3-22 PowerShell reads a plain `<<` body out too (M-1: that script runs nothing)",
             SG._executable_text("cat > a <<'E'\nx\nE", "powershell"), "cat > a <<'E'")
    # script_run, by tokens
    def run(command: str) -> bool:
        return SG.script_run(hooklib.walk(command, "bash")[0].segments[0])
    for command, want in (("python x.py a", True), ("python3.11 -B -u x.py", True), ("py $P/x.py", True),
                          ('python "$P/x.py" a', True), ("run-py x.py", True), ("FOO=1 python x.py", True),
                          ("python -", False), ("python -c x.py", False), ("python -X utf8 x.py", False), ("python", False),
                          ("python x.txt", False), ("python $S", False), ("python $(x)/a.py", False), ("python x.py sh", False),
                          ("python /dev/stdin", False), ("python CON", False), ("cat x.py", False), ("pythonish x.py", False),
                          # r0107 clones: the head is read by adapter_forms.head_at (`NAME=` is [A-Za-z_][A-Za-z0-9_]*): a dotted,
                          # dashed or digit-leading word is no assignment, so it is the head and no launcher; a head whose first
                          # path component holds `=` names no program (head_program), a later component does not
                          ("FOO_1=1 BAR=2 python x.py", True), ("a.b=1 python x.py", False), ("-x=1 python x.py", False),
                          ("1x=1 python x.py", False), ("A=1", False), ("a.b=/x/python x.py", False),
                          ("-x=/usr/bin/python x.py", False), ("1x=/usr/bin/python3.11 x.py", False), ("a.b=/x/run-py x.py", False),
                          ("a.b=/x/python -B x.py", False), ("./a=b/python x.py", True), ("/a=b/python x.py", True)):
        check_eq(f"OH3-22 script_run {command!r}", run(command), want)
    # r0107 clones (critic F1/F5): the head reader is the guard's one; every row below was refused at 268e7608 or is a control
    def receiver(command: str) -> bool:
        return SG._text_receiver(hooklib.walk(command, "bash")[0].segments[0])
    for command, want in (("a.b=1 cat", False), ("a.b=/bin/cat", False), ("-x=/bin/tee n", False), ("a.b=/x/python x.py", False),
                          ("FOO=1 cat", True), ("cat", True), ("./a=b/cat", True), ("a.b=1", False)):
        check_eq(f"r0107 _text_receiver {command!r}", receiver(command), want)
    body = "\ngh pr create\nE\n"
    for command in ('a.b=/x/python x.py "gh pr create"', '-x=/usr/bin/python x.py "gh pr create"',
                    '1x=/usr/bin/python3.11 x.py "gh pr create"', 'a.b=/x/run-py x.py "gh pr create"',
                    'a.b=/x/python -B x.py "gh pr create"', "a.b=/bin/cat > n.txt <<'E'" + body, "-x=/bin/tee n.txt <<'E'" + body,
                    "1x=/bin/wc <<'E'" + body, "a.b=/x/python x.py <<'E'" + body, "a.b=1 cat > n <<'E'" + body,
                    'a.b=/bin/echo "gh pr create"', '-x=/bin/grep "gh pr create"', 'a.b=1 echo "gh pr create"',
                    'a.b=1 python x.py "gh pr create"'):
        check("r0107 refused: " + repr(command), SG._delivery_match(command, None) is not None, command)
    for command in ("cat > n.txt <<'E'" + body, "FOO=1 cat > n.txt <<'E'" + body, 'echo "gh pr create"', 'FOO=1 echo "gh pr create"',
                    "git -c x=1 status"):
        check_eq("r0107 control passes: " + repr(command), SG._delivery_match(command, None), None)
    # _git_words (critic F4): the same head reader; `a.b=/bin/echo git commit` stays a commit as at base, an echo head is text
    for command, want in (("git commit -m x tests/t.py", True), ("a.b=/bin/echo git commit -m x tests/t.py", True),
                          ("a.b=/usr/bin/git commit -m x tests/t.py", True), ("-x=/usr/bin/git commit -m x tests/t.py", True),
                          ("a.b=1 git commit -m x tests/t.py", True), ("FOO=/usr/bin/git commit -m x tests/t.py", True),
                          ("echo git commit tests/t.py", False), ("FOO=1 echo git commit tests/t.py", False),
                          ("git status", False)):
        check_eq("r0107 commit shape " + repr(command), SG._is_commit_shape(command, {}, {"tool_name": "Bash"}), want)
    # _payload_text keeps the wide key (a key prefix on a quoted argument is no assignment): narrowing it would pass these
    for command in ("git -c 'alias.x=!gh pr create' x", "foo --cmd='gh pr create'", "foo '--cmd=gh pr create'", "CMD='gh pr create' foo"):
        check("r0107 payload key: " + repr(command), SG._delivery_match(command, None) is not None, command)
    # magnitude: closed heredocs are linear (10x the input under 25x the time) and a 64 KB command is read, not skipped
    import time
    def cost(count: int) -> float:
        text = "cat > f <<'E'\nx\nE\n" * count + "echo done"
        start = time.perf_counter()
        SG._executable_text(text + " " * count, "bash")   # the blanks defeat the cache of an earlier count
        return time.perf_counter() - start
    small, large = max(cost(100), 1e-3), cost(1000)
    check("OH3-22 magnitude: 10x the heredocs under 25x the time", large < 25 * small, f"{small:.4f}s -> {large:.4f}s")
    wide = "cat > f <<'E'\n" + ("x" * 60000) + "\ngh pr create\nE"
    check_eq("OH3-22 a 64 KB body is read and comes out", SG._delivery_match(wide, None), None)
    check_in("OH3-22 a 64 KB body that a shell runs is still refused", "gh pr create",
             SG._delivery_match("bash <<'E'\n" + ("x" * 60000) + "\ngh pr create\nE", None)[0])


# OH3-32 (K3): `hooklib.shell_opaque_found`; the value is the sequence the refusal names ("" = nothing found). A backslash
# before `|`, `;`, `&` inside a quoted run, in BOTH readings, is text; every other member and every unquoted one is not.
# Values come from the shell rules (bash keeps the backslash in '...' and before these characters in "...";
# PowerShell has no backslash escape), not from running the code (FR-58).
OH3_32_ROWS = [
    ("q1", 'ls "$S" | grep -i "probe\\|fingerprint\\|provenance\\|stand"', ""),
    ("q2", "x | grep -o '\"totals\".*\"skip_reasons\"\\|\"summary_path\".*'", ""),
    ("q3", "echo a \\| b", "a backslash before `|`"),
    ("q5", 'grep "a\\|b" f; x\\&y', "a backslash before `&`"),
    ("q6", 'grep "a\\|b\\(c" f', "a backslash before `(`"),
    ("q7", 'grep "a\\"\\|b"', "a backslash before `\"`"),
    ("q10", 'echo "$(echo "a\\|b")"', ""),
    ("q10b", '"a\\\\|b"', ""),
    ("q10c", "'a\\\\|b'", ""),
    ("q12", '# it\'s "a\\|b"', "a backslash before `|`"),
    ("q13", "python -X 'a'\\|cat run_suite.py --task X", "a backslash before `|`"),
    ("q13b", "python -X a\\&cat run_suite.py --task X", "a backslash before `&`"),
    ("q18", 'grep "\u0436\u0443\\|\u0434\u0443" f', ""),
    ("semicolon", "grep 'a\\;b' f", ""),
    ("ampersand", 'grep "a\\&b" f', ""),
    ("a quoted pair is no cover for the unquoted one after it", 'grep "a\\|b" f\\|g', "a backslash before `|`"),
    ("a typographic quote behind a quoted pipe", 'grep "a\\|b\u201c" f', "the typographic quote U+201C"),
]


def part_oh3_32_quoted_backslash() -> None:
    """OH3-32 (K3): the ban reads quotes. Error direction: a backslash stays banned; never a member the shell reads as
    code is exempted. The mutations: `search` for `finditer` (q5), the exemption stretched to `\\"` (q7), the new door
    shown outside quotes (the door rows)."""
    for key, command, want in OH3_32_ROWS:
        what, door = hooklib.shell_opaque_found(command)
        if want:
            check_in(f"OH3-32 {key}: refused, and the refusal names the member", want, what)
            check(f"OH3-32 {key}: ...with a door", bool(door), command)
        else:
            check_eq(f"OH3-32 {key}: quoted text is no hit", (what, door), ("", ""))
    # the doors: a quoted hit gets the quote door, an unquoted one today's, byte for byte
    quoted_door = hooklib.shell_opaque_found(OH3_32_ROWS[4][1])[1]
    for phrase in ("already in quotes", "forward slashes (C:/p/(1)/x)", "[(] for"):
        check_in(f"OH3-32 door: a quoted `\\(` gets the quote door ({phrase})", phrase, quoted_door)
    check_eq("OH3-32 door: an unquoted backslash keeps today's door byte for byte",
             hooklib.shell_opaque_found(OH3_32_ROWS[2][1])[1], hooklib._DOOR_BACKSLASH)
    check_not_in("OH3-32 door: ...and says nothing of quotes it is not in", "already in quotes",
                 hooklib.shell_opaque_found(OH3_32_ROWS[2][1])[1])
    # the same rows through the runner guard (a running dispatch): the ban's own text, and the slices still judge the rest
    event = {"cwd": str(PLUGIN_ROOT), "tool_input": {}}
    active = {"dispatches": {"d-1": {"id": "d-1", "status": "running", "scope": ["i-1"]}}}
    check_eq("OH3-32 q1 through the runner guard: an ordinary grep with a quoted alternation passes",
             SG.rule_typed_runner(OH3_32_ROWS[0][1], event, "X", active), "")
    for key, command in (("q13", OH3_32_ROWS[10][1]), ("q13b", OH3_32_ROWS[11][1])):
        check_in(f"OH3-32 {key}: the runner guard still refuses the launch hidden in a backslash", "run_suite.py --request FILE",
                 SG.rule_typed_runner(command, event, "X", active))
    check("OH3-32 q14: a quoted alternation frees no launch behind it (the slices judge it)",
          SG.rule_typed_runner('grep "a\\|b" f; python run_suite.py --task X', event, "X", active) != "")
    check_in("OH3-32 q6 through the runner guard: the refusal carries the quote door", "already in quotes",
             SG.rule_typed_runner(OH3_32_ROWS[4][1], event, "X", active))
    # no dispatch, no read (R22): unchanged
    check_eq("OH3-32 no running dispatch: a quoted alternation is not touched",
             SG.rule_typed_runner(OH3_32_ROWS[4][1], event, "X", {}), "")
    # the whole check: a walker that fails on the text is the guard's door, never a pass (AR-25, AR-28)
    def boom(self):
        raise IndexError("k3 synthetic")
    raised = []
    with reader_patched("_run", lambda real: boom):
        for _ in range(2):
            try:
                hooklib.shell_opaque_found(OH3_32_ROWS[0][1])
                raised.append(None)
            except hooklib.WalkerError as exc:
                raised.append(str(exc))
    check_eq("OH3-32 a failing walker is a WalkerError out of the ban both times, not a pass", raised,
             ["IndexError: k3 synthetic"] * 2)
    check_eq("OH3-32 control: the restored walker reads the same text", hooklib.shell_opaque_found(OH3_32_ROWS[0][1]), ("", ""))
    # at and beyond the limit (guard_pre_tool.MAX_COMMAND_CHARS, 64 KB: `size_check` refuses beyond it before any read):
    # a command AT the limit is read and judged, the hit after the cap-sized quoted run is still found
    cap = 64 * 1024
    at_limit = 'grep "' + "a\\|" * ((cap - 10) // 3) + '" f'
    check("OH3-32 a command at the 64 KB limit is no longer than it", len(at_limit) <= cap, str(len(at_limit)))
    check_eq("OH3-32 at the limit: its quoted pipes are text", hooklib.shell_opaque_found(at_limit), ("", ""))
    check_in("OH3-32 at the limit: an unquoted pipe after them is still found", "a backslash before `|`",
             hooklib.shell_opaque_found(at_limit + " x\\|y")[0])


def part_commit_shape() -> None:
    """B-407 A4 (K-A5, K-A2): the commit shape is read by SEGMENT, in the dialect of the tool, and the test-file half is
    `test_files.is_test_for("commit")`: names and folders are data, the project's word counts, and the old regex over
    the raw command text is gone."""
    root = temp_project("qa-factory-commit-")
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.update(app_root=".", protected_app_paths=["src"], test_locations=["src/legacy/"])
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    (root / "src" / "legacy").mkdir(parents=True)
    bash = {"tool_name": "Bash", "cwd": str(root)}
    power = {"tool_name": "PowerShell", "cwd": str(root)}

    def shape(command: str, event=bash, config=None) -> bool:
        return SG._is_commit_shape(command, config, event)

    try:
        with hooklib.selftest_root_restored():
            use_project(root)
            check_eq("A4: TEST_FILE_RE is gone and the tokenizer is the public name",
                     (hasattr(SG, "TEST_FILE_RE"), SG._walk is hooklib.walk), (False, True))   # CX1-20: the one walker (was the tokenizer's public name)
            # --- K-A2: every sample the old regex matched, in its commit form, is still a commit shape ---
            old = ("tests/a.py", "test/a.py", "spec/a.js", "e2e/a.ts", "x/tests/y/z.py", "test_a.py", "test_a-b.js", "a_test.py",
                   "a_test.go", "a.spec.ts", "a.spec.tsx", "test-harness/x.py", "qa-factory/artifacts/QA-1/test-plan.md")
            check_eq("K-A2: every sample of the old test-file regex (and the factory path) is still a commit shape",
                     [p for p in old if not shape(f"git commit -m x {p}")], [])
            check_eq("K-A2: ... after `--` too, and quoted", [p for p in old if not shape(f'git commit -m x -- "{p}"')], [])
            # --- E-A4 (F-3): the narrowing, each name with its reason ---
            narrowed = ("contest_x.py", "latest_report.py", "my_test_foo.py", "pytest_plugin.py", "protest_utils.py",
                        "foo_test.py.bak", "README.md", "src/app.py")
            check_eq("E-A4: names the old regex found INSIDE longer words are no test: `test_` in contest_x, latest_report, "
                     "pytest_plugin, protest_utils; `_test.py` in foo_test.py.bak", [p for p in narrowed if shape(f"git commit -m x {p}")], [])
            check_eq("E-A4: a test path that stands in a segment that is no commit or add is no commit shape (analog 1)",
                     [shape("pytest tests/x.py && git commit -m x"), shape("python tests/test_a.py; git commit -m x")], [False, False])
            check_eq("E-A4: the message is not a path (the value of -m is skipped)",
                     [shape('git commit -m "add tests/x.py"'), shape("git commit --message=tests/x.py"),
                      shape("git commit -F tests/x.py")], [False, False, False])
            check_eq("E-A4: a bare commit names nothing", [shape("git commit -m x"), shape("git commit --amend")], [False, False])
            # --- widening ---
            wide = ("Tests/a.py", "specs/a.js", "__tests__/a.ts", "test-harness/x.py", "src/FooTests.cs", "FooTest.java", "UITest.cs",
                    "FooIT.java", "FooSpec.scala", "test_a.go", "test_a.json", "src/Foo.Tests/BarTests.cs", "tests/")
            check_eq("E-A4 widening: folders in any case, camel names, test_*.go/.json, a folder with a trailing slash",
                     [p for p in wide if not shape(f"git commit -m x {p}")], [])
            check_eq("E-A4 widening: `git commit -m x -- src/Foo.Tests/BarTests.cs` is a commit", shape("git commit -m x -- src/Foo.Tests/BarTests.cs"), True)
            check_eq("E-A8 on the commit shape: Test.java, AUDIT.java, Latest.java, MyTEST.cs, Contest.cs are not",
                     [p for p in ("Test.java", "AUDIT.java", "Latest.java", "MyTEST.cs", "Contest.cs") if shape(f"git commit -m x {p}")], [])
            check_eq("E-A9: `.`, empty and an option are no path", [shape("git commit -m x ."), shape('git commit -m x ""'),
                                                                   shape("git commit -a -m x")], [False, False, False])
            # --- E-A3: an add segment names the paths of a bare commit ---
            check_eq("E-A3: `git add tests/x.py && git commit -m x` is a commit shape (the add names the path)",
                     shape("git add tests/x.py && git commit -m x"), True)
            check_eq("E-A3: ... also across `;` and newline, and with `git add -- tests/x.py`",
                     [shape("git add tests/x.py; git commit -m x"), shape("git add tests/x.py\ngit commit -m x"),
                      shape("git add -- tests/x.py && git commit -m x")], [True, True, True])
            check_eq("E-A3: an add of a doc names no test; an add alone is no commit",
                     [shape("git add README.md && git commit -m x"), shape("git add tests/x.py"),
                      shape("git add -A && git commit -m x")], [False, False, False])
            # --- K-A5: a backslash path survives (no shell-grammar posix reading), in both dialects ---
            check_eq("K-A5: `git commit -m x tests\\test_a.py` is a commit shape in bash and in PowerShell",
                     [shape("git commit -m x tests\\test_a.py", e) for e in (bash, power)], [True, True])
            check_eq("K-A5: `git add tests\\x.py && git commit -m x`", [shape("git add tests\\x.py && git commit -m x", e) for e in (bash, power)],
                     [True, True])
            check_eq("K-A5: a backslash path of a doc is no test", shape("git commit -m x docs\\a.md", power), False)
            check_eq("K-A5: PowerShell `-m 'it''s'` with a test path after it",
                     shape("git commit -m 'it''s' tests/x.py", power), True)
            # --- E-A10: only a real git commit meets the rules ---
            check_eq("E-A10: a delivery whose body names a commit of tests is no commit",
                     [shape('glab mr create --body "see: git commit -m x tests/x.py"'),
                      shape('gh pr create --body "git commit -m x tests/x.py"'),
                      shape("echo git commit -m x tests/x.py"), shape('echo "git commit -m x tests/x.py"'),
                      shape("grep -rn 'git commit tests/x.py' docs")], [False] * 5)
            check_eq("E-A10: a shell that runs a quoted command, and a $( ) region, are commits (never narrower than the substring)",
                     [shape('bash -c "git commit -m x tests/x.py"'), shape("eval 'git add tests/x.py && git commit -m x'"),
                      shape("echo $(git commit -m x tests/x.py)"), shape("FOO=1 git commit -m x tests/x.py"),
                      shape("sudo bash -lc 'git commit -m x tests/x.py'"), shape('pwsh -Command "git commit -m x tests\\a.py"', power)],
                     [True] * 6)
            wrapped = ("sudo git commit -m x tests/a.py", "env X=1 git commit -m x tests/a.py", "time git commit -m x tests/a.py",
                       "nohup git commit -m x tests/a.py", "command git commit -m x tests/a.py", "exec git commit -m x tests/a.py",
                       "! git commit -m x tests/a.py", "{ git commit -m x tests/a.py; }",
                       "if true; then git commit -m x tests/a.py; fi", "for f in x; do git commit -m x tests/a.py; done",
                       "sudo git add tests/a.py && git commit -m x", "/usr/bin/git commit -m x tests/a.py")
            check_eq("F1 (critic t-557): `git` stands anywhere in its segment, unquoted, behind a wrapper or a keyword: every form "
                     "main caught is a commit shape (the mutation 'git must be the first word' is killed here)",
                     [c for c in wrapped if not shape(c)], [])
            check_eq("F1: ... in PowerShell too", [shape(c, power) for c in ("& git commit -m x tests\\a.py", "sudo git commit -m x tests\\a.py")],
                     [True, True])
            check_eq("F1: a wrapped commit of a doc is still no commit shape; a mention command that names git is text",
                     [shape("sudo git commit -m x README.md"), shape("echo sudo git commit -m x tests/a.py"),
                      shape("printf '%s' git commit tests/a.py"), shape('sudo ssh host "git commit -m x tests/a.py"')],
                     [False, False, False, False])
            check_eq("E-A12: `git -C dir commit` and `git -c x=1 commit` are not recognised (as before); neither is a git alias",
                     [shape("git -C app commit -m x tests/x.py"), shape("git -c x=1 commit -m x tests/x.py"),
                      shape("sudo git -c x=1 commit -m x tests/x.py"), shape("git ci -m x tests/x.py")], [False] * 4)
            # --- E-A11: an unterminated quote is dropped by the tokenizer and the tail is read as unquoted words ---
            check_eq("E-A11: `git commit -m \"oops tests/x.py` (unterminated): the words after the quote are checked",
                     [shape('git commit -m "oops tests/x.py'), shape("git commit -m 'oops tests/x.py"),
                      shape('git commit -m "oops tests/x.py && echo ok')], [True, True, True])
            check_eq("E-A11: the same with no path in the tail is no commit shape (a command with an unterminated quote "
                     "is a syntax error to both shells and commits nothing)",
                     [shape('git commit -m "oops'), shape('git commit -m x README.md "oops')], [False, False])
            # --- the project's word, matched from the event's cwd ---
            check_eq("K-A5: a place the project named is a commit shape with its config, and not without it",
                     [shape("git commit -m x src/legacy/c.py", bash, cfg), shape("git commit -m x src/legacy/c.py", bash, {})],
                     [True, False])
            sub = dict(bash, cwd=str(root / "src" / "legacy"))
            check_eq("K-A5: a relative path is taken from the event's cwd", shape("git commit -m x c.py", sub, cfg), True)
            # --- the commit shapes of command_shapes, and the fast gate ---
            check_eq("command_shapes: a commit of tests, a delivery and a stash in one command, in the guard's order",
                     SG.command_shapes("git commit -m x tests/a.py && gh pr create && git stash", cfg, bash),
                     ["delivery", "commit", "stash"])
            check_eq("needs_stage_guard: every `git commit` passes the gate (the shape decides), nothing else of git does",
                     [SG.needs_stage_guard(c) for c in ("git commit -m x README.md", "git commit", "git status", "git log -1",
                                                        "git add tests/x.py", "ls -la")], [True, True, False, False, False, False])
            # --- E-A1: unreadable markers: a path the names cannot judge counts (the guard errs toward checking) ---
            real_ref = hooklib.ref
            import tempfile
            empty = Path(tempfile.mkdtemp(prefix="qa-sg-nomarkers-"))
            try:
                hooklib.ref = lambda rel: empty / rel if rel == "test-path-markers.json" else real_ref(rel)
                with contextlib.redirect_stderr(io.StringIO()) as note:
                    got = [shape("git commit -m x README.md"), shape("git commit -m x"), shape("git commit -m x tests/a.py")]
                check_eq("E-A1: with the markers unreadable a commit that names any path is checked; a bare commit still names none",
                         got, [True, False, True])
                check_in("E-A1: ... and one note on stderr names the file", "test-path-markers.json", note.getvalue())
            finally:
                hooklib.ref = real_ref
                cleanup(empty)
            # --- E-A2, positional: nothing is read for a command without `git commit` ---
            real_load = hooklib.load_ref_json
            reads: list = []

            def loader(name):
                if name == "test-path-markers.json":
                    reads.append(name)
                    raise OSError("the markers loader raises")
                return real_load(name)
            hooklib.load_ref_json = loader
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    quiet = [SG.needs_stage_guard("ls -la"), SG.command_shapes("ls -la", cfg, bash), SG.command_shapes("git status", cfg, bash),
                             SG.command_shapes("python -m pytest tests/test_a.py", cfg, bash)]
                    check_eq("E-A2: a loader that raises is never reached by commands without `git commit`", (quiet, reads),
                             ([False, [], [], []], []))
                    check_eq("E-A2 control: the same loader IS reached by a commit, which then errs toward checking",
                             (SG.command_shapes("git commit -m x README.md", cfg, bash), bool(reads)), (["commit"], True))
            finally:
                hooklib.load_ref_json = real_load
    finally:
        cleanup(root)


def part_guard_crash() -> None:
    """RH1-5 B7 (owner's word 27.10.2026, F-9): a crash of the guard BEFORE a verdict allows and leaves exactly one
    `guard_crashed` signal (any tool); a crash AFTER `deny(...)` has spoken denies (E15); the walker's deny stays (control);
    the advices H2/H3 are queued for the model, not printed to stderr."""
    root = temp_project("qa-sg-crash-")
    real_check = SG._check
    try:
        use_project(root)
        journal = RP.record(root, "journal.jsonl")

        def crashes() -> list:
            if not journal.is_file():
                return []
            return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
                    if json.loads(line).get("kind") == "guard_crashed"]

        def boom(event):
            raise ValueError("synthetic guard failure")
        SG._check = boom
        for tool in ("Bash", "Agent", "SendMessage"):
            before = len(crashes())
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = SG.check({"tool_name": tool, "cwd": str(root), "session_id": "s-" + tool, "tool_input": {}})
            rows = crashes()
            check_eq(f"K5 {tool}: a crash before a verdict is ALLOW", code, 0)
            check_eq(f"K5 {tool}: exactly one guard_crashed signal", len(rows) - before, 1)
            check_in(f"K5 {tool}: it names the tool and the exception", f"{tool}: ValueError: synthetic guard failure", rows[-1]["notes"])
            check_eq(f"K5 {tool}: nothing on stderr (it reached nobody before)", err.getvalue(), "")

        def deny_then_boom(event):
            SG.deny("the verdict is spoken")
            raise ValueError("a late crash")
        SG._check = deny_then_boom
        before = len(crashes())
        with contextlib.redirect_stderr(io.StringIO()):
            code = SG.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {}})
        check_eq("E15: a crash AFTER deny(...) is DENY, the verdict stands", code, 2)
        check_eq("E15: ...and no guard_crashed signal (the guard did speak)", len(crashes()) - before, 0)
        # LAST_DENIAL is cleared on entry: an earlier call's refusal is not this call's
        SG._check = boom
        with contextlib.redirect_stderr(io.StringIO()):
            code = SG.check({"tool_name": "Bash", "cwd": str(root), "tool_input": {}})
        check_eq("E15: the denial of the PREVIOUS call does not turn this crash into a deny", code, 0)
        # control: the walker failure is still the deny with its door (not the allow)
        SG._check = lambda event: (_ for _ in ()).throw(hooklib.WalkerError("walker"))
        with contextlib.redirect_stderr(io.StringIO()):
            check_eq("control: a WalkerError is still a DENY", SG.check({"tool_name": "Bash", "tool_input": {}}), 2)
        SG._check = real_check

        # H3: no pipeline.json in an onboarded project: the advice is QUEUED for the orchestrator, not printed
        del hooklib._NOTICES[:]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            SG.check({"tool_name": "Agent", "cwd": str(root), "tool_input": {"subagent_type": "qa-factory:qa-scout", "prompt": "x"}})
        check_eq("H3: nothing printed to stderr", err.getvalue(), "")
        check_eq("H3: one notice for the orchestrator, naming the missing pipeline",
                 [(reader, "no pipeline.json found" in text) for text, reader in hooklib._NOTICES], [("orchestrator", True)])
        del hooklib._NOTICES[:]
        (root / "qa-factory" / "config.json").unlink()
        with contextlib.redirect_stderr(io.StringIO()):
            SG.check({"tool_name": "Agent", "cwd": str(root), "tool_input": {"subagent_type": "qa-factory:qa-scout", "prompt": "x"}})
        check_eq("H3 (control): a project that is not onboarded gets no advice", list(hooklib._NOTICES), [])
    finally:
        SG._check = real_check
        del hooklib._NOTICES[:]
        cleanup(root)


def optional_dispatch_rows_checks() -> None:
    """t-2277 FL-5 (decision 3): the ONE reader of a stage's `optional_dispatches` rows - admits a (role, purpose) row, places the ONE running
    dispatch of the role on the stage, and is blind to everything else (negative controls inline)."""
    model = json.loads((PLUGIN_ROOT / "references" / "stages.json").read_text(encoding="utf-8"))
    row = SG.optional_row(model, "S3", "qa-runner", "first_look")
    check_eq("optional rows: S3 admits qa-runner with purpose first_look", (row or {}).get("role"), "qa-runner")
    for label, args in (("no purpose", ("S3", "qa-runner", "")), ("another purpose", ("S3", "qa-runner", "initial")),
                        ("another role", ("S3", "qa-scout", "first_look")), ("another stage", ("S6", "qa-runner", "first_look")),
                        ("an unknown stage", ("S99", "qa-runner", "first_look"))):
        check_eq(f"optional rows: {label} is not admitted", SG.optional_row(model, *args), None)
    check_eq("optional rows: a malformed list is no rows", SG.optional_rows({"optional_dispatches": [1, {"role": "x"}, "y", {"role": " ", "purpose": "p"}]}), [])
    check_eq("optional rows: the S3 stage's own roles are unchanged by them", SG.stages_of_role(model, "qa-runner")[-1]["id"], "S6")
    live = {"role": "qa-runner", "stage": "S3", "status": "running", "request_binding": {"purpose": "first_look"}}
    placed = SG.optional_stage_of_dispatch(model, "qa-runner", {"d1": live})
    check_eq("optional rows: the one running first-look dispatch stands on S3", (placed or [{}])[0].get("id"), "S3")
    check_eq("optional rows: a running plain runner stands nowhere optional", SG.optional_stage_of_dispatch(
        model, "qa-runner", {"d1": dict(live, stage="S6", request_binding={"purpose": "manual"})}), None)
    check_eq("optional rows: two running dispatches of the role are not established", SG.optional_stage_of_dispatch(
        model, "qa-runner", {"d1": live, "d2": dict(live)}), None)
    check_eq("optional rows: a finished dispatch is not placed", SG.optional_stage_of_dispatch(model, "qa-runner", {"d1": dict(live, status="accepted")}), None)
    check_eq("optional rows: a held name picks one of two", (SG.optional_stage_of_dispatch(model, "qa-runner", {"d1": live, "d2": dict(live)}, name="d2")
                                                           or [{}])[0].get("id"), "S3")
    check_eq("optional rows: a role no row names is never placed by them", SG.optional_stage_of_dispatch(model, "qa-scout", {"d1": dict(live, role="qa-scout")}), None)
    check_eq("optional rows: anything but a mapping of records is None", SG.optional_stage_of_dispatch(model, "qa-runner", ["x"]), None)
    # t-2181 PC-9b (critic t-2513 B2): the owed output and the admitted purposes are DATA of the row, read through the one reader
    check_eq("optional rows: the owed outputs are the rows' own `output` (S3 first look, S1 reference walk)",
             (SG.optional_outputs(SG.optional_row(model, "S3", "qa-runner", "first_look")),
              SG.optional_outputs(SG.optional_row(model, "S1", "qa-runner", "reference_walk"))),
             (("work/first-look.yaml",), ("work/reference-snapshot.yaml",)))
    check_eq("optional rows: a row with no output, a blank one or a non-mapping owes nothing",
             (SG.optional_outputs({"role": "r", "purpose": "p"}), SG.optional_outputs({"output": " "}), SG.optional_outputs(None)), ((), (), ()))
    check_eq("optional rows: a list of outputs is read whole, blanks dropped", SG.optional_outputs({"output": ["a.yaml", " ", 3, "b.yaml"]}), ("a.yaml", "b.yaml"))
    check_eq("optional rows: the purposes a role is admitted with are the rows' (both stages), none for another role",
             (SG.optional_purposes(model, "qa-runner"), SG.optional_purposes(model, "qa-scout")), ({"first_look", "reference_walk"}, set()))
    live_s1 = {"role": "qa-runner", "stage": "S1", "status": "running", "request_binding": {"purpose": "reference_walk"}}
    check_eq("optional rows: the one running reference-walk dispatch stands on S1, owing the snapshot",
             [(p[0].get("id"), SG.optional_outputs(p[1])) for p in [SG.optional_stage_of_dispatch(model, "qa-runner", {"d1": live_s1})]],
             [("S1", ("work/reference-snapshot.yaml",))])


def main() -> None:
    optional_dispatch_rows_checks()
    p = run_script("stage_guard.py", "--selftest")
    check("stage_guard.py --selftest is green", p.returncode == 0,
          (p.stdout or p.stderr).strip()[-600:])

    model = json.loads((PLUGIN_ROOT / "references" / "stages.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in model["stages"]]
    check_eq("stages.json lists S0..S9 in order", ids, [f"S{i}" for i in range(10)])

    roles = SG.known_roles(model)
    missing = [r for r in V0_ROLES if r not in roles]
    check("stages.json names all twelve v0 roles", not missing, f"missing: {missing}")
    extra = [r for r in roles if r not in V0_ROLES]
    check("stages.json names no role outside the v0 twelve", not extra, f"extra: {extra}")

    for role, stage in (("qa-scout", "S1"), ("qa-automator", "S5"), ("qa-code-critic", "S5"),
                        ("qa-runner", "S6"), ("qa-doc-scribe", "S8"), ("qa-retro-analyst", "S9")):
        check_eq(f"role map: {role} -> {stage}", (SG.stage_of_role(model, role) or {}).get("id"), stage)

    # Every stage after S0 requires its predecessor: this is what makes rule 1 catch a skipped
    # retro (A18) — S9 cannot be reached while S8 is pending.
    for stage in model["stages"][1:]:
        check(f"{stage['id']} requires the stage before it",
              bool(stage.get("requires")), "requires is empty")

    check_eq("gate A is declared after S4", model["gates"]["A"]["after"], "S4")
    check_eq("gate B is declared after S8", model["gates"]["B"]["after"], "S8")

    # The dispatch guard reads the role out of subagent_type, and out of free text when the
    # orchestrator writes "dispatch <role>" into the description instead.
    check_eq("role from subagent_type",
             SG.requested_role({"tool_input": {"subagent_type": "qa-runner"}}, model), "qa-runner")
    check_eq("role from a description",
             SG.requested_role({"tool_input": {"description": "dispatch qa-failure-analyst for QA-1"}}, model),
             "qa-failure-analyst")
    check_eq("no role in a plain prompt",
             SG.requested_role({"tool_input": {"prompt": "summarize the diff"}}, model), "")

    # Fail-open: the plugin's hooks fire in every repository on the machine.
    check_eq("a foreign agent is allowed", SG.check(
        {"tool_name": "Task", "tool_input": {"subagent_type": "general-purpose", "prompt": "x"}}), 0)
    check_eq("a non-guarded tool is allowed", SG.check({"tool_name": "Read", "tool_input": {}}), 0)
    check_eq("an unparsable event is allowed (fail-open)", SG.check(None), 0)

    active = {"dispatches": {"d-1": {"id": "d-1", "status": "running",
                                      "scope": ["i-1", "i-2"]}}}
    event = {"cwd": str(PLUGIN_ROOT), "tool_input": {}}
    check_in("active factory dispatch rejects legacy full-suite runner",
             "--request FILE", SG.rule_typed_runner("python run_suite.py --task X --label all",
                                                    event, "X", active))
    request_path = PLUGIN_ROOT / ".stage-guard-run-request.json"
    try:
        request_path.write_text(json.dumps({"dispatch_id": "d-1",
                                            "selected_instance_ids": ["i-2"]}), encoding="utf-8")
        check_eq("typed request matching active dispatch and scope is allowed",
                 SG.rule_typed_runner(f'python run_suite.py --request "{request_path}"',
                                      event, "X", active), "")
        request_path.write_text(json.dumps({"requests": [
            {"dispatch_id": "d-1", "selected_instance_ids": ["i-1"]},
            {"dispatch_id": "d-1", "selected_instance_ids": ["i-2"]}]}), encoding="utf-8")
        check_eq("typed schedule matching active dispatch and scope is allowed",
                 SG.rule_typed_runner(f'python run_suite.py --schedule "{request_path}"',
                                      event, "X", active), "")
        request_path.write_text(json.dumps({"dispatch_id": "d-other",
                                            "selected_instance_ids": ["i-2"]}), encoding="utf-8")
        check_in("typed request must match active dispatch", "dispatch_id",
                 SG.rule_typed_runner(f"python run_suite.py --request={request_path}",
                                      event, "X", active))
        request_path.write_text(json.dumps({"dispatch_id": "d-1",
                                            "selected_instance_ids": ["outside"]}), encoding="utf-8")
        check_in("typed request cannot exceed active dispatch scope", "exceed",
                 SG.rule_typed_runner(f"python run_suite.py --request {request_path}",
                                      event, "X", active))
    finally:
        request_path.unlink(missing_ok=True)
    check_eq("standalone user retains legacy runner interface",
             SG.rule_typed_runner("python run_suite.py --task X --label all", event, "X", {}), "")

    part_typed_runner_tax(event)
    part_one_tokenizer(event)
    part_cx20_walker(event)
    part_cx20_round3()
    part_story_identity()
    part_resume_ids()
    part_resume_no_recipient()
    part_third_verdict()
    part_held_for_code()
    part_manifest_not_read()
    part_adapter_forms()
    part_cx2_27_matcher()
    part_cx2_27_door()
    part_oh3_22_bodies()
    part_oh3_32_quoted_backslash()
    part_commit_shape()
    part_guard_crash()

    check_in("--ticket/--stage explains a missing pipeline",
             "no pipeline.json", run_script("stage_guard.py", "--ticket", "NOPE-1", "--stage", "S4").stdout)

    finish("test_stage_guard")


if __name__ == "__main__":
    main()
