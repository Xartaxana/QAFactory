"""CL1-1 (t-973 with its sections L and L-2, t-987): machine_facts, the one spelling generator and the exit filter of the collect
archive. Every expected value below comes from the requirement named beside the pin (t-962 section 4, the review t-972 leak table,
the sections L and L-2 of t-973), never from running the code (FR-58). The fixture identities are fictional; Cyrillic is written as
\\u escapes (FR-30). Secret-shaped literals are assembled from pieces.

Pins: P1..P49 of t-973 section 6 as corrected by L-2, plus the L-2 additions (the views M2, the non-finite floats and lone
surrogates M3, the torn JSONL line, machine_identities, secret_values and known_hosts M4/M6, the gaps M8), the fix round of the
critic t-999 (t-1009: M-1 the letter escapes, M-2 camelCase names, M-3 escaped separators, m-2 U+E000) and P48, the negative
control: a leak planted into a clean output must be found by residue(), each by its own finder, or the post-check is dead.
"""
import copy
import hashlib
import json
from collections import Counter
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import machine_facts as M  # noqa: E402

RULES = M.load_rules()
HOME = "C:\\Users\\Alexandra_Testova"
PROJECT = "C:\\Work\\proj-zq"
PLUGIN = HOME + "\\.claude\\plugins\\cache\\qafactory\\qa-factory\\0.9.3"
TMP = "C:\\Users\\ALEXAN~1\\AppData\\Local\\Temp"
CYR = "\u0410\u043b\u0435\u043a\u0441\u0430"
CYR_ESC = "\\u0410\\u043b\\u0435\\u043a\\u0441\\u0430"          # the same name as six literal escapes (backslash, u, four hex)
IDS = {"users": ["Alexandra_Testova", "AlexandraTestova"], "display_names": ["Alexandra Testova", CYR], "emails": [],
       "machine": ["WKS-ZT9QA01"], "domain": ["EXAMPLECORP"]}
HOSTS = ("git.corp-zq.example", "stand.corp-zq.example", "10.20.30.40")
SECRETS = {"STAND_PASSWORD": "Zq7-pass-Word", "SHORT_PW": "seven77"}
LEAKS = ["Alexandra_Testova", "AlexandraTestova", "Alexandra Testova", CYR, "WKS-ZT9QA01", "EXAMPLECORP", "stand.corp-zq.example",
         "git.corp-zq.example", "10.20.30.40", "Zq7-pass-Word", "ALEXAN~1", PROJECT, HOME]
SEEN: list = []                       # (redactor, output) of every pin that records: the sweep of P48 reads them


def h8(host):                          # the formula of section 2, written from the requirement
    return "host-" + hashlib.sha256(host.lower().encode()).hexdigest()[:8]


def mk(rules=None, **over):
    args = dict(project_root=PROJECT, plugin_root=PLUGIN, pythons=("C:\\Py312\\python.exe",), home=HOME, tmp=TMP, identities=IDS,
                hosts=HOSTS, secret_values=SECRETS, short=lambda p: None)
    args.update(over)
    return M.compile_redactor(rules or RULES, **args)


R = mk()


def T(name, expected, text, red=None, record=True):
    red = red or R
    got = red.text(text)[0]
    check_eq(name, got, expected)
    if record:
        SEEN.append((red, got))
    return got


def F(red, name, data):
    return red.file(name, data if isinstance(data, bytes) else data.encode("utf-8"))


KEPT_KEYS = {"Set-Cookie", "aws_secret_access_key", "password"}      # key names kept on purpose: the name is context, the value is the secret


def leaves(node):
    """The strings of a parsed JSON output the sweep reads: every value and every key except the kept secret-key names."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key not in KEPT_KEYS:
                yield key
            yield from leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from leaves(value)
    elif isinstance(node, str):
        yield node


def jfile(name, text, red=None):
    res = F(red or R, name, text)
    out = json.loads(res.data.decode("utf-8-sig")) if res.status == "copied" else None
    SEEN.extend((red or R, leaf) for leaf in leaves(out))
    return res, out


def sweep(pairs):
    found = []
    for red, out in pairs:
        found += [("residue", f["finder"], out) for f in red.residue(out)]
        found += [("literal", lit, out) for lit in LEAKS if lit.lower() in out.lower()]
    return found


# --- the spellings of a path -----------------------------------------------------------------------------------------------

def paths_and_names():
    T("P1: the project root -> <project>", "see <project>\\state\\x.json", "see C:\\Work\\proj-zq\\state\\x.json")
    res, out = jfile("a.json", '{"p": "C:\\\\Users\\\\Alexandra_Testova\\\\AppData\\\\x"}')
    check_eq("P2: a JSON value (parsed, backslashes single) -> <home>\\AppData\\x", out, {"p": "<home>\\AppData\\x"})
    T("P3: forward slashes", "<home>/x", "C:/Users/Alexandra_Testova/x")
    T("P3: lower case", "<home>\\x", "c:\\users\\alexandra_testova\\x")
    T("P3: the JSON-escaped spelling inside a text line (the rest of the line is untouched)", "<home>\\\\x", "C:\\\\Users\\\\Alexandra_Testova\\\\x")
    T("P4: Claude's slug of the home", "<home>-proj", "C--Users-Alexandra-Testova-proj")
    T("P5: MSYS /c/Users/<name> -> <abs>/<last>", "<abs>/x", "/c/Users/Alexandra_Testova/x")
    T("P6: file:/// -> <abs>/<last segment> (t-962 section 4)", "<abs>/x.html", "file:///C:/Users/Alexandra_Testova/x.html")
    T("P7: the 8.3 temp folder", "<tmp>\\a.txt", "C:\\Users\\ALEXAN~1\\AppData\\Local\\Temp\\a.txt")
    T("P7: the derived 8.3 alias of the name, in text", "user <user> here", "user ALEXAN~1 here")
    res, out = jfile("b.json", '{"u": "ALEXAN~1"}')
    check_eq("P7: ... as a whole JSON value", out, {"u": "<user>"})
    T("P7: the alias of a name with a dot: john.smith -> JOHN~1.SMI (m4)", "x <user> y", "x JOHN~1.SMI y",
      mk(identities={"users": ["john.smithson"]}))
    alias = mk(short=lambda p: "C:\\Users\\ALEXAN~2" if p == HOME else None)
    T("P7: the real 8.3 form of the home through the seam", "<home>\\z", "C:\\Users\\ALEXAN~2\\z", alias)
    ann, jo = mk(identities={"users": ["ann"]}), mk(identities={"users": ["jo"]})
    T("P8: a name of 3 characters is replaced as a word (AT 3)", "by <user> today", "by ann today", ann)
    T("P8: ... never inside a longer word", "annotation", "annotation", ann)
    T("P8: a name of 2 characters is not searched (BEYOND 2)", "by jo today", "by jo today", jo)
    check("P8: ... and is a named gap of kind identity_too_short, 2 chars", any(g["kind"] == "identity_too_short" and "2 chars" in g["what"] for g in jo.gaps))
    wk6, wk5 = mk(identities={"machine": ["WKS001"]}), mk(identities={"machine": ["WKS01"]})
    T("P9: a machine name of 6 characters is replaced (AT)", "built on <machine>", "built on WKS001", wk6)
    T("P9: 5 characters is not (BEYOND)", "built on WKS01", "built on WKS01", wk5)
    check("P9: ... and is a gap that does not carry the name", any(g["kind"] == "identity_too_short" for g in wk5.gaps) and "WKS01" not in json.dumps(wk5.gaps))
    T("P28: the machine name in a hostname field", 'hostname="<machine>"', 'hostname="WKS-ZT9QA01"')
    T("P26: AzureAD+Name", "AzureAD+<user>", "AzureAD+AlexandraTestova")
    T("P26: AzureAD+ the Cyrillic name", "AzureAD+<user>", "AzureAD+" + CYR)
    T("P27: DOMAIN\\user", "<domain>\\<user>", "EXAMPLECORP\\Alexandra_Testova")
    T("P27: a display name with a space", "Author: <user>", "Author: Alexandra Testova")
    T("P27: one part of a display name (F-2 a)", "<user> wrote", "Testova wrote")
    T("generic accounts are not replaced as words (F-1 a)", "root_dir", "root_dir", mk(identities={"users": ["root"]}))
    T("P38: a user named abs is not re-read in the <abs> token", "<abs>/y", "C:\\x\\y", mk(identities={"users": ["abs"]}))
    T("P39: text() of a name inside a file name", "state/<user>-notes.md", "state/Alexandra_Testova-notes.md")
    check_eq("P39: member_name() -> filesystem-safe tokens", R.member_name("state/Alexandra_Testova-notes.md"), "state/_user_-notes.md")


def residual_paths():
    T("P24: UNC with a name inside", "<abs>/f.txt", "\\\\fileserv\\share\\Users\\Alexandra_Testova\\f.txt")
    T("P24: UNC server and share only", "<abs>", "\\\\fileserv\\share")
    T("P24: file://server/share/file", "<abs>/f.txt", "file://fileserv/share/f.txt")
    T("P25: WSL path", "<abs>/f.txt", "/mnt/c/Users/Alexandra_Testova/proj/f.txt")
    T("P25: the segment after Users is a person: <abs> alone", "<abs>", "C:\\Users\\Ivan\\")
    T("P23: percent-encoded name in file:///", "<abs>/x.txt", "file:///C:/Users/Alexandra%20Testova/x.txt")
    T("P23: percent-encoded drive and separators -> the whole unit", "<redacted>", "C%3A%5CUsers%5CAlexandra_Testova%5Cx")
    T("a residual path with a space in it (a run crosses a single space before a chunk with a slash)", "<abs>/x", "C:\\Program Files\\App\\x")
    T("a path that continues after a token is not residual (m11)", "<project>/a/b.json", "<project>/a/b.json", record=False)
    check_eq("a token-anchored run, the project form", R.text("C:\\Work\\proj-zq/a/b.json")[0], "<project>/a/b.json")


def secrets_and_hosts():
    T("P10: a literal secret value", "pw <secret:STAND_PASSWORD>", "pw Zq7-pass-Word")
    at8 = mk(secret_values={"AT8": "Abcdefg1"})
    T("P10: a value of 8 characters is searched (AT)", "x <secret:AT8> y", "x Abcdefg1 y", at8)
    T("P10: 7 characters is not (BEYOND)", "seven77", "seven77")
    check("P10: ... and is a gap naming the variable and the length, not the value",
          any(g["what"] == "secret below 8: SHORT_PW, 7 chars" for g in R.gaps) and "seven77" not in json.dumps(R.gaps))
    T("P44: a value with a newline: both lines (>= 8) are searched", "<secret:ML>\n<secret:ML>", "Zq7-pass-Word\nSecondLine9",
      mk(secret_values={"ML": "Zq7-pass-Word\nSecondLine9"}))
    T("P11: password, no quotes, long", "<secret>", "password: hunter2hunter2xx")
    T("P11: password, 7 characters", "<secret>", "password: hunter2")
    T("P11: password, 1 character (AT 1)", "<secret>", "password: x")
    T("P11: password with no value (BEYOND 0)", "password:", "password:")
    T("P11: password with only a space", "password: ", "password: ")
    T("P12: Authorization: Bearer", "<secret>", "Authorization: Bearer eyJabc.def")
    T("P12: a bare Bearer of 40", "<secret>", "Bearer " + "A1b2C3d4E5" * 4)
    T("P12: Bearer of 8 (AT)", "<secret>", "Bearer abcd1234")
    T("P12: Bearer of 7 (BEYOND)", "Bearer abcd123", "Bearer abcd123")
    T("P13: Authorization: Basic", "<secret>", "Authorization: Basic dXNlcjpwYXNz")
    T("P13: Basic of 8 (AT)", "<secret>", "Basic dXNlcjpw")
    T("P13: Basic of 7 (BEYOND)", "Basic dXNlcjp", "Basic dXNlcjp")
    T("P14: Cookie", "<secret>", "Cookie: sid=abc")
    T("P14: set-cookie", "<secret>", "set-cookie: a=b")
    for label, head, ok, bad in (("glpat-", "glpat-", 20, 19), ("ghp_", "ghp_", 36, 35), ("github_pat_", "github_pat_", 22, 21),
                                 ("xoxb-", "xoxb-", 10, 9), ("AKIA", "AKIA", 16, 15), ("sk-", "sk-", 20, 19), ("AIza", "AIza", 35, 34)):
        T(f"P15: {label} AT {ok}", "<secret>", "k " + head + "Q" * ok)
        T(f"P15: {label} BEYOND {bad}", "k " + head + "Q" * bad, "k " + head + "Q" * bad)
    T("P16: aws_secret_access_key = value, in a text line (R5: the whole line)", "<secret>", "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    T("P40: a pattern written into a config value", "<secret>", "(?i)aws_secret_access_key")
    pem = "-----" + "BEGIN RSA PRIVATE KEY" + "-----"
    end = "-----" + "END RSA PRIVATE KEY" + "-----"
    got = R.lines(f"{pem}\nMIIEabc\nMIIEdef\n{end}\nafter")[0]
    check_eq("P17: a PEM block, body and END line replaced one by one, the line after kept", got, "<secret>\n<secret>\n<secret>\n<secret>\nafter")
    check_eq("P17: a PEM block with no END runs to the end of the text", R.lines(f"{pem}\nbody\nnext")[0], "<secret>\n<secret>\n<secret>")
    check_eq("P17: BEGIN and END on one line close on that line (m6)", R.lines(f"{pem}x{end}\nafter")[0], "<secret>\nafter")
    T("P17: a PEM inside one JSON value", "<secret>", f"{pem}\nMIIE\n{end}")
    T("P18: URL with userinfo, port, query and fragment", "https://" + h8("stand.corp-zq.example") + ":8443/app", "https://u:p@stand.corp-zq.example:8443/app?q=abc#f")
    T("P18: ?token= in a URL is a secret (the whole unit)", "<secret>", "https://stand.corp-zq.example/app?token=abc")
    T("P18: a kept host stays", "http://localhost:8080/x", "http://localhost:8080/x?y=1")
    T("P18: a port the URL cannot print", "<redacted>", "http://stand.corp-zq.example:99999/x")
    T("P19: scp remote", h8("git.corp-zq.example") + ":team/repo.git", "git@git.corp-zq.example:team/repo.git")
    T("P19: host:port with no user is not an scp remote", "localhost:8080/x", "localhost:8080/x")
    T("P20: known host and IP in prose", f"ping {h8('stand.corp-zq.example')} and {h8('10.20.30.40')}", "ping stand.corp-zq.example and 10.20.30.40")
    T("P20: a longer name that contains the host is another host", "stand.corp-zq.example.org", "stand.corp-zq.example.org", record=False)
    T("P20: ... and so is a longer prefix", "mystand.corp-zq.example", "mystand.corp-zq.example", record=False)
    T("P21: e-mail", "mail <email>", "mail alexandra.testova@corp-zq.example")
    T("P43: NAME=<secret> is not collapsed again", "FOO=<secret>", "FOO=<secret>")
    T("P29: NAME=value in a text unit keeps its place", "x FOO=<secret> y", "x FOO=bar y")
    check_eq("P29: text, A=1 not searched (name < 3), BCD=2 is", R.lines("A=1\nBCD=2\n")[0], "A=1\nBCD=<secret>\n")


def private_ranges():
    for ok, bad in (("10.0.0.1", "11.0.0.1"), ("172.16.0.1", "172.32.0.1"), ("192.168.0.1", "192.169.0.1"), ("169.254.0.1", "169.255.0.1"),
                    ("172.31.255.255", "172.15.255.255")):
        T(f"F-6: {ok} is private (AT)", h8(ok), ok, record=False)
        T(f"F-6: {bad} is not (BEYOND)", bad, bad, record=False)
    T("F-6: a version string that starts with 10. is hashed (the price named in section F)", h8("10.2.3.4"), "10.2.3.4", record=False)
    check("F-6: the ranges are data", RULES["private_ip_ranges"] == ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16"])


def json_files():
    res, out = jfile("c.json", '{"Set-Cookie": "sid=abc", "Accept": "x"}')
    check_eq("P14: JSON header keys: the value is the secret", out, {"Set-Cookie": "<secret>", "Accept": "x"})
    res, out = jfile("d.json", '{"aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG", "region": "eu"}')
    check_eq("P16: JSON: the key stays, the value is the secret", out, {"aws_secret_access_key": "<secret>", "region": "eu"})
    check_eq("P16: ... in the same key order", list(out), ["aws_secret_access_key", "region"])
    res, out = jfile("e.json", '{"x":"FOO=bar","y":1}')
    check_eq("P29: JSON stays JSON, FOO=bar -> FOO=<secret>", out, {"x": "FOO=<secret>", "y": 1})
    check_eq("P29: ... and the key order", list(out), ["x", "y"])
    res, out = jfile("f.json", '{"C:\\\\a\\\\x.json": 1, "D:\\\\b\\\\x.json": 2}')
    check_eq("P31: colliding redacted keys get ' #2'", list(out), ["<abs>/x.json", "<abs>/x.json #2"])
    res, out = jfile("g.json", '{"k": 1, "k": 2}')
    check_eq("P31: a duplicate key in the input is not lost", out, {"k": 1, "k #2": 2})
    res, out = jfile("h.json", '{"ghp_' + "Q" * 36 + '": {"a": 1}}')
    check_eq("P32: a key that carries a secret", out, {"<secret>": {"a": "<secret>"}})
    res, out = jfile("i.json", '{"password": ["abc", 5, true, null, ""]}')
    check_eq("P33: a secret subtree: strings and numbers replaced, true/null/empty kept", out, {"password": ["<secret>", "<secret>", True, None, ""]})
    res, out = jfile("j.json", '{"n": 1234567890}')
    check_eq("P33: a plain number stays", out, {"n": 1234567890})
    res, out = jfile("k.json", '{"who": "' + CYR_ESC + '"}')
    check_eq("P22: an escaped Cyrillic name in a JSON file is parsed, then replaced", out, {"who": "<user>"})
    T("P22: the same escapes in a markdown line -> the unit (escape view)", "<redacted>", "| " + CYR_ESC + " |")
    res, out = jfile("l.json", '{"a": 1e400}')
    check("M3: 1e400 -> the text algorithm, counted json_as_text, never 'Infinity'", res.status == "copied" and res.json_as_text == 1 and b"Infinity" not in res.data)
    res, out = jfile("m.json", '{"x": "\\ud800"}')
    check("M3: a lone surrogate escape -> the text algorithm, no crash", res.status == "copied" and res.json_as_text == 1 and res.data is not None)
    res, out = jfile("n.json", '[1, 2]\n')
    check_eq("indent follows the input: a newline in -> indent 2, trailing newline kept", res.data, b"[\n  1,\n  2\n]\n")
    res, out = jfile("o.json", "\ufeff" + '{"a": 1}')
    check("a UTF-8 BOM of the input is kept", res.data.startswith("\ufeff".encode("utf-8")))


def line_endings():
    check_eq("P30: a lone CR inside a text line is data", R.lines("left\rC:\\Work\\proj-zq\\x")[0], "left\r<project>\\x")
    check_eq("P30: CRLF text keeps its CR", R.lines("a C:\\Work\\proj-zq\\b\r\n")[0], "a <project>\\b\r\n")
    check_eq("P30: JSONL with CRLF", R.jsonl_text('{"p":"C:\\\\Work\\\\proj-zq"}\r\n')[0], '{"p": "<project>"}\r\n')
    raw = '{"p": "a\u2028b"}\n{"q": 2}\n'
    out = R.jsonl_text(raw)[0]
    check("P30: U+2028 inside a JSONL string is escaped; a splitlines() reader still sees one record per line",
          len(out.splitlines()) == 2 and "\u2028" not in out and json.loads(out.splitlines()[0]) == {"p": "a\u2028b"})
    res = F(R, "t.jsonl", '{"a": "C:\\\\Work\\\\proj-zq"}\n{"torn": "' + CYR_ESC + '\n{"p": "C:\\\\Work\\\\proj-zq", "q"\n\n{"ok": 1}\n')
    lines = res.data.decode("utf-8").split("\n")
    check_eq("P49: a torn JSONL line goes through the text algorithm and is counted", res.jsonl_text_lines, 2)
    check_eq("P49: ... the torn line with an escaped name is the whole unit, the other keeps its parts", lines[1:3], ["<redacted>", '{"p": "<project>", "q"'])
    check_eq("P49: ... a blank line stays and the next good line is intact", lines[3:5], ["", '{"ok": 1}'])


def bytes_and_limits():
    res = R.file("e.txt", b"")
    check("P34: an empty file is `empty` with no bytes", (res.status, res.data) == ("empty", b""))
    res = R.file("a.json", b'"   "')
    check("P34: a JSON string of spaces is valid JSON (m5)", res.status == "copied" and res.data == b'"   "')
    check_eq("P34: whitespace that is not JSON", (R.file("a.json", b"   ").status, R.file("a.json", b"   ").reason), ("skipped", "json_unparsable"))
    check_eq("P35: not UTF-8", R.file("a.txt", b"\xc3\x28").reason, "not_utf8")
    check_eq("P35: UTF-16 with a BOM carries NULs -> binary (L-2 M1)", R.file("a.txt", "abc".encode("utf-16")).reason, "binary")
    check_eq("P35: a NUL byte", R.file("a.txt", b"a\x00b").reason, "binary")
    base = b'{"a": 1}'
    at, beyond = R.file("a.json", base + b" " * (16777216 - len(base))), R.file("a.json", base + b" " * (16777217 - len(base)))
    check_eq("P36: JSON of exactly 16777216 bytes is parsed (AT)", at.status, "copied")
    check("P36: 16777217 is too_large with no data and an excerpt (BEYOND)", beyond.status == "too_large" and beyond.data is None and beyond.excerpt is not None)
    small = copy.deepcopy(RULES)
    small["limits"]["text_max_bytes"] = 1000
    tiny = mk(small)
    check_eq("m7: text of exactly text_max_bytes is processed (AT)", tiny.file("n.txt", b"a" * 1000).status, "copied")
    over = tiny.file("n.txt", ("x\n" * 600 + "C:\\Work\\proj-zq\\z\n").encode())
    check("m7: ... one byte more is too_large with an excerpt that went through the editor (BEYOND)",
          over.status == "too_large" and "C:\\Work" not in over.excerpt and "<project>" in over.excerpt)
    small["limits"]["parse_max_bytes"] = 40
    narrow = mk(small)
    res = narrow.file("n.jsonl", b'{"a": 1}\n{"b": "' + b"x" * 60 + b'"}\n')
    check_eq("m7: parse_max_bytes applies per JSONL line: a longer line takes the text algorithm", res.jsonl_text_lines, 1)
    deep = lambda n: ("[" * n + "]" * n).encode()          # noqa: E731
    check_eq("P37: nesting 200 (AT)", R.file("a.json", deep(200)).status, "copied")
    res = R.file("a.json", deep(201))
    check_eq("P37: nesting 201 (BEYOND)", (res.status, res.reason), ("skipped", "too_deep"))
    check_eq("P37: nesting past the parser's own limit", R.file("a.json", deep(5000)).reason, "too_deep")
    check_eq("a top-level scalar is depth 0", R.file("a.json", b"7").status, "copied")
    check_eq("redactions has exactly the manifest keys", sorted(R.file("a.txt", b"x").redactions), ["email", "host", "path", "secret", "user"])
    res = R.file("a.txt", b"C:\\Work\\proj-zq\\a and C:\\Work\\proj-zq\\b")
    check_eq("redactions count the replacements", res.redactions["path"], 2)


def views():
    T("M2: percent view to a fixpoint: double-encoded drive and separators", "<redacted>", "C%253A%255CUsers%255CAlexandra_Testova")
    T("M2: two percent rounds are fine for a benign string (AT)", "q%2541", "q%2541")
    T("M2: three rounds are not provable (BEYOND) -> the unit", "<redacted>", "q%252541")
    T("M2: escaped credential in a URL (escaped slashes)", "<redacted>", "https:\\/\\/admin:S3cret@52.1.2.3\\/x")
    T("M2: a name in angle brackets, escaped, is not hidden by the token mask", "<redacted>", "<" + CYR_ESC + ">")
    T("M2: seven escape rounds of a benign string (AT)", "\\" * 64 + "x41", "\\" * 64 + "x41", record=False)
    T("M2: eight rounds (BEYOND) -> the unit", "<redacted>", "\\" * 128 + "x41")
    T("P42: a secret value that needs JSON escapes, written escaped", "<redacted>", 'v Zq\\"7\\\\pass',
      mk(secret_values={"ODD": 'Zq"7\\pass'}))
    T("M2: a lone-surrogate escape cannot stop the decoder", "a \\ud800 b", "a \\ud800 b", record=False)


def letter_escapes():
    """M-1 (t-999, widened by the Lead's word in t-1009): a name or a known host glued to the letter of a JSON escape."""
    for esc in ("\\n", "\\r", "\\t", "\\b", "\\f"):
        T(f"M-1: a login right after a literal {esc} (AT, each of the five)", "<redacted>", "see" + esc + "Alexandra_Testova")
    T("M-1: the text line of the review", "<redacted>", "line one\\nAlexandra_Testova wrote")
    T("M-1: a known host after a literal \\n", "<redacted>", "see\\nstand.corp-zq.example")
    T("M-1: a part of the display name after a literal \\n", "<redacted>", "log\\nAlexandra_Testova")
    T("M-1: the escape at the very end of the input is no name (BEYOND)", "end\\n", "end\\n", record=False)
    T("M-1: a lone backslash at the end (BEYOND)", "end\\", "end\\", record=False)
    T("M-1: an escaped backslash and an n is not a line break: nothing glued, nothing found (BEYOND)", "a\\\\n b", "a\\\\n b", record=False)
    check_eq("M-1: one pass decodes one level: `\\\\n` -> `\\n`, not a line break", M._unescape("\\\\n"), "\\n")
    check_eq("M-1: the five letters decode, a quote and a slash too", M._unescape("a\\nb\\rc\\td\\be\\ff\\\"g\\/h"), "a\nb\rc\td\be\ff\"g/h")
    check_eq("M-1: controls=False leaves the letters (a folder `\\new`), still decodes hex", M._unescape("C:\\new\\x41", controls=False), "C:\\newA")
    res = F(R, "t.jsonl", '{"msg": "by:\\nAlexandra_Testova", "x"\n')
    check("M-1: a torn JSONL line keeps no login: the unit is replaced and counted", res.data == b"<redacted>\n" and res.jsonl_text_lines == 1)


def camel_names():
    """M-2 (t-999): a camelCase secret name is a secret name, in a JSON key and in text; the price is in the rules `note`."""
    for key, value in (("dbPassword", "Hunter2xyz!"), ("githubToken", "abcdEFGH1234"), ("jiraApiKey", "abcdEFGH1234"),
                       ("awsSecretAccessKey", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"), ("DBPassword", "x1"), ("PASSWORD", "x1"),
                       ("Password", "x1"), ("db_password", "x1")):
        res, out = jfile("cam.json", json.dumps({key: value}))
        check_eq(f"M-2: JSON key {key}: the value is the secret", out, {key: "<secret>"})
    res, out = jfile("cam2.json", '{"dbPassword": "", "passwordless_login_count": 3}')
    check_eq("M-2: ... an empty value stays a key match with nothing to mask; a word that only contains `password` is no secret name", out,
             {"dbPassword": "", "passwordless_login_count": 3})
    T("M-2: text `dbPassword: value`", "<secret>", "dbPassword: Hunter2xyz!")
    T("M-2: text `const dbPassword = \"value\";`", "<secret>", 'const dbPassword = "Hunter2xyz!";')
    T("M-2: text `githubToken=value`", "<secret>", "githubToken=abcdEFGH1234")
    T("M-2: text, a quoted JSON key inside a markdown line", "<secret>", '| "jiraApiKey": "abcdEFGH1234" |')
    T("M-2: text, awsSecretAccessKey", "<secret>", "awsSecretAccessKey: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    T("M-2: control, the snake form is caught as before", "<secret>", "db_password: Hunter2xyz!")
    T("M-2: negative control, `password` inside a word that is not a secret name stays", "passwordless_login_count: 3", "passwordless_login_count: 3")
    T("M-2: ... and a camel word with no value after the name stays", "dbPassword:", "dbPassword:")
    T("M-2: the price named in the note: maxToken is replaced", "<secret>", "maxToken: 4096")
    check("M-2: the camel text row and the camel key form are data (FR-13)",
          any(r["id"] == "assign_secret_name_camel" for r in RULES["secret_patterns"]) and "(?-i:(?=[A-Z]))" in RULES["secret_key_names"])


def escaped_separators():
    """M-3 (t-999) and m-2: a path whose last segment is an escape, a hex escape that looks like part of a folder name, the input's own U+E000."""
    u5c = "\\" + "u005c"
    T("M-3: `D:<u005c>data<u005c>login` -> no login, no `u005c` residue (the reading as written and the decoded one differ: `<abs>`)", "<abs>",
      "D:" + u5c + "data" + u5c + "Alexandra_Testova")
    T("M-3: an escape that makes a letter of the login", "<abs>", "D:\\x\\" + "u0041lexandra_Testova")
    T("M-3: the home root decoded: the segment after Users is a person", "<abs>", "C:" + u5c + "Users" + u5c + "Alexandra_Testova")
    T("M-3: a path that is only an escaped separator (the edge)", "<abs>", "C:" + u5c)
    T("M-3: the unknown last segment behind an escape is not kept", "<abs>", "D:" + u5c + "data" + u5c + "bob")
    T("M-3: the percent twin goes through the percent fixpoint: the unit", "<redacted>", "C:\\x\\q%5CAlexandra_Testova")
    T("M-3: ... and the fully percent-encoded run", "<redacted>", "D%3A%5Cdata%5CAlexandra_Testova")
    T("M-3: control, the plain path keeps its last segment, the login as its token", "<abs>/<user>", "D:\\data\\Alexandra_Testova")
    T("M-3: `\\xaa` after Users is a folder `xaaron`, not a character: Users stays the previous segment", "<abs>", "C:\\Users\\xaaron")
    T("M-3: the five letter escapes are folders in a path: `\\new\\temp\\table.txt`", "<abs>/table.txt", "C:\\work\\new\\temp\\table.txt")
    pua = chr(0xE000)
    T("m-2: the input's own U+E000 before a path is no emitted token: the path is redacted", pua + "<abs>/x", pua + "C:\\Users\\Bob\\x")
    check("m-2: ... and the post-check sees the same path in an unredacted text",
          any(f["finder"] == "residual-path" for f in R.residue(pua + "C:\\Users\\Bob\\x")))
    T("m-2: U+E000 alone changes nothing", pua, pua, record=False)
    T("m-2: a path start right after a real token is still skipped (m11)", "<project>/a/b.json", "<project>/a/b.json", record=False)


def sources():
    ids = M.machine_identities(env={"USERNAME": "winuser01", "USERDOMAIN": "CORPDOM", "COMPUTERNAME": "WKSENV01"}, home="/people/homefolder",
                               run_git=lambda a: {"user.name": "Gitty Person", "user.email": "gp@corp.example"}[a[1]], hostname="wks-host-9.corp",
                               display_name="Display Person", getuser=lambda: "loginname")
    check_eq("F-5: users", ids["users"], ["loginname", "winuser01", "homefolder"])
    check_eq("F-5: display names (git, then the Windows display name)", ids["display_names"], ["Gitty Person", "Display Person"])
    check_eq("F-5: git email", ids["emails"], ["gp@corp.example"])
    check_eq("F-5: machine (hostname, its first label, COMPUTERNAME)", ids["machine"], ["wks-host-9.corp", "wks-host-9", "WKSENV01"])
    check_eq("F-5: domain", ids["domain"], ["CORPDOM"])
    check_eq("F-5: every source gave something, no gap", ids["gaps"], [])
    bare = M.machine_identities(env={}, home="", run_git=lambda a: "", hostname="", display_name="")
    labels = sorted(g["what"] for g in bare["gaps"])
    check_eq("F-5: an absent source is a gap row, one per source", len(labels), 8)
    check("F-5: ... the row names the source", "identity source gave nothing: git user.email" in labels)
    d = temp_dir()
    try:
        (d / ".env.t").write_text("export API_KEY=abcd1234xyz # a note\nQ=\"quoted-value-1234\"\n", encoding="utf-8")
        cfg = {"environment": {"env_file": ".env.t", "secret_keys": ["API_KEY", "Q", "MISSING_KEY"], "user_key": "LOGIN_USER"}}
        values, gaps = M.secret_values(cfg, {"LOGIN_USER": "someuser99"}, root=d)
        check_eq("F-8: `export KEY=` is KEY, the ` # note` tail is cut as a second candidate", values["API_KEY"], ["abcd1234xyz # a note", "abcd1234xyz"])
        check_eq("F-8: quotes stripped; the environment value of user_key", (values["Q"], values["LOGIN_USER"]), (["quoted-value-1234"], ["someuser99"]))
        check_eq("F-8: a name with no value is a gap that names the key only", [g["what"] for g in gaps], ["secret not found: MISSING_KEY"])
        _v, gaps = M.secret_values({"environment": {"env_file": "nope.env", "secret_keys": []}}, {}, root=d)
        check_eq("F-8: env_file absent -> a gap row, never a crash", [g["kind"] for g in gaps], ["env_file_absent"])
        red = mk(secret_values=values, source_gaps=gaps)
        T("F-8: the cut candidate is searched", "tok <secret:API_KEY>", "tok abcd1234xyz", red, record=False)
    finally:
        cleanup(d)
    cfg = {"adapters": {"ticket": {"direct_api": {"base_url": "https://Stand.Corp-ZQ.example:8443/app"}}}, "x": ["host.corp-zq.example:9000", "pytest.ini"],
           "remote": "git@git.corp-zq.example:team/r.git"}
    check_eq("M6: known_hosts: URL, bare host:port, scp, remotes, extra; file names are not hosts",
             M.known_hosts(cfg, remotes=["ssh://git@vcs.corp-zq.example/r.git"], extra=["Extra.Corp-ZQ.example"]),
             ["extra.corp-zq.example", "git.corp-zq.example", "host.corp-zq.example", "stand.corp-zq.example", "vcs.corp-zq.example"])
    import reachability
    check("M6: hosts_kept is a subset of what reachability.LOCAL calls local", all(reachability.LOCAL.match(h) for h in RULES["hosts_kept"]))
    try:
        mk(config_patterns=["fine", "("])
        raised = None
    except M.PatternUnusable as exc:
        raised = exc
    check("F-7: an uncompilable project pattern is a refusal naming its number and the door",
          raised is not None and raised.index == 2 and "fix or remove pattern 2 in qa-factory/config.json secret_content_patterns" in str(raised))
    T("F-7: a good project pattern is a detector", "<secret>", "see zzcustom123", mk(config_patterns=["zzcustom\\d+"]), record=False)


def gaps_and_rules():
    r = mk(identities={"users": ["qx"], "machine": ["WKS01"]}, secret_values={"SHORT_PW": "seven77"})
    rows = json.dumps(r.gaps)
    check("M8: gaps rows carry the kind and the length, never the value", all(v not in rows for v in ("qx", "WKS01", "seven77")) and "SHORT_PW, 7 chars" in rows)
    check("M8: and every gaps row passes through residue()", all(r.residue(g["what"] + " " + g["why"]) == [] for g in r.gaps))
    d = temp_dir()
    try:
        def broken(name, text):
            p = d / name
            p.write_text(text, encoding="utf-8")
            try:
                M.load_rules(p)
            except M.RulesUnreadable as exc:
                return exc
            return None
        missing = None
        try:
            M.load_rules(d / "absent.json")
        except M.RulesUnreadable as exc:
            missing = exc
        check("P47: absent -> RulesUnreadable naming the file and the cause", missing is not None and "absent.json" in str(missing) and missing.why == "the file is absent")
        exc = broken("bad.json", "{not json")
        check("P47: not JSON", exc is not None and exc.why == "not valid JSON")
        exc = broken("s2.json", json.dumps({**RULES, "schema": 2}))
        check("P47: schema 2", exc is not None and "schema" in exc.why)
        exc = broken("nokey.json", json.dumps({k: v for k, v in RULES.items() if k != "tokens"}))
        check_eq("P47: a key missing", exc.why if exc else None, "tokens missing")
    finally:
        cleanup(d)
    check_eq("rules_sha256 is the sha256 of the file bytes", M.rules_sha256(), hashlib.sha256(M.RULES_FILE.read_bytes()).hexdigest())
    import stand_gaps
    row = next(r for r in RULES["secret_patterns"] if r["id"] == "assigned_value")
    mine = M.re.compile(row["regex"])
    check("P45: assigned_value is the twin of stand_gaps._ASSIGNED_VALUE_RE, pattern and flags (no re.I, m1)",
          (mine.pattern, mine.flags) == (stand_gaps._ASSIGNED_VALUE_RE.pattern, stand_gaps._ASSIGNED_VALUE_RE.flags))
    steps = json.loads((PLUGIN_ROOT / "references" / "manual-capture-steps.json").read_text(encoding="utf-8"))
    check("P46: header_names is a superset of manual-capture-steps redact_headers",
          {h.lower() for h in steps["redact_headers"]} <= {h.lower() for h in RULES["header_names"]})
    check_eq("m3 constants: names 3, machine 6", (M.MIN_NAME_CHARS, M.MIN_HOST_CHARS), (3, 6))
    home = M.machine_table(home="/root")
    check("P41: a short home is guarded (`/rooted` does not match)", home.rows[0][2].search("/rooted") is None and home.rows[0][2].search("see /root now") is not None)
    open_t, shut = M.machine_table(tmp="/tmp"), M.machine_table(tmp="/tmp", guard_all=True)
    check("P41: python and tmp rows are unguarded for the census (a match inside x/tmpdir)", open_t.rows[0][2].search("x/tmpdir") is not None)
    check("P41: ... and guarded for the redactor (guard_all)", shut.rows[0][2].search("x/tmpdir") is None)
    check_eq("the machine name shorter than 6 is not in the table", (M.machine_table(host="WKS01").host, M.machine_table(host="WKS001").host), ("", "WKS001"))
    # RH1 canon (t-1461): the slug of `/root` is `-root`, which is also the tail of the CLI flag `--root`; a slug that opens with a
    # dash is a fact only right after a path separator, a raw path stays found wherever it stands.
    rx = home.rows[0][2]
    check("RH1 slug: `--root <x>` with HOME=/root is not a hit", rx.search("context-bundle.json --root <task root> - builds") is None)
    check("RH1 slug: ... nor is a lone `-root` flag or `--root=x`", rx.search("run -root x") is None and rx.search("--root=x") is None)
    check("RH1 slug: a real `/root/...` path is a hit", rx.search("opened /root/.claude/x.json") is not None)
    check("RH1 slug: the project-folder slug `projects/-root-x` is still a hit", rx.search("projects/-root-x/s.jsonl") is not None
          and rx.search("projects\\-root-x\\s.jsonl") is not None)
    check("RH1 slug: `/x-root/` is not the home `/root`", rx.search("/x-root/y") is None)
    seg = M.machine_table(home="/x-root").rows[0][2]
    check("RH1 slug edge: home `/x-root` is found as a path segment, and `--x-root` is not a hit",
          seg.search("see /x-root/y") is not None and seg.search("--x-root a") is None)
    win = M.machine_table(home="C:\\a-root", short=lambda _p: None).rows[0][2]
    check("RH1 slug edge: home `C:\\a-root` is found (raw and forward) and its flag-looking tail is not", win.search("C:\\a-root\\f") is not None
          and win.search("C:/a-root/f") is not None and win.search("--a-root") is None)
    tmp_row = M.machine_table(tmp="/tmp").rows[0][2]
    check("RH1 slug: the same rule holds for the tmp row (`--tmp` is a flag, `/tmp/x` a path)",
          tmp_row.search("pytest --tmp x") is None and tmp_row.search("at /tmp/x") is not None)


def long_unbroken_line():
    """t-1043 DoD 7 / t-1051: the credential-URL finder tried a match at EVERY letter of an unbroken run (quadratic: 5 s for 16 KB, 76 s for
    64 KB). The count is operations, not seconds (FR-31): the positions where a scheme match may START, counted with the rule's own head."""
    rule = RULES["credential_url_regex"]
    marker = "[a-z0-9+.-]*:"
    check("P49 precondition: the rule has the scheme repetition this pin reads the head of", marker in rule, rule)
    probe = M.re.compile(rule[:rule.index(marker)] + "(?=[a-z])")
    check_eq("P49: a 64 KB unbroken alphanumeric line has ONE start position for the credential-URL scan (was 65535)", len(probe.findall("a" * 65536)), 1)
    check_eq("P49: ... and the starts grow with the number of runs, not with their length (two runs, two starts)",
             len(probe.findall("a" * 30000 + " " + "b" * 30000)), 2)
    out, counts = R.text("a" * 65536)
    check("P49: the 64 KB line passes the redactor unchanged", out == "a" * 65536 and sum(counts.values()) == 0)
    cred = M.re.compile(rule)
    check("P49: the finder still sees a credential URL, also after a digit, a dot or a plus (the run start is not a letter)",
          all(cred.search(s) for s in ("https://user:tok@host.example", "xhttps://u:p@h", "1http://u:p@h", ".http://u:p@h", "git+ssh://u@h")))
    check("P49: ... and not a URL without userinfo", cred.search("https://host.example/a@b") is None)


class Counting:
    """A compiled pattern whose calls are counted: a `re.Pattern` cannot be patched in place, so the redactor's own attribute is swapped."""

    def __init__(self, rx, calls):
        self._rx, self._calls = rx, calls

    def __getattr__(self, name):
        attr = getattr(self._rx, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            self._calls["regex"] += 1
            return attr(*args, **kwargs)
        return wrapped


def counting_redactor():
    """(redactor, calls, number of patterns): a fresh redactor whose every compiled pattern and per-unit pass is counted."""
    calls, red = Counter(), mk()
    t, wrapped = red._t, 0
    for name in ("assigned", "email", "url", "scp", "cred", "ipv4", "token_rx", "host_rx"):
        if getattr(t, name) is not None:
            setattr(t, name, Counting(getattr(t, name), calls))
            wrapped += 1
    t.detectors = [(ident, Counting(rx, calls)) for ident, rx in t.detectors]
    t.starts = [Counting(rx, calls) for rx in t.starts]
    wrapped += len(t.detectors) + len(t.starts)
    for ns in (t.paths, t.secrets, t.ident):
        if ns.rx is not None:
            ns.rx, wrapped = Counting(ns.rx, calls), wrapped + 1
    for name in ("_pipeline", "_scan_view", "_residual_spans"):
        def spy(*args, _inner=getattr(red, name), _name=name, **kwargs):
            calls[_name] += 1
            return _inner(*args, **kwargs)
        setattr(red, name, spy)
    return red, calls, wrapped


def one_pass_per_unit():
    """t-1187 (the CL1-2 finding `text` is quadratic on a long unbroken run, 16 KB 5 s, 64 KB 76 s). Measured on the tree of that day: the time
    sat INSIDE one `search` of the old credential-URL rule (a match attempt at every letter of the run), fixed at the rule by t-1051 and pinned
    by P49 above; the redactor's own passes were never per character. This pin holds that second half: the passes a unit takes are
    a function of its VIEWS, never of its length (the count is operations, not seconds, FR-31)."""
    red, calls, k = counting_redactor()

    def run(s):
        calls.clear()
        out, c = red.text(s)
        got = dict(calls)
        return out, c, got, (len(red._views(out)) if out else 0)

    out, c, got, n = run("")
    check("one pass: an empty string -> itself, an empty Counter, no pass and no pattern call", out == "" and not c and got == {}, got)
    out, c, one, n1 = run("a")
    check_eq("one pass: a 1-character unit takes ONE pipeline, one scan per view, and one span search per view plus the residual step",
             (one["_pipeline"], one["_scan_view"], one["_residual_spans"], n1), (1, n1, n1 + 1, 1))
    check("one pass: ... and returns the character unchanged", out == "a" and not c)
    out, c, big, nb = run("a" * 65536)
    check_eq("one pass: the 64 KB unbroken run costs EXACTLY what the 1-character unit costs (every count, patterns included)", big, one)
    check("one pass: ... returned unchanged, Counter empty", out == "a" * 65536 and not c)
    for label, tail in (("an escape", "\\x41" * 100), ("a percent escape", "%41" * 100)):
        out, c, got, views_n = run("a" * 65000 + tail)
        check_eq(f"one pass: a 64 KB run with {label} takes one scan per view ({views_n} views), one pipeline", (got["_scan_view"], got["_pipeline"]), (views_n, 1))
        check(f"one pass: ... and at most 3 calls per pattern per view and per pass ({k} patterns, views + 1 passes)", got["regex"] <= 3 * k * (views_n + 1), got)
        check(f"one pass: ... {label}: more than one view, so the bound is not read at 1", views_n > 1)
    out, c, got, _n = run("ghp_" + "Q" * 65532)
    check_eq("one pass: a 64 KB run that IS a secret-shaped token is still the secret token, counted once", (out, dict(c)), ("<secret>", {"secret": 1}))
    check_eq("one pass: ... and it stops at the detector (no scan of the output)", got.get("_scan_view", 0), 0)
    out, c, got, _n = run("a" * 30000 + "Zq7-pass-Word" + "a" * 30000)
    check_eq("one pass: a named secret value inside a 60 KB run is replaced, once", ("Zq7-pass-Word" in out, c["secret"]), (False, 1))


def document_leaves():
    """t-1187: the post-check reads a JSON file by its string leaves (keys and values after parsing), JSONL by line, text by line. The
    escaped text of a whole JSON file is not a unit the filter wrote: `\\\\.env\\\\.` of the shipped config's pattern list reads as a UNC path."""
    tpl = (PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8")
    check("document: precondition, the shipped template carries the escaped `\\\\.env\\\\.` pattern", '"\\\\.env\\\\."' in tpl)
    patterns = json.dumps({"exempt_path_patterns": ["\\.env$", "\\.env\\."]}, indent=2)       # the template's own two lines, as the file writes them
    check("document: ... and the pattern list read whole as ONE unit IS flagged as a residual path (the defect this reader removes)",
          any(f["finder"] == "residual-path" for f in R.residue(patterns)))
    check_eq("document: the shipped template's pattern list, kind json -> NO finding", R.residue_document(patterns, "json"), [])
    res = F(R, "config.json", tpl)
    out = res.data.decode("utf-8")
    check("document: precondition, the packer's redacted copy of the template read whole as ONE unit is flagged (what t-1024 measured)",
          res.status == "copied" and any(f["finder"] == "residual-path" for f in R.residue(out)))
    check_eq("document: ... and read by its leaves -> NO finding", R.residue_document(out, "json"), [])
    check_eq("document: the early exit and the full list agree on that clean document", R.residue_document(out, "json", _first=True), [])
    check_eq("document: a BOM before the document does not change the reading", R.residue_document(chr(0xFEFF) + out, "json"), [])
    # NEGATIVE control: a real UNC path in a leaf (value, then key) is found, by the same finder `residue` names for the unit
    unc = "\\\\server\\share\\x"
    for label, doc in (("a value", {"a": unc}), ("a key", {unc: 1}), ("a nested value", {"a": [{"b": [unc]}]})):
        got = R.residue_document(json.dumps(doc), "json")
        check(f"document: NEGATIVE control, a UNC path as {label} is found as a residual path", any(f["finder"] == "residual-path" for f in got), got)
    check_eq("document: a leaf is a plain residue unit (the rows are the unit's own rows: finder, category, view)",
             R.residue_document(json.dumps({"a": "pw Zq7-pass-Word"}), "json"), R.residue("pw Zq7-pass-Word"))
    check("document: a stand host as a key is found", "known-host" in [f["finder"] for f in R.residue_document(json.dumps({"stand.corp-zq.example": 1}), "json")])
    check_eq("document: a kept secret-key name (`password`) is read as the writer reads a key: no finding", R.residue_document('{"password": "<secret>"}', "json"), [])
    # the KEY semantics of `_leaves_of` (`key_secret(node) if is_key else False`), pinned in both directions (t-1206 C2-2): a key that is NOT a
    # secret-named key is read with the detectors ON (a token-shaped key is a finding), a secret-named key is read as the writer reads it
    # (`key=True`: the name is context, kept on purpose; detectors-on would flag it as `detector:guard:2`)
    check_eq("document: a token-shaped KEY is read with the detectors on: one detector:github_token row (every key detectors-off would miss it)",
             R.residue_document(json.dumps({"ghp_" + "Q" * 36: 1}), "json"), [{"finder": "detector:github_token", "category": "secret", "view": "raw"}])
    check_eq("document: a secret-NAMED key (`aws_secret_access_key`) is read as the writer reads a key: no finding (every key detectors-on would flag the name)",
             R.residue_document('{"aws_secret_access_key": "<secret>"}', "json"), [])
    nested = '{"p": "\\\\.env\\\\."}'
    check("document: precondition, the text of a nested document read as ONE unit is flagged", R.residue(nested) != [])
    check_eq("document: a leaf that itself looks like JSON is ONE unit, not a nested document (the unit's own rows)",
             R.residue_document(json.dumps({"a": nested}), "json"), R.residue(nested))
    for label, doc in (("a missing brace", '{"a": "\\\\\\\\server\\\\share"'), ("empty", ""), ("a bare word", "nope"), ("a lone surrogate", '"\\ud800"')):
        got = R.residue_document(doc, "json")
        check(f"document: JSON that does not parse ({label}) falls back to its lines, no crash", isinstance(got, list), got)
    check("document: ... and the fallback reads the text as written: the unparsable UNC line is found (never a silent pass)",
          any(f["finder"] == "residual-path" for f in R.residue_document('{"a": "\\\\\\\\server\\\\share"', "json")))
    deep = "[" * 300 + "]" * 300
    check_eq("document: nesting beyond the writer's limit falls back to lines, no crash", R.residue_document(deep, "json"), [])
    # JSONL and text
    clean_jl = '{"a": "\\\\.env\\\\."}\r\n\r\n{"k": ["x", "plain"]}\n'
    check_eq("document: JSONL by line (CRLF, a blank line): the escaped pattern line is read by its leaf -> no finding", R.residue_document(clean_jl, "jsonl"), [])
    got = R.residue_document(clean_jl + "not json C:\\Users\\Alexandra_Testova\\x\n", "jsonl")
    check("document: ... and a line that is not JSON is a unit of its own: its home path is found", "path-literal" in [f["finder"] for f in got], got)
    check_eq("document: an unknown kind is read as text lines (the line reader, never a pass)",
             R.residue_document("a\n\\\\.env\\\\.\n", "whatever"), R.residue("\\\\.env\\\\."))
    check_eq("document: text kind: a clean text -> no finding", R.residue_document("hello\nworld\r\n", "text"), [])
    check("document: text kind: a leak on the second line is found", R.residue_document("hello\nsee C:\\Work\\proj-zq\\x", "text") != [])
    # _first stops at the first leaking unit; the no-fixpoint verdict of a unit passes through
    leaky = json.dumps({"a": "pw Zq7-pass-Word", "b": "pw Zq7-pass-Word", "c": "built on WKS-ZT9QA01"})
    seen = []
    orig = R.residue
    R.residue = lambda unit, *a, **k: (seen.append(unit), orig(unit, *a, **k))[1]
    try:
        first = R.residue_document(leaky, "json", _first=True)
        n_first = len(seen)
        seen.clear()
        every = R.residue_document(leaky, "json")
    finally:
        del R.residue
    check_eq("document: _first stops at the first leaking unit (key `a`, then the leaking value), the full read goes on (3 keys + 3 values)", (n_first, len(seen)), (2, 6))
    check("document: ... and the full list is longer than the early one", len(every) > len(first) >= 1)
    check_eq("document: a leaf with no fixpoint -> the unit's own `no fixpoint` row, unchanged", R.residue_document(json.dumps({"a": "q%252541"}), "json"),
             [{"finder": "views", "category": "secret", "view": "no fixpoint"}])


def negative_control():
    problems = sweep(SEEN)
    check_eq(f"P48: the sweep over {len(SEEN)} recorded outputs finds nothing", problems, [])
    # (expected finder of residue(), planted text): all three are also LEAKS literals, so only the residue() half can tell a live
    # post-check from a dead one (t-999 m-1): the assertion names the finder of each item and nothing else
    planted = [("secret-value", "pw " + "Zq7-pass-Word"), ("path-literal", "see " + PROJECT + "\\state"), ("identity", "built on WKS-ZT9QA01")]
    found = sweep([(R, text) for _finder, text in planted])
    for item in found:
        print("P48 planted finding:", item)
    got = sorted((out, finder) for kind, finder, out in found if kind == "residue" and finder in {f for f, _t in planted})
    check_eq("P48: a leak planted into a clean output is found by residue(), each by its own finder (a check that cannot fail is broken)",
             got, sorted((text, finder) for finder, text in planted))
    check("P48: residue() names a category for a planted secret", R.residue("pw Zq7-pass-Word")[0]["category"] == "secret")


def entry_point():
    proc = subprocess.run([sys.executable, "-B", str(SCRIPTS / "machine_facts.py")], capture_output=True, text=True, timeout=60)
    shape = json.loads(proc.stdout) if proc.returncode == 0 else {}
    check("main(): prints the rules sha256 and the table shape, counts only", proc.returncode == 0 and shape.get("redaction_rules_sha256") == M.rules_sha256()
          and all(set(r) == {"fact", "kind", "spellings"} for r in shape["table"]["rows"]), proc.stderr[-300:])


for step in (paths_and_names, residual_paths, secrets_and_hosts, private_ranges, json_files, line_endings, bytes_and_limits, views, letter_escapes,
             camel_names, escaped_separators, sources, gaps_and_rules, entry_point, long_unbroken_line, one_pass_per_unit, document_leaves,
             negative_control):
    step()
finish("test_collect_redact")
