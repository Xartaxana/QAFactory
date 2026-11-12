"""hooklib._scan / command_segments - the part of the tokenizer contract CX1-19 corrects (t-976 sections L-3, L-4).

Where the shell reads ONE word and `_scan` cut it, the contract is now the shell's:
  bash        a backslash before `$` or another backslash is part of the word (POSIX 2.2.1); a backslash before
              ANY other character is NOT modelled - `( ) " ' ` ` and a blank, as well as `; & |` and a line end,
              are read as before (the safe, finer side: a Codex host labels PowerShell commands `Bash`, and the
              readers behind no ban would merge two commands otherwise; the join is node CX1-20);
  powershell  `<# ... #>` at the START of a word is a comment (about_Comments; unclosed it runs to the end of the
              input; inside a word `<#` is text), `--%` makes the rest of the line literal up to a line end, an
              unquoted `|` or `&&` (about_Parsing; measured in PowerShell 5.1 and 7.6);
  nothing else changes: `$( )`, `$(( ))`, `<( )`, `( )`, `@( )` and the backtick are cut as before (node CX1-20).
Every expected value below is derived from the shell rule quoted in the row's comment - never from running the
code (FR-58). A slice is the RAW text behind a segment (`command_segments(..., spans=True)[2]`): it holds neither
a top-level separator nor a trailing comment, and a block comment inside it stays inside (one slice around it).
Fixtures with backslashes and quotes are escaped Python literals (FR-29), non-ASCII ones are \\uXXXX (FR-30)."""
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish, reader_patched  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402

RUN = "C:/p/run_suite.py"


def slices(text: str, dialect: str) -> list:
    return [text[a:b] for a, b in hooklib.command_segments(text, dialect, spans=True)[2]]


def words(text: str, dialect: str) -> list:
    return [[word for word, _quoted in segment] for segment in hooklib.command_segments(text, dialect)[0]]


# (row, text, expected slices, expected words or None, the rule the expectation comes from)
BASH_ROWS = [
    # --- the join CX1-20 owns (L-3 NB-1): the BASH reading joins `\( \) \" \' \` \<blank>` (POSIX 2.2.1: the escaped
    # character is part of the word); R1-R3 take the UNION with the PowerShell reading, so the label decides nothing
    # (these rows were "NOT a join, the bracket cuts" under CX1-19: rewritten to the CX1-20 contract)
    ("G-1 form 2: a backslash before ( IS a join in bash", f"python -X a\\(cat {RUN} --task X",
     [f"python -X a\\(cat {RUN} --task X"], [["python", "-X", "a\\(cat", RUN, "--task", "X"]],
     "POSIX 2.2.1: `\\(` is a literal parenthesis inside the word `a\\(cat`; the PowerShell reading (a Codex host "
     "labels it `Bash`) runs `(...)` as a subexpression and is read too - see the PS rows"),
    ("a backslash before ) IS a join in bash", f"python -X a\\)cat {RUN} --task X",
     [f"python -X a\\)cat {RUN} --task X"], None, "as above"),
    # --- the cut that stays (L-3, t-983 NB-1): a separator after a backslash still cuts
    ("G-1 form 1: a backslash before & is still a cut", f"python -X a\\&cat {RUN} --task X",
     ["python -X a\\", f"cat {RUN} --task X"], None,
     "POSIX reads `a&cat` as one word; the tokenizer keeps the finer cut on purpose (the readers behind no ban would "
     "merge two commands on a Codex host); the ban refuses the form whole in the two guards that have one"),
    ("a backslash before ; is still a cut", "a\\;b", ["a\\", "b"], None, "kept cut, as above"),
    ("a backslash before | is still a cut", "a\\|b", ["a\\", "b"], None, "kept cut, as above"),
    ("a backslash before LF is still a cut", "a\\\nb", ["a\\", "b"], None, "kept cut (PowerShell reads the LF as a line end)"),
    ("a backslash before CR LF is still a cut, the CR a blank", "a\\\r\nb", ["a\\\r", "b"], None,
     "kept cut; CR is a blank to the tokenizer, the slice is the raw text up to the LF"),
    # --- quotes: a backslash before a quote is NOT a join (L-4 B-1): the quote opens its run as before, so the
    # quote parity is the one PowerShell reads (it has no backslash escape)
    ("a backslash before \" IS a join in bash: the literal quote joins the word, the next pair quotes",
     'echo \\""a;b"', ['echo \\""a;b"'], [["echo", '\\"a;b']],
     "POSIX 2.2.1: `\\\"` is a literal quote in the word, `\"a;b\"` is a quoted run - the `;` inside it is text"),
    ("a backslash before ' IS a join in bash: the literal quote opens no run, the ; cuts", "echo a\\'b;c\\'d",
     ["echo a\\'b", "c\\'d"], [["echo", "a\\'b"], ["c\\'d"]],
     "POSIX 2.2.1: `\\'` is a literal quote, so no run opens and the `;` is a real separator"),
    # --- substitutions: an escaped $ starts none (the parenthesis after `\$` still cuts, as before)
    ("an escaped dollar is a literal dollar", "echo \\$HOME;ls", ["echo \\$HOME", "ls"], None,
     "2.2.1: `\\$` is a literal dollar; the `;` after it separates"),
    ("an escaped $( starts no substitution", "echo \\$(ls)", ["echo \\$", "ls"], None,
     "2.6.3: only an unescaped `$(` is a substitution - so no region; the bare `(` still cuts, as before CX1-19"),
    ("a backslash before a backtick IS a join in bash: no region", "echo \\`ls\\`", ["echo \\`ls\\`"],
     None, "POSIX 2.2.1: the escaped backtick is a literal character (CX1-20): one command, no region"),
    # --- blanks and the comment sign (a backslash before a blank IS a join in bash since CX1-20)
    ("a backslash before a blank IS a join in bash: the escaped blank stays in the word", "rg a\\ b;c", ["rg a\\ b", "c"],
     [["rg", "a\\ b"], ["c"]], "POSIX 2.2.1: `\\ ` is a literal blank inside the word"),
    ("a backslash before a TAB is NOT a join (the walker ends the word at the TAB, the finer side)", "rg a\\\tb;c",
     ["rg a\\\tb", "c"], [["rg", "a\\", "b"], ["c"]],
     "POSIX 2.2.1 keeps `\\<TAB>` inside the word; the walker keeps the CX1-19 cut (a Codex host labels PowerShell "
     "commands `Bash`, where a TAB ends the word) - and a `#` right after the pair is no comment, see the F-3 rows"),
    # --- F-3 (review t-1071): bash has `\;`, `\|`, `\&`, `\<LF>`, `\<TAB>` mid-word, so a `#` right after them is no
    # comment there; the walker still cuts at them, but the `#` must not hide the text behind it
    ("F-3: a # after a backslash-TAB is no comment: the segment after the ; stays", "echo a\\\t#; pytest -q",
     ["echo a\\\t#", " pytest -q"], [["echo", "a\\", "#"], ["pytest", "-q"]],
     "POSIX 2.2.1: the escaped TAB keeps the `#` inside the word, so `; pytest -q` runs"),
    ("F-3: a # after a backslash-; is no comment", "echo a\\;#; pytest -q", ["echo a\\", "#", " pytest -q"],
     [["echo", "a\\"], ["#"], ["pytest", "-q"]], "POSIX 2.2.1: `\\;` is a literal semicolon in the word, `#` follows it mid-word"),
    ("F-3: a # after a backslash-| is no comment", "echo a\\|#; pytest -q", ["echo a\\", "#", " pytest -q"],
     [["echo", "a\\"], ["#"], ["pytest", "-q"]], "as above"),
    ("F-3: a # after a backslash-& is no comment", "echo a\\&#; pytest -q", ["echo a\\", "#", " pytest -q"],
     [["echo", "a\\"], ["#"], ["pytest", "-q"]], "as above"),
    ("F-3: a # after a backslash-LF is no comment (a continuation joins the lines)", "echo x\\\n#; pytest -q",
     ["echo x\\", "#", " pytest -q"], [["echo", "x\\"], ["#"], ["pytest", "-q"]], "POSIX 2.2.1: `x\\<LF>#` is the word `x#`"),
    ("F-3 control: a # after a plain ; is a comment (it starts a word)", "echo a; #; pytest -q", ["echo a"],
     [["echo", "a"]], "POSIX 2.3: `#` at the start of a word begins a comment to the line end"),
    ("F-3 control: a # after an ESCAPED backslash and a real ; is a comment", "echo a\\\\;#; pytest -q", ["echo a\\\\"],
     [["echo", "a\\\\"]], "2.2.1: `\\\\` is one literal backslash, the `;` is real and `#` then starts a comment"),
    ("a # after a backslash-blank is no comment in bash: the word goes on", "echo a\\ #b", ["echo a\\ #b"],
     [["echo", "a\\ #b"]],
     "POSIX 2.3: the escaped blank keeps `#b` inside the word, so no comment starts (the PS reading sees one)"),
    ("a backslash at a word start keeps a following # in the word", "echo \\#x; y", ["echo \\#x", " y"],
     [["echo", "\\#x"], ["y"]], "the backslash starts the word, so the `#` is not at a word start: no comment"),
    # --- the backslash itself escaped: the pair is read together, the next character is NOT escaped
    ("an escaped backslash does not escape the parenthesis after it", "echo a\\\\(b", ["echo a\\\\", "b"], None,
     "2.2.1: `\\\\` is one literal backslash, then `(` is an operator: it cuts"),
    ("an escaped backslash does not escape the quote after it", 'echo \\\\"a;b"', ['echo \\\\"a;b"'], None,
     "2.2.1: `\\\\` then a quoted run `\"a;b\"`: the `;` is text, one command"),
    ("an escaped backslash does not escape the separator after it", "echo \\\\;x", ["echo \\\\", "x"], None,
     "2.2.1: `\\\\` then a real `;`"),
    # --- edges
    ("a backslash at the very end of the input is literal", "echo a\\", ["echo a\\"], [["echo", "a\\"]],
     "2.2.1: nothing follows, nothing is escaped; no crash"),
    ("a lone backslash", "\\", ["\\"], [["\\"]], "as above"),
    ("a backslash before a multibyte character is literal", "echo a\\\u00e9;b", ["echo a\\\u00e9", "b"], None,
     "only the listed characters are escaped: a Windows-style path (A2) stays readable"),
    ("a backslash before an ordinary character is literal (Windows paths)", "C:\\p\\run_suite.py --task X",
     ["C:\\p\\run_suite.py --task X"], [["C:\\p\\run_suite.py", "--task", "X"]], "A2: unchanged"),
    ("quotes first: a backslash-parenthesis inside double quotes", 'echo "a\\(b" ; c', ['echo "a\\(b" ', " c"], None,
     "inside \"...\" the double-quote rules apply, not this branch; the `;` after the closing quote cuts"),
    ("quotes first: a backslash-parenthesis inside single quotes", "echo '\\(' ;c", ["echo '\\(' ", "c"], None,
     "inside '...' nothing is special"),
    ("a comment ends the slice; a backslash in it is nothing", "echo a # \\(b; c", ["echo a "], None,
     "2.3: the comment runs to the line end, a `;` in it separates nothing"),
    # --- the PowerShell forms are plain text to bash
    ("<# is an ordinary word to bash; the # after a blank is a comment", f"python <# #> {RUN} --task X",
     ["python <# "], None, "2.3: `#` at the start of a word begins a comment; `<#` itself is one word here, as before"),
    ("--% is an ordinary word to bash: the ; cuts", f"python --% -X a;cat {RUN} --task X",
     ["python --% -X a", f"cat {RUN} --task X"], None, "bash has no stop-parsing token"),
    ("--% is an ordinary word to bash: the | cuts", "rg x --% y|pytest -q", ["rg x --% y", "pytest -q"], None,
     "bash has no stop-parsing token"),
    # --- the four commands of the review t-1000 B-1 (PowerShell commands that arrive under the Codex `Bash` label):
    # the BASH reading joins them (one command, words below); the PowerShell reading, read too by R1-R3 (the union),
    # keeps the second command visible - those rows are in PS_ROWS (measured: pwsh 7.6.7 and 5.1 run it)
    ("B-1 (bash reading): a backslash before a quoted run joins; the quote parity is bash's",
     'Get-Content C:\\p\\"a b.txt"; pytest -q; echo "done"', ['Get-Content C:\\p\\"a b.txt"; pytest -q; echo "done"'],
     [["Get-Content", 'C:\\p\\"a', 'b.txt; pytest -q; echo done']], "POSIX 2.2.1: `\\\"` is a literal quote"),
    ("B-1 (bash reading): a backslash before ( joins; the parenthesis is a literal", "dir C:\\p\\(pytest -q)",
     ["dir C:\\p\\(pytest -q"], [["dir", "C:\\p\\(pytest", "-q"]],
     "POSIX 2.2.1: `\\(` is literal; the final bare `)` cuts"),
    ("B-1 (bash reading): a backslash before a backtick joins", ".venv\\Scripts\\`pytest -q",
     [".venv\\Scripts\\`pytest -q"], [[".venv\\Scripts\\`pytest", "-q"]], "POSIX 2.2.1: `\\`` is a literal backtick"),
    ("B-1 (bash reading): a backslash before a blank joins; the # stays in the word", "dir C:\\p\\ #it's\npytest -q; echo 'x'",
     ["dir C:\\p\\ #it's\npytest -q; echo 'x'"], [["dir", "C:\\p\\ #its\npytest -q; echo x"]],
     "POSIX 2.2.1: `\\ ` is a literal blank, so `#it's` is no comment; the `'` opens a run to the next `'`"),
]

PS_ROWS = [
    # --- the backslash is NOT an escape in PowerShell (the backtick is): unchanged
    ("a backslash before ( is literal; the ( opens a subexpression glued to the word (a region, CX1-20)",
     f"python -X a\\(cat {RUN} --task X", [f"python -X a\\(cat {RUN} --task X"],
     [["python", "-X", f"a\\(cat {RUN} --task X"]],
     "about_Special_Characters: the escape character is the backtick; `(` glued to a word opens a group to the end "
     "of the input, whose body `cat ...` is its own unit (it was a cut at the bracket under CX1-19)"),
    # --- the four commands of the review t-1000 B-1, read as PowerShell (the reading the union keeps; was in BASH_ROWS)
    ("B-1: a backslash before a quoted run keeps PowerShell's quote parity",
     'Get-Content C:\\p\\"a b.txt"; pytest -q; echo "done"',
     ['Get-Content C:\\p\\"a b.txt"', " pytest -q", ' echo "done"'],
     [["Get-Content", "C:\\p\\a b.txt"], ["pytest", "-q"], ["echo", "done"]],
     "PowerShell: the quoted run is closed, the `;` after it separates and `pytest -q` runs"),
    ("B-1: a backslash before ( leaves the subexpression visible", "dir C:\\p\\(pytest -q)",
     ["dir C:\\p\\(pytest -q)"], [["dir", "C:\\p\\(pytest -q)"]],
     "PowerShell: `(pytest -q)` is a subexpression (a region of its own, read by R1) and runs"),
    ("B-1: a backslash before a backtick leaves the program word in view", ".venv\\Scripts\\`pytest -q",
     [".venv\\Scripts\\`pytest -q"], [[".venv\\Scripts\\pytest", "-q"]],
     "PowerShell: `p is p, so the relative path `.venv\\Scripts\\pytest` runs"),
    ("B-1: a backslash before a blank leaves the comment a comment", "dir C:\\p\\ #it's\npytest -q; echo 'x'",
     ["dir C:\\p\\ ", "pytest -q", " echo 'x'"], [["dir", "C:\\p\\"], ["pytest", "-q"], ["echo", "x"]],
     "PowerShell: `#it's` is a comment to the line end, the next line runs"),
    ("a backslash before ; is literal; the ; cuts", "a\\;b", ["a\\", "b"], None, "as above"),
    ("a backslash-blank does not keep a # in the word", "echo a\\ #b", ["echo a\\ "], None,
     "the backslash is a plain character, the blank ends the word, `#` then begins a comment"),
    # --- <# ... #>
    ("G-1 form 8: a block comment is not text", f"python <# #> {RUN} --task X", [f"python <# #> {RUN} --task X"],
     [["python", RUN, "--task", "X"]], "about_Comments: <# ... #> is a comment: `python run_suite.py --task X`"),
    ("a ; inside a block comment separates nothing: one slice around it", f"python <# a ; b #> {RUN}",
     [f"python <# a ; b #> {RUN}"], [["python", RUN]], "about_Comments: the comment is dropped whole"),
    ("a block comment spans lines without cutting", f"python <# a\nb ; c\n#> {RUN}", [f"python <# a\nb ; c\n#> {RUN}"],
     [["python", RUN]], "about_Comments: the comment runs to its `#>`, line ends included"),
    ("CRLF before #> closes the comment", f"python <# a\r\n#> {RUN}", [f"python <# a\r\n#> {RUN}"],
     [["python", RUN]], "about_Comments: the closing `#>` after a CR LF still closes"),
    ("a real ; after the comment still cuts", "a <# x #> b; c", ["a <# x #> b", " c"], [["a", "b"], ["c"]],
     "the comment is dropped, the separator after it is real"),
    ("an unclosed <# is a comment to the end of the input", f"python <# {RUN} --task X; z", ["python "],
     [["python"]], "about_Comments: a block comment with no `#>` runs to the end; nothing after it is run"),
    ("an unclosed <# after a separator leaves the earlier command", "a; <# b ; c", ["a"], [["a"]],
     "as above"),
    ("<#> is not closed by its own # and >", f"python <#> {RUN}", ["python "], [["python"]],
     "about_Comments: the closer `#>` must follow the opener `<#`; `<#>` has none"),
    ("a command of only a comment has no slice", "<# a ; b #>", [], [], "nothing is run"),
    ("an unclosed comment alone has no slice", "<# a", [], [], "nothing is run"),
    ("the empty command has no slice", "", [], [], "nothing is run"),
    ("quotes first: <# inside double quotes is text", 'echo "a <# b" ; c', ['echo "a <# b" ', " c"],
     [["echo", "a <# b"], ["c"]], "about_Quoting_Rules: inside \"...\" nothing is a comment"),
    ("quotes first: <# inside single quotes is text", "echo 'a <# b' ; c", ["echo 'a <# b' ", " c"], None,
     "inside '...' nothing is a comment"),
    # --- --%
    ("G-1 form 9: the rest of the line after --% is literal", f"python --% -X a;cat {RUN} --task X",
     [f"python --% -X a;cat {RUN} --task X"], [["python", "--%", "-X", "a;cat", RUN, "--task", "X"]],
     "about_Parsing: after `--%` the arguments are passed as they are; the `;` is not a separator"),
    ("the literal part ends at the line end", "python --% a;b\nrg x", ["python --% a;b", "rg x"],
     [["python", "--%", "a;b"], ["rg", "x"]], "about_Parsing: the stop-parsing token acts to the end of the line"),
    ("--% at the end of the input: nothing after it, one slice", "python --%", ["python --%"], [["python", "--%"]],
     "no arguments follow"),
    ("--% at the end of the line: nothing after it", "python --%\nz", ["python --%", "z"], [["python", "--%"], ["z"]],
     "no arguments follow on that line"),
    ("quotes, # and ( after --% are literal text", 'python --% "a;b" # c (d) ; e', ['python --% "a;b" # c (d) ; e'],
     [["python", "--%", '"a;b"', "#", "c", "(d)", ";", "e"]], "about_Parsing: nothing after `--%` is interpreted"),
    ("--% in quotes is text", 'echo "--%" ; x', ['echo "--%" ', " x"], [["echo", "--%"], ["x"]],
     "about_Quoting_Rules: inside quotes it is a string"),
    ("--% in single quotes is text", "echo '--%';x", ["echo '--%'", "x"], None, "as above"),
    ("--% glued to more text is no token", "python --%x;y", ["python --%x", "y"], [["python", "--%x"], ["y"]],
     "about_Parsing: the token is `--%` as a word of its own"),
    ("--% inside a word is no token", "x--% a;b", ["x--% a", "b"], None, "as above"),
    ("--% after a ; starts its own command", "a; b --% c;d", ["a", " b --% c;d"], None, "the ; before it is real"),
    # --- the literal part of --% ends at an unquoted | and at && (L-4 B-3; measured: pwsh 7.6.7 and 5.1 end it at |,
    # 7.x at && and ||; a single & and a ; do not end it; "a|b" does not)
    ("B-3: an unquoted | right after the text ends the literal part", "rg x --% y|pytest -q",
     ["rg x --% y", "pytest -q"], [["rg", "x", "--%", "y"], ["pytest", "-q"]], "about_Parsing: until the pipeline character"),
    ("B-3: a | with blanks around it ends the literal part", "rg x --% y | pytest -q",
     ["rg x --% y ", " pytest -q"], [["rg", "x", "--%", "y"], ["pytest", "-q"]], "as above"),
    ("B-3: && with no blank ends the literal part", "rg x --% y&&pytest -q", ["rg x --% y", "pytest -q"],
     [["rg", "x", "--%", "y"], ["pytest", "-q"]], "PowerShell 7: the pipeline-chain operator ends it"),
    ("B-3: || ends the literal part", "rg x --% y||pytest -q", ["rg x --% y", "pytest -q"],
     [["rg", "x", "--%", "y"], ["pytest", "-q"]], "PowerShell 7: the pipeline-chain operator ends it"),
    ("B-3: a | right after the token is no token and cuts", "rg x --%|pytest -q", ["rg x --%", "pytest -q"],
     [["rg", "x", "--%"], ["pytest", "-q"]], "the token is `--%` followed by a blank or the end; the | is a real pipe"),
    ("B-3: a | right after a token followed by a blank ends the literal part", "rg --% | pytest -q",
     ["rg --% ", " pytest -q"], [["rg", "--%"], ["pytest", "-q"]], "as above"),
    ("B-3: a quoted | does not end the literal part", 'rg x --% "a|b" c;d', ['rg x --% "a|b" c;d'],
     [["rg", "x", "--%", '"a|b"', "c;d"]], "about_Parsing: a pipe inside double quotes is text (measured)"),
    ("B-3: a real | after a quoted one ends it", 'rg --% "a|b"|pytest -q', ['rg --% "a|b"', "pytest -q"],
     [["rg", "--%", '"a|b"'], ["pytest", "-q"]], "the quoted pair is text, the pipe after it is real"),
    ("B-3: a double quote with no partner on its line opens nothing: the | ends the literal part",
     'rg --% "a|pytest -q', ['rg --% "a', "pytest -q"], [["rg", "--%", '"a'], ["pytest", "-q"]],
     "the SAFE side: PowerShell reads such a quote to the line end, the tokenizer cuts finer and sees the launch"),
    ("B-3: a single & and a ; do not end the literal part", "rg x --% y&z;w", ["rg x --% y&z;w"],
     [["rg", "x", "--%", "y&z;w"]], "about_Parsing: only a line end, | and (7.x) && / || end it (measured)"),
    ("B-3: a single-quoted | ends it (single quotes do not quote after --%)", "rg --% 'a|b'", ["rg --% 'a", "b'"],
     [["rg", "--%", "'a"], ["b"]], "measured: pwsh ends at the | (a ParserError later); the lone ' is dropped as ever"),
    # --- <# is a comment only at the START of a word (L-4 B-2; measured: pwsh 7.6.7 and 5.1)
    ("B-2: <# inside a word is text: the word goes on after the closer", "a<#x#>b", ["a<#x#>b"], [["a<#x#>b"]],
     "about_Comments: a block comment starts at a token start; `a<#x#>b` is ONE word"),
    ("B-2: a<# is a word, the ; after it cuts and the next command runs", "echo a<#;pytest -q",
     ["echo a<#", "pytest -q"], [["echo", "a<#"], ["pytest", "-q"]], "measured: PowerShell runs `pytest -q`"),
    ("B-2: pytest<#c#> -q is the word pytest<#c#>", "pytest<#c#> -q", ["pytest<#c#> -q"], [["pytest<#c#>", "-q"]],
     "measured: one word"),
    ("B-2: <# at the very start of the input is a comment", "<#c#>pytest -q", ["<#c#>pytest -q"], [["pytest", "-q"]],
     "about_Comments: at a token start"),
    ("B-2: <# after a ; is a comment", "a;<#c#>b", ["a", "<#c#>b"], [["a"], ["b"]], "a `;` ends the word"),
    ("B-2: <# after a blank is a comment", "a <#c#>b", ["a <#c#>b"], [["a", "b"]], "a blank ends the word"),
    ("B-2: <# right after a quoted run is read as one word (the refusal side)", '"x"<#c#>y', ['"x"<#c#>y'],
     [["x<#c#>y"]], "the word started with the quoted run; PowerShell reads a comment here, the tokenizer reads text"),
    ("B-2: an unclosed <# after a blank is a comment to the end", "a <#x;pytest -q", ["a "], [["a"]],
     "about_Comments: nothing after it runs (a ParserError in PowerShell)"),
]


def part_rows(label: str, dialect: str, rows: list) -> None:
    for name, text, want_slices, want_words, rule in rows:
        check_eq(f"{label}: {name}: the slices ({rule[:70]})", slices(text, dialect), want_slices)
        if want_words is not None:
            check_eq(f"{label}: {name}: the words", words(text, dialect), want_words)


def part_contract() -> None:
    """The (segments, regions, spans) contract of CX1-5 holds on every new row, in both dialects."""
    for dialect, rows in (("bash", BASH_ROWS), ("powershell", PS_ROWS)):
        for name, text, _slices, _words, _rule in rows:
            segments, regions, spans = hooklib.command_segments(text, dialect, spans=True)
            check_eq(f"spans: {name} [{dialect}]: the first two members equal the plain answer",
                     (segments, regions), hooklib.command_segments(text, dialect))
            check_eq(f"spans: {name} [{dialect}]: slices run 1:1 with segments", len(spans), len(segments))
            check(f"spans: {name} [{dialect}]: slices are ordered and disjoint, inside the text",
                  all(a[1] <= b[0] for a, b in zip(spans, spans[1:])) and all(0 <= s <= e <= len(text) for s, e in spans))
    check_eq("regions: an escaped $( records none (bash)",
             [hooklib.command_segments(t, "bash")[1] for t in ("echo \\$(ls)",)], [[]])
    check_eq("regions: a backslash before a backtick IS a join in bash - the escaped pair is two literals, no region (CX1-20)",
             hooklib.command_segments("echo \\`ls\\`", "bash")[1], [])
    check_eq("regions: an unescaped $( and backtick pair still record theirs (bash)",
             [hooklib.command_segments(t, "bash")[1] for t in ("echo $(ls)", "echo `ls`")], [["ls"], ["ls"]])
    # CX1-20 (rewritten: these five were "cut at every ( and ) as before" under CX1-19): a substitution or a group
    # is a REGION of the walker and its word stays ONE word of ONE slice (`$(true)cat` is the word `cat` to the shell)
    for dialect, text, want in (
            ("bash", f"python -X $(true)cat {RUN}", [f"python -X $(true)cat {RUN}"]),
            ("bash", f"python -X $((0))cat {RUN}", [f"python -X $((0))cat {RUN}"]),
            ("bash", f"python -X <(true)cat {RUN}", [f"python -X <(true)cat {RUN}"]),
            ("powershell", f"python -X (@())cat {RUN}", [f"python -X (@())cat {RUN}"]),
            ("powershell", f"python -X $()cat {RUN}", [f"python -X $()cat {RUN}"])):
        check_eq(f"walker: a substitution/group is one word of one slice [{dialect}] {text[:24]!r}",
                 slices(text, dialect), want)
    check_eq("walker: the $( ) region of the G-1 form 3 is recorded", hooklib.command_segments("python -X $(true)cat x", "bash")[1],
             ["true"])


def part_ban_still_first() -> None:
    """The invariant of the node: every form whose cut changed here is one the shared ban refuses whole before any
    segmentation in the two guards that hold it (stage_guard, host_adapter) - so no verdict of those moves."""
    for text in (f"python -X a\\&cat {RUN} --task X", f"python -X a\\(cat {RUN} --task X",
                 f"python <# #> {RUN} --task X", f"python --% -X a;cat {RUN} --task X",
                 f"python -X a\\\"cat {RUN}", f"python -X a\\'cat {RUN}", f"python -X a\\)cat {RUN}",
                 f"python -X a\\ #{RUN}"):
        check("ban: the form is still refused whole: " + repr(text[:30]), bool(hooklib.shell_opaque_found(text)[0]))


def part_quoted_backslash() -> None:
    """OH3-32 (K3, the reader's side): the walker records the backslashes it read inside a quoted run (`Unit.quoted_bs`, the
    top unit only), `hooklib.quoted_backslash` answers for BOTH readings, and `shell_opaque_found` frees only a backslash
    before `|`, `;`, `&` that is quoted in both. Expected values come from the shell rules (bash: a single-quoted run
    has no escapes, in a double-quoted one a backslash escapes only a dollar, a backtick, a double quote, a backslash and
    a line end; PowerShell: no backslash escape), not from running the code (FR-58). The mutations: the record not dropped on a rewind (q11b), a region's backslash inside a dq counted (q8), a tick
    not excluded (q9), `<<` ignored (q19), either reading instead of both (the PowerShell-only row), the record list not
    frozen (the frozen row)."""
    def offsets(text: str, dialect: str) -> tuple:
        return hooklib._read_units(text, dialect)[0].quoted_bs

    # what is recorded: the offset of each backslash of a closed '...' and of a "..." run; both of an escaped pair
    for text, want in (('"a\\|b"', (2,)), ("'a\\|b'", (2,)), ("'a\\\\|b'", (2, 3)), ('"a\\\\|b"', (2, 3)),
                       ('x\\|y', ()), ('"a" \\| "b"', ()), ("", ())):
        for dialect in ("bash", "powershell"):
            check_eq(f"OH3-32 record {text!r} [{dialect}]", offsets(text, dialect), want)
    # q11: an unclosed single quote quotes nothing; q11b: an unclosed double quote is dropped with what it held (E8)
    for key, text in (("q11", "'a\\|b"), ("q11b", '"a\\|b')):
        for dialect in ("bash", "powershell"):
            check_eq(f"OH3-32 {key} [{dialect}]: the unclosed quote leaves no record ({text!r})", offsets(text, dialect), ())
        check_in(f"OH3-32 {key}: so the ban names it", "backslash before `|`", hooklib.shell_opaque_found(text)[0])
    # q8: a backslash in a `$( )` region inside a double quote is the region's code, not the quote's; q10: its own quotes count
    check_in("OH3-32 q8: a region's backslash inside dq is code", "backslash before `|`",
             hooklib.shell_opaque_found('echo "$(python -X a\\|cat run)"')[0])
    check_eq("OH3-32 q10: a quote inside that region quotes its own text", hooklib.shell_opaque_found('echo "$(echo "a\\|b")"'),
             ("", ""))
    # q9: bash cuts a backquoted text at its partner before it reads a quote, so nothing inside a tick is quoted
    check_in("OH3-32 q9: a quote inside a backtick pair quotes nothing", "backslash before `|`",
             hooklib.shell_opaque_found('echo `echo "a\\|b"`')[0])
    check_eq("OH3-32 q9: no record of the bash reading inside the pair", offsets('echo `echo "a\\|b"`', "bash"), ())
    # both readings: a quote PowerShell reads (its backtick escapes the quote) and bash does not frees nothing
    ps_only = 'echo "a`" \\|"'
    check_eq("OH3-32 the PowerShell reading records the pair as quoted", hooklib.quoted_backslash(ps_only, ps_only.index("\\"), either=True), True)
    check_eq("OH3-32 ...the bash reading does not, so `quoted_backslash` is False", hooklib.quoted_backslash(ps_only, ps_only.index("\\")), False)
    check_in("OH3-32 ...and the ban holds", "backslash before `|`", hooklib.shell_opaque_found(ps_only)[0])
    # q19: a body the walker does not know makes its quote fact unreliable: no hit is freed past a `<<` or a here-string
    q19 = "python - <<'E'\nit's\nE\npython -X a\\|cat run_suite.py --task X 'y'"
    check_in("OH3-32 q19: a `<<` anywhere frees no hit", "backslash before `|`", hooklib.shell_opaque_found(q19)[0])
    for text in ('grep "a\\|b" <<< x', 'cat <<E\nx\nE\ngrep "a\\|b" f', "x = @'\nb\n'@\ngrep \"a\\|b\" f"):
        check_in(f"OH3-32 {text[:24]!r}: an opener anywhere, the quoted pipe is banned", "backslash before `|`",
                 hooklib.shell_opaque_found(text)[0])
    check_eq("OH3-32 control: the same quoted pipe with no opener is text", hooklib.shell_opaque_found('grep "a\\|b" f'), ("", ""))
    # round 2, F5: the walker reads the quotes of a `${ }` by its own rules, so a `${` anywhere frees no hit. The critic's
    # run of a real shell (Git Bash 5.2.37 for f5a, PowerShell 5.1 for f5b) RAN the launch behind each of these two.
    bs = chr(92)
    f5a = 'cat "${x#\'"\'}" ' + bs * 2 + "|python run_suite.py --task X 'y'"
    f5b = 'cat "${a"} "' + bs + '|python run_suite.py --task X "b"'
    for key, text in (("f5a", f5a), ("f5b", f5b)):
        check_in(f"OH3-32 {key}: a `${{` anywhere frees no hit", "backslash before `|`", hooklib.shell_opaque_found(text)[0])
    check_in("OH3-32 f5: ...even for a quoted pipe that stands alone", "backslash before `|`",
             hooklib.shell_opaque_found('grep "${x}' + bs + '|b" f')[0])
    check_eq("OH3-32 f5 control: a `$` that opens no `${` leaves the quoted pipe text", hooklib.shell_opaque_found('grep "$x' + bs + '|b" f'),
             ("", ""))
    # round 2, the doors (FR-1, AR-9): a quoted line-end backslash and a quoted pipe get a step a role can take; the unreliable
    # case names the split; an unquoted backslash on a reliable text keeps today's door
    for key, text in (("lf", 'echo "a' + bs + "\nb\""), ("crlf", 'echo "a' + bs + "\r\nb\"")):
        what, door = hooklib.shell_opaque_found(text)
        check_in(f"OH3-32 door {key}: the member is a line end", "a line end", what)
        for phrase in ("already in quotes", "end a line without the backslash", "Write tool", "character class"):
            check_in(f"OH3-32 door {key}: carries {phrase!r}", phrase, door)
    for key, text in (("heredoc", 'cat <<E\nx\nE\ngrep "a' + bs + '|b" f'), ("expansion", 'grep "${x}" f ' + bs + "| y")):
        door = hooklib.shell_opaque_found(text)[1]
        check_in(f"OH3-32 door {key}: the unreliable case names the split", "give that part its own command", door)
        check_in(f"OH3-32 door {key}: ...after today's door", hooklib._DOOR_BACKSLASH, door)
        check_not_in(f"OH3-32 door {key}: ...and says nothing of quotes it cannot see", "already in quotes", door)
    check_not_in("OH3-32 door: a reliable unquoted backslash has no split clause", "give that part its own command",
                 hooklib.shell_opaque_found("echo a " + bs + "| b")[1])
    # the frozen record (the cache's rule): a tuple, in the top unit only; a region's unit carries none
    units = hooklib._read_units('echo "a\\|b" $(echo \'c\\|d\')', "bash")
    check_eq("OH3-32 the record is a tuple of the top unit", (type(units[0].quoted_bs), units[0].quoted_bs), (tuple, (7, 21)))
    check_eq("OH3-32 a region's unit carries no record", [unit.quoted_bs for unit in units[1:]], [()])
    check_eq("OH3-32 the payload walk keeps the field", type(hooklib.walk("bash -c 'echo \"a\\|b\"'", "bash")[0].quoted_bs), tuple)
    # empty and absent text: nothing to read, no answer of a stale cache
    check_eq("OH3-32 quoted_backslash on empty and None is False", (hooklib.quoted_backslash("", 0), hooklib.quoted_backslash(None, 0)), (False, False))
    # magnitude: 10x the quoted pipes under 25x the time (a membership test per hit is O(log n), not a scan of the record)
    import time

    def cost(count: int) -> float:
        text = 'grep "' + "a\\|" * count + '" f' + " " * count   # the blanks defeat the cache of an earlier count
        started = time.perf_counter()
        found = hooklib.shell_opaque_found(text)
        elapsed = time.perf_counter() - started
        check_eq(f"OH3-32 magnitude: {count} quoted pipes are text", found, ("", ""))
        return elapsed

    small, large = max(cost(2000), 1e-3), cost(20000)
    check("OH3-32 magnitude: 10x the quoted pipes under 25x the time", large < 25 * small, f"{small:.4f}s -> {large:.4f}s")


def part_readers_keep_the_launch_in_view() -> None:
    """L-4 B-1/B-2/B-3, the verdicts the review t-1000 measured: a launch (R1, `is_direct_test_run`) and a commit
    (R3, `stage_guard._is_commit_shape`) that PowerShell RUNS stay visible to the two readers, as on main. R1 and R3
    read one dialect taken from the tool name, and a Codex host labels PowerShell commands `Bash`, so the B-1
    commands are read in BOTH dialects. Each pin has its control: the same text without the launch/commit is not
    one."""
    import stage_guard
    commit = "git commit -m x qa-factory/a.py"
    launches = (
        'Get-Content C:\\p\\"a b.txt"; pytest -q; echo "done"', "dir C:\\p\\(pytest -q)",
        ".venv\\Scripts\\`pytest -q", "dir C:\\p\\ #it's\npytest -q; echo 'x'",       # B-1 (the review's four)
        "echo a\\$HOME; pytest -q", "echo a\\\\; pytest -q")                         # the joins that stay
    for text in launches:
        for dialect in ("bash", "powershell"):
            check_eq(f"R1: still a launch [{dialect}] {text[:34]!r}", hooklib.is_direct_test_run(text, dialect), True)
    for text in ('Get-Content C:\\p\\"a b.txt"; echo "done"', "dir C:\\p\\(echo x)", "echo a\\$HOME; echo x"):
        check_eq(f"R1 control: no launch, no verdict {text[:34]!r}", hooklib.is_direct_test_run(text, "bash"), False)
    for text in ("echo a<#;pytest -q", "rg x --% y|pytest -q", "rg x --% y && pytest -q", "rg x --% y||pytest -q",
                 "rg x --%|pytest -q", 'rg x --% "a|b" | pytest -q'):
        check_eq(f"R1: still a launch [powershell] {text[:34]!r}", hooklib.is_direct_test_run(text, "powershell"), True)
    for text in ("echo a<#x#>b; echo y", "rg x --% y|echo z"):
        check_eq(f"R1 control: no launch {text[:34]!r}", hooklib.is_direct_test_run(text, "powershell"), False)
    twins = (
        f'git status C:\\p\\"a b"; {commit}; echo "d"', f"dir C:\\p\\({commit})", f"C:\\p\\`{commit}",
        f"git status C:\\p\\ #it's\n{commit}; echo 'x'")
    for text in twins:
        for tool in ("Bash", "PowerShell"):
            check_eq(f"R3: still a commit [{tool}] {text[:34]!r}",
                     stage_guard._is_commit_shape(text, None, {"tool_name": tool}), True)
    for text in (f"echo a<#;{commit}", f"git status --% x|{commit}", f"git status --% x&&{commit}"):
        check_eq(f"R3: still a commit [PowerShell] {text[:34]!r}",
                 stage_guard._is_commit_shape(text, None, {"tool_name": "PowerShell"}), True)
    for text in ('git status C:\\p\\"a b"; echo "d"', "git status --% x|echo z"):
        check_eq(f"R3 control: no commit {text[:34]!r}",
                 stage_guard._is_commit_shape(text, None, {"tool_name": "PowerShell"}), False)


def part_backtick_regions() -> None:
    """The backtick surface (review t-1071 B-1, B-2) and the rows of F-3 / F-5, the answer per reader. Bash cuts a
    backquoted text at its FIRST unescaped backtick before it reads what is inside (POSIX 2.6.3), so a `$(`, `"` or `'`
    opened inside the pair ends at its partner, and the SECOND substitution of the line runs (Git Bash, the review's
    probes: `echo `$(a` b `echo RAN >&2` c` prints RAN). Each shape is read by R1-R4 with the launch in the second pair."""
    import stage_guard
    event = {"cwd": str(hooklib.PLUGIN_ROOT), "tool_input": {}}
    dispatch = {"dispatches": {"d-1": {"id": "d-1", "status": "running", "scope": ["TC-012"]}}}
    tick = chr(96)
    launches = {  # reader -> (the command in the second pair, how the reader answers)
        "R1": ("pytest -q", lambda t: hooklib.is_direct_test_run(t, "bash")),
        "R2": ("gh pr create --fill", lambda t: stage_guard._delivery_match(t, None) is not None),
        "R3": ("git commit -m x tests/test_a.py", lambda t: stage_guard._is_commit_shape(t, {}, {"tool_name": "Bash"})),
        "R4": (f"python {RUN} --task X", lambda t: bool(stage_guard.rule_typed_runner(t, event, "X", dispatch))),
    }
    shapes = {
        "a $( opened in the first pair": "echo {T}$(a{T} b {T}{X}{T} c",
        "a \" opened in the first pair": "echo {T}echo \"a{T} b {T}{X}{T} \"c\"",
        "a ' opened in the first pair": "echo {T}echo 'a{T} b {T}{X}{T} 'c'",
        "the same inside a bare group": "( {T}$(a{T} b {T}{X}{T} c )",
        "a comment in the first pair": "x={T}a # b{T}; {X}",
    }
    for shape, template in shapes.items():
        for reader, (command, answer) in launches.items():
            check_eq(f"B-1 {reader}: {shape}: the launch in the second pair is seen",
                     answer(template.format(T=tick, X=command)), True)
            check_eq(f"B-1 {reader} control: {shape}: the same text with `ls -la` is no launch",
                     answer(template.format(T=tick, X="ls -la")), False)
    units = [hooklib.masked_text(u) for u in hooklib.walk(f"echo {tick}$(a{tick} b {tick}pytest -q{tick} c", "bash") if u.kind == "region"]
    check_eq("B-1 the first pair is cut at its partner: the `$(` inside it ends there, the second pair is its own region",
             units, ["QASUB", "a", "pytest -q"])
    sq = f"echo {tick}echo 'a{tick} b {tick}x{tick} 'c'"
    check_eq("B-1 a single quote opened in the first pair has no partner INSIDE it: it is dropped (E8), the word is `a`",
             [[[word for word, _quoted in segment] for segment in unit.segments] for unit in hooklib.walk(sq, "bash")
              if unit.kind == "region"][0], [["echo", "a"]])
    # B-2: after an E8 rewind (the unclosed quote is dropped) a backtick that HAS a partner is still a region - the text reads
    # as the text without the dropped quote
    plain = f"echo '{tick}'{tick}pytest -q{tick}"
    dropped = 'echo "' + plain[len("echo "):]
    region_texts = lambda text: [hooklib.masked_text(u) for u in hooklib.walk(text, "bash") if u.kind == "region"]  # noqa: E731
    check_eq("B-2 a rewound text reads as the text without the dropped quote (the regions are the same)",
             (region_texts(dropped), region_texts(plain)), (["pytest -q"], ["pytest -q"]))
    check_eq("B-2 ... and R1 sees the launch in both", [hooklib.is_direct_test_run(t, "bash") for t in (dropped, plain)], [True, True])
    # F-3: a # that bash reads mid-word must not hide the launch behind it (the union: bash finds it, PowerShell does not)
    for text in ("echo a\\\t#; pytest -q", "echo a\\\x0b#; pytest -q", "echo a\\\x0c#; pytest -q", "echo a\\;#; pytest -q",
                 "echo a\\|#; pytest -q", "echo a\\&#; pytest -q", "echo x\\\n#; pytest -q", "echo a\\ #; pytest -q"):
        check_eq(f"F-3 R1: {text!r} is a launch", hooklib.is_direct_test_run(text, "bash"), True)
    for text in ("echo a\\\t#; ls", "echo a; #; pytest -q", "echo a\\\\;#; pytest -q"):
        check_eq(f"F-3 R1 control: {text!r} is none (a real comment, or no launch)", hooklib.is_direct_test_run(text, "bash"), False)
    # F-5: a reader's flag launches only under its own program (`find -exec pytest`; `echo -exec pytest` prints it)
    for text, want in (("find . -exec pytest -q {} +", True), ("rg --pre pytest x f.json", True), ("find . -execdir pytest -q {} +", True),
                       ("nice find . -exec pytest -q {} +", True), ("$(which find) . -exec pytest -q {} +", True),
                       ("echo -exec pytest -q", False), ("echo --pre pytest -q", False), ("printf '%s' -exec pytest", False),
                       ("find . -exec echo pytest {} +", False), ("rg -e -exec x f.json", False)):
        check_eq(f"F-5 R1 {text!r}", hooklib.is_direct_test_run(text, "bash"), want)


def part_rewind_leaves_no_state() -> None:
    """Review t-1082 N-1: a backtick pair inside an unclosed `"` whose partner is an escaped LAST character (`\\`` is one
    pair, it jumps past the partner to the end) left the pair's limit behind after the E8 rewind; a `#` of the re-read
    ended at it and the walker raised IndexError - the hook exited 1 (fail-open). Expected values are the shell's: after
    the rewind the text reads as the text without the dropped quote (E8), `#` at a word start begins a comment."""
    tick, bs = chr(96), chr(92)
    shape = lambda text: [(u.kind, u.form, [[w for w, _q in s] for s in u.segments]) for u in hooklib.walk(text, "bash")]  # noqa: E731
    stale = '" #' + tick + bs + tick
    check_eq("N-1 a comment at a stale limit: one top unit, the comment holds no command, no exception",
             shape(stale), [("top", "top", [])])
    tail = " #" + tick + " " + bs + tick
    for name, text in (("a quoted heredoc delimiter, an odd quote in the body", "cat <<'EOF'\n\"\nEOF\npytest -q" + tail),
                       ("an unquoted delimiter, ${HOME} and an odd quote in the body", 'cat <<EOF\n${HOME} "\nEOF\npytest -q' + tail)):
        check_eq(f"N-1 R1: {name}, a launch before the comment: a launch", hooklib.is_direct_test_run(text, "bash"), True)
        check_eq(f"N-1 R1 control: {name}, `ls -la` there: none", hooklib.is_direct_test_run(text.replace("pytest -q", "ls -la"), "bash"), False)
    in_dq = '"echo ' + tick + "pytest -q" + bs + tick
    check_eq("N-1 a backtick inside an unclosed quote, its partner an escaped last character: the pair after the rewind",
             shape(in_dq), [("top", "top", [["echo", tick + "pytest -q" + bs + tick]]), ("region", "tick", [["pytest", "-q" + bs + tick]])])
    check_eq("N-1 ... R1 sees the launch in it", hooklib.is_direct_test_run(in_dq, "bash"), True)
    # the order: the limit is tested BEFORE the end of the input, so the pair closes AT its partner even when the escaped
    # partner jumped past the end (a pair left open to the end could outlive a rewind)
    check_eq("N-1 an escaped partner as the last character: the region ends AT the partner (index 8), not at the end (9)",
             [(u.start, u.end) for u in hooklib.walk("echo " + tick + "a" + bs + tick, "bash") if u.kind == "region"], [(6, 8)])
    # the rewind itself: no frame-bound state survives the frames it deletes (the reader's own moves, then the rewind)
    reader = hooklib._Reader('"' + tick + "a" + tick, "bash")
    reader._code(reader.stack[-1], '"')
    reader._dq(reader.stack[-1], tick)
    opened = (reader.tick is not None, [frame.kind for frame in reader.stack])
    reader.i = reader.n
    check_eq("N-1 a rewind that deletes the open pair clears it: no stale limit is left behind",
             (opened, reader._rewind_unclosed_quote(), reader.tick, [frame.kind for frame in reader.stack]),
             ((True, ["top", "dq", "tick"]), True, None, ["top"]))
    for text, want in (('pytest -q "', True), ('echo "', False), ('"', False)):
        check_eq(f"N-1 an unclosed quote at the end: {text!r} reads without it (E8)", hooklib.is_direct_test_run(text, "bash"), want)
    check_eq("N-1 an empty command: no unit, no launch", (hooklib.walk("", "bash"), hooklib.is_direct_test_run("", "bash")), ([], False))
    # F-9: the ONE argv join; Q-9: never str(list)
    check_eq("F-9 argv_text: a list and a tuple are their joined line; None and empty are empty; text is itself",
             [hooklib.argv_text(v) for v in (["git", "commit", "-m", "x"], ("pytest", "-q"), None, [], "", "ls -la", ["a b", 1])],
             ["git commit -m x", "pytest -q", "", "", "", "ls -la", "a b 1"])
    join = '" ".join(str(part) for part in'
    copies = {path.name: path.read_text(encoding="utf-8").count(join) for path in sorted(hooklib.PLUGIN_ROOT.glob("scripts/*.py"))}
    check_eq("F-9 the argv join is written ONCE in the shipped scripts (hooklib.argv_text); a reader joins through it",
             {name: count for name, count in copies.items() if count}, {"hooklib.py": 1})
    # a walker that raises is a WalkerError for every caller (the guards block on it, never let it through unread)
    def boom(self, *args, **kwargs):
        raise IndexError("synthetic walker failure")

    raised = []
    with reader_patched("_code", lambda real: boom) as real:   # SC1-5b: from an empty cache, or a cached text never reaches `boom`
        for call in (lambda: hooklib.walk("pytest -q", "bash"), lambda: hooklib.command_segments("pytest -q", "bash"),
                     lambda: hooklib.is_direct_test_run("pytest -q", "bash")):
            try:
                call()
                raised.append(None)
            except hooklib.WalkerError as exc:
                raised.append(str(exc))
    check_eq("N-1 a failure inside the walker is a WalkerError naming the cause, for walk, the _scan view and R1",
             raised, ["IndexError: synthetic walker failure"] * 3)
    check_eq("N-1 the walker is restored", hooklib._Reader._code is real, True)


def part_edges_and_caps() -> None:
    """Magnitude and the reader's caps. `_scan` has NO byte cap (it is linear); the only cap on its readers in
    hooklib is `_MAX_PAYLOAD_DEPTH` (3: the text is depth 0, payloads 1..3), pinned here AT (3) and BEYOND (4)
    with the new escapes inside the payload; the 60 KB magnitude is the one test_run_forms uses."""
    big = "a\\$b " * 20000
    check_eq("magnitude: 100 KB of escaped dollars is one slice (bash)", len(slices(big, "bash")), 1)
    check_eq("magnitude: 100 KB of block comments with a word between is one slice (powershell)",
             len(slices("<# x #> a " * 12000, "powershell")), 1)
    check_eq("magnitude: 60 KB of unclosed <# is no slice (powershell)", slices("<#" * 30000, "powershell"), [])
    check_eq("magnitude: 20000 stop-parsing tokens in one line are one slice (powershell)",
             len(slices("--% " * 20000, "powershell")), 1)
    check_eq("magnitude: an odd run of 100001 backslashes ends in a literal one, no crash (bash)",
             len(slices("\\" * 100001, "bash")), 1)

    def bash_c(levels: int, inner: str) -> str:
        out = inner
        for _ in range(levels):
            out = "bash -c " + '"' + out.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return out
    payload = "echo a\\$b; pytest -q"
    check_eq("cap: a launch behind an escaped dollar at payload depth 3 (AT the cap) is found",
             hooklib.is_direct_test_run(bash_c(3, payload)), True)
    check_eq("cap: ... at depth 4 (BEYOND the cap) the BASH reading does not read it",
             "bash" in hooklib.launch_readings(bash_c(4, payload)), False)
    check_eq("cap: ... and at depth 3 the bash reading does",
             "bash" in hooklib.launch_readings(bash_c(3, payload)), True)
    check_eq("cap: ... the union answer at depth 4 is True BY DESIGN (CX1-20 F-3): the PowerShell reading closes the "
             "outer quote at the first `\\\"` and meets the launch at a lower depth",
             hooklib.is_direct_test_run(bash_c(4, payload)), True)
    check_eq("cap: ... and at depth 0 it is found", hooklib.is_direct_test_run(payload), True)
    check_eq("magnitude: a launch at the end of 100 KB of escaped dollars is found (bash)",
             hooklib.is_direct_test_run("echo a\\$b; " * 9000 + "pytest -q"), True)
    check_eq("magnitude: 100 KB of escaped dollars and no launch passes (bash)",
             hooklib.is_direct_test_run("echo a\\$b; " * 9000), False)


def part_walk_contract() -> None:
    """CX1-20 W1-W12 (t-995 section 6) and the R1/R5 rows of the walker: the answer per reader (FR-58: from the shell's
    rules and the reviews' verdicts)."""
    import time
    unit_texts = lambda text, d: [hooklib.masked_text(u) for u in hooklib.walk(text, d) if u.kind == "region"]  # noqa: E731
    check_eq("W1 echo $(echo $(true)): flat masked regions", unit_texts("echo $(echo $(true))", "bash"), ["echo QASUB", "true"])
    check_eq("W2 echo $(a $(b) c $(d))", unit_texts("echo $(a $(b) c $(d))", "bash"), ["a QASUB c QASUB", "b", "d"])
    top = hooklib.walk(f"python -X $(true)cat {RUN} --task X", "bash")[0]
    word = top.segments[0][2][0]
    check_eq("W3 one slice, the word raw, wild, cleaned `cat`", (len(top.segments), str(word), hooklib.is_wild(word), hooklib.cleaned_word(word)),
             (1, "$(true)cat", True, "cat"))
    for dialect, text, want in (("bash", "$((0))cat", [("arith", "0")]), ("bash", "<(true)cat", [("proc", "true")]),
                                ("bash", ">(true)cat", [("proc", "true")]),
                                ("powershell", "<(x)", [("group", "x")])):   # PowerShell: `(` glued to a word opens a group (W5)
        check_eq(f"W4 {dialect} {text!r}: ONE region of the named form, its body is judged on its own (Q1: the safe side)",
                 [(u.form, hooklib.masked_text(u)) for u in hooklib.walk(text, dialect) if u.kind == "region"], want)
    check_eq("W5 PowerShell (@())cat and x(...)", [len(unit_texts(t, "powershell")) > 0 for t in ("(@())cat", "x(pytest -q)")], [True, True])
    check_eq("W6 bash (L) is a cut, no region", unit_texts(f"(python {RUN})", "bash"), [])
    check_eq("W7 single quotes hold no region", [unit_texts("'$(x)'", d) for d in ("bash", "powershell")], [[], []])
    check_eq("W8 a backtick pair outside and inside double quotes; an unpaired one is dropped",
             [unit_texts(t, "bash") for t in ("echo `a`", 'echo "`a`"', "echo `a")], [["a"], ["a"], []])
    check_eq("W9 unpaired $( $(( <( run to the end", [unit_texts(t, "bash") for t in ("echo $(a b", "echo $((a b", "echo <(a b")],
             [["a b"], ["a b"], ["a b"]])
    check_eq("W10 None, empty and blanks: `walk` yields no unit at all (it skips a blank source)",
             [hooklib.walk(t, "bash") for t in (None, "", "   ")], [[], [], []])
    check_eq("W10 ... and `command_segments` (the _scan view) answers no segments and no regions",
             [hooklib.command_segments(t, "bash") for t in (None, "", "   ")], [([], [])] * 3)
    check_eq("W11 no substitution: the old answer (words, no regions, raw slices)",
             (words("rg -n 'a|b' f; ls | wc", "bash"), hooklib.command_segments("rg -n 'a|b' f; ls | wc", "bash")[1],
              slices("rg -n 'a|b' f; ls | wc", "bash")),
             ([["rg", "-n", "a|b", "f"], ["ls"], ["wc"]], [], ["rg -n 'a|b' f", " ls ", " wc"]))

    def took(n: int) -> float:
        started = time.perf_counter()
        hooklib.walk("$(" * n, "bash")
        return time.perf_counter() - started
    small, big = took(20000), took(200000)
    check("W12/33 200 000 openers: no exception, a flat walk, 10x the input under 25x the time", big / max(small, 1e-6) < 25, f"{big:.2f}/{small:.2f}")
    check_eq("33 unpaired and PowerShell openers: no exception",
             [len(hooklib.walk(t, d)) > 0 for t, d in (("<(" * 200000, "bash"), ("(" * 200000, "powershell"))], [True, True])
    # R1, the answer per row
    cases = (("echo $(echo $(echo $(echo $(pytest -q))))", True), ("echo $(" * 5 + "pytest -q" + ")" * 5, True),
             ("Write-Output (pytest -q)", True), ("(pytest -q)", True), ("@(pytest -q)", True), ("C:\\venv\\Scripts\\pytest.exe -q", True),
             ("py$(true)test -q", True), ('"py$(true)test" -q', True), ("$(true) pytest -q", True), ("python -m $(true) pytest -q", True),
             ("python $(echo -m) pytest -q", True), ("uv run $(true) pytest -q", True), ("`true` pytest -q", True),
             ("echo $(true) pytest -q", False), ("echo $(date) done", False), ("Write-Output x(pytest -q)", True),
             ("find . -name x -exec pytest -q {} +", True), ("ForEach-Object { pytest -q }", True), ("& { pytest -q }", True),
             ("$f = { pytest -q }", True), ("$f = { Write-Host x }", False), ("<# x #> pytest -q", True),
             ("echo ${x:-$(pytest -q)}", True), ("echo \"a\" \\\"; pytest -q; echo \"b\"", True), ("echo a\\ #; pytest -q", True),
             ("pwsh -Command 'git commit -m \"a`\" ; dotnet test\"'", False), ('git commit -m "a\\" ; dotnet test"', True))
    for text, want in cases:
        check_eq(f"R1 {text[:60]!r}", hooklib.is_direct_test_run(text, "bash"), want)
    check_eq("R1 None, empty, blanks", [hooklib.is_direct_test_run(t, "bash") for t in (None, "", "   ")], [False] * 3)
    check_eq("R1 the 400 and 3000 pins: no exception", [hooklib.is_direct_test_run(t) for t in ("echo " + "$(" * 400, "bash -c " * 3000 + "pytest")], [False, False])
    # R5: the read guard reads the one table after the quote and escape characters are out
    import host_adapter
    for text, refused in (("rg --p\\re python x f.json", True), ("rg --pre\\=python x f.json", True), ("rg --pre python x f.json", True),
                          ("rg -n 'x --pre y' f.json", False), ("rg -n -e foo f.json", False), ("rg -n -- -exec f.json", False),
                          ("rg -n 'system(' f.json", False), ("Get-Content (Remove-Item x)", True)):
        check_eq(f"R5 {text!r}", bool(host_adapter._read_refusal(text)), refused)


@contextlib.contextmanager
def counted_reads():
    """The (text, dialect) of every `_Reader.run` while the block runs, from an EMPTY cache (SC1-5b: a read that is a cache hit
    never reaches the reader, so a count that starts from a warm cache counts nothing)."""
    calls = []

    def counting(real):
        def run(self):
            calls.append((self.text, self.dialect))
            return real(self)
        return run

    with reader_patched("run", counting):
        yield calls


def unit_snapshot(text: str, dialect: str) -> list:
    """Everything a reader could change in what `walk` hands over, as plain values (a Word's `wild` and `clean` included)."""
    return [(u.kind, u.form, u.depth, u.start, u.end, u.quoted, list(u.spans), list(u.kids),
             [[(str(w), hooklib.is_wild(w), getattr(w, "clean", None), q) for w, q in segment] for segment in u.segments])
            for u in hooklib.walk(text, dialect)]


@contextlib.contextmanager
def one_read_project():
    """A temp project with a pending pipeline for QA-9, the hook layer pointed at it, and `hook_call(command)`: the stage guard
    as the hook runs it, returning (exit code, the refusal text). Restores the hook layer's root and removes the project."""
    import io
    import json
    import stage_guard as SG
    from harness import cleanup, temp_project, use_project

    root = temp_project("qa-one-read-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-9"
        (art / "work").mkdir(parents=True)
        with hooklib.selftest_root_restored():
            use_project(root)
            stages = {s["id"]: {"status": "pending"} for s in SG.stage_model()["stages"]}
            (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-9", "gates": {}, "stages": stages}), encoding="utf-8")

            def hook_call(command: str) -> tuple:
                event = {"tool_name": "Bash", "cwd": str(root), "task_id": "QA-9", "tool_input": {"command": command}}
                SG.LAST_DENIAL["message"] = ""
                with contextlib.redirect_stderr(io.StringIO()):
                    code = SG.check_command(event)
                return code, SG.LAST_DENIAL["message"]

            yield hook_call
    finally:
        cleanup(root)


def key_one_delivery_and_commit(hook_call) -> None:
    """K1: the stage guard on a delivery + commit command reads each distinct (text, dialect) once."""
    both = "git commit -m x tests/test_a.py && gh pr create"
    # the pipeline here has S8 pending, so the refusal is the one before gate B (CX2-27 N1, `rule_delivery`); the pin was
    # the older sentence of a ledger that is not ready, left stale by N1
    refusal = ("QA-9: this delivery command (`gh pr create`, from references/adapter-forms.json (github)) is blocked: the guard "
               "read these words as a delivery, and no delivery is possible yet: gate B comes after S8, which is pending. If this "
               "command does not deliver anything, write it without those words in one command: split it into plain commands, or "
               "put the text in a file with the Write tool and name the file. If it does deliver, it waits for gate B.")
    with counted_reads() as calls:
        verdict = hook_call(both)
        after_first = len(calls)
        again = hook_call(both)
    check_eq("K1 the verdict of the delivery + commit command is the refusal of the walk-per-call code (code 2, same text)",
             verdict, (2, refusal))
    check_eq("K1 exactly one `_Reader.run` per distinct (text, dialect) of the call (it was 4 runs for 2 pairs)",
             (after_first, len(set(calls[:after_first]))), (len(set(calls)), len(set(calls))))
    check("K1 ... and there is at least one pair read (the counter counts)", after_first >= 1, str(after_first))
    check_eq("K1 the same call again reads nothing and gives the same verdict", (len(calls) - after_first, again), (0, verdict))


def key_one_b_shared_read(hook_call) -> None:
    """K1b (B-5): the read guard and the stage guard on ONE text share the read."""
    import host_adapter
    text = 'rg -n "git commit" tests/test_a.py'
    with counted_reads() as calls:
        refused = host_adapter._read_refusal(text)
        hook_call(text)
        together = list(calls)
    with counted_reads() as calls:
        host_adapter._read_refusal(text)
        alone_read = len(calls)
    with counted_reads() as calls:
        hook_call(text)
        alone_guard = len(calls)
    check_eq("K1b the read guard accepts the text (so its tokenizer ran in both dialects)", refused, "")
    check_eq("K1b read guard then stage guard: runs == distinct (text, dialect) pairs of the two calls",
             len(together), len(set(together)))
    check("K1b ... fewer than the two calls would make apart (the pair they share is read once)",
          len(together) < alone_read + alone_guard, f"{len(together)} vs {alone_read}+{alone_guard}")


def key_two_the_bound() -> None:
    """K2: the bound (32), at and beyond."""
    texts = [f"echo k2-{n} $(ls k2-{n}); rg -n x f{n}" for n in range(33)]
    with counted_reads():
        first = hooklib.walk(texts[0], "bash")
        for text in texts[1:32]:
            hooklib.walk(text, "bash")
        full = hooklib._read_units.cache_info()
        same = hooklib.walk(texts[0], "bash")
        hit = hooklib._read_units.cache_info()
        check_eq("K2 32 distinct texts fill the cache to its bound", (full.currsize, full.maxsize), (32, 32))
        check_eq("K2 at the bound the first text is still a HIT, with the same verdict", (hit.hits - full.hits, hit.misses - full.misses, same == first),
                 (1, 0, True))
    with counted_reads():
        first = hooklib.walk(texts[0], "bash")
        for text in texts[1:]:
            hooklib.walk(text, "bash")
        full = hooklib._read_units.cache_info()
        same = hooklib.walk(texts[0], "bash")
        evicted = hooklib._read_units.cache_info()
        check_eq("K2 beyond the bound (33 texts) the first is evicted: read again (a MISS), size stays 32, same verdict",
                 (evicted.misses - full.misses, evicted.currsize, same == first), (1, 32, True))


def key_three_frozen(hook_call) -> None:
    """K3: frozen all the way down; a reader's edit of its own answer never reaches the cache."""
    import copy
    import stage_guard as SG
    import host_adapter
    probe = "echo a $(true)b; rg -n 'x|y' f | wc"
    top = hooklib.walk(probe, "bash")[0]
    check_eq("K3 a Unit's segments are a tuple of tuples, its spans and kids tuples",
             (type(top.segments), {type(s) for s in top.segments}, type(top.spans), type(top.kids)), (tuple, {tuple}, tuple, tuple))
    edits = []
    for label, edit in (("append a segment", lambda: top.segments.append(())), ("assign a token", lambda: top.segments[0].__setitem__(0, ("x", False))),
                        ("append a span", lambda: top.spans.append((0, 0))), ("append a kid", lambda: top.kids.append((0, 0)))):
        try:
            edit()
            edits.append(label)
        except (AttributeError, TypeError):
            pass
    check_eq("K3 every edit of a cached Unit fails loudly", edits, [])
    opaque = hooklib.walk("ls", "bash", lambda tokens, d: [("echo hi", "bash")])   # a payload at every hop: the 4th is past the cap
    check_eq("K3 the opaque Unit past the payload cap is frozen too",
             [(type(u.segments), type(u.spans), type(u.kids)) for u in opaque if u.kind == "opaque"], [(tuple, tuple, tuple)])
    check_eq("K3 command_segments of nothing is ([], []) and its outer container is a list",
             (hooklib.command_segments("", "bash"), type(hooklib.command_segments("", "bash")[0])), (([], []), list))
    pristine = copy.deepcopy(hooklib.command_segments(probe, "bash", spans=True))
    mine = hooklib.command_segments(probe, "bash", spans=True)
    mine[0].append("x")
    mine[0][0].append(("y", False))
    mine[1].append("z")
    mine[2].append((0, 0))
    check_eq("K3 a reader that edits the lists it got changes nothing for the next reader",
             hooklib.command_segments(probe, "bash", spans=True), pristine)
    battery = ("git commit -m x tests/test_a.py && gh pr create", "echo $(git stash) `git add tests/x.py`",
               'bash -c "git commit -m x tests/a.py"', "python -X $(true)cat C:/p/run_suite.py --task X", probe, "git stash push -u")
    before = [(unit_snapshot(t, "bash"), unit_snapshot(t, "powershell"), copy.deepcopy(hooklib.command_segments(t, "bash"))) for t in battery]
    for t in battery:
        SG._is_commit_shape(t, {}, {"tool_name": "Bash"})
        SG._delivery_match(t, {})
        SG._shell_segments(t, "bash")
        SG._slices(t, "bash")
        SG._slices(t, "powershell")
        host_adapter._read_refusal(t)
        hook_call(t)
    after = [(unit_snapshot(t, "bash"), unit_snapshot(t, "powershell"), copy.deepcopy(hooklib.command_segments(t, "bash"))) for t in battery]
    check_eq("K3 the Units of the battery texts are equal before and after every reader of the stage guard has run", after == before, True)


def key_four_failed_read_not_cached() -> None:
    """K4: a failing read is never cached; the guard blocks every time."""
    import io
    import stage_guard as SG
    from harness import PLUGIN_ROOT
    bad = "git commit -m k4 tests/test_k4.py && echo $(k4)"

    def boom(self):
        raise IndexError("k4 synthetic failure")

    err = io.StringIO()
    raised, codes = [], []
    with reader_patched("_run", lambda real: boom):
        size = hooklib._read_units.cache_info().currsize
        for _ in range(2):
            try:
                hooklib.walk(bad, "bash")
                raised.append(None)
            except hooklib.WalkerError as exc:
                raised.append(str(exc))
        grown = hooklib._read_units.cache_info().currsize - size
        for _ in range(2):
            with contextlib.redirect_stderr(err):
                codes.append(SG.check({"tool_name": "Bash", "cwd": str(PLUGIN_ROOT), "tool_input": {"command": bad}}))
    check_eq("K4 a failing read is a WalkerError both times, and the cache did not grow",
             (raised, grown), (["IndexError: k4 synthetic failure"] * 2, 0))
    check_eq("K4 the stage guard blocks both times, with the door", (codes, err.getvalue().count("could not read this command")), ([2, 2], 2))
    check_eq("K4 control: the restored reader reads the same text", bool(hooklib.walk(bad, "bash")), True)


def part_one_read_per_text() -> None:
    """SC1-5b (t-1290; spec t-1244 section 3.4 K1-K4): one hook call reads a command text ONCE per dialect, whichever reader asks
    (`walk` for the delivery, commit and runner shapes, `_scan` for the read guard). The cache changes the price, never the verdict
    (AR-15, AR-28); the Units it hands out are frozen, so one reader's edit never reaches another. One function per key."""
    with one_read_project() as hook_call:
        key_one_delivery_and_commit(hook_call)
        key_one_b_shared_read(hook_call)
        key_two_the_bound()
        key_three_frozen(hook_call)
        key_four_failed_read_not_cached()


def main() -> None:
    part_one_read_per_text()
    part_walk_contract()
    part_rows("bash", "bash", BASH_ROWS)
    part_rows("powershell", "powershell", PS_ROWS)
    part_contract()
    part_ban_still_first()
    part_quoted_backslash()
    part_readers_keep_the_launch_in_view()
    part_backtick_regions()
    part_rewind_leaves_no_state()
    part_edges_and_caps()
    finish("test_hooklib_scan")


if __name__ == "__main__":
    main()
