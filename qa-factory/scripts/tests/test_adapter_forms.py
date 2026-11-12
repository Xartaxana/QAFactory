"""adapter_forms.py - the ticket-key form and the delivery forms as DATA (B-405, B-406).

What this file holds, and the mutation each part kills (the one file that kills it):
  the table and its loader ........ a damaged table is named, never read half
  key forms ........................ the Jira near-misses, the prefix-less battery, `key_pattern`, one form per kind
  keys_in / labelled_keys / is_key . the mention lookbehinds, the label, `fullmatch` (B6), leading zeros
  delivery forms ................... the boundary AT and BEYOND two words, config widens and never narrows
  segment_matches .................. the grammar of a delivery command: words, options between, quotes are mentions
  case_forms ....................... `{ticket}` is the project's key shape; one cache per form; the B3 pins
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, SCRIPTS, cleanup, check, check_eq, check_in, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import adapter_forms as AF  # noqa: E402
import case_forms as CF  # noqa: E402

TABLE_FILE = PLUGIN_ROOT / "references" / "adapter-forms.json"
GITHUB = {"adapters": {"ticket": {"name": "github"}}}
GITLAB = {"adapters": {"ticket": {"name": "gitlab"}}}
ADO = {"adapters": {"ticket": {"name": "ado"}}}
RAW = json.loads(TABLE_FILE.read_text(encoding="utf-8"))


def ticket(**row) -> dict:
    return {"adapters": {"ticket": row}}


def vcs(**row) -> dict:
    return {"adapters": {"vcs": row}}


def tokens(text: str) -> list:
    return [(word, False) for word in text.split()]


# --- the table -------------------------------------------------------------------------------------

def table_and_loader() -> None:
    table = AF.load_table()
    check_eq("table: the kinds the data holds", sorted(table.kinds), ["ado", "file", "github", "gitlab", "jira"])
    check_eq("table: jira and file are the one Jira form", table.kinds["jira"]["key"], table.kinds["file"]["key"])
    check_eq("table: the Jira key", table.kinds["jira"]["key"], "[A-Z][A-Z0-9_]+-\\d+")
    check_eq("table: github and gitlab are bare numbers, ado has its extra mention",
             (table.kinds["github"]["key"], table.kinds["gitlab"]["key"], len(table.kinds["ado"]["mentions"])),
             ("\\d+", "\\d+", 1))
    check_eq("table: the fallback kind is jira", table.fallback, "jira")
    check_eq("table: the aliases", table.aliases, {"glab": "gitlab", "gh": "github"})
    check_eq("table: the delivery commands, per host", {k: list(v) for k, v in table.vcs.items()},
             {"gitlab": ["glab mr create", "merge_request.create"], "github": ["gh pr create", "hub pull-request"]})
    check_eq("table: the list heads (CX2-27)", table.list_heads, ("for", "foreach"))
    check("table: cached per process by stat (the same object twice)", AF.load_table() is table)

    work = temp_dir("qa-adapter-forms-")
    try:
        path = work / "adapter-forms.json"
        path.write_text(json.dumps(RAW), encoding="utf-8")
        first = AF.load_table(path)
        check("loader: a file of another path is its own entry", first is not table and first.kinds == table.kinds)
        changed = json.loads(json.dumps(RAW))
        changed["ticket"]["kinds"]["jira"]["example"] = "ZED-1"
        path.write_text(json.dumps(changed, indent=2), encoding="utf-8")
        check_eq("loader: a rewrite is seen (the stat key moved)", AF.load_table(path).kinds["jira"]["example"], "ZED-1")

        def refused(label: str, mutate, needle: str) -> None:
            doc = json.loads(json.dumps(RAW))
            mutate(doc)
            path.write_text(json.dumps(doc), encoding="utf-8")
            try:
                AF.load_table(path)
                got = "no refusal"
            except AF.FormsTableError as exc:
                got = str(exc)
            check(f"loader refuses {label}: names the file, what is wrong and the restore door",
                  "adapter-forms.json" in got and needle in got and "restore references/adapter-forms.json" in got, got)

        refused("a key with a capture group", lambda d: d["ticket"]["kinds"]["jira"].update(key="([A-Z]+)-\\d+"), "capture group")
        refused("a key that matches the empty text", lambda d: d["ticket"]["kinds"]["github"].update(key="\\d*"), "empty text")
        refused("a key that does not compile", lambda d: d["ticket"]["kinds"]["github"].update(key="[0-9"), "does not compile")
        refused("a key that is not text", lambda d: d["ticket"]["kinds"]["github"].update(key=5), "not text")
        refused("a mention with no {key} slot", lambda d: d["ticket"]["prefixless_mentions"].update(hash="#(\\d+)"), "exactly one")
        refused("a mention with two {key} slots", lambda d: d["ticket"]["prefixless_mentions"].update(
            label="({key}) and ({key})"), "exactly one")
        refused("a mention with a second capture group", lambda d: d["ticket"]["prefixless_mentions"].update(
            label="(x)Ticket: ({key})"), "exactly one capture group")
        refused("an extra mention that does not compile", lambda d: d["ticket"]["kinds"]["ado"].update(mentions=["([({key})"]),
                "does not compile")
        refused("a fallback kind the table lacks", lambda d: d["ticket"].update(fallback_kind="linear"), "fallback_kind")
        refused("a schema_version other than 1", lambda d: d.update(schema_version=2), "schema_version")
        refused("no kinds", lambda d: d["ticket"].update(kinds={}), "non-empty")
        refused("an upper-case kind name", lambda d: d["ticket"]["kinds"].update(Linear={"key": "\\d+", "example": "#1"}), "lower-case")
        refused("an empty delivery list", lambda d: d["vcs"]["kinds"]["gitlab"].update(delivery_commands=[]), "non-empty list")
        refused("a delivery command with a quote", lambda d: d["vcs"]["kinds"]["gitlab"].update(delivery_commands=['glab "mr" create']),
                "no quote or escape")
        refused("no mention_commands", lambda d: d["vcs"].pop("mention_commands"), "mention_commands")
        refused("a mention command of three words", lambda d: d["vcs"].update(mention_commands=["git commit now"]), "mention_commands")
        refused("a mention command with a quote", lambda d: d["vcs"].update(mention_commands=['"echo"']), "mention_commands")
        refused("list_heads that is not a list", lambda d: d["vcs"].update(list_heads="for"), "list_heads")
        refused("a list head of two words", lambda d: d["vcs"].update(list_heads=["for each"]), "list_heads")
        refused("a list head with a quote", lambda d: d["vcs"].update(list_heads=['"for"']), "list_heads")
        doc = json.loads(json.dumps(RAW))
        doc["vcs"].pop("list_heads")
        path.write_text(json.dumps(doc), encoding="utf-8")
        check_eq("loader: list_heads is optional, absent reads as no head (today's reading, the side of refusal)",
                 AF.load_table(path).list_heads, ())
        refused("an alias to a host the table lacks", lambda d: d["vcs"]["aliases"].update(bb="bitbucket"), "vcs.aliases")
        refused("a root that is not an object", lambda d: d.clear() or d.update(), "schema_version")
        path.write_text("[1, 2]", encoding="utf-8")
        try:
            AF.load_table(path)
            got = "no refusal"
        except AF.FormsTableError as exc:
            got = str(exc)
        check("loader refuses a JSON list: names the type", "JSON object, got list" in got, got)
        path.write_text("{broken", encoding="utf-8")
        try:
            AF.load_table(path)
            got = "no refusal"
        except AF.FormsTableError as exc:
            got = str(exc)
        check("loader refuses invalid JSON, naming it", "not valid JSON" in got and "adapter-forms.json" in got, got)
        try:
            AF.load_table(work / "absent.json")
            got = "no refusal"
        except AF.FormsTableError as exc:
            got = str(exc)
        check("loader refuses a missing file: names the path and the door", "cannot be read" in got and "absent.json" in got
              and "plugin package" in got, got)
    finally:
        cleanup(work)


# --- the key form -----------------------------------------------------------------------------------

def key_forms() -> None:
    default = AF.key_form(None)
    check_eq("form: no config is the Jira form, from the default", (default.kind, default.prefixed, default.example),
             ("jira", True, "PROJ-123"))
    check_in("form: ...and says it is the default", "the default", default.source)
    check_eq("form: strict is ^(?:p)$", default.strict.pattern, r"^(?:[A-Z][A-Z0-9_]+-\d+)$")
    for label, cfg in (("{}", {}), ("None", None), ("a string", "x"), ("adapters.ticket absent", {"adapters": {}}),
                       ("adapters.ticket not an object", {"adapters": {"ticket": "jira"}}), ("adapters a list", {"adapters": []})):
        check_eq(f"form edge 2: {label} -> the Jira form", (AF.key_form(cfg).kind, AF.key_form(cfg).pattern),
                 ("jira", AF.FLOOR_KEY))
    for kind in ("jira", "file", "JIRA", " Jira "):
        check_eq(f"form: tracker kind {kind!r} -> the Jira form", AF.key_form(ticket(name=kind)).pattern, AF.FLOOR_KEY)
    check_eq("form: `kind` beats `name` (the one reader of the tracker kind)",
             (AF.ticket_kind(ticket(kind="GitHub", name="jira")), AF.key_form(ticket(kind="github", name="jira")).prefixed),
             ("github", False))
    check_eq("form: ticket_kind of nothing is the empty kind", [AF.ticket_kind(c) for c in (None, {}, ticket())], ["", "", ""])
    for cfg in (GITHUB, GITLAB, ADO):
        form = AF.key_form(cfg)
        check_eq(f"form: {form.kind} is a prefix-less number", (form.pattern, form.prefixed, form.example), ("\\d+", False, "#123"))
    check("form: cached by the project's three words (the same object for the same words)",
          AF.key_form(GITHUB) is AF.key_form({"adapters": {"ticket": {"name": "github"}, "vcs": {"name": "x"}}}))
    check("form: and one object per form", AF.key_form(GITHUB) is not AF.key_form({}))

    # edge 3: an unknown tracker kind is the fallback form AND says it is a guess
    guess = AF.key_form(ticket(name="linear"))
    check_eq("form edge 3: an unknown kind with no key_pattern is the Jira form", (guess.kind, guess.pattern), ("linear", AF.FLOOR_KEY))
    check_in("form edge 3: ... a guess, in its source", "a guess", guess.source)
    check_eq("form edge 3: ... and a typed note", [p.code for p in guess.problems], [AF.TRACKER_KIND_GUESSED])
    check_in("form edge 3: ... naming the key that fixes it", "adapters.ticket.key_pattern", guess.problems[0].text)

    # key_pattern: read for `file` and for a kind the data does not know
    mine = AF.key_form(ticket(name="linear", key_pattern="[A-Z]{2,5}-\\d+"))
    check_eq("form: an unknown kind with a valid key_pattern uses it, and it is no guess",
             (mine.pattern, mine.source, mine.problems, mine.prefixed), ("[A-Z]{2,5}-\\d+", "adapters.ticket.key_pattern", (), True))
    check_eq("form: ...and reads keys by it", AF.keys_in("see ABC-12, XYZZY-1 and x-9", ticket(name="linear", key_pattern="[A-Z]{2,5}-\\d+")),
             ["ABC-12", "XYZZY-1"])
    check_eq("form: `file` reads key_pattern too", AF.key_form(ticket(name="file", key_pattern="\\d{4}-[a-z]+")).pattern, "\\d{4}-[a-z]+")
    numeric = AF.key_form(ticket(name="linear", key_pattern="\\d+"))
    check_eq("form: a bare-number key_pattern is a prefix-less form", numeric.prefixed, False)
    # critic t-549 F3 / edge 6: ANY all-digit run of 1..12 that the pattern reads makes it prefix-less, so a number in running
    # text is never a key unless a mention says so
    for word in ("\\d{4,}", "[0-9]{5}", "\\d{12}", "\\d{3}"):
        cfg = ticket(name="linear", key_pattern=word)
        check_eq(f"form F3: key_pattern {word} is prefix-less, and `in 2026 we shipped 12345 items` names no key",
                 (AF.key_form(cfg).prefixed, AF.keys_in("in 2026 we shipped 12345 items", cfg)), (False, []))
    check_eq("form F3: ...and its mentions still read it (`Ticket: 2026`, `#12345`)",
             AF.keys_in("Ticket: 2026 and #12345", ticket(name="linear", key_pattern="\\d{4,}")), ["2026", "12345"])
    check_eq("form F3: a pattern with letters is still prefixed (`[A-Z]{2}\\d{4}`, `\\d{13}`)",
             [AF.key_form(ticket(name="linear", key_pattern=w)).prefixed for w in ("[A-Z]{2}\\d{4}", "\\d{13}")], [True, True])
    # edge 5: one form per kind
    ignored = AF.key_form(ticket(name="github", key_pattern="[A-Z]+-\\d+"))
    check_eq("form edge 5: key_pattern on a kind the data knows is ignored, with a typed note",
             (ignored.pattern, [p.code for p in ignored.problems]), ("\\d+", [AF.KEY_PATTERN_IGNORED]))
    check_eq("form edge 5: jira too", [p.code for p in AF.key_form(ticket(name="jira", key_pattern="[A-Z]+-\\d+")).problems],
             [AF.KEY_PATTERN_IGNORED])
    # edge 4: an invalid key_pattern is ignored AND named; recognition never shrinks to nothing
    for label, word, reason in (("not text", 5, "not text"), ("a list", ["a"], "not text"), ("does not compile", "[A-Z", "does not compile"),
                                ("has a capture group", "([A-Z]+)-\\d+", "capture group"), ("matches the empty text", "[A-Z]*", "empty text")):
        form = AF.key_form(ticket(name="linear", key_pattern=word))
        codes = [p.code for p in form.problems]
        check_eq(f"form edge 4: a key_pattern that {label} is named and ignored (the Jira form stays)",
                 (form.pattern, AF.KEY_PATTERN_UNREADABLE in codes), (AF.FLOOR_KEY, True))
        check_in(f"form edge 4: ({label}) the note names the key and the expected shape", "adapters.ticket.key_pattern",
                 " ".join(p.text for p in form.problems))
    for blank in ("", "   ", None):
        check_eq(f"form: key_pattern {blank!r} is no word at all (no note)", [p.code for p in AF.key_form(ticket(name="github", key_pattern=blank)).problems], [])
    check_in("form: describe_key_form names the example, the pattern and where it comes from", "like #123",
             AF.describe_key_form(GITHUB))
    check_in("form: ...and the source", "tracker kind `github`", AF.describe_key_form(GITHUB))
    check_in("form: a custom pattern with no example still says what it reads", "pattern ABC",
             AF.describe_key_form(ticket(name="linear", key_pattern="ABC-\\d+")))


def reading_keys() -> None:
    jira = {}
    check_eq("keys_in: Jira near-misses (glued letter before, lowercase letter after, glued digit, underscore in front)",
             [AF.keys_in(t, jira) for t in ("fooTP1-9", "TP1-9a", "9TP1-12", "x_TP1-12")], [[], [], [], []])
    check_eq("keys_in: MY_PROJ-12 is ONE key", AF.keys_in("see MY_PROJ-12 and PROJ-13", jira), ["MY_PROJ-12", "PROJ-13"])
    check_eq("keys_in: punctuation and slashes around keys", AF.keys_in("(TP1-9) TP1-9/TP1-10, TP1-11.", jira),
             ["TP1-9", "TP1-10", "TP1-11"])
    check_eq("keys_in: ordered and unique", AF.keys_in("BB-2 AA-1 BB-2 AA-1", jira), ["BB-2", "AA-1"])
    check_eq("keys_in: a one-letter prefix is no Jira key (the shape needs two characters, as it always did)",
             AF.keys_in("A-1", jira), [])
    check_eq("keys_in lookahead pin (C11, edge 10): `TP1-15045_TC_001` names the key TP1-15045",
             AF.keys_in("TP1-15045_TC_001", {}), ["TP1-15045"])
    check_eq("keys_in: a non-string is read as its text, never a raise", [AF.keys_in(v, jira) for v in (None, 5, [], b"A-1")], [[], [], [], []])

    # prefix-less battery (edge 6, edge 7)
    gh = GITHUB
    check_eq("keys_in/gh edge 6: a bare number is no key; #123, `Ticket: 123` are",
             (AF.keys_in("order 123 of 456", gh), AF.keys_in("#123", gh), AF.keys_in("Ticket: 123", gh)), ([], ["123"], ["123"]))
    for text in ("repo#12", "page#12", "&#123;", "#12a", "x#5", "a/#5", "!#5"):
        check_eq(f"keys_in/gh edge 7: {text!r} is not a key", AF.keys_in(text, gh), [])
    check_eq("keys_in/gh edge 7: a hex colour and `Step #1` are candidates for free text", AF.keys_in("color #123456 and Step #1", gh),
             ["123456", "1"])
    check_eq("keys_in/gh: ordered across mentions, once each", AF.keys_in("#9 Ticket: 3 #9 and #3", gh), ["9", "3"])
    check_eq("keys_in/gh edge 8: leading zeros are not normalised", AF.keys_in("#0123 and #123", gh), ["0123", "123"])
    check_eq("keys_in/ado: AB#123 is a key too, rAB#5 is not", AF.keys_in("AB#123 #124 rAB#5", ADO), ["123", "124"])
    check_eq("keys_in/gh: the mention label with a hash or spaces", AF.keys_in("Ticket:#5 Ticket:   6", gh), ["5", "6"])

    # labelled_keys: the Ticket: line only, under every form
    check_eq("labelled: `Step #1 ... Ticket: 123` gives only 123", AF.labelled_keys("Step #1 ... Ticket: 123", gh), ["123"])
    check_eq("labelled: `Fixes #1` gives nothing", AF.labelled_keys("Fixes #1", gh), [])
    check_eq("labelled: under the Jira form the same line names the Jira key",
             AF.labelled_keys("You are qa-scout. Ticket: TP2-2556. Compare TP2-2534.", jira), ["TP2-2556"])
    check_eq("labelled: a key glued to what follows the line is no key (`5-`, `5a`, `5_x`)",
             [AF.labelled_keys(t, gh) for t in ("Ticket: 5-x", "Ticket: 5a", "Ticket: 5_x")], [[], [], []])
    check_eq("labelled: `Ticket` glued to a word before it is no label", AF.labelled_keys("MyTicket: 5", gh), [])
    check_eq("labelled: two lines, ordered, once each", AF.labelled_keys("Ticket: 7 and Ticket: 3 and Ticket: 7", gh), ["7", "3"])

    # B6: a key is the whole value
    for value, expected in (("PROJ-1", True), ("MY_PROJ-12", True), ("PROJ-1\n", False), (" PROJ-1", False), ("PROJ-1 ", False),
                            ("", False), ("proj-1", False), ("PROJ-", False), (5, False), (None, False), (["PROJ-1"], False),
                            (b"PROJ-1", False)):
        check_eq(f"is_key (jira) {value!r}", AF.is_key(value, jira), expected)
    for value, expected in (("123", True), ("123\n", False), (" 123", False), ("#123", False), ("12a", False), ("", False), (123, False)):
        check_eq(f"is_key (github) {value!r}", AF.is_key(value, gh), expected)
    check_eq("prefix_of: PROJ-123 -> PROJ, MY_PROJ-12 -> MY_PROJ; a prefix-less form, a non-key and a non-string have none",
             [AF.prefix_of("PROJ-123", AF.key_form({})), AF.prefix_of("MY_PROJ-12", AF.key_form({})), AF.prefix_of("123", AF.key_form(gh)),
              AF.prefix_of("123", AF.key_form({})), AF.prefix_of(5, AF.key_form({}))], ["PROJ", "MY_PROJ", None, None, None])


# --- the delivery forms ------------------------------------------------------------------------------

def delivery_forms() -> None:
    base = AF.delivery_forms({})
    check_eq("delivery edge 1: no config -> every data kind's commands, each with its source",
             [form for form, _ in base], ["glab mr create", "merge_request.create", "gh pr create", "hub pull-request"])
    check_eq("delivery: the sources name the table and the host", [source for _, source in base][:3],
             ["references/adapter-forms.json (gitlab)", "references/adapter-forms.json (gitlab)",
              "references/adapter-forms.json (github)"])
    check_eq("delivery: vcs_kind goes through the aliases, lower-cased",
             [AF.vcs_kind(vcs(name=n)) for n in ("glab", "GH", "gitlab", "bitbucket", "", " Gitlab ")],
             ["gitlab", "github", "gitlab", "bitbucket", "", "gitlab"])
    check_eq("delivery: `kind` is read when `name` is empty", AF.vcs_kind(vcs(kind="gh")), "github")
    check_eq("delivery: and a config with no vcs at all", [AF.vcs_kind(c) for c in (None, {}, {"adapters": {"vcs": "x"}})], ["", "", ""])
    for label, value, accepted in (
            ("AT the limit: `bb pr`", ["bb pr"], ["bb pr"]), ("a string is ONE entry", "bb pr create", ["bb pr create"]),
            ("whitespace runs collapse", ["bb   pr    create"], ["bb pr create"]),
            ("BEYOND: `git`", ["git"], []), ("BEYOND: empty", [""], []), ("BEYOND: blanks", ["  "], []),
            ("BEYOND: the number 5", [5], []), ("BEYOND: a None element", [None, "bb pr"], ["bb pr"]),
            ("BEYOND: an empty string value", "", []), ("a quote inside", ['bb "pr" create'], []),
            ("a backslash inside", ["bb pr" + chr(92) + " create"], []),
            ("[] keeps the defaults", [], []), ("null is absent", None, []), ("a dict is one invalid entry", {"a": 1}, []),
            ("two valid and one not", ["bb pr create", "git", "az repos pr create"], ["bb pr create", "az repos pr create"])):
        got = [form for form, source in AF.delivery_forms(vcs(delivery_commands=value)) if source == "adapters.vcs.delivery_commands"]
        check_eq(f"delivery config {label}", got, accepted)
        check_eq(f"delivery config {label}: the defaults are never narrowed",
                 [form for form, _ in AF.delivery_forms(vcs(delivery_commands=value))][:4], [form for form, _ in base])
    check_eq("delivery: a configured duplicate of a data command keeps the data source (one entry)",
             [s for f, s in AF.delivery_forms(vcs(delivery_commands=["gh pr create"])) if f == "gh pr create"],
             ["references/adapter-forms.json (github)"])
    problems = AF.delivery_problems(vcs(delivery_commands=["git", 5, None, "bb pr create", ""]))
    check_eq("delivery_problems: one typed row per invalid entry", [p.code for p in problems], [AF.DELIVERY_ENTRY_INVALID] * 4)
    check_in("delivery_problems: names the entry and the expected shape", "`bb pr create`", problems[0].text)
    check_eq("delivery_problems: nothing for a valid config", AF.delivery_problems(vcs(delivery_commands=["bb pr create"])), [])
    check_eq("delivery_problems: nothing for an absent one", AF.delivery_problems({}), [])


def floor_and_damage() -> None:
    table = AF.load_table()
    check_eq("floor: the declared Jira key is the table's", AF.FLOOR_KEY, table.kinds["jira"]["key"])
    check_eq("floor: the declared label is the table's", AF.FLOOR_LABEL, table.mentions["label"])
    check("floor: the declared delivery commands are a subset of the data's",
          set(AF.FLOOR_DELIVERY) <= {form for forms in table.vcs.values() for form in forms})
    saved = AF.TABLE_PATH
    work = temp_dir("qa-adapter-forms-damage-")
    try:
        AF.TABLE_PATH = work / "missing.json"
        for call, label in ((lambda: AF.key_form({}), "key_form"), (lambda: AF.delivery_forms({}), "delivery_forms"),
                            (AF.load_table, "load_table")):
            try:
                call()
                got = "no raise"
            except AF.FormsTableError as exc:
                got = str(exc)
            check(f"damage edge 12: {label} raises, naming the file and the door", "adapter-forms.json" in got and "restore" in got, got)
        form = AF.key_form({}, floor=True)
        check_eq("damage: floor=True gives the Jira floor with a typed note naming the file",
                 (form.pattern, form.prefixed, [p.code for p in form.problems]), (AF.FLOOR_KEY, True, [AF.TABLE_UNREADABLE]))
        check_in("damage: ...and the source says floor", "floor", form.source)
        check_eq("damage: the floor delivery commands are glab and gh only",
                 [f for f, _ in AF.delivery_forms({}, floor=True)], ["glab mr create", "gh pr create"])
        check_eq("damage: a configured command still widens the floor",
                 [f for f, _ in AF.delivery_forms(vcs(delivery_commands=["bb pr create"]), floor=True)],
                 ["glab mr create", "gh pr create", "bb pr create"])
        check_eq("damage: the readers never raise and read the floor", (AF.keys_in("AB-1 #5", GITHUB), AF.labelled_keys("Ticket: AB-1", GITHUB),
                                                                        AF.is_key("AB-1", GITHUB), AF.is_key("5", GITHUB)),
                 (["AB-1"], ["AB-1"], True, False))
        check_eq("damage: delivery_problems names the table first", [p.code for p in AF.delivery_problems({})], [AF.TABLE_UNREADABLE])
        check_eq("damage: vcs_kind still answers (no alias map)", AF.vcs_kind(vcs(name="Glab")), "glab")
    finally:
        AF.TABLE_PATH = saved
        cleanup(work)
    check_eq("damage: after the table is back the answers are the table's again", AF.key_form(GITHUB).prefixed, False)


# --- the grammar of a delivery command ----------------------------------------------------------------

def segment_grammar() -> None:
    gl, gh = "glab mr create", "gh pr create"
    for form, command, expected in (
            (gl, "glab mr create", True), (gl, "glab mr create --fill", True), (gl, "glab  mr create", True),
            (gl, "glab --repo x/y mr create", True), (gl, "glab -R x/y mr create", True), (gl, "glab --repo=x/y mr create", True),
            (gl, "glab mr --repo x/y create", True), (gl, "glab --version mr create", True), (gl, "glab -- mr create", True),
            (gl, "sudo glab mr create", True), (gl, "env X=1 glab mr create", True), (gl, "xargs -I{} glab mr create", True),
            (gl, "glab mr list", False), (gl, "glab mr list create", False), (gl, "glab mr view create", False), (gl, "glab issue create", False),
            (gl, "glab create mr", False), (gl, "glab mr", False), (gl, "glab", False), (gl, "mr create", False),
            (gl, "gh mr create", False), (gl, "glab --repo x/y mr", False), (gh, "gh pr create", True), (gh, "gh pr list", False),
            (gh, "gh -R o/r pr create --draft", True), (gh, "gh   pr   create", True), (gh, "echo gh pr create", True),
            ("bb pr", "bb pr create", True), ("bb pr", "bb pr", True), ("bb pr", "bb issue", False),
            ("merge_request.create", "git push -o merge_request.create", True),
            ("merge_request.create", "git push --push-option=merge_request.create", True),
            ("merge_request.create", "git push -o merge_request.target=main", False),
            ("merge_request.create", "git push", False), ("", "gh pr create", False)):
        check_eq(f"grammar: `{form}` in `{command}`", AF.segment_matches(form, tokens(command)), expected)
    # quotes: the whole command in ONE quoted argument is a mention (the B-404 E4 invariant)
    quoted = [("echo", False), ("glab mr create", True)]
    check_eq("grammar: `echo \"glab mr create\"` (one quoted token) is a mention, not a delivery", AF.segment_matches(gl, quoted), False)
    check_eq("grammar: three quoted words in a row are mentions too",
             AF.segment_matches(gl, [("echo", False), ("glab", True), ("mr", True), ("create", True)]), False)
    check_eq("grammar: a quoted value of an option is skipped as its value",
             AF.segment_matches(gl, [("glab", False), ("--repo", False), ("x y", True), ("mr", False), ("create", False)]), True)
    check_eq("grammar: a one-word form is a mention inside quotes (`echo \"merge_request.create\"`) ...",
             AF.segment_matches("merge_request.create", [("echo", False), ("merge_request.create", True)]), False)
    check_eq("grammar: ... but the quoted VALUE of an option is a push option (`-o \"merge_request.create\"`)",
             AF.segment_matches("merge_request.create", [("git", False), ("push", False), ("-o", False), ("merge_request.create", True)]), True)
    # the program name normaliser of the caller (basename, no .exe)
    base = lambda text: text.replace(chr(92), "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")  # noqa: E731
    check_eq("grammar: a normaliser admits a path and an .exe spelling when the caller has one",
             [AF.segment_matches(gl, tokens(c), base) for c in ("/usr/bin/glab mr create", "glab.exe mr create", "GLAB mr create")],
             [True, True, True])
    check_eq("grammar: without one they are not read (the program is compared as written)",
             [AF.segment_matches(gl, tokens(c)) for c in ("/usr/bin/glab mr create", "glab.exe mr create")], [False, False])
    check_eq("grammar: prefilter words are lower-cased", AF.prefilter_words("Glab MR create"), ("glab", "mr", "create"))
    # critic t-549 F1 (c): a variable in program position may be the program
    for command, expected in (("$gh pr create", True), ("${tool} pr create --fill", True), ("$gh pr list", False),
                              ("$ pr create", False)):
        check_eq(f"grammar F1: `{command}` against `gh pr create`", AF.segment_matches(gh, tokens(command)), expected)
    # CX1-20 B-1 (rewritten: `$(gh) pr create` was False): the walker marks a word with an unquoted substitution wild,
    # and a wild word in program position may BE the program; the tokens below come from the walker, not from split()
    import hooklib
    walked = lambda command, dialect="bash": hooklib.command_segments(command, dialect)[0][0]  # noqa: E731
    for command, expected in (("$(gh) pr create", True), ("$(echo gh) pr create --fill", True), ("`echo gh` pr create --fill", True),
                              ("`echo gh pr` create --fill", True), ("gh $(echo pr) create --fill", True), ("gh pr cre$(true)ate", True), ("gh pr $(echo create) --fill", True),
                              ("gh pr view $(x) --web", False), ("glab mr list --author=$(whoami)", False), ("echo $(date) done", False),
                              ("$(date) pr", False)):
        check_eq(f"CX1-20 wild word: `{command}` against `gh pr create`",
                 AF.segment_matches(gh, walked(command), None, hooklib.cleaned_word, hooklib.is_wild), expected)
    check_eq("CX1-20 wild word: a PowerShell group in program position",
             AF.segment_matches(gh, walked("(gh) pr create", "powershell"), None, hooklib.cleaned_word, hooklib.is_wild), True)
    # F-4: the module keeps no cleaner and no wild test of its own - the reading of a word is the caller's (the stage
    # guard passes `hooklib.cleaned_word` and `hooklib.is_wild`); with none supplied a word is what it is written as
    check_eq("CX1-20 F-4: with no reader supplied no word is wild and none is glued",
             [AF.segment_matches(gh, walked(c)) for c in ("$(gh) pr create", "gh pr cre$(true)ate", "gh $(echo pr) create")],
             [False, False, False])
    check_eq("CX1-20 F-4: the one cleaner reads a backslash inside a plain word too (`g\\h` is `gh` to bash)",
             AF.segment_matches(gh, walked("g\\h pr create"), None, hooklib.cleaned_word, hooklib.is_wild), True)
    # Q-5 (FR-1): a refusal names the command the ROLE wrote, not a form a substitution happens to fit
    named = lambda form, command: AF.written_form(form, walked(command), None, hooklib.cleaned_word)  # noqa: E731
    for form, command, want in (
            (gh, "gh pr create --fill", gh), (gh, "gh pr cre$(true)ate", gh), (gh, "gh $(x) create --fill", "gh ..."),
            (gh, "gh pr $(echo create) --fill", "gh ..."), (gl, "gh $(x) create --fill", "gh $(x) create --fill"),
            (gl, "$(echo glab) mr create --fill", "$(echo glab) mr create --fill"),
            (gl, "`echo glab mr` create --fill --a --b", "`echo glab mr` create --fill --a ...")):
        check_eq(f"CX1-20 Q-5: `{command}` read against `{form}` is named `{want}`", named(form, command), want)
    check_eq("CX1-20 Q-5: the program written in the segment is preferred (`gh` over `glab` for `gh $(x) create`)",
             [AF.program_written(f, walked("gh $(x) create"), None, hooklib.cleaned_word) for f in (gh, gl)], [True, False])
    check_eq("CX1-20 gate: the raw view and the cleaned view both pass `gh pr cre$(true)ate` / `$(echo gh) pr create`",
             (AF.could_be_in(gh, "gh pr cre$(true)ate", "gh pr cre$(true)ate"), AF.could_be_in(gh, "$(echo gh) pr create", "$(echo gh) pr create"),
              AF.could_be_in(gh, "`printf g; printf h` pr create", "`printf g; printf h` pr create"), AF.could_be_in(gh, "ls", "ls")),
             (True, True, True, False))
    check_eq("grammar F1: a quoted `$gh` is text, not a program", AF.segment_matches(gh, [("$gh", True), ("pr", False), ("create", False)]), False)
    check_eq("grammar F1: the cheap gate lets `$tool pr create` through without the program word, not without the subcommand words",
             (AF.could_be_in(gh, "$tool pr create"), AF.could_be_in(gh, "tool pr create"), AF.could_be_in(gh, "$tool pr list")),
             (True, False, False))
    # mention commands: their quoted arguments are text
    said = AF.mention_commands()
    check_eq("mention: the table's list", ("echo",) in said and ("git", "commit") in said and ("grep",) in said, True)
    for command, expected in (("echo gh pr create", True), ("FOO=1 echo x", True), ("grep -rn x docs", True), ("git commit -m x", True),
                              ("git -C app commit -m x", True), ("git --no-pager log", True), ("git push", False), ("git status", False),
                              ("ssh host", False), ("python -c x", False), ("eval x", False), ("/usr/bin/echo x", True), ("", False),
                              ("FOO=1", False),
                              # r0107 clones: one head reader; a dotted, dashed or digit-leading word is no assignment, so it is the head
                              ("FOO_1=1 BAR=2 echo x", True), ("a.b=1 echo x", False), ("-x=1 echo x", False), ("1x=1 echo x", False),
                              ("A=1 B=2", False),
                              # critic F1/F2: a head whose first path component holds `=` names no program; a later component does
                              ("a.b=/bin/echo x", False), ("-x=/bin/grep x", False), ("a.b=/x/for f", False), ("./a=b/echo x", True),
                              ("/a=b/echo x", True), ("C:\\a=b\\echo x", True)):
        check_eq(f"mention: `{command}`", AF.mention_command(tokens(command), lambda t: t.replace(chr(92), "/").rsplit("/", 1)[-1].lower()), expected)
    base = lambda t: t.replace(chr(92), "/").rsplit("/", 1)[-1].lower()
    for text, expected in (("a.b=/x/python", ""), ("-x=/bin/cat", ""), ("a.b=1", ""), ("/usr/bin/Python", "python"), ("./a=b/python", "python"),
                           ("C:\\a=b\\python", "python"), ("a.b", "a.b"), ("", "")):
        check_eq(f"head_program `{text}`", AF.head_program(text, base), expected)
    check_eq("head_program: no name function reads the word lower-case", AF.head_program("Echo"), "echo")
    for command, expected in (("a.b=/bin/echo $(a) $(b)", False), ("echo $(a) $(b)", True), ("-x=/usr/bin/for f", False),
                              ("for f in $(a)", True), ("a.b=1 echo $(a)", False), ("FOO=1 echo $(a)", True)):
        check_eq(f"releases: `{command}`", AF.releases(tokens(command), base, heads=("for",)), expected)
    saved, work = AF.TABLE_PATH, temp_dir("qa-adapter-forms-mention-")
    try:
        AF.TABLE_PATH = work / "missing.json"
        check_eq("mention: with the table unreadable the floor still knows echo, printf, grep and git commit",
                 AF.mention_commands(), (("echo",), ("printf",), ("grep",), ("git", "commit")))
    finally:
        AF.TABLE_PATH = saved
        cleanup(work)



# --- CX2-27: what counts as evidence of the form ---------------------------------------------------------

def oh3_22_table_and_glue() -> None:
    """OH3-22 (N2): the three new `vcs` word lists (readers, validation, the floor) and the consistency rule for a wild word
    that carries literal text: it stands for a word of the form only if that text can be part of it."""
    import hooklib
    check_eq("OH3-22 table: the receivers", AF.text_receivers(), ("cat", "tee", "wc", "sort", "head", "tail"))
    check_eq("OH3-22 table: the script runners", AF.script_runners(), ("run-py",))
    flags = AF.script_plain_flags()
    check("OH3-22 table: flags keep their case (`-s` and `-S`, `-O` and `-OO`)", {"-B", "-u", "-s", "-S", "-O", "-OO"} <= set(flags), flags)
    work = temp_dir("adapter-forms-oh3-22-")
    saved = AF.TABLE_PATH
    try:
        data = json.loads(Path(saved).read_text(encoding="utf-8"))
        for label, key, bad in (("a blank inside a word", "text_receivers", ["cat tee"]), ("a quote", "script_runners", ["run'py"]),
                                ("not a list", "script_plain_flags", "-B")):
            broken = json.loads(json.dumps(data))
            broken["vcs"][key] = bad
            path = Path(work) / f"{key}.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            AF.TABLE_PATH = path
            try:
                AF.load_table()
                got = "no raise"
            except AF.FormsTableError as exc:
                got = str(exc)
            check(f"OH3-22 table: {label} in vcs.{key} raises and names the key", f"vcs.{key}" in got and "restore" in got, got)
            check_eq(f"OH3-22 floor: the damaged table reads none of the lists ({key})",
                     (AF.text_receivers(), AF.script_runners(), AF.script_plain_flags()), ((), (), ()))
        absent = json.loads(json.dumps(data))
        for key in ("text_receivers", "script_runners", "script_plain_flags"):
            absent["vcs"].pop(key)
        path = Path(work) / "absent.json"
        path.write_text(json.dumps(absent), encoding="utf-8")
        AF.TABLE_PATH = path
        check_eq("OH3-22 table: keys absent from a valid table read as none", (AF.text_receivers(), AF.script_runners()), ((), ()))
    finally:
        AF.TABLE_PATH = saved
        cleanup(work)

    def fits(command: str, form: str = "gh pr create") -> bool:
        return any(AF.segment_matches(form, tokens, hooklib._name, hooklib.cleaned_word, hooklib.is_wild)
                   for dialect in ("bash", "powershell") for unit in hooklib.walk(command, dialect) for tokens in unit.segments)
    for command in ("GH$(x) pr create", "/usr/bin/$(x) pr create", "C:" + chr(92) + "t" + chr(92) + "$(x).exe pr create",
                    "$(x).exe pr create", "gh --repo=$(r) pr create", "g$(x) pr create", "gh pr cre$(true)ate", "gh $(x) pr create"):
        check(f"OH3-22 glue r8: {command!r} may stand for the form", fits(command), command)
    for command, form in (("def log(a): foo(b), create_mr()", "glab mr create"),
                          ("source, target = project(), project()  # mr create", "glab mr create"),
                          ("FOO=$(f) pr create", "gh pr create"), ("foo$(x) pr create", "gh pr create")):
        check(f"OH3-22 glue: {command!r} is no {form}", not fits(command, form), command)


def segment_evidence() -> None:
    """Rule L (a `$var` start needs a literal form word after it), Rule H (`released`: pure substitutions under a head that
    is no command of its own are arguments) and `releases`. Tokens come from the walker, so a substitution is a wild Word."""
    import hooklib
    gh, gl = "gh pr create", "glab mr create"
    walked = lambda command, dialect="bash": hooklib.command_segments(command, dialect)[0][0]  # noqa: E731
    reads = lambda form, command, released=False: AF.segment_matches(  # noqa: E731
        form, walked(command), None, hooklib.cleaned_word, hooklib.is_wild, released=released)
    for form, command, want in (
            # Rule L alone: a bare variable with only substitutions after it is no evidence (the finding's rows 1, 2, 4)
            (gh, "$a $(f)", False), ("hub pull-request", "$a $(f)", False),
            (gl, "$a $(f) $(g)", True),   # Rule L alone leaves `$(f)` a start: Rule H (a `$var` head releases it) is what clears it

            (gh, "python x.py --n $a --f b-$(f).txt", False), (gh, "echo $a $(f)", False),
            # ... and a literal form word after it is evidence: the written form stays refused
            (gh, "$gh pr create", True), (gh, "${tool} pr create --fill", True), (gh, "$gh pr $(echo create)", True),
            (gh, "$gh $(echo pr) create", True), (gl, "$gh $(echo pr) create", True), (gh, "$gh pr list", False),
            # a wild word's RAW text is a literal (`$(echo pr create)` holds `pr` and `create`): it fills both words
            (gh, "$gh $(echo pr create)", True), (gh, "gh $(echo pr create) --fill", True), (gh, "$gh $(echo pr list)", False),
            # a named program never needs one
            (gh, "gh $(x) create", True), (gh, "$(echo gh) pr create", True),
            # a start with a substitution keeps today's reading when nothing releases it (pin B-1)
            (gl, "$(a) $(b)", True), (gl, "git $(a) $(b) commit -m x", True)):
        check_eq(f"CX2-27 L: `{command}` against `{form}`", reads(form, command), want)
    for form, command, want in (
            (gl, "echo $(a) $(b)", False), (gl, "$a $(f) $(g)", False), (gl, "for f in $(a) $(b)", False),
            (gl, "$(a) $(b)", False), (gh, "echo $(a) $(b)", False),
            # a literal form word after the substitution keeps the start, whoever the head is
            (gh, "echo $(a) pr create", True), (gl, "for f in $(a) mr create", True),
            # the literal must stand AFTER the start: what a substitution writes inside itself is its own region's business
            (gh, "echo $(echo pr create) x", False), (gh, "echo $(a) pr", False)):
        check_eq(f"CX2-27 H: `{command}` against `{form}`, released", reads(form, command, True), want)
    check_eq("CX2-27 H: released changes nothing for a written program (`echo gh pr create` is still a delivery)",
             reads(gh, "echo gh pr create", True), True)
    check_eq("CX2-27 H: the keyword is optional and off by default (`released` is the caller's reading)",
             AF.segment_matches(gl, walked("echo $(a) $(b)"), None, hooklib.cleaned_word, hooklib.is_wild), True)
    said, heads = AF.mention_commands(), AF.list_heads()
    check_eq("CX2-27 releases: the data's list heads", heads, ("for", "foreach"))
    for command, want in (("echo $(a) $(b)", True), ("FOO=1 echo $(a)", True), ("git commit -m $(a)", True), ("for f in $(a)", True),
                          ("foreach ($x in $(a))", True), ("$a $(f)", True), ("${tool} x", True), ("$(a) $(b)", False),
                          ("git $(a) $(b) commit", False), ("python x.py $(a)", False), ("gh $(a)", False), ("", False),
                          ("FOO=1", False), ("`echo a` $(b)", False)):
        toks = walked(command) if command else []
        check_eq(f"CX2-27 releases: `{command}`", AF.releases(toks, None, said, heads, hooklib.is_wild), want)
    check_eq("CX2-27 releases: a quoted head releases nothing (`\"for\"` and `\"$a\"` stay as they are read)",
             [AF.releases([(w, True)] + tokens("x"), None, said, heads) for w in ("for", "$a")], [False, False])
    saved, work = AF.TABLE_PATH, temp_dir("qa-adapter-forms-heads-")
    try:
        AF.TABLE_PATH = work / "missing.json"
        check_eq("CX2-27 damage: with the table unreadable no list head releases anything (never widens)",
                 (AF.list_heads(), AF.releases(tokens("for f in x"), None, (), None)), ((), False))
    finally:
        AF.TABLE_PATH = saved
        cleanup(work)
    check_eq("CX2-27: many bare variables then a substitution is no match", AF.segment_matches(gh, [("$a", False)] * 5 + [("$(f)", False)],
                                                                               None, hooklib.cleaned_word, lambda t: t == "$(f)"), False)


# --- case_forms: the {ticket} of a case id form ---------------------------------------------------------

def case_form_sites() -> None:
    form = "{ticket}_TC_{nnn}"
    jira = {"case_id_form": form}
    gh = {"case_id_form": form, "adapters": {"ticket": {"name": "github"}}}
    check_eq("case_forms: Jira reads TP1-13877_TC_001", CF.ids_in("see TP1-13877_TC_001 now", jira), ["TP1-13877_TC_001"])
    check_eq("case_forms edge 11: under a numeric form `{ticket}_TC_{nnn}` reads `123_TC_001`",
             CF.ids_in("see 123_TC_001 and TC-9", gh), ["123_TC_001", "TC-9"])
    check_eq("case_forms edge 11 (pinned, noticed): a hyphen is a boundary, so a Jira-shaped id read under a numeric form "
             "gives its number part - `TP1-5_TC_002` reads `5_TC_002`",
             CF.ids_in("TP1-5_TC_002", gh), ["5_TC_002"])
    check_eq("case_forms edge 11: `{ticket}{nnn}` is still refused (the digits would run together)",
             [bool(CF.problems({"case_id_form": "{ticket}{nnn}", "adapters": {"ticket": {"name": "github"}}})),
              CF.forms({"case_id_form": "{ticket}{nnn}"})], [True, ("TC-{nnn}",)])
    check("case_forms edge 11: two configs of one template never share a cache entry",
          CF.pattern(jira) is not CF.pattern(gh) and CF.pattern(gh).pattern != CF.pattern(jira).pattern)
    check_eq("case_forms: the same template compiled per form (the ticket pattern is in it)",
             ("(?:\\d+|" + AF.load_table().local["key"] + ")_TC_" in CF.pattern(gh).pattern,
              "[A-Z][A-Z0-9_]+-\\d+_TC_" in CF.pattern(jira).pattern), (True, True))
    check_eq("case_forms: example under a numeric form, and a placeholder for a non-key",
             (CF.example("123", gh), CF.example("TP1-1", gh), CF.example("TP1-1", jira), CF.example("not a key", jira)),
             ("123_TC_001", "<TICKET>_TC_001", "TP1-1_TC_001", "<TICKET>_TC_001"))
    check_eq("case_forms: is_id and is_case_file_name under the numeric form",
             (CF.is_id("123_TC_001", gh), CF.is_case_file_name("123_TC_001-login.md", gh), CF.is_id("TP1-1_TC_001", gh)),
             (True, True, False))
    # edge 11 / B3: the accepted divergences under the C11 shape, pinned
    check_eq("case_forms B3 pin: is_case_file_name(\"notes_tp1-1_tc_001.md\") is True (IGNORECASE plus `_` in the key)",
             CF.is_case_file_name("notes_tp1-1_tc_001.md", jira), True)
    check_eq("case_forms B3 pin: ids_in(\"S5_TP1-1_TC_001\") returns the phantom id",
             CF.ids_in("S5_TP1-1_TC_001", jira), ["S5_TP1-1_TC_001"])
    check_eq("case_forms: the default form is unchanged and needs no key shape",
             (CF.forms({}), CF.pattern({}).pattern, CF.ids_in("TC-12 and ATC-5", {})), (("TC-{nnn}",), "TC-\\d+", ["TC-12", "TC-5"]))
    # edge 12: a table that cannot be read - the {ticket} templates are unreadable, TC-{nnn} applies, problems() names the file
    saved = AF.TABLE_PATH
    work = temp_dir("qa-adapter-forms-case-")
    try:
        AF.TABLE_PATH = work / "gone.json"
        both = {"case_id_form": [form, "{nnn}_X"]}
        check_eq("case_forms edge 12: the {ticket} template is dropped, the default stays", CF.forms({"case_id_form": form}), ("TC-{nnn}",))
        check_eq("case_forms edge 12: a template with no {ticket} still applies", CF.forms({"case_id_form": ["Z{nnn}", form]}), ("Z{nnn}", "TC-{nnn}"))
        check_in("case_forms edge 12: problems() names the file", "adapter-forms.json", " ".join(CF.problems({"case_id_form": form})))
        check_eq("case_forms edge 12: no problem to report when no template reads a ticket", CF.problems({"case_id_form": "Z{nnn}"}), [])
        check_eq("case_forms edge 12: ids still read in the default form", CF.ids_in("TC-3 TP1-1_TC_001", both), ["TC-3"])
    finally:
        AF.TABLE_PATH = saved
        cleanup(work)
    check_eq("case_forms: and back to normal when the table is back", CF.forms({"case_id_form": form}), (form, "TC-{nnn}"))


# --- the paste route of ticket_adapter (R5) -------------------------------------------------------------------

def paste_route() -> None:
    """`ticket_adapter.write_paste_references` reads the person's text in the project's key form: under a bare-number
    form only `#N` and `Ticket: N` are tickets and the parent is checked by the form; a table that cannot be read is
    the factory's refusal (a TableError, which the verbs turn into exit 4 naming the file)."""
    import ticket_adapter as TA
    import ticket_light as TL
    work = temp_dir("qa-adapter-forms-paste-")
    try:
        def rows_of(cfg: dict, key: str, text: str, parent: str = "") -> dict:
            path = work / "ticket.md"
            path.write_text(text, encoding="utf-8")
            TA.write_paste_references(path, {"title": "Add thing #5", "parent": parent}, cfg, key, work)
            document = json.loads((work / "ticket-references.json").read_text(encoding="utf-8"))
            return {row["ref"]: row for row in document["rows"]}

        rows = rows_of(GITHUB, "123", "Fixes #12 and Ticket: 7, see TP1-9, bare 456", parent="8")
        check_eq("paste/gh: the tickets are the mentions (title #5, #12, Ticket: 7) and the numeric parent",
                 sorted(rows), ["12", "5", "7", "8"])
        check_eq("paste/gh: every ticket row is unproven (no tracker read yet) and has no prefix to probe",
                 sorted((r["status"], r["prefix_known"]) for r in rows.values()), [("unproven", True)] * 4)
        check_eq("paste/gh: the story's own key is not a row", "123" in rows_of(GITHUB, "123", "see #123 and #12"), False)
        rows = rows_of({}, "TP1-15045", "see TP1-9 and #5 and MY_PROJ-12", parent="TP1-100")
        check_eq("paste/jira: today's behaviour - the Jira keys, and `#5` is none", sorted(rows),
                 ["MY_PROJ-12", "TP1-100", "TP1-9"])
        check_eq("paste/jira: the parent's prefix is known, a stranger's is not",
                 (rows["TP1-100"]["prefix_known"], rows["TP1-9"]["prefix_known"], rows["MY_PROJ-12"]["prefix_known"]),
                 (True, True, False))
        saved = AF.TABLE_PATH
        AF.TABLE_PATH = work / "gone.json"
        try:
            try:
                rows_of({}, "TP1-15045", "see TP1-9")
                got = "no refusal"
            except TL.TableError as exc:
                got = str(exc)
        finally:
            AF.TABLE_PATH = saved
        check("paste edge 12: a table that cannot be read is a TableError naming the file (exit 4 in the verbs)",
              "adapter-forms.json" in got and "restore" in got, got)
        check_eq("paste: resolve_adapter reads the kind through adapter_forms.ticket_kind",
                 TA.resolve_adapter(ticket(kind="GitHub", name="jira"))[0], "github")
    finally:
        cleanup(work)


def local_key_forms() -> None:
    """SS1-14 N2a: `ticket.local`, `story_pattern`, `key_refused`, `is_local_form`, `key_pattern_honoured`."""
    table = AF.load_table()
    check_eq("local: the table row", table.local, {"key": "LOCAL-\\d+", "example": "LOCAL-1"})
    check_eq("local: it is no kind (the five kinds of the pin stay)", sorted(table.kinds), ["ado", "file", "github", "gitlab", "jira"])
    jira = AF.key_form({})
    check_eq("local: Jira takes the local example whole, so story_pattern is the pattern", jira.story_pattern, jira.pattern)
    gh = AF.key_form(GITHUB)
    check_eq("local: GitHub's story_pattern is (?:pattern|local key) built from the table", gh.story_pattern, "(?:\\d+|LOCAL-\\d+)")
    check_eq("local: ... and its pattern is still the bare number (the pins of the tracker form)", (gh.pattern, gh.prefixed), ("\\d+", False))
    check_eq("local: a bare number in running text under GitHub is still no key; #N and the Ticket: line with a local key are",
             AF.keys_in("in 2026 we shipped 12345 items, see #7 and Ticket: LOCAL-3", GITHUB), ["7", "LOCAL-3"])
    check_eq("local: Ticket: LOCAL-1 is a label under GitHub", AF.labelled_keys("Ticket: LOCAL-1", GITHUB), ["LOCAL-1"])
    mine = ticket(name="file", key_pattern="[A-Z]{2,4}-\\d+")
    check_eq("local: a project key_pattern that misses the local example takes the union",
             (AF.key_form(mine).pattern, AF.key_form(mine).story_pattern), ("[A-Z]{2,4}-\\d+", "(?:[A-Z]{2,4}-\\d+|LOCAL-\\d+)"))
    check_eq("local: ... one that takes it does not",
             AF.key_form(ticket(name="file", key_pattern="[A-Z]{2,6}-\\d+")).story_pattern, "[A-Z]{2,6}-\\d+")
    for label, cfg in (("jira", {}), ("github", GITHUB), ("gitlab", GITLAB), ("file+pattern", mine)):
        check(f"local: LOCAL-1 is a key under {label}", AF.is_key("LOCAL-1", cfg))
        check(f"local: LOCAL-1_TC_001 is a case id under {label}", CF.is_id("LOCAL-1_TC_001", {"case_id_form": "{ticket}_TC_{nnn}", **cfg}))
    # key_refused: the ONE gate of a launch key (t-508 N2 section 3), the error direction is a question, never a silent pass
    for value, cfg, want in (("ADD-TO-CART", {}, True), ("CART-1", {}, False), ("LOCAL-1", {}, False), ("123", GITHUB, False),
                             ("LOCAL-1", GITHUB, False), ("eng-123", ticket(name="linear"), False),   # a guessed form never refuses
                             ("PROJ-1\n", {}, True), ("PROJ-1 ", {}, True), ("", {}, True), (None, {}, True), (5, {}, True),
                             ("ADD-TO-CART", ticket(name="linear", key_pattern="[A-Z]{2,5}-\\d+"), True)):
        check_eq(f"key_refused({value!r}, {cfg.get('adapters', {}).get('ticket')})", AF.key_refused(value, cfg), want)
    check_eq("form_is_guess: an unknown kind with no pattern", (AF.form_is_guess(ticket(name="linear")), AF.form_is_guess({}), AF.form_is_guess(GITHUB)),
             (True, False, False))
    check_eq("key_pattern_honoured: file and an unknown kind and none; not jira, github",
             [AF.key_pattern_honoured(c) for c in (ticket(name="file"), ticket(name="linear"), {}, {"adapters": {"ticket": {"name": "jira"}}}, GITHUB)],
             [True, True, True, False, False])
    # is_local_form: the shape only, fullmatch, ASCII digits; not text and no table are False
    for value, want in (("LOCAL-1", True), ("LOCAL-12", True), ("LOCAL-", False), ("LOCAL-1\n", False), ("LOCAL-1 ", False),
                        ("local-1", False), ("../../README", False), ("LOCAL-1/../x", False), ("PROJ-1", False), ("", False),
                        (None, False), (1, False), ("LOCAL-" + chr(0x661), False)):
        check_eq(f"is_local_form({value!r})", AF.is_local_form(value), want)
    work = temp_dir("qa-adapter-forms-local-")
    try:
        path = work / "adapter-forms.json"

        def refused(label: str, local, needle: str) -> None:
            doc = json.loads(json.dumps(RAW))
            doc["ticket"]["local"] = local
            path.write_text(json.dumps(doc), encoding="utf-8")
            try:
                AF.load_table(path)
                got = "no refusal"
            except AF.FormsTableError as exc:
                got = str(exc)
            check_in(f"local table: {label} is refused, naming the file", needle, got)
            check_in(f"local table: {label}: and the restore door", "restore references/adapter-forms.json", got)

        refused("a row that is not an object", "LOCAL-1", "`ticket.local` must be an object")
        refused("a key with a capture group", {"key": "(LOCAL)-\\d+", "example": "LOCAL-1"}, "capture group")
        refused("a key that matches nothing of its example", {"key": "LOCAL-\\d+", "example": "X-1"}, "example")
        refused("no example", {"key": "LOCAL-\\d+"}, "example")
        doc = json.loads(json.dumps(RAW))
        del doc["ticket"]["local"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        check_eq("local table: absent reads as none (an old table recognises no local key)", AF.load_table(path).local, None)
    finally:
        cleanup(work)


def main() -> None:
    table_and_loader()
    local_key_forms()
    key_forms()
    reading_keys()
    delivery_forms()
    floor_and_damage()
    segment_grammar()
    segment_evidence()
    oh3_22_table_and_glue()
    case_form_sites()
    paste_route()
    finish("test_adapter_forms")


if __name__ == "__main__":
    main()
