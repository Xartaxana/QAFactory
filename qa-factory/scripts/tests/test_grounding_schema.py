"""The data form of the S3 grounding step (G1-3): the vocabulary words, the thresholds file, the ONE reader of
`work/grounding.yaml`, the three plan references, the register columns `delta` / `origin`, the two delivery
kinds and the artifact declarations. The step's logic (skeleton, check, measure, gate) is other nodes'.

Edges (spec t-988 section 5 / L-2 / L-4): "no file" is not "empty"; a `schema_version` that is not exactly the
whole number 1 is a problem, never a guess; an unknown top-level key is a problem naming it; typed values and
comments survive in the returned Doc; no other module parses the file; the policy refuses a number that is
not a whole 0..100.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import artifact_registry as AR  # noqa: E402
import contract as C  # noqa: E402
import delivery_verdict as DV  # noqa: E402
import handoff as H  # noqa: E402
import planning_contract as PC  # noqa: E402
import runtime_paths as RP  # noqa: E402

REF = PLUGIN_ROOT / "references"

# --- the vocabulary: the words and their order ---------------------------------------------------------------
vocab = H.vocabulary()
LABELS = ["implements", "refactoring", "behaviour_change", "unrelated", "infrastructure", "test_code", "unclassified"]
STATES = ["implemented", "partial", "not_implemented", "outside_diff", "unknown"]
check_eq("grounding_labels: exactly the seven words, in the refusal order", list(vocab["grounding_labels"]), LABELS)
check_eq("requirement_grounding_states: exactly the five words, in order", list(vocab["requirement_grounding_states"]), STATES)
meanings = list(vocab["grounding_labels"].values()) + list(vocab["requirement_grounding_states"].values())
check("every meaning is a non-empty sentence", all(isinstance(m, str) and len(m.split()) >= 3 for m in meanings))
check("no meaning uses the word AC (the vocabulary says requirement)", not any(re.search(r"\bAC\b", m) for m in meanings))
check("the closed lists are readable through handoff.allowed", sorted(H.allowed("grounding_labels")) == sorted(LABELS)
      and sorted(H.allowed("requirement_grounding_states")) == sorted(STATES))

# --- the thresholds file ---------------------------------------------------------------------------------------
shipped, why = PC.grounding_policy()
check("the shipped policy is readable", shipped is not None and why == "", why)
check_eq("shipped thresholds: notify 30, stop 50, coverage stop below 50",
         (shipped["notify_above_percent"], shipped["stop_above_percent"], shipped["coverage_stop_below_percent"]), (30, 50, 50))
check_eq("shipped numerator: refactoring and unclassified", shipped["numerator_labels"], ["refactoring", "unclassified"])

tmp = temp_dir("grounding-policy-")


def policy(**over):
    doc = dict(shipped)
    doc.update(over)
    for key in [k for k, v in over.items() if v is KeyError]:
        doc.pop(key)
    path = tmp / "policy.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return PC.grounding_policy(path)


for notify, stop in ((0, 1), (29, 30), (30, 50), (49, 50), (99, 100)):
    got, why = policy(notify_above_percent=notify, stop_above_percent=stop)
    check(f"policy accepts notify {notify} / stop {stop} (at the boundary)", got is not None, why)
for cov in (0, 50, 100):
    got, why = policy(coverage_stop_below_percent=cov)
    check(f"policy accepts coverage_stop_below_percent {cov}", got is not None, why)
for notify, stop in ((50, 50), (51, 50), (-1, 50), (30, 101), (30.0, 50), (True, 50), ("30", 50), (30, 50.0), (30, "50"), (30, None)):
    got, why = policy(notify_above_percent=notify, stop_above_percent=stop)
    check(f"policy refuses notify {notify!r} / stop {stop!r} with a reason", got is None and ("notify_above_percent" in why or "stop_above_percent" in why), why)
for cov in (-1, 101, 50.0, True, "50", None, KeyError):
    got, why = policy(coverage_stop_below_percent=cov)
    check(f"policy refuses coverage_stop_below_percent {cov!r} and names the key", got is None and "coverage_stop_below_percent" in why, why)
for labels in ([], ["refactoring", "made_up"], "refactoring", [1], KeyError):
    got, why = policy(numerator_labels=labels)
    check(f"policy refuses numerator_labels {labels!r} and names the key", got is None and "numerator_labels" in why, why)
got, why = policy(measure="changed_files")
check("policy refuses another measure", got is None and "measure" in why, why)
check("policy: a missing file is a reason, not a crash", PC.grounding_policy(tmp / "nothing.json")[0] is None)
(tmp / "broken.json").write_text("{not json", encoding="utf-8")
check("policy: a broken file is a reason", PC.grounding_policy(tmp / "broken.json")[0] is None)
(tmp / "list.json").write_text("[1]", encoding="utf-8")
check("policy: a JSON list is a reason", PC.grounding_policy(tmp / "list.json")[0] is None)
(tmp / "empty.json").write_text("", encoding="utf-8")
check("policy: an empty file is a reason", PC.grounding_policy(tmp / "empty.json")[0] is None)
cleanup(tmp)

# --- the plan references -----------------------------------------------------------------------------------------
def refs(*items):
    return PC.grounding_refs({"risk_source_refs": list(items)})


check_eq("grounding_refs: the three prefixes", refs("grounding:K-1", "blast:B-2", "refactoring:G-3", "register:R-1"),
         {"K": ["K-1"], "B": ["B-2"], "G": ["G-3"]})
check_eq("grounding_refs: spaces and backticks around the entry are taken off", refs(" grounding:K-1 ", "`blast:B-10`"),
         {"K": ["K-1"], "B": ["B-10"], "G": []})
check_eq("grounding_refs: order of the row, each once", refs("grounding:K-2", "grounding:K-1", "grounding:K-2"),
         {"K": ["K-2", "K-1"], "B": [], "G": []})
for bad in ("grounding:K-0", "grounding:k-1", "Grounding:K-1", "blast:B-", "blast:B-1x", "blast:B-01", "grounding:K-1 grounding:K-2",
            "grounding:G-1", "derived_risk:K-1", "grounding:K-１", "grounding:K-1 x", ""):
    check_eq(f"grounding_refs: {bad!r} is not a reference", refs(bad), {"K": [], "B": [], "G": []})
for odd in (None, [], "grounding:K-1", {"risk_source_refs": "grounding:K-1"}, {"risk_source_refs": [None, 5, {"a": 1}]}):
    check_eq(f"grounding_refs: {odd!r} names none", PC.grounding_refs(odd), {"K": [], "B": [], "G": []})
check("row_requirements does not read the grounding prefixes",
      PC.row_requirements({"risk_source_refs": ["grounding:K-1", "blast:B-1", "refactoring:G-1"]}) == [])
check("row_requirements still reads requirement: and register:",
      PC.row_requirements({"risk_source_refs": ["requirement:R-4", "register:R-5"]}) == ["R-4", "R-5"])

# --- the ONE reader of work/grounding.yaml ------------------------------------------------------------------------
story = temp_dir("grounding-story-")
target = story / "work" / "grounding.yaml"
check_eq("the artifact registry puts the table at work/grounding.yaml", AR.canonical(story, "grounding.yaml"), target)


def read(content, raw=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if raw else content.encode("utf-8"))
    return PC.read_grounding(story)


# The problem is a typed record: callers route on `.kind` / `.who` (t-1046 section 9.2 R0, t-1015 G-0a / G-0c), never on the
# wording. Every test below compares the KIND and the WHO; the sentence is checked once for what an FR-1 refusal owes (the file).
LS, PS, BOM = chr(0x2028), chr(0x2029), chr(0xFEFF)
WHO = {"missing": "driver", "empty": "driver", "not_a_mapping": "driver", "encoding": "role", "control_char": "role",
       "syntax": "role", "duplicate_key": "role", "schema_version": "conductor", "unknown_key": "conductor"}
check_eq("the kind table: nine kinds and who acts on each (t-1046 section 9.2)", PC.GROUNDING_PROBLEM_WHO, WHO)


def refused(label, content, kind, raw=False):
    """The reader refuses `content` with `kind` (and the `who` the table gives it): (None, problem), never a partial Doc."""
    doc, problem = read(content, raw=raw)
    got = (doc, getattr(problem, "kind", None), getattr(problem, "who", None))
    check(f"refused as {kind}: {label}", got == (None, kind, WHO[kind]) and isinstance(problem, str) and "grounding.yaml" in problem,
          f"{got!r} {str(problem)[:100]}")
    return problem


def accepted(label, content):
    doc, problem = read(content)
    check(f"positive control, read clean: {label}", doc is not None and problem == "" and not hasattr(problem, "kind"), str(problem))
    return doc


doc, problem = PC.read_grounding(story)
check("no file: (None, kind missing / driver)", doc is None and (problem.kind, problem.who) == ("missing", "driver"), str(problem))
check("the problem is a plain str that carries its record", isinstance(problem, str) and problem.text == str(problem) and bool(problem))
check_eq("a record is made from a kind and a text; `who` comes from the table", (PC.GroundingProblem("syntax", "x").kind,
         PC.GroundingProblem("syntax", "x").who, PC.GroundingProblem("syntax", "x").text), ("syntax", "role", "x"))
target.parent.mkdir(parents=True, exist_ok=True)
target.mkdir()
doc, problem = PC.read_grounding(story)
check("a folder named grounding.yaml: missing / driver, and not 'does not exist'", doc is None and problem.kind == "missing"
      and "not a file" in problem, str(problem))
target.rmdir()
for label, content in (("0 bytes", ""), ("only comments", "# nothing\n\n"), ("an empty flow map", "{}\n"), ("blank lines", "\n  \n")):
    refused(f"empty file ({label})", content, "empty")
for label, content in (("a block list", "- a\n- b\n"), ("an empty flow list", "[]\n"), ("a dash alone", "-\n"),
                       ("a list after comments", "# top\n\n- schema_version: 1\n")):
    refused(f"top-level list ({label}), not 'empty'", content, "not_a_mapping")
refused("no schema_version", "implementation_source: diff\n", "schema_version")
for bad in ('"1"', "2", "0", "1.0", "true", "false", "null", "[1]", "01x"):
    refused(f"schema_version {bad}, never a guess", f"schema_version: {bad}\n", "schema_version")
doc = accepted("schema_version 1 with a comment", "schema_version: 1 # the form\nimplementation_source: diff\n")
check_eq("the Doc is a handoff.Doc with typed scalars", (type(doc).__name__, doc.get("schema_version"), doc.get("implementation_source")),
         ("Doc", 1, "diff"))
refused("an unknown top-level key: not 'syntax'", "schema_version: 1\nhunks_typo: []\n", "unknown_key")
check("the unknown-key problem names the key", "hunks_typo" in refused("(text)", "schema_version: 1\nhunks_typo: []\n", "unknown_key"))
refused("a byte-order mark", BOM + "schema_version: 1\n", "encoding")
refused("bytes that are not UTF-8", b"schema_version: 1\n\xff\xfe\n", "encoding", raw=True)
refused("a top-level key written twice", "schema_version: 1\nrows: []\nrows: []\n", "duplicate_key")

# The broken-YAML class (code critic t-1077 M-1; the Lead's ruling: a form no writer of ours produces is not read silently).
# The probe strings are the review's, with the LITERAL character: the escaped form inside quotes is text and stays legal.
HEAD = "schema_version: 1\n"
for name, ch in (("U+2028", LS), ("U+2029", PS), ("U+0085", "\x85"), ("VT", "\x0b"), ("FF", "\x0c"), ("NUL", "\x00"),
                 ("FS", "\x1c"), ("ESC", "\x1b"), ("DEL", "\x7f"), ("U+009F", "\x9f"), ("BEL", "\x07")):
    problem = refused(f"a literal {name} inside a quoted value", HEAD +'implementation_source: "di' + ch + 'ff"\n', "control_char")
    refused(f"a literal {name} in a plain value", HEAD +"implementation_source: di" + ch + "ff\n", "control_char")
    check(f"the {name} problem names the character and its line", f"U+{ord(ch):04X}" in problem and "line 2" in problem, str(problem))
refused("a literal U+2028 in the LAST field of a claim", HEAD +"claims:\n  - row: G-1\n    requirement: abc" + LS + "\n", "control_char")
problem = refused("a literal U+2028 in a MIDDLE field of a claim (never 'unknown_key' naming `impact`)",
                  HEAD +"claims:\n  - row: G-1\n    requirement: a" + LS + "b\n    impact: x\n", "control_char")
check("the middle-field problem names line 4, not a key", "line 4" in problem and "impact" not in problem, str(problem))
refused("a U+2028 inside a comment", HEAD +"# a" + LS + "b\nrows: []\n", "control_char")
refused("CRLF line ends", "schema_version: 1\r\nimplementation_source: diff\r\n", "control_char")
refused("one lone CR", HEAD +"implementation_source: di\rff\n", "control_char")
refused("a tab in the indentation of a list row", HEAD +"claims:\n\t- row: G-1\n", "syntax")
refused("a tab after spaces in the indentation", HEAD +"refactoring_share:\n  \tmeasure: x\n", "syntax")
for label, content in (("a tab inside a quoted value", HEAD +'implementation_source: "a\tb"\n'),
                       ("a tab after the colon", HEAD +"implementation_source:\tdiff\n"),
                       ("an escaped U+2028 (backslash u 2028) inside quotes", HEAD +'implementation_source: "a\\u2028b"\n'),
                       ("an escaped NUL inside quotes", HEAD +'implementation_source: "a\\u0000b"\n'),
                       ("a blank line holding only a tab", HEAD +"\t\nrows: []\n"),
                       ("a trailing newline missing", "schema_version: 1"),
                       ("non-ASCII text", HEAD +"implementation_source: déjà vu\n")):
    accepted(label, content)
refused("a line that is no YAML, at the top level", HEAD +"this line is not yaml at all\n", "syntax")
refused("a line that is no YAML, inside a row map", HEAD +"claims:\n  - row: G-1\n    this is not yaml\n    now: x\n", "syntax")
refused("a key with no space after the colon", HEAD +"implementation_source:diff\n", "syntax")
refused("a list item where a mapping is", HEAD +"implementation_source: diff\n- a\n", "syntax")
refused("a key line inside a list", HEAD +"rows:\n  - a\n  b: 1\n", "syntax")
refused("a document marker line", "---\n" + HEAD, "syntax")
refused("a flow map at the top that holds keys", "{schema_version: 1}\n", "syntax")
problem = refused("the line of the unparseable text is named", HEAD +"rows: []\n\nbroken line here\n", "syntax")
check("the syntax problem names its line (4) and shows the text", "line 4" in problem and "broken line here" in problem, str(problem))
refused("an unclosed double quote", HEAD +'implementation_source: "diff\n', "syntax")
refused("an unclosed single quote", HEAD +"implementation_source: 'diff\n", "syntax")
refused("an unclosed list", HEAD +"rows: [a, b\n", "syntax")
refused("an unclosed flow map", HEAD +"refactoring_share: {total: 300, road: none\n", "syntax")
refused("an unclosed quote inside a flow-map row", HEAD +"requirements:\n  - {r: R-1, where: \"x}\n", "syntax")
refused("a closer that closes nothing", HEAD +"rows: [a]]\n", "syntax")
refused("text after the closing quote", HEAD +'implementation_source: "diff" tail\n', "syntax")
refused("text after the closing bracket", HEAD +"rows: [a] tail\n", "syntax")
refused("an unclosed list item", HEAD +"rows:\n  - [a, b\n", "syntax")
for label, content in (("an apostrophe inside prose", HEAD +"implementation_source: the project's own ledger\n"),
                       ("a doubled single quote inside single quotes", HEAD +"implementation_source: 'it''s'\n"),
                       ("a bracket inside quotes", HEAD +'implementation_source: "a [b"\n'),
                       ("a closed flow list and a flow map", HEAD +"rows: [a, b]\nrefactoring_share: {total: 3, road: none}\n"),
                       ("a flow map wrapped over two lines", HEAD +"requirements:\n  - {r: R-1, state: implemented,\n     hunks: [h-1], where: \"\", question: \"\"}\n"),
                       ("a block scalar", HEAD +"implementation_source: |\n  line one\n  line two\nrows: []\n"),
                       ("an empty value with a comment", HEAD +"rows: # none yet\nclaims: []\n")):
    accepted(label, content)
refused("a duplicate NESTED key in a block map", HEAD +"refactoring_share:\n  total: 300\n  total: 3\n", "duplicate_key")
refused("a duplicate key in a row of a list", HEAD +"rows:\n  - id: G-1\n    id: G-2\n", "duplicate_key")
refused("a duplicate key in the second row only", HEAD +"rows:\n  - id: G-1\n    hunks: []\n  - id: G-2\n    hunks: []\n    hunks: []\n", "duplicate_key")
refused("a duplicate key in an inline flow map (the review's probe)", HEAD +"refactoring_share: {total: 300, total: 3}\n", "duplicate_key")
refused("a duplicate key in a nested flow map of a row", HEAD +"rows:\n  - {id: G-1, risks: [{id: K-1, id: K-2}]}\n", "duplicate_key")
refused("a duplicate quoted key", HEAD +"rows: []\n\"rows\": []\n", "duplicate_key")
problem = refused("the duplicate problem names key and line", HEAD +"refactoring_share:\n  total: 300\n  total: 3\n", "duplicate_key")
check("the duplicate problem names `total` and line 4", "`total`" in problem and "line 4" in problem, str(problem))
for label, content in (("the same key in two rows", HEAD +"rows:\n  - id: G-1\n    hunks: []\n  - id: G-2\n    hunks: []\n"),
                       ("the same key at two depths", HEAD +"rows:\n  - id: G-1\n    rows: []\nrequirements: []\n"),
                       ("the same key in two flow maps", HEAD +"rows:\n  - {id: G-1}\n  - {id: G-2}\nrefactoring_share: {id: 1}\n"),
                       ("one key in a flow map and the same one outside it", HEAD +"refactoring_share: {rows: 1}\nrows: []\n")):
    accepted(label, content)
doc = accepted("floats stay strings and unquoted digits are numbers", HEAD +"refactoring_share:\n  percent: 30.1\n  total: 007\n  note: \"007\"\n")
check_eq("a float is a STRING ('30.1'); 007 unquoted is the int 7; \"007\" is a string", (doc.get("refactoring_share.percent"),
         doc.get("refactoring_share.total"), doc.get("refactoring_share.note")), ("30.1", 7, "007"))

check("only schema_version: read (every other key absent)", read("schema_version: 1\n")[0] is not None)
for key in PC.GROUNDING_KEYS:
    if key == "schema_version":
        continue
    for empty in ("[]", "{}", ""):
        doc, problem = read(f"schema_version: 1\n{key}: {empty}\n")
        check(f"key {key} written empty ({empty or 'nothing'}) is read, not judged", doc is not None, problem)
        if doc is not None:
            check(f"key {key} empty: the Doc holds it empty", not doc.data.get(key), repr(doc.data.get(key)))

typed = ("schema_version: 1\n"
         "claims:\n"
         "  - row: G-4\n"
         "    before: 400   # the status code\n"
         "    now: \"007\"\n"
         "    ref: \"a #b\"\n"
         "    sep: \"a\\u2028b\"\n"
         "    differs: yes\n"
         "requirements:\n"
         "  - {r: R-1, state: implemented, hunks: [h-1], where: \"\", question: \"\"}\n")
doc, problem = read(typed)
check("typed file is read", doc is not None, problem)
node = doc.nodes["claims[0].before"]
check_eq("400 is an int and keeps its comment", (node.value, node.comment), (400, "# the status code"))
check_eq("\"007\" stays a string", doc.get("claims[0].now"), "007")
check_eq("a quoted ' #' is text, not a comment", (doc.get("claims[0].ref"), doc.nodes["claims[0].ref"].comment), ("a #b", ""))
check_eq("an escaped U+2028 survives as the character", doc.get("claims[0].sep"), "a b")
check_eq("a flow-map row keeps typed members", doc.get("requirements[0]"),
         {"r": "R-1", "state": "implemented", "hunks": ["h-1"], "where": "", "question": ""})

# The form the writer (G1-4) will produce: every key of the table, in the shapes of t-1010 section L-2.K - flow-map rows (one
# wrapped over two lines), a flow-map value, block maps, a block list of rows, an empty key, comments. It must read CLEAN: the
# refusals above are for forms no writer of ours produces, and a reader that also refused its own writer would block every story.
WRITER_FORM = ("schema_version: 1                       # the form\n"
               "implementation_source: diff\n"
               "diff:\n"
               "  - {path: work/impl-diff.txt, repo: \"\", sha256: " + "a" * 64 + ", implementation_commit: \"unmeasured: no checkout\"}\n"
               "hunks:                                  # the G1-1 index\n"
               "  - {id: 3f2a9c01b7de-1, short: H-7, repo: \"\", file: src/a.py, kind: production, old: \"10,4\", new: \"10,5\",\n"
               "     function: \"def f(x):\", added: 2, removed: 1, sha256: " + "b" * 64 + ", pseudo: \"\"}\n"
               "rows:\n"
               "  - {id: G-1, hunks: [3f2a9c01b7de-1], label: implements, requirements: [R-3],\n"
               "     risks: [{id: K-1, hypothesis: \"null @ src/a.py:10\"}], question: \"\", reason: \"adds the check\"}\n"
               "requirements:\n"
               "  - {r: R-3, state: implemented, hunks: [3f2a9c01b7de-1], where: \"\", question: \"\"}\n"
               "refactoring_share: {measure: changed_production_lines, refactoring: 120, total: 300, percent: 40, road: notify,\n"
               "                    policy: \"references/grounding-policy.json@0123456789ab\", decision: \"\", decision_ref: \"\"}\n"
               "requirement_coverage:\n"
               "  n: 3\n"
               "  implemented: 2\n"
               "  percent: 66.6\n"
               "  road: none\n"
               "blast_radius:\n"
               "  index: {schema: 1, built_at: \"2026-10-20T00:00:00\", test_roots: [tests], repos: [{repo: \"\", state: ok}]}\n"
               "  areas:\n"
               "    - id: B-1\n"
               "      key: src/a.py\n"
               "      touched: {repo: \"\", file: src/a.py, hunks: [3f2a9c01b7de-1], symbols: [f]}\n"
               "      callers: {unmeasured: \"no checkout\"}\n"
               "      matters: \"\"\n"
               "claims:\n"
               "  - {row: G-4, r: new, requirement: \"one verifiable statement\", observable: \"diff:src/a.py:10\", before: \"400\",\n"
               "     before_ref: \"diff:-src/a.py:9\", now: \"403\", now_ref: \"diff:src/a.py:10\", differs: yes,\n"
               "     question: {question: \"is the change intended?\", source_says: [], severity: major}, origin: S3-grounding}\n"
               "base_slice:\n"
               "  - {repo: \"\", file: src/a.py, base_rev: abc123, path: work/base/a.py, state: read, why: \"\"}\n"
               "orphans: []\n"
               "register_sha256: " + "c" * 64 + "\n")
doc = accepted("the writer form: every key of the table, flow rows, block maps, wrapped rows", WRITER_FORM)
check_eq("round trip: all thirteen keys that go with a diff are in the Doc (`null_outcome` is for a run outside `diff`)",
         sorted(doc.data), sorted(k for k in PC.GROUNDING_KEYS if k != "null_outcome"))
doc2 = accepted("a table outside diff: null_outcome in place of the diff keys", "schema_version: 1\nimplementation_source: current-code\n"
                "null_outcome: {source: current-code, words: \"no diff: the code was read as it is\"}\nhunks: []\nrows: []\n")
check_eq("round trip: null_outcome reads as a map", doc2.data["null_outcome"]["source"], "current-code")
check_eq("round trip: typed members of rows and flow values", (doc.data["rows"][0]["risks"], doc.data["refactoring_share"]["total"],
         doc.data["refactoring_share"]["percent"], doc.data["claims"][0]["differs"], doc.data["hunks"][0]["function"]),
         ([{"id": "K-1", "hypothesis": "null @ src/a.py:10"}], 300, 40, "yes", "def f(x):"))
check_eq("round trip: a block-form row and a float stay as written", (doc.get("blast_radius.areas[0].key"), doc.get("blast_radius.areas[0].matters"),
         doc.get("requirement_coverage.percent"), doc.get("requirement_coverage.n")), ("src/a.py", "", "66.6", 3))
check_eq("round trip: a comment survives", doc.nodes["schema_version"].comment, "# the form")
cleanup(story)

# One reader: no other module of the package that names the file parses it. The unit judged is a FUNCTION (or the rest of
# the module with the function bodies blanked), not the whole file: a module that names `work/grounding.yaml` in a role's
# dispatch text and parses some OTHER YAML elsewhere (story_run / story_step parse a handover form) is not a second reader.
import ast


def parses_yaml(text, whole=None) -> bool:
    """Does this source parse YAML: `handoff.parse` / `handoff._read` under any alias (aliases are read from `whole`, the
    module the unit lives in), `from handoff import parse`, a yaml library?"""
    names = {"handoff"} | set(re.findall(r"import handoff as (\w+)", whole or text))
    calls = "|".join(re.escape(n) for n in sorted(names))
    return bool(re.search(rf"\b(?:{calls})\.(?:parse|_read)\(", text)
                or re.search(r"from handoff import[^\n]*\b(?:parse|_read)\b", text)
                or re.search(r"\byaml\.(?:safe_)?load|import yaml|from yaml import", text))


def source_units(text):
    """The units of a module: the source of every function (ast.walk: methods and nested functions too), plus the rest of
    the module with those bodies blanked. A file ast cannot parse is ONE unit (the whole file: the old, stricter answer)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [text]
    lines = text.splitlines(keepends=True)
    units, blanked = [], set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.append("".join(lines[node.lineno - 1:node.end_lineno]))
            blanked.update(range(node.lineno - 1, node.end_lineno))
    units.append("".join(line for i, line in enumerate(lines) if i not in blanked))
    return units


def parser_offenders(files):
    return sorted(p.name for p, text in files if p.name != "planning_contract.py"
                  and any("grounding.yaml" in unit and parses_yaml(unit, text) for unit in source_units(text)))


scripts = [(p, p.read_text(encoding="utf-8", errors="replace")) for p in sorted(SCRIPTS.glob("*.py"))]
check("positive control: the reader file names the file AND parses it",
      any(p.name == "planning_contract.py" and "grounding.yaml" in t and parses_yaml(t) for p, t in scripts))
check_eq("no module besides planning_contract parses a file it names grounding.yaml", parser_offenders(scripts), [])
for label, source in (("handoff.parse", "handoff.parse(text)"), ("an alias", "import handoff as _h\n_h.parse(text)"),
                      ("from-import", "from handoff import parse\n"), ("a yaml library", "import yaml\n")):
    check_eq(f"negative control: a second parser ({label}) would be caught",
             parser_offenders([(Path("x.py"), "# grounding.yaml\n" + source + "\n")]), ["x.py"])
check_eq("control: ast.parse beside the file name is not a YAML parse", parser_offenders([(Path("x.py"), "# grounding.yaml\nast.parse(src)\n")]), [])
check_eq("control: a module that names the file in one function and parses another YAML in a second is not an offender",
         parser_offenders([(Path("x.py"), "def a():\n    return 'work/grounding.yaml'\n\n\ndef b(text):\n    return handoff.parse(text)\n")]), [])
check_eq("negative control: a function that names the file AND parses is caught",
         parser_offenders([(Path("x.py"), "def a(text):\n    # grounding.yaml\n    return handoff.parse(text)\n")]), ["x.py"])
check_eq("negative control: an alias imported at module level is seen inside the function",
         parser_offenders([(Path("x.py"), "import handoff as _h\n\n\ndef a(text):\n    # grounding.yaml\n    return _h.parse(text)\n")]), ["x.py"])
check_eq("negative control: a file ast cannot parse is judged whole",
         parser_offenders([(Path("x.py"), "# grounding.yaml\ndef (:\nhandoff.parse(text)\n")]), ["x.py"])

# --- the register: delta (last) and origin (last) -----------------------------------------------------------------
template = (REF / "templates" / "requirements-register.md").read_text(encoding="utf-8")
reg_header = [c.strip() for c in C.md_table(template, "## Register")[0]]
check_eq("template register header: observable 6, impact 7, delta 8, code_says 9 and last (t-1676 RN1-17 p.0; R is 0)",
         (reg_header.index("observable"), reg_header.index("impact"), reg_header.index("delta"), reg_header.index("code_says"), len(reg_header) - 1), (6, 7, 8, 9, 9))
claim_header = [c.strip() for c in C.md_table(template, C.CLAIM_HEADING)[0]]
check_eq("template claims header: origin is 7 and last", (claim_header.index("origin"), claim_header[-1]), (7, "origin"))
check_eq("CLAIM_COLUMNS: eight, origin last", (len(C.CLAIM_COLUMNS), C.CLAIM_COLUMNS[-1]), (8, "origin"))
check("the template's rows read: delta and empty origin", [r["delta"] for r in C.register_rows(template)][:2] == ["changed", "unchanged"]
      and all(r["origin"] == "" for r in C.behaviour_claims(template)))
s2 = (PLUGIN_ROOT / "handoffs" / "s2-tester-to-strategist.yaml").read_text(encoding="utf-8")
check_in("the S2 form carries scope[].delta", "    delta: <", s2)
spec = H.spec("s2-tester-to-strategist")
delta_field = [f for path, f in spec.items() if path.endswith("scope[].delta")]
check("the S2 form's delta is optional (a saved form without it stays valid)", bool(delta_field) and delta_field[0].optional,
      str(sorted(spec)[:6]))
# spec t-1765 X1 (B-D, "moved"): the rule is under code (the S2 form), so its text is the form's and the tester's key page's,
# not the charter's; the verbatim "Fill `delta`" has no carrier any more - the key page's line for the field is pinned instead
tester_keys = (PLUGIN_ROOT / "references" / "slices" / "qa-requirements-tester" / "handoff-keys.md").read_text(encoding="utf-8")
check_in("the requirements tester is told the delta column before the work (its key page)",
         "`scope[].delta` (optional) - the register's delta column", tester_keys)
check_not_in("the key page control: a wrong delta line is not there", "`scope[].delta` (required)", tester_keys)

# --- the artifact contract text and the declarations ---------------------------------------------------------------
plan_text = (REF / "artifact-contract-plan.md").read_text(encoding="utf-8")
KEYS = ("schema_version", "implementation_source", "null_outcome", "diff", "implementation_commit", "repo_id", "hunks", "rows",
        "requirements", "refactoring_share", "requirement_coverage", "blast_radius", "path_kind", "matters", "regression",
        "add_tests", "text_says", "claims", "base_slice", "orphans", "register_sha256", "delta", "origin",
        "grounding:K-n", "blast:B-n", "refactoring:G-n")
check_eq("artifact-contract-plan.md names every key and reference", [k for k in KEYS if f"`{k}`" not in plan_text
                                                                       and f"{k}" not in plan_text], [])
check("artifact-contract-plan.md stays within the 12000-byte reference ceiling", len(plan_text.encode("utf-8")) <= 12000)
check("every top-level key of the reader appears in the contract text", all(k in plan_text for k in PC.GROUNDING_KEYS))

stages = json.loads((REF / "stages.json").read_text(encoding="utf-8"))
s3 = next(s for s in stages["stages"] if s["id"] == "S3")
check("S3 outputs hold work/grounding.yaml", "work/grounding.yaml" in s3["outputs"])
check("S3 required_outputs do not (the gate decides when a table is owed)", "work/grounding.yaml" not in s3["required_outputs"])
table = json.loads((REF / "artifact-writers.json").read_text(encoding="utf-8"))["artifacts"]
order = list(table)
check("the writers record exists, strategist's, with grounding_table.py (G1-4) and base_slice.py (G1-8) in its machinery", "work/grounding.yaml" in table
      and "grounding_table.py" in table["work/grounding.yaml"]["machinery"] and "base_slice.py" in table["work/grounding.yaml"]["machinery"]
      and "qa-test-strategist" in table["work/grounding.yaml"]["writer"])
check("the record sits right after work/test-plan.json (the strategist's first artifact stays test-plan.md)",
      order.index("work/grounding.yaml") == order.index("work/test-plan.json") + 1)
entry = AR.entries()["grounding.yaml"]
check_eq("registry entry: path, producer, schema, no legacy alias",
         (entry["path"], entry["producer"], entry["schema"], "legacy_alias" in entry), ("work/grounding.yaml", "qa-test-strategist", "yaml", False))
check_eq("registry entry consumers", entry["consumers"], ["planner", "controller", "delivery"])
check_eq("KNOWN_ARTIFACTS: a role reaches the table by the key `grounding` (the path is the registry's, resolved at use)",
         RP.KNOWN_ARTIFACTS.get("grounding"), "grounding.yaml")

# --- the delivery kinds ------------------------------------------------------------------------------------------------
kinds = DV.load_kinds()[0]["kinds"]
check_eq("pending_implementation blocks (FR-21): no / product", kinds["pending_implementation"], {"verdict": "no", "owner": "product"})
check_eq("bug_candidate is a candidate, not a confirmed failure: after_checks / product", kinds["bug_candidate"],
         {"verdict": "after_checks", "owner": "product"})
check_eq("decide: pending_implementation -> no", DV.decide(["passed", "pending_implementation"])[0], "no")
check_eq("decide: bug_candidate alone -> after_checks", DV.decide(["passed", "bug_candidate"])[0], "after_checks")
check_eq("decide: a blocking kind beats a candidate", DV.decide(["bug_candidate", "red"])[0], "no")
for spelling in ("Bug_candidate", "bug-candidate", "bug_candidate ", "", None, "pending-implementation"):
    word, findings = DV.decide([spelling])
    check(f"decide: kind {spelling!r} is unknown -> no + VERDICT_KIND_UNKNOWN",
          word == "no" and [f["code"] for f in findings] == ["VERDICT_KIND_UNKNOWN"], str((word, findings)))

finish("test_grounding_schema")
