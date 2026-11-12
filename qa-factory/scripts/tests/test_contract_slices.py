"""contract_slices.py — the role slices, on a synthetic plugin and on the shipped one.

The rules under test, each one a way a slice could lie to a role:
  a section reaches only the roles marked on its heading, and `all` reaches every reader;
  a `###` with no marker of its own stays with its `##`, a marked one leaves it;
  the lead is in every slice (a slice that opens mid-rule reads as a different document);
  a slice that is missing, stale, empty or orphaned is a finding, not a silent half-truth;
  a section whose **Writer** is a role that has a slice of that file cannot be dropped from
  it — that was the 0.7.7 defect this package closes (four roles writing fields out of
  documents nobody delivered to them);
  a marked subject is injected through slices only, never whole.

Runnable on its own: `python -B scripts/tests/test_contract_slices.py`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir,
)

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import contract_slices as CS  # noqa: E402

SOURCE = """# The subject

What this subject is.

## Manifest <!-- roles: qa-automator, qa-code-critic -->

**Writer** `qa-automator`. Fields: `a`, `b`.

### Deep detail

inherited by the manifest's readers.

### Critic only <!-- roles: qa-code-critic -->

the probe receipt.

## Everyone <!-- roles: all -->

shared law.

## Runner only <!-- roles: qa-runner -->

manual evidence.
"""


def fake_plugin(tmp: Path, roles: dict, source: str = SOURCE) -> Path:
    """A plugin root with one marked subject and an inject-map that asks for slices."""
    root = tmp / "plugin"
    (root / "references").mkdir(parents=True)
    (root / "references" / "subject.md").write_text(source, encoding="utf-8", newline="\n")
    (root / "references" / "inject-map.json").write_text(
        json.dumps({"common": [], "roles": roles}), encoding="utf-8", newline="\n")
    return root


def test_rendering() -> None:
    critic = CS.render("subject.md", "qa-code-critic", SOURCE)
    automator = CS.render("subject.md", "qa-automator", SOURCE)
    runner = CS.render("subject.md", "qa-runner", SOURCE)
    check_in("the lead is in every slice", "What this subject is.", runner)
    check_in("a marked section reaches its role", "Fields: `a`, `b`.", critic)
    check_in("an unmarked `###` stays with its `##`", "inherited by the manifest", automator)
    check_not_in("a marked `###` leaves its parent's other readers", "probe receipt", automator)
    check_in("and reaches the role it names", "probe receipt", critic)
    check_in("`all` reaches a role named on no other section", "shared law", runner)
    check_not_in("another role's section is not delivered", "manual evidence", critic)
    check_not_in("the marker itself is never injected", "<!-- roles:", automator)
    check_in("the slice names the source it was rendered from",
             "plugin:references/subject.md", automator.splitlines()[0])


def test_findings_and_write() -> None:
    tmp = temp_dir("qa-factory-slices-")
    try:
        roles = {"qa-automator": ["plugin:references/slices/qa-automator/subject.md"],
                 "qa-code-critic": ["plugin:references/slices/qa-code-critic/subject.md"]}
        root = fake_plugin(tmp, roles)
        check_in("BAD: a slice that was never generated is named as missing",
                 "missing", CS.findings(root))
        CS.write(root)
        check_eq("GOOD: after --write nothing is wrong", CS.findings(root), [])

        slice_path = root / "references" / "slices" / "qa-automator" / "subject.md"
        slice_path.write_text(slice_path.read_text(encoding="utf-8") + "\nhand-added line\n",
                              encoding="utf-8", newline="\n")
        check_in("BAD: a hand-edited slice is stale", "stale", CS.findings(root))
        CS.write(root)
        check_eq("and --write restores it from the source", CS.findings(root), [])

        (root / "references" / "slices" / "qa-scout").mkdir(parents=True)
        (root / "references" / "slices" / "qa-scout" / "subject.md").write_text(
            "left behind", encoding="utf-8", newline="\n")
        check_in("BAD: a slice no role is injected is an orphan", "no role is injected",
                 CS.findings(root))
        cleanup(root / "references" / "slices" / "qa-scout")

        # The writer of an artifact must be injected the section that defines it.
        moved = SOURCE.replace("## Manifest <!-- roles: qa-automator, qa-code-critic -->",
                               "## Manifest <!-- roles: qa-code-critic -->")
        (root / "references" / "subject.md").write_text(moved, encoding="utf-8", newline="\n")
        CS.write(root)
        found = CS.findings(root)
        check_in("BAD: the role named **Writer** cannot be left out of its own slice",
                 "**Writer**", found)
        check_in("and the finding names the role and the section", "qa-automator", found)

        # A marked subject is delivered through slices only.
        (root / "references" / "subject.md").write_text(SOURCE, encoding="utf-8", newline="\n")
        direct = dict(roles, **{"qa-runner": ["plugin:references/subject.md"]})
        (root / "references" / "inject-map.json").write_text(
            json.dumps({"common": [], "roles": direct}), encoding="utf-8", newline="\n")
        CS.write(root)
        check_in("BAD: a marked subject injected whole is refused with the entry to write",
                 "plugin:references/slices/qa-runner/subject.md", CS.findings(root))

        # A role in the map that no marker mentions would be handed a title and nothing else.
        (root / "references" / "subject.md").write_text(
            SOURCE.replace("## Everyone <!-- roles: all -->", "## Everyone <!-- roles: qa-runner -->"),
            encoding="utf-8", newline="\n")
        (root / "references" / "inject-map.json").write_text(json.dumps({"common": [], "roles": {
            "qa-doc-scribe": ["plugin:references/slices/qa-doc-scribe/subject.md"]}}),
            encoding="utf-8", newline="\n")
        CS.write(root)
        empty = [f for f in CS.findings(root) if "qa-doc-scribe" in f]
        check("BAD: a role marked on no section is named, not silently given a title",
              any("marked on no section" in f for f in empty), str(empty))
    finally:
        cleanup(tmp)


def test_shipped_package() -> None:
    """The package as it ships: every declared slice fresh, and every role's injection under
    A22's cap measured on the files the map really delivers."""
    check_eq("SHIPPED: every slice named in inject-map.json is present and fresh",
             CS.findings(PLUGIN_ROOT), [])
    declared = CS.targets(PLUGIN_ROOT)
    check("SHIPPED: the map delivers slices, not whole subjects, to the tight roles",
          {t["role"] for t in declared} >= {"qa-automator", "qa-code-critic", "qa-scout",
                                            "qa-requirements-tester", "qa-case-critic"},
          str(sorted({t["role"] for t in declared})))
    # The deferred injection findings of 0.7.7, as a test: these four roles write or cite
    # fields out of documents that used to reach nobody.
    owed = {("qa-code-critic", "artifact-contract-automation.md"),
            ("qa-failure-analyst", "artifact-contract-automation.md"),
            ("qa-case-critic", "case-lifecycle.md"),
            ("qa-doc-scribe", "coverage-design.md")}
    have = {(t["role"], t["subject"]) for t in declared}
    check_eq("SHIPPED: the four roles that wrote out of undelivered contracts now get them",
             sorted(owed - have), [])
    for role, subject, needle in (
            ("qa-code-critic", "artifact-contract-automation.md", "review_receipt_ref"),
            ("qa-code-critic", "artifact-contract-automation.md", "obligation_bindings"),
            ("qa-failure-analyst", "artifact-contract-automation.md", "`runs[]`"),
            ("qa-failure-analyst", "artifact-contract-automation.md", "instance_id"),
            ("qa-case-critic", "case-lifecycle.md", "## Gate A debts"),
            ("qa-doc-scribe", "coverage-design.md", "only reviewed coverage")):
        path = PLUGIN_ROOT / "references" / "slices" / role / subject
        check_in(f"SHIPPED: {role} is injected `{needle}`", needle,
                 path.read_text(encoding="utf-8") if path.exists() else "")


STRATEGIST_SLICE = PLUGIN_ROOT / "references" / "slices" / "qa-test-strategist" / "artifact-contract-plan.md"
PLAN_CONTRACT = PLUGIN_ROOT / "references" / "artifact-contract-plan.md"
# The sentence the plan contract carried before HF1-13: it named two vocabulary lists and no word, and the
# strategist (who may read only `references/`) could not open the file that holds them.
OLD_WORDS_SENTENCE = "Words:\n`vocabulary.grounding_labels`, `requirement_grounding_states`."


def reads_the_plugin_for_its_words(text: str) -> bool:
    """True when the text sends the role to a plugin file for the closed words: the `handoffs/` folder, or the bare
    `vocabulary.<list>` name with no value given (FR-15/AR-8: a role is handed its words, never a path it cannot open)."""
    return "handoffs/" in text or "vocabulary.grounding_labels" in text or "vocabulary.requirement_grounding_states" in text


def test_grounding_words() -> None:
    """HF1-13 (OH3-14 class): the plan contract hands the strategist the grounding WORDS, through the one vocabulary reader."""
    import handoff as H
    line = H.grounding_vocabulary_line()
    source = PLAN_CONTRACT.read_text(encoding="utf-8")
    shipped = STRATEGIST_SLICE.read_text(encoding="utf-8")
    check_in("WORDS: the contract source carries the generator's token, not a typed list", CS.GROUNDING_WORDS_TOKEN, source)
    check_not_in("WORDS: the source types no label by hand", "behaviour_change", source)
    check_in("WORDS: the strategist's slice holds the line `handoff.grounding_vocabulary_line` builds, whole", line, shipped)
    for name in ("grounding_labels", "requirement_grounding_states"):
        words = H.allowed(name)
        check(f"WORDS: `{name}` is non-empty in the shipped vocabulary (the control for the checks below)", bool(words))
        for word in words:
            check_in(f"WORDS: the slice names `{word}` ({name})", word, shipped)
    check_not_in("WORDS: the token never reaches the role", CS.GROUNDING_WORDS_TOKEN, shipped)
    check("WORDS: the slice names no plugin path outside references/ and no bare vocabulary list for the words",
          not reads_the_plugin_for_its_words(shipped), "handoffs/ or vocabulary.<list> in the slice")
    check_not_in("WORDS: the requirements tester's slice carries no word list (the section is the strategist's)",
                 "behaviour_change", CS.render("artifact-contract-plan.md", "qa-requirements-tester", source))

    # NEGATIVE CONTROL: the old sentence restored in the source FAILS the same predicate (a check that cannot fail is broken).
    new_sentence = source[source.index(CS.GROUNDING_WORDS_TOKEN):source.index("A plan row answers")]
    old_source = source.replace(new_sentence, OLD_WORDS_SENTENCE + " ")
    check("control: the old sentence is in the doctored source", OLD_WORDS_SENTENCE in old_source and old_source != source)
    check("control: a slice rendered from the old sentence FAILS the no-plugin-words predicate",
          reads_the_plugin_for_its_words(CS.render("artifact-contract-plan.md", "qa-test-strategist", old_source)))
    check("control: the slice rendered from the real source passes it",
          not reads_the_plugin_for_its_words(CS.render("artifact-contract-plan.md", "qa-test-strategist", source)))

    # ONE READER: the generator types no label of its own; its words come from the helper, so a vocabulary change is a
    # change of the slice and of nothing else.
    generator = Path(CS.__file__).read_text(encoding="utf-8")
    typed = [w for w in H.allowed("grounding_labels") + H.allowed("requirement_grounding_states")
             if f'"{w}"' in generator or f"'{w}'" in generator]
    check_eq("ONE READER: contract_slices.py holds no grounding word as a string literal", typed, [])
    check_in("ONE READER: the words come from `handoff.grounding_vocabulary_line`",
             "handoff.grounding_vocabulary_line()", generator)

    # THE RATCHET and the unreadable cases, on a synthetic plugin (the shipped slices are only read).
    tmp = temp_dir("qa-factory-slices-words-")
    real_vocabulary, real_allowed = H.vocabulary, H.allowed
    try:
        text = SOURCE.replace("shared law.", "shared law. Words: " + CS.GROUNDING_WORDS_TOKEN)
        root = fake_plugin(tmp, {"qa-runner": ["plugin:references/slices/qa-runner/subject.md"]}, text)
        CS.write(root)
        check_eq("GOOD: a token source and its slice are fresh after --write", CS.findings(root), [])
        out = (root / "references" / "slices" / "qa-runner" / "subject.md").read_text(encoding="utf-8")
        check_in("the written slice holds the helper's line", line, out)

        H.allowed = lambda name: real_allowed(name) + (["zz_new_word"] if name == "grounding_labels" else [])
        check_in("RATCHET: a word added to the vocabulary makes the slice stale until --write",
                 "stale", CS.findings(root))
        CS.write(root)
        check_eq("and --write brings it back", CS.findings(root), [])
        check_in("and the new word reached the slice", "zz_new_word",
                 (root / "references" / "slices" / "qa-runner" / "subject.md").read_text(encoding="utf-8"))
        H.allowed = real_allowed

        def gone():
            raise FileNotFoundError("vocabulary.yaml")

        H.vocabulary = gone
        unreadable = CS.render("subject.md", "qa-runner", text)
        check_in("UNREADABLE: no vocabulary -> the slice says NONE READABLE for the labels", "labels: NONE READABLE", unreadable)
        check_in("UNREADABLE: and for the requirement states", "requirement states: NONE READABLE", unreadable)
        check_not_in("UNREADABLE: the word is never left blank after `Words:`", "Words:  ", unreadable)
        check_in("UNREADABLE: and the stale committed slice is red, not silently kept", "stale", CS.findings(root))
        H.vocabulary = real_vocabulary

        sys.modules["handoff"], saved = None, sys.modules.get("handoff")     # an import that fails: the reader itself is broken
        try:
            broken = CS.grounding_words()
        finally:
            sys.modules["handoff"] = saved
        check_in("UNREADABLE: a reader that cannot be imported is declared, not blank", "NONE READABLE", broken)
    finally:
        H.vocabulary, H.allowed = real_vocabulary, real_allowed
        cleanup(tmp)


# --- SC1-9: the common rules are sliced per role ------------------------------------------------------------------------------

COMMON_SOURCE = PLUGIN_ROOT / "references" / "common-rules.md"
CORE = ("The witness contract", "Your handover: the form, then the digest line", "Real data in artifacts", "Language",
        "Cross-cutting rules carried from the factory's history", "Source lookups after grounding")
# Spec t-1765 X1-7: the four roles whose file is a charter are not handed these two sections (the charter's «When to ask» is
# their one road of a question, and their turn economy is the guard's refusal text). Every other role is, as before.
TURN_AND_HALTS = ("Turn economy", "Gates and halts — no questions in between")
SLIM_ROLES = ("qa-scout", "qa-requirements-tester", "qa-test-strategist", "qa-case-designer")
# Per role, the headings of its slice of common-rules.md beyond CORE - written out, one line per role, so that a rule
# that stops reaching a role which acts on it (A-K10) is a red line here and not a silent half-truth. The reasons are in
# the sections' markers (references/common-rules.md) and in the t-1252 spec table.
EXTRA = {
    "qa-scout": ("No writes to external systems", "What a path is relative to"),
    "qa-requirements-tester": ("No writes to external systems",),
    "qa-test-strategist": ("What a path is relative to",),
    "qa-case-designer": ("What a path is relative to",),
    "qa-case-critic": ("Your own test data",),
    "qa-automator": ("Quiet runs only, through the runner", "Your own test data", "What a path is relative to"),
    "qa-code-critic": ("Quiet runs only, through the runner", "Your own test data", "No writes to external systems",
                       "What a path is relative to"),
    "qa-runner": ("Quiet runs only, through the runner", "Your own test data", "No writes to external systems",
                  "What a path is relative to"),
    "qa-failure-analyst": ("Quiet runs only, through the runner", "Your own test data", "No writes to external systems",
                           "What a path is relative to"),
    "qa-bug-reporter": ("No writes to external systems", "What a path is relative to"),
    "qa-doc-scribe": ("No writes to external systems", "What a path is relative to"),
    "qa-retro-analyst": ("No writes to external systems", "What a path is relative to"),
}
NEVER_DELIVERED = ("Resolving the plugin root", "Runtime and discovery policy")
THIRTY_KB_RULE = "A whole read over 30 KB is blocked"


def squash(text: str) -> str:
    return " ".join(text.split())


def core_missing(text: str, slim: bool = False) -> list:
    """What a role's slice of the common rules lacks of the rules every role acts on (headings; for a role that is not
    SLIM also `Turn economy`, `Gates and halts` and the 30 KB rule, which lives in `Turn economy`)."""
    titles = [s.title for s in CS.parse(text)[1]]
    want = CORE if slim else TURN_AND_HALTS + CORE
    return [h for h in want if h not in titles] + ([] if slim or THIRTY_KB_RULE in squash(text) else [THIRTY_KB_RULE])


def slice_of(role: str) -> str:
    return (PLUGIN_ROOT / "references" / "slices" / role / "common-rules.md").read_text(encoding="utf-8")


def test_common_rules_slices() -> None:
    """A-K3 (every role gets the core, none gets the host-only sections) and A-K10 (no role loses a rule it uses)."""
    source = COMMON_SOURCE.read_text(encoding="utf-8")
    imap = json.loads((PLUGIN_ROOT / "references" / "inject-map.json").read_text(encoding="utf-8"))
    source_titles = [s.title for s in CS.parse(source)[1]]
    for gone in NEVER_DELIVERED:
        check(f"A-K3: the source still holds `{gone}` (the conductor and the skills read it)", gone in source_titles)
    check_eq("A-K10: the table names exactly the twelve roles of the map", sorted(EXTRA),
             sorted({t["role"] for t in CS.targets(PLUGIN_ROOT)}))
    for role in sorted(EXTRA):
        text = slice_of(role)
        slim = role in SLIM_ROLES
        check_eq(f"A-K3: {role}'s slice has every core rule", core_missing(text, slim), [])
        for gone in NEVER_DELIVERED:
            check_not_in(f"A-K3: {role}'s slice does not carry `{gone}`", gone, text)
        check_not_in(f"A-K3: {role}'s slice does not carry the host-only phrase", "Role files pin no model", text)
        titles = [s.title for s in CS.parse(text)[1]]
        check_eq(f"A-K10: {role}'s slice holds exactly its sections", sorted(titles),
                 sorted(CORE + (() if slim else TURN_AND_HALTS) + EXTRA[role]))
        check_eq(f"A-K10: {role}'s own list opens with its slice of the rules (who you are, how you work, then references)",
                 imap["roles"][role][0], f"plugin:references/slices/{role}/common-rules.md")
    for role in ("qa-test-strategist", "qa-case-designer", "qa-case-critic"):
        check_not_in(f"A-K3: {role} has no shell, so its slice names no `diff_pass`", "diff_pass", slice_of(role))
    check("A-K3: the failure analyst gets the test-data rule (it reads failures by their data)",
          "Your own test data" in [s.title for s in CS.parse(slice_of("qa-failure-analyst"))[1]])
    # The four charter roles lose the two sections; the case critic (S4's second role, byte for byte) and the others keep them.
    for role in SLIM_ROLES:
        for gone in TURN_AND_HALTS:
            check_not_in(f"X1-7: {role}'s slice does not carry `{gone}`", gone, slice_of(role))
    for kept in TURN_AND_HALTS:
        check_in(f"X1-7 control: qa-case-critic keeps `{kept}` (its slice is unchanged)", kept, slice_of("qa-case-critic"))
    # NEGATIVE control: the core check is red on a source where `Turn economy` is marked for one role only.
    doctored = source.replace("<!-- roles: qa-case-critic, qa-automator, qa-code-critic, qa-runner, qa-failure-analyst, "
                              "qa-bug-reporter, qa-doc-scribe, qa-retro-analyst -->\n## Turn economy",
                              "<!-- roles: qa-runner -->\n## Turn economy")
    check("A-K3 control: the doctored source differs", doctored != source)
    check_in("A-K3 NEGATIVE: the core check is red when `Turn economy` is not for every role that keeps it", "Turn economy",
             core_missing(CS.render("common-rules.md", "qa-automator", doctored)))
    check_eq("A-K3 control: and green on the shipped rendering of the same role",
             core_missing(CS.render("common-rules.md", "qa-automator", source)), [])
    # The common list holds the manifesto only; the rules are a slice (A-K1 reads the same fact in A22).
    check_eq("A-K1: `common` is the manifesto alone", imap["common"], ["plugin:references/tester-manifesto.md"])


def build_layer_tree(tmp: Path, source: str, roles=("qa-a", "qa-b")) -> Path:
    """A plugin root whose common list is one 100-byte manifesto and whose roles are handed a slice of `source`."""
    root = tmp / "plugin"
    (root / "references").mkdir(parents=True)
    (root / "references" / "m.md").write_text("m" * 99 + "\n", encoding="utf-8", newline="\n")
    (root / "references" / "common-rules.md").write_text(source, encoding="utf-8", newline="\n")
    (root / "references" / "inject-map.json").write_text(json.dumps({
        "common": ["plugin:references/m.md"],
        "roles": {r: [f"plugin:references/slices/{r}/common-rules.md"] for r in roles}}),
        encoding="utf-8", newline="\n")
    return root


LAYER_SOURCE = ("# Rules\n\nLead.\n\n"
                "<!-- roles: all -->\n## All\n\nshared line.\n\n"
                "<!-- roles: qa-a -->\n## Only A\n\nA only body here.\n\n"
                "<!-- roles: qa-b -->\n## Only B\n\nB only.\n")


def test_common_layer() -> None:
    """A-K9 (FR-28): the measurer of the layer every role gets alike, on a tree whose answer is known to the byte."""
    tmp = temp_dir("qa-factory-common-layer-")
    try:
        root = build_layer_tree(tmp, LAYER_SOURCE)
        CS.write(root)
        layer = CS.common_layer(root)
        # list: the manifesto, 100 B. shared rules: the lead (15 B: "# Rules\n\nLead.\n") + the `all` section
        # ("\n## All\n\nshared line.\n" = 22 B) = 37 B, WITHOUT the provenance line. Each role's slice also holds a
        # 131 B provenance line (it names the role) and its own section: A 30 B, B 20 B.
        check_eq("A-K9: the list is the manifesto's bytes", layer["list"], 100)
        check_eq("A-K9: shared = list + the lead and `all` sections, no provenance", layer["shared"], 137)
        check_eq("A-K9: per role = list + that role's own slice", layer["per_role"], {"qa-a": 298, "qa-b": 288})
        check_eq("A-K9: nothing went unmeasured", layer["errors"], [])
        check("A-K9: shared is not the minimum over roles (the 'min' measurer is wrong here)",
              layer["shared"] != min(layer["per_role"].values()))
        check("A-K9: and every role holds at least the shared bytes",
              all(v >= layer["shared"] for v in layer["per_role"].values()))
        shipped = CS.common_layer(PLUGIN_ROOT)
        check("A-K9: the shipped layer is measured (control)", shipped["shared"] > shipped["list"] > 0 and not shipped["errors"],
              str(shipped["errors"]))
        check("A-K9: and report() prints the same two numbers",
              f"list {shipped['list']:,} bytes, shared with every role {shipped['shared']:,} bytes" in CS.report(PLUGIN_ROOT))

        # unknown is not zero: the source gone while the map names its slices; a slice gone; a map nobody can read
        (root / "references" / "common-rules.md").unlink()
        gone = CS.common_layer(root)
        check("A-K9: a missing source is an error, not a zero", bool(gone["errors"]) and "common-rules.md" in gone["errors"][0],
              str(gone))
        check("A-K9: and report() says NOT MEASURED", "NOT MEASURED" in CS.report(root))
        (root / "references" / "common-rules.md").write_text(LAYER_SOURCE, encoding="utf-8", newline="\n")
        (root / "references" / "slices" / "qa-a" / "common-rules.md").unlink()
        check("A-K9: a missing slice is an error naming the role", any("qa-a" in e for e in CS.common_layer(root)["errors"]))
        (root / "references" / "inject-map.json").write_text("{not json", encoding="utf-8")
        check_eq("A-K9: an unreadable map measures nothing", CS.common_layer(root), {})
        # no common-layer slice in the map: nothing to add, nothing to complain about
        (root / "references" / "inject-map.json").write_text(json.dumps({"common": ["plugin:references/m.md"], "roles": {
            "qa-a": []}}), encoding="utf-8")
        check_eq("A-K9: a map with no common-rules slice has shared == list", CS.common_layer(root)["shared"], 100)
        # the catalogue never names the common-layer slice
        (root / "references" / "inject-map.json").write_text(json.dumps({"common": ["plugin:references/m.md"], "roles": {
            "qa-b": ["plugin:references/slices/qa-b/common-rules.md"]}}), encoding="utf-8")
        check_not_in("A-K2: the catalogue of a role skips its common-rules slice", "common-rules.md",
                     CS.catalogue(root, "qa-b"))
    finally:
        cleanup(tmp)


def test_cli() -> None:
    p = run_script("contract_slices.py", "--check")
    check("CLI: --check exits 0 on the shipped package", p.returncode == 0,
          (p.stdout + p.stderr)[-400:])
    p = run_script("contract_slices.py", "--selftest")
    check("CLI: --selftest exits 0", p.returncode == 0, (p.stdout + p.stderr)[-400:])
    p = run_script("contract_slices.py", "--report")
    check_in("CLI: --report prints the per-role weight", "qa-code-critic", p.stdout)


def test_plan_role_charter_line() -> None:
    """F-10: a role dispatched for the S5 plan as well as a window names no path and counts both units."""
    for role in ("qa-automator", "qa-code-critic"):
        line = CS.charter_line(PLUGIN_ROOT, role)
        check_in(f"F-10: {role} line covers the plan dispatch unit", "a plan dispatch: per case", line)
        check_not_in(f"F-10: {role} line names no artifact path", "`work/", line)
    other = CS.charter_line(PLUGIN_ROOT, "qa-bug-reporter")
    check_not_in("F-10 control: a role with one dispatch kind keeps its single line", "plan dispatch", other)
    text = (PLUGIN_ROOT / "agents" / "qa-automator.md").read_text(encoding="utf-8")
    check_not_in("F-10: the prose patch that contradicted the generated line is gone",
                 "Plan dispatch: one line per case", text)


def test_handoff_keys_pages() -> None:
    """X1-7: the generated key page of the four charter roles (`handoff_keys_page`): present, fresh, generated, and unknowns named."""
    roles = ("qa-scout", "qa-requirements-tester", "qa-test-strategist", "qa-case-designer")
    roles += ("qa-automator", "qa-code-critic")                       # X7-1
    # X7-3: the runner and the analyst have a key page too; their forms get the `tried` table in X7-7, so the table is checked for the four
    # X7-4: the reporter, the scribe and the retro analyst have one too
    x7_roles = ("qa-runner", "qa-failure-analyst", "qa-bug-reporter", "qa-doc-scribe", "qa-retro-analyst")
    check_eq("X1-7: the map names a key page for exactly the roles that have a slice", sorted(r for r, _e, _p in CS.keys_targets(PLUGIN_ROOT)),
             sorted(roles + x7_roles))
    for role in x7_roles:
        page = (PLUGIN_ROOT / "references" / "slices" / role / CS.KEYS_NAME).read_text(encoding="utf-8")
        for anchor in ("## Outputs", "## Witness", "## Handoff form", "generated by scripts/contract_slices.py"):
            check_in(f"X7-3: {role}'s key page holds `{anchor}`", anchor, page)
    check_not_in("X1-7: `targets` never names a key page (no source file to cut it from)", CS.KEYS_NAME,
                 " ".join(t["subject"] for t in CS.targets(PLUGIN_ROOT)))
    for role in roles:
        page = (PLUGIN_ROOT / "references" / "slices" / role / CS.KEYS_NAME).read_text(encoding="utf-8")
        for anchor in ("## Outputs", "## Witness", "## Handoff form", "generated by scripts/contract_slices.py"):
            check_in(f"X1-7: {role}'s key page holds `{anchor}`", anchor, page)
        if role in ("qa-scout", "qa-requirements-tester", "qa-test-strategist", "qa-case-designer"):
            # the forms of S5-S9 get `tried` in X7-7 (handoff_check.TRIED_CONTRACTS); that node adds its roles to this tuple
            check_in(f"X1-7: {role}'s key page carries the tried table from its form", "`tried[].technique`", page)
            check_in(f"X1-7: {role}'s key page carries tried_note as optional", "`tried_note` (optional)", page)
    scout = (PLUGIN_ROOT / "references" / "slices" / "qa-scout" / CS.KEYS_NAME).read_text(encoding="utf-8")
    check_in("X1-7: the scout's page names the validator's keys (PHASE_JSON_KEYS)", "`acceptance_criteria`", scout)
    check_in("X1-7: the designer's page carries the token the case identity gate demands", "= the file name",
             (PLUGIN_ROOT / "references" / "slices" / "qa-case-designer" / CS.KEYS_NAME).read_text(encoding="utf-8"))
    check_in("X1-7: the tester's page carries the token the grounding gate demands", "derived",
             (PLUGIN_ROOT / "references" / "slices" / "qa-requirements-tester" / CS.KEYS_NAME).read_text(encoding="utf-8"))
    check_in("X1-7: the catalogue names the key page", CS.KEYS_NAME, CS.catalogue(PLUGIN_ROOT, "qa-scout"))
    unknown = CS.handoff_keys_page(PLUGIN_ROOT, "qa-nobody")
    check_in("X1-7 AR-28: a role in no stage is declared NOT KNOWN on its page, not given an empty one", "NOT KNOWN", unknown)
    tmp = temp_dir("qa-factory-keys-")
    try:
        root = tmp / "plugin"
        (root / "references").mkdir(parents=True)
        (root / "references" / "inject-map.json").write_text(json.dumps({"common": [], "roles": {
            "qa-scout": ["plugin:references/slices/qa-scout/handoff-keys.md"]}}), encoding="utf-8", newline="\n")
        check_in("BAD: a key page that was never generated is named as missing", "missing", " ".join(CS.keys_findings(root)))
        CS.keys_write(root)
        check_eq("GOOD: after the write nothing is wrong with the key page", CS.keys_findings(root), [])
        path = root / "references" / "slices" / "qa-scout" / CS.KEYS_NAME
        path.write_text(path.read_text(encoding="utf-8") + "hand-added\n", encoding="utf-8", newline="\n")
        check_in("BAD: a hand-edited key page is stale", "stale", " ".join(CS.keys_findings(root)))
        (root / "references" / "slices" / "qa-runner").mkdir(parents=True)
        (root / "references" / "slices" / "qa-runner" / CS.KEYS_NAME).write_text("left", encoding="utf-8", newline="\n")
        check_in("BAD: a key page no role is injected is an orphan", "no role is injected", " ".join(CS.keys_findings(root)))
    finally:
        cleanup(tmp)


def test_ladder_one_carrier() -> None:
    """X7-0 (K-L1, K-L1b): the P28 decision and the P19 ladder live in the manifesto alone; roles refer to the rung."""
    manifesto = (PLUGIN_ROOT / "references" / "tester-manifesto.md").read_text(encoding="utf-8")
    check_in("K-L1: the manifesto decides what to automate first", "decided first", manifesto)
    check_in("K-L1: and the ladder answers only the level", "only at which level", manifesto)
    check_in("K-L1: the section is craft (kind marker directly above its heading)",
             "<!-- kind: craft -->\n## What to automate, and at which level", manifesto)
    ladder = "(1) an automated test"
    check_eq("K-L1b control: the manifesto carries the ladder once", manifesto.count(ladder), 1)
    others = [p for d in ("agents", "references") for p in sorted((PLUGIN_ROOT / d).rglob("*.md"))
              if p.name != "tester-manifesto.md"]
    check("K-L1b control: the scan sees files", len(others) > 20)
    retold = [str(p.relative_to(PLUGIN_ROOT)) for p in others if ladder in p.read_text(encoding="utf-8")]
    check_eq("K-L1b: no other agent or reference retells the ladder", retold, [])
    # NEGATIVE control: the same scan is red on a text that retells it.
    check("K-L1b NEGATIVE: a doctored file that retells the ladder is caught", ladder in (manifesto + "x"))


test_rendering()
test_handoff_keys_pages()
test_plan_role_charter_line()
test_findings_and_write()
test_shipped_package()
test_grounding_words()
test_common_rules_slices()
test_common_layer()
test_cli()
test_ladder_one_carrier()

finish("contract slices (markup, generation, freshness, shipped map)")
