#!/usr/bin/env python3
"""scripts/ticket_light.py: the ticket in a light form (D-06, t-267 builder B1).

What is proved (K keys of the t-267 spec, each with its negative control):
  * K1  the acceptance criteria of TP1-15045's description (plain-line heading, numbered list,
        a glued next section) are exactly 15 items; the three extra shapes (wiki `# ` list,
        `h3. *Acceptance Criteria:*`, ADF list) and 13797's 13 items; 0 criteria is `[]`;
  * K2  (fixture part) the own-words share of the light projection against the unfiltered input;
  * K3  the one-line-per-comment view round-trips, backslash first, never splitlines();
  * K7  person vs tracker: the person is the authority, `\\{` against `{` is not a difference;
  * K8  (pure part) the references of 15045's text, and the key-shape class (URLs consumed first,
        uppercase only, `MY_PROJ-12` is not `PROJ-12`);
  * K14 the description note: nothing at N bytes, one line at N+1, never cut;
  * the projection's own invariants (noise, empties, schema keys, value walk) and the data
    tables' refusals (a missing or empty table never becomes a silent empty whitelist).
Fixtures are synthetic, shaped like TP1-15045 (the description string is the owner's own test
ticket, copied verbatim); every host is example.test.
"""
import contextlib
import copy
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import adapter_forms as AF  # noqa: E402
import ticket_light as T  # noqa: E402

FIX =harness.FIXTURES / "ticket-15045"
RAW = json.loads((FIX / "raw-issue.json").read_text(encoding="utf-8"))
# Line endings of the checkout are not the fixture's content: a clone made before the package's .gitattributes keeps this file CRLF until git rewrites it (B-409 E13), and the adapter prints LF (the K2 check "a dict is measured as the adapter prints it").
AGENT_BYTES = (FIX / "agent-snapshot.json").read_bytes().replace(b"\r\n", b"\n")
TABLE = T.load_fields_table()
KINDS = T.load_reference_kinds()
HEADINGS, SECTIONS = TABLE["acceptance_headings"], TABLE["section_names"]
BS, MID, SEP = T.BS, T.MID_DOT, T.SEP
DESC = RAW["fields"]["description"]
ITEM_1 = "Visual revision diff opens from workflow version history."
ITEM_15 = "Existing workflow versioning/text diff behavior is not regressed."


def kline(label: str, text: str) -> None:
    print(f"{label}: {text}")


def ac(description, **kw):
    kw.setdefault("headings", HEADINGS)
    kw.setdefault("section_names", SECTIONS)
    return T.acceptance_criteria(description, **kw)


def light(raw=None, **kw):
    kw.setdefault("config_custom_fields", [])
    kw.setdefault("acceptance_fields", [])
    return T.project(raw or RAW, fields_table=TABLE, acceptance_headings=HEADINGS,
                    section_names=SECTIONS, **kw)


# --- the data tables ------------------------------------------------------------------------

def tables() -> None:
    import source_inventory as SI
    check_eq("tables: the not-tracker prefixes MOVED from code unchanged",
             set(TABLE["not_tracker_prefixes"]), set(SI.NOT_TRACKER_PREFIXES))
    check_eq("tables: attachment policy defaults are labelled as a proposal",
             TABLE["attachment_policy"]["note"], "proposal, unmeasured")
    check_eq("tables: description limit N = 32768 and labelled as a proposal",
             (TABLE["description_limit_bytes"], TABLE["description_limit_note"]), (32768, "proposal, unmeasured"))
    rules = {r["class"]: r for r in TABLE["attachment_policy"]["rules"]}
    check_eq("tables: images <= 5 MB, documents <= 10 MB, video and archives never",
             (rules["image"]["max_bytes"], rules["document"]["max_bytes"], rules["video"].get("never"),
              rules["archive"].get("never")), (5 * 1024 * 1024, 10 * 1024 * 1024, True, True))
    check("tables: the default headings hold the three the spec names",
          {"Acceptance Criteria", "What needs to be tested", "AC"} <= set(HEADINGS), str(HEADINGS))
    check("tables: 'QA Factory evaluation goals' is a known section name", "QA Factory evaluation goals" in SECTIONS)
    check("tables: reference kinds name Jira, Confluence, GitLab MR and issue, GitHub pull, Figma",
          {"ticket", "confluence", "merge_request", "gitlab_issue", "pull_request", "figma"}
          <= {k["kind"] for k in KINDS["kinds"]})
    import ticket_adapter
    check_eq("tables: the light snapshot keeps the adapter's SCHEMA_KEYS", T.SCHEMA_KEYS, ticket_adapter.SCHEMA_KEYS)

    tmp = harness.temp_dir()
    try:
        def refused(name, path, loader=T.load_fields_table):
            try:
                loader(path)
            except T.TableError as exc:
                return str(exc)
            return None

        msg = refused("missing", tmp / "jira-fields.json")
        check("refusal: a MISSING fields table raises and names the file", msg is not None and "jira-fields.json" in msg, str(msg))
        (tmp / "bad.json").write_text("{not json", encoding="utf-8")
        msg = refused("malformed", tmp / "bad.json")
        check("refusal: a MALFORMED table raises, names the file and says how to restore it",
              msg is not None and "bad.json" in msg and "restore" in msg, str(msg))
        empty = dict(TABLE, standard=[])
        (tmp / "empty.json").write_text(json.dumps(empty), encoding="utf-8")
        msg = refused("empty", tmp / "empty.json")
        check("refusal (K12 spirit): an EMPTY whitelist raises naming the key - never a silent empty projection",
              msg is not None and "`standard`" in msg and "empty.json" in msg, str(msg))
        lacking = dict(TABLE, standard=[n for n in TABLE["standard"] if n != "comment"])
        (tmp / "lack.json").write_text(json.dumps(lacking), encoding="utf-8")
        msg = refused("lacking", tmp / "lack.json")
        check("refusal: a whitelist without a core field raises naming the field", msg is not None and "comment" in msg, str(msg))
        (tmp / "nonoise.json").write_text(json.dumps(dict(TABLE, noise=[])), encoding="utf-8")
        msg = refused("nonoise", tmp / "nonoise.json")
        check("refusal: an empty noise list raises naming the key", msg is not None and "`noise`" in msg, str(msg))
        msg = refused("kinds-missing", tmp / "reference-kinds.json", T.load_reference_kinds)
        check("refusal: a missing reference-kinds table raises and names the file",
              msg is not None and "reference-kinds.json" in msg, str(msg))
        (tmp / "kinds.json").write_text(json.dumps({"kinds": [{"kind": "x", "hosts": [], "path_regexes": ["("]}]}), encoding="utf-8")
        msg = refused("kinds-regex", tmp / "kinds.json", T.load_reference_kinds)
        check("refusal: a reference kind whose regex does not compile raises naming kind and file",
              msg is not None and "`x`" in msg and "kinds.json" in msg, str(msg))
        try:
            T.project(RAW, fields_table=dict(TABLE, standard=[]), config_custom_fields=[], acceptance_fields=[],
                      acceptance_headings=HEADINGS, section_names=SECTIONS)
            got = "no refusal"
        except T.TableError as exc:
            got = str(exc)
        check("refusal: project() with an empty whitelist raises, it never projects everything", "`standard`" in got, got)
        for what, kw, named in (("config_custom_fields a string", {"config_custom_fields": "customfield_1"}, "direct_api.custom_fields"),
                                ("acceptance_headings empty", {"acceptance_headings": []}, "acceptance headings")):
            try:
                T.project(RAW, **dict(dict(fields_table=TABLE, config_custom_fields=[], acceptance_fields=[],
                                           acceptance_headings=HEADINGS, section_names=SECTIONS), **kw))
                got = "no refusal"
            except T.TableError as exc:
                got = str(exc)
            check(f"refusal: project() with {what} raises with `{named}` named", named in got, got)
    finally:
        harness.cleanup(tmp)


# --- K1 -------------------------------------------------------------------------------------

def adf_doc(*blocks):
    return {"type": "doc", "version": 1, "content": list(blocks)}


def adf_p(text, marks=None):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = marks
    return {"type": "paragraph", "content": [node]}


def adf_list(kind, *texts):
    return {"type": kind, "content": [{"type": "listItem", "content": [adf_p(t)]} for t in texts]}


def adf_h(level, text):
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


def k1() -> None:
    import source_inventory as SI
    items = ac(DESC)
    check_eq("K1: 15 items on the 15045 description (plain-line heading, glued next section)", len(items), 15)
    check_eq("K1: item 1 verbatim", items[0], ITEM_1)
    check_eq("K1: item 15 verbatim", items[14], ITEM_15)
    check("K1: no item holds 'QA Factory evaluation goals' (the glue is absent)",
          not any("QA Factory evaluation goals" in i for i in items), str(items[14]))
    check("K1: no item holds 'Verify' (the five indented lines are not items)", not any("Verify" in i for i in items))
    kline("K1", f"{len(items)} items on the 15045 description; item 1 = {items[0]!r}; item 15 = {items[14]!r}")

    check_eq("K1 negative (i): the heading list WITHOUT 'What needs to be tested' gives 0 items",
             ac(DESC, headings=["Acceptance Criteria", "AC"]), [])
    check_eq("K1 negative (ii): today's acceptance_criteria_from_description gives []",
             SI.acceptance_criteria_from_description(DESC), [])
    glued = ac(DESC, section_names=[])
    check_eq("K1: the blank-line rule alone also ends the section (glue stays absent without the names)", len(glued), 15)
    check_eq("K1: the section-name rule ends a section with no blank line before it",
             ac("AC\n1. one\n2. two\nQA Factory evaluation goals\n3. three"), ["one", "two"])
    check_eq("K1 negative control of that rule: the same text without the name continues item 2 (the old glue)",
             ac("AC\n1. one\n2. two\nQA Factory evaluation goals\n3. three", section_names=[]),
             ["one", "two QA Factory evaluation goals", "three"])

    # three extra shapes
    wiki_hash = "Intro\r\n\r\nh3. Acceptance Criteria\r\n# first\r\n# second\r\n# third\r\n\r\nh3. Notes\r\nnot a criterion"
    check_eq("K1 shape 1: wiki `# item` list is three ITEMS (`#` is a list marker in wiki)",
             ac(wiki_hash, markup="wiki"), ["first", "second", "third"])
    check_eq("K1 shape 1 control: in MARKDOWN the same `# ` lines are headings, the section ends at once",
             ac(wiki_hash.replace("h3. ", "### "), markup="markdown"), [])
    check_eq("K1 shape 1 control: in wiki `# Acceptance Criteria` is an item, never the heading",
             ac("# Acceptance Criteria\n# a\n# b", markup="wiki"), [])
    wiki_bold = "Intro\n\nh3. *Acceptance Criteria:*\n * alpha\n * beta\n\nh3. Notes\n * not this"
    check_eq("K1 shape 2: `h3. *Acceptance Criteria:*` with ` * ` items", ac(wiki_bold), ["alpha", "beta"])
    check_eq("K1 shape 2: markdown `**What needs to be tested**` and `## AC:`",
             (ac("**What needs to be tested**\n\n- x\n- y\n\n## Notes\n- z", markup="markdown"),
              ac("## AC:\n1. p\n2. q", markup="markdown")), (["x", "y"], ["p", "q"]))
    adf = adf_doc(adf_p("Context paragraph."), adf_h(3, "Acceptance Criteria"),
                  adf_list("orderedList", "adf one", "adf two", "adf three"), adf_h(3, "Notes"), adf_p("later"))
    check_eq("K1 shape 3: an ADF description (dict) with an ordered list", ac(adf), ["adf one", "adf two", "adf three"])
    check_eq("K1 shape 3: ADF bullet list under a bold plain-line heading",
             ac(adf_doc(adf_p("What needs to be tested", [{"type": "strong"}]), adf_list("bulletList", "b1", "b2"),
                        adf_p("QA Factory evaluation goals"), adf_list("bulletList", "goal"))), ["b1", "b2"])
    flat = T.flatten_adf(adf)
    check("K1 shape 3: the ADF flattening KEEPS the list markers", "1. adf one" in flat and "3. adf three" in flat, flat)
    import source_inventory as SI2
    check_not_in("K1 shape 3 negative control: source_inventory._text drops them (why C2 exists)", "1. adf one", SI2._text(adf))
    kline("K1 shapes", f"wiki '# ' list -> {ac(wiki_hash)}; 'h3. *Acceptance Criteria:*' -> {ac(wiki_bold)}; "
                       f"ADF ordered list -> {ac(adf)}")

    # 13797: wiki h2 + ' * ' items (one wrapped), and the markdown paste
    lines13 = [f" * Criterion {n} of the webhook filter ticket." for n in range(1, 14)]
    lines13[4] += "\nwrapped tail of criterion 5"
    wiki13 = "Description: advanced filtering.\n\nh2. Acceptance Criteria\n" + "\n".join(lines13) + "\n\nh2. Comments\nnot a criterion"
    got13 = ac(wiki13)
    check_eq("K1: the 13797 shape (h2. Acceptance Criteria + ' * ' items) = 13 items", len(got13), 13)
    check_eq("K1: a wrapped line directly after an item continues it", got13[4], "Criterion 5 of the webhook filter ticket. wrapped tail of criterion 5")
    md13 = "# Title\n\n## Acceptance criteria\n\n" + "\n".join(f"{n}. Criterion {n}" for n in range(1, 14)) + "\n\n## Comments\n\n- **x** (2026): y"
    check_eq("K1: the 13797 markdown paste (## heading, numbered items, markup markdown) = 13", len(ac(md13, markup="markdown")), 13)
    kline("K1 13797", f"wiki {len(got13)} items, markdown paste {len(ac(md13, markup='markdown'))} items")

    # negatives and edges of the section rule
    check_eq("K1: 0 criteria is [] - never invented (the caller asks the person)", ac("Just a story.\n\nNothing else."), [])
    check_eq("K1: an empty / None description is []", (ac(""), ac(None), ac({})), ([], [], []))
    check_eq("K1 edge: a paragraph after the heading and a blank line ends the section with 0 items (the next list is not ours)",
             ac("AC\n\nSome intro paragraph.\n\nOther section\n1. not ours\n2. not ours either"), [])
    check_eq("K1 edge: indented non-item lines inside the list are ignored",
             ac("AC\n1. one\n   detail under one\n2. two"), ["one", "two"])
    check_eq("K1 edge: a line holding U+2028 stays whole (splitlines would cut it)",
             ac("AC\n1. one" + chr(0x2028) + "still one\n2. two"), ["one" + chr(0x2028) + "still one", "two"])
    check_eq("K1 edge: heading matches case-insensitively with a trailing colon", ac("acceptance criteria:\n- a"), ["a"])
    check_eq("K1 precedence (F8): a non-empty configured field wins over the description",
             ac(DESC, acceptance_field_value="1. field one\n2. field two"), ["field one", "field two"])
    check_eq("K1 precedence: an empty / whitespace field falls back to the description",
             len(ac(DESC, acceptance_field_value="  \n ")), 15)
    check_eq("K1 precedence: an ADF field value is flattened", ac("none", acceptance_field_value=adf_doc(adf_list("bulletList", "f1", "f2"))), ["f1", "f2"])
    for bad in ({"headings": []}, {"headings": "AC"}):
        try:
            ac(DESC, **bad)
            got = "no refusal"
        except T.TableError as exc:
            got = str(exc)
        check(f"K1 refusal: headings={bad['headings']!r} raises instead of silently finding nothing", got != "no refusal", got)
    try:
        ac(DESC, markup="html")
        got = "no refusal"
    except ValueError as exc:
        got = str(exc)
    check("K1 refusal: an unknown markup names the allowed ones", "wiki" in got and "markdown" in got and "adf" in got, got)


# --- projection, K2 fixture part, K14 ---------------------------------------------------------

def string_walk(node, path=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from string_walk(value, path + (str(key),))
    elif isinstance(node, list):
        for value in node:
            yield from string_walk(value, path)
    elif isinstance(node, str):
        yield path, node


USER_KEYS = {"author", "reporter", "assignee", "updateAuthor"}
NOISE_ANYWHERE = {"self", "expand", "avatarUrls", "iconUrl", "statusCategory", "timeZone", "thumbnail", "emailAddress"}


def exempt(path, text):
    """Strings of a whitelisted field that the light form is ALLOWED not to carry, each with its why."""
    if any(p in NOISE_ANYWHERE for p in path):
        return True                                        # the noise blacklist
    last = path[-1]
    if last == "id" and path not in (("comment", "comments", "id"), ("attachment", "id")):
        return True                                        # nested ids; comment and attachment keep theirs
    if any(p in USER_KEYS for p in path) and last != "displayName":
        return True                                        # a user object is its displayName
    if path[0] == "parent" and last != "key":
        return True                                        # parent is its key, as before
    if path[0] == "attachment" and last in ("created", "content"):
        return True                                        # spec: {id, filename, size, mimeType}
    if last == "description" and len(path) > 1:
        return True                                        # status / issuetype descriptions
    if path[0] == "comment" and last == "updated":
        return True
    if path[0] == "issuelinks" and ("priority" in path or "issuetype" in path):
        return True
    return False


def projection() -> None:
    out = light()
    check("projection: SCHEMA_KEYS all present", all(k in out for k in T.SCHEMA_KEYS), str(list(out)))
    check_eq("projection: the `links` dict shape", sorted(out["links"]), ["branch", "issue_links", "merge_request", "remote_links"])
    check_eq("projection: description is whole and byte-equal to the raw", out["description"], DESC)
    check_eq("projection: 15 acceptance items; parent, type, status as names",
             (len(out["acceptance_criteria"]), out["parent"], out["type"], out["status"]),
             (15, "TP1-14482", "Sub-task", "Ready for Review"))
    check_eq("projection: a comment keeps its id", [c["id"] for c in out["comments"]], ["15923998"])
    check_eq("projection: attachments are {id, filename, size, mimeType} and the count is unchanged",
             [sorted(a) for a in out["attachments"]], [["filename", "id", "mimeType", "size"]] * 2)
    check_eq("projection: `updated` is kept once, as the revision", out["revision"], RAW["fields"]["updated"])
    check("projection: user objects are display names - no email address anywhere in the light form",
          "@example.test" not in json.dumps(out), "")
    check_eq("projection: reporter is a display name, an empty assignee is not printed",
             (out.get("reporter"), "assignee" in out), ("Exemplar Reporter", False))

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    forbidden = NOISE_ANYWHERE | {"active"}
    check("noise: no blacklisted key survives at any depth of the output", not (forbidden & set(keys(out))), str(forbidden & set(keys(out))))

    # custom fields: named only, never empty, light values
    cf_ids = [f"customfield_2000{n}" for n in range(1, 10)] + ["customfield_20010", "customfield_20011", "customfield_20012", "customfield_99999"]
    named = light(config_custom_fields=cf_ids)
    cf = named["custom_fields"]
    check_eq("custom: the unnamed ones are never in the light form (customfield_10800, 25700, 33100, 33334)",
             [k for k in cf if k in ("customfield_10800", "customfield_25700", "customfield_33100", "customfield_33334")], [])
    check_eq("custom: a named EMPTY one (None, '', [], {}, whitespace) is never in it",
             [k for k in ("customfield_20002", "customfield_20005", "customfield_20006", "customfield_20007", "customfield_20008") if k in cf], [])
    check_eq("custom: a named non-empty string is kept", cf["customfield_20001"], "Synthetic named note kept because config names it.")
    check_eq("custom: an option object becomes its `value`", cf["customfield_20003"], "Planned")
    check_eq("custom: an option object with no value becomes its `name`", cf["customfield_20010"], "Option by name")
    check_eq("custom: a list of user objects becomes displayNames", cf["customfield_20004"], ["Exemplar Member"])
    check_eq("custom: noise is stripped recursively from a nested object (self, id, iconUrl at depth)",
             cf["customfield_20009"], {"boardId": 3, "goal": "synthetic goal", "nested": {"label": "deep value"}})
    check_eq("custom: ADF in a named field is text", cf["customfield_20011"], "Rich text in a named field.")
    check_eq("custom: the number 0 is a value, not an empty", cf["customfield_20012"], 0)
    check_eq("custom: a named id the issue does not carry is NAMED in fields_missing", named["fields_missing"], ["customfield_99999"])
    check("custom: a lean projection carries neither custom_fields nor fields_missing when empty",
          "custom_fields" not in out and "fields_missing" not in out, str(list(out)))
    field_ac = light(acceptance_fields=["customfield_20001"])
    check_eq("custom: a named acceptance field wins over the description section and is kept",
             (field_ac["acceptance_criteria"], "customfield_20001" in field_ac["custom_fields"]),
             (["Synthetic named note kept because config names it."], True))
    try:
        light(config_custom_fields="customfield_20001")
        got = "no refusal"
    except T.TableError as exc:
        got = str(exc)
    check("custom: a malformed config list is refused naming the config key", "direct_api.custom_fields" in got, got)

    # issue links and remote links
    raw2 = copy.deepcopy(RAW)
    raw2["fields"]["issuelinks"] = [{"id": "20001", "self": "https://jira.example.test/l/1",
                                     "type": {"id": "1", "name": "Relates", "inward": "relates to", "outward": "relates to"},
                                     "outwardIssue": {"id": "3", "key": "TP1-14483", "self": "https://jira.example.test/i/3",
                                                      "fields": {"summary": "Linked story", "status": {"name": "Open", "id": "1"},
                                                                 "priority": {"name": "Minor"}, "issuetype": {"name": "Story"}}}}]
    raw2["fields"]["subtasks"] = [{"id": "9", "key": "TP1-15046", "fields": {"summary": "s", "status": {"name": "Done"}}}]
    remote = [{"object": {"title": "Draft MR", "url": "https://gi.example.test/org-cdme/testproject1-ui/-/merge_requests/1924"}},
              {"object": {"title": "Real MR", "url": "https://gi.example.test/org-cdme/testproject1-ui/-/merge_requests/1881"}}]
    out2 = light(raw2, remote_links=remote)
    check_eq("links: issue_links carry relation, type, key, summary, status",
             out2["links"]["issue_links"], [{"relation": "relates to", "type": "Relates", "key": "TP1-14483",
                                              "summary": "Linked story", "status": "Open"}])
    check_eq("links: subtasks are {key, status}", out2["subtasks"], [{"key": "TP1-15046", "status": "Done"}])
    check_eq("links: merge_request is the first remote-link MR, remote_links are {title, url}",
             (out2["links"]["merge_request"], [r["title"] for r in out2["links"]["remote_links"]]),
             (remote[0]["object"]["url"], ["Draft MR", "Real MR"]))
    raw3 = copy.deepcopy(RAW)
    raw3["fields"]["parent"] = None
    raw3["fields"]["customfield_10014"] = "TP1-777"
    check_eq("links: a classic Epic Link field gives the parent when `parent` is absent",
             (light(raw3)["parent"], light(raw3, epic_fields=["customfield_10014"])["parent"]), (None, "TP1-777"))

    # ADF description projects to a string with markers, and the criteria are found in it
    raw4 = copy.deepcopy(RAW)
    raw4["fields"]["description"] = adf_doc(adf_p("Intro."), adf_h(2, "Acceptance Criteria"), adf_list("bulletList", "x1", "x2"))
    out4 = light(raw4)
    check("projection: an ADF description becomes a string that keeps its list markers",
          isinstance(out4["description"], str) and "* x1" in out4["description"], str(out4["description"]))
    check_eq("projection: the criteria of an ADF description", out4["acceptance_criteria"], ["x1", "x2"])

    # the value walk (the invariant): whitelisted strings are in the light form, or exempt with a stated why
    out_strings = [s for _p, s in string_walk(out2)]
    missing = []
    for name in TABLE["standard"]:
        for path, text in string_walk(raw2["fields"].get(name), (name,)):
            if not exempt(path, text) and not any(text in o for o in out_strings):
                missing.append((path, text[:60]))
    check_eq("INVARIANT: every string of the whitelisted fields is in the light form or is exempt noise", missing, [])
    check("INVARIANT control: the walk is not vacuous (it saw a long list of strings)",
          sum(1 for name in TABLE["standard"] for _ in string_walk(raw2["fields"].get(name), (name,))) > 40)
    broken = copy.deepcopy(out2)
    broken["attachments"] = [{k: v for k, v in a.items() if k != "filename"} for a in broken["attachments"]]
    broken_strings = [s for _p, s in string_walk(broken)]
    lost = [text for path, text in string_walk(raw2["fields"].get("attachment"), ("attachment",))
            if not exempt(path, text) and not any(text in o for o in broken_strings)]
    check("INVARIANT negative: dropping the attachment names makes the walk fail", "diff-view.png" in lost, str(lost))


def inflate(raw, total=164, empty=132):
    """The raw issue with `total` custom fields, `empty` of them empty - the 15045 shape (164 / 132)."""
    big = copy.deepcopy(raw)
    fields = big["fields"]
    have = [k for k in fields if k.startswith("customfield_")]
    n = 0
    while len(have) < total:
        fid = f"customfield_{30000 + n}"
        n += 1
        if fid in fields:
            continue
        if len([k for k in have if fields[k] in (None, "", [])]) < empty:
            fields[fid] = [None, "", []][n % 3]
        else:
            fields[fid] = {"disabled": False, "id": str(100000 + n), "self": f"https://jira.example.test/rest/api/2/customFieldOption/{100000 + n}",
                           "value": f"Option value {n}"}
        have.append(fid)
    return big


def unfiltered_snapshot(raw):
    """What source_inventory._snapshot printed for 15045: every customfield_*, the AC as an empty string."""
    fields = raw["fields"]
    return {"acceptance_criteria": "",
            "comments": [{"author": c["author"]["displayName"], "created": c["created"], "id": c["id"], "text": c["body"], "updated": c["updated"]}
                         for c in fields["comment"]["comments"]],
            "custom_fields": {k: v for k, v in fields.items() if k.startswith("customfield_")},
            "description": fields["description"], "id": raw["id"], "key": raw["key"], "links": [],
            "parent": fields["parent"]["key"], "status": fields["status"]["name"], "title": fields["summary"],
            "type": fields["issuetype"]["name"]}


def k2() -> None:
    agent = T.own_words_share(AGENT_BYTES)
    check_eq("K2: the agent-snapshot-shaped fixture is 2,062 bytes, own words 1,495 (AC joined by LF)", agent[:2], (1495, 2062))
    check_eq("K2: ... that is 72.5 % (71.8 % with the criteria joined by nothing)", round(agent[2] * 100, 1), 72.5)
    check_eq("K2: a dict is measured as the adapter prints it (same bytes as the file)", T.own_words_share(json.loads(AGENT_BYTES)), agent)
    big = inflate(RAW)
    n_cf = len([k for k in big["fields"] if k.startswith("customfield_")])
    n_empty = len([k for k in big["fields"] if k.startswith("customfield_") and big["fields"][k] in (None, "", [])])
    check_eq("K2 fixture: 164 custom fields, 132 of them empty (the 15045 shape)", (n_cf, n_empty), (164, 132))
    unf = unfiltered_snapshot(big)
    unf_words, unf_bytes, unf_share = T.own_words_share(unf)
    out = light(big)
    words, size, share = T.own_words_share(out)
    check("K2: the light projection's own-words share is >= the agent snapshot's", share >= agent[2], f"{share:.4f} < {agent[2]:.4f}")
    check("K2: the light snapshot is smaller than the unfiltered input", size < unf_bytes, f"{size} >= {unf_bytes}")
    check("K2 negative: the UNFILTERED input fails the same check (below the agent snapshot's share)", unf_share < agent[2],
          f"{unf_share:.4f}")
    check("K2: the 132 empty and 32 non-empty unnamed custom fields are all absent from the light form", "customfield_" not in json.dumps(out))
    check("K2: the projection did not change with the 164 fields (same output as the lean fixture)", out == light(RAW))
    kline("K2", f"agent snapshot {agent[0]}/{agent[1]} B = {agent[2]*100:.1f} %; light {words}/{size} B = {share*100:.1f} %; "
                f"unfiltered {unf_words}/{unf_bytes} B = {unf_share*100:.1f} %")

    # the readers of the light snapshot: brief_pack.snapshot_mask_lines and stage_compare.s0
    import brief_pack
    import source_exclusions as SE
    remote = [{"object": {"title": "Draft MR", "url": "https://gi.example.test/org-cdme/testproject1-ui/-/merge_requests/1924"}},
              {"object": {"title": "Real MR", "url": "https://gi.example.test/org-cdme/testproject1-ui/-/merge_requests/1881"}}]
    snap = light(big, remote_links=remote)
    tmp = harness.temp_dir()
    try:
        task = tmp / "task"
        work = task / "work"
        work.mkdir(parents=True)
        (work / "ticket-snapshot.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        SE.record_path(work).write_text(json.dumps({"schema_version": 1, "list_file": "list.txt", "exclusions": [
            {"id": "X1", "as_written": "testproject1-ui!1924", "origin": "person_before_run", "revoked_at": None,
             "target": {"kind": "mr", "host": None, "project": "testproject1-ui", "iid": "1924"},
             "reason": "Draft MR of an earlier factory run"}]}), encoding="utf-8")
        masks = brief_pack.snapshot_mask_lines(task)
        check("FR-14: brief_pack.snapshot_mask_lines reads the light snapshot's links (the left-out MR is named once)",
              len(masks) == 1 and "1924" in masks[0] and "1881" not in masks[0], str(masks))
        s0_text = run_stage_compare_s0(work / "ticket-snapshot.json")
        if s0_text is None:
            print("SKIP stage_compare.s0 (experiments/measurers is not in this tree or cannot be imported)")
        else:
            row = {m.group(1): m.group(2).strip() for m in re.finditer(r"^(\w+)\s+\|\s+(.*?)\s*$", s0_text, re.M)}
            check_eq("FR-14: stage_compare.s0 reads the light snapshot: acceptance_criteria, comments, parent, attachments",
                     (row.get("acceptance_criteria"), row.get("comments"), row.get("parent"), row.get("attachments")),
                     ("15", "1", "TP1-14482", "2"))
            check_eq("FR-14: stage_compare.s0 reads description_len and the merge request",
                     (row.get("description_len"), row.get("merge_request")), (str(len(DESC)), "True"))
    finally:
        harness.cleanup(tmp)


def run_stage_compare_s0(snapshot: Path):
    folder = harness.PLUGIN_ROOT.parents[1] / "experiments" / "measurers"
    if not (folder / "stage_compare.py").exists():
        return None
    sys.path.insert(0, str(folder))
    try:
        import stage_compare as SC
    except Exception:
        return None
    finally:
        sys.path.remove(str(folder))
    saved = (SC.RUNS, SC.art)
    SC.RUNS = {"fixture": "fixture"}
    SC.art = lambda run, rel: snapshot if rel == "work/ticket-snapshot.json" else None
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            SC.s0()
    except Exception:
        return None
    finally:
        SC.RUNS, SC.art = saved
    return buf.getvalue()


def k14() -> None:
    limit = TABLE["description_limit_bytes"]
    at, over = "a" * limit, "a" * (limit + 1)
    check_eq("K14: a description of N bytes prints no line", T.description_note(at, limit_bytes=limit), None)
    line = T.description_note(over, limit_bytes=limit)
    check("K14: N+1 bytes prints ONE line naming both sizes", line is not None and "\n" not in line and "32,769" in line and "32,768" in line, str(line))
    check_eq("K14: N bytes in two-byte characters is N bytes, not N characters (no line)",
             T.description_note(chr(0xE9) * (limit // 2), limit_bytes=limit), None)
    check("K14: one more byte after that is the line", T.description_note(chr(0xE9) * (limit // 2) + "a", limit_bytes=limit) is not None)
    for text in (at, over):
        raw = copy.deepcopy(RAW)
        raw["fields"]["description"] = text
        out = light(raw)
        check_eq(f"K14: the description length is equal before and after the projection ({len(text)})", len(out["description"]), len(text))
    check("K14: the line says the description was kept whole", "kept whole" in (line or ""), str(line))
    kline("K14", f"at {limit} B -> {T.description_note(at, limit_bytes=limit)!r}; at {limit + 1} B -> {line!r}; "
                 f"length unchanged {len(light(dict(RAW, fields=dict(RAW['fields'], description=over)))['description'])} == {len(over)}")


# --- K3 -------------------------------------------------------------------------------------

def k3() -> None:
    comments = [
        {"id": "15923998", "created": "2026-09-18T08:20:40.161+0000", "author": "Exemplar Test Author",
         "text": RAW["fields"]["comment"]["comments"][0]["body"]},
        {"id": "15924001", "created": "2026-09-19T09:00:00.000+0000", "author": "Second Author", "text": "line one\nline two\r\nline three\rline four"},
        {"id": "15924002", "created": "2026-09-19T09:01:00.000+0000", "author": "Path Author",
         "text": "The folder is C:" + BS + "new and the endpoint is /v1/workflows/" + BS + "{id} and a literal " + BS + "n and " + BS + BS},
        {"id": "15924003", "created": "2026-09-19T09:02:00.000+0000", "author": "Dot Author",
         "text": "left" + SEP + "right" + SEP + "and again " + MID + " alone"},
        {"id": "15924004", "created": "2026-09-19T09:03:00.000+0000", "author": "Empty Text", "text": ""},
        {"id": "15924005", "created": "2026-09-19T09:04:00.000+0000", "author": None, "text": "no author"},
        {"id": "15924006", "created": "2026-09-19T09:05:00.000+0000", "author": "Separators",
         "text": "a" + chr(0x2028) + "b" + chr(0x2029) + "c" + chr(0x85) + "d"},
        {"id": "15924007", "created": "2026-09-19T09:06:00.000+0000", "author": "Dotted" + SEP + "Name", "text": "author with the separator"},
        {"id": "15924008", "created": "2026-09-19T09:07:00.000+0000", "author": "Trailing", "text": "ends with a backslash" + BS},
        {"id": "15924009", "created": "2026-09-19T09:08:00.000+0000", "author": "Space Only", "text": "   "},
    ]
    view = T.comment_lines(comments)
    physical = view.split("\n")
    check_eq("K3: one physical line per comment", len(physical), len(comments))
    check("K3: no line holds CR, U+2028, U+2029 or U+0085 (the text is escaped)",
          not any(c in line for line in physical for c in ("\r", chr(0x2028), chr(0x2029), chr(0x85))))
    check("K3 control: str.splitlines() WOULD cut the unescaped separators (why it is not used)",
          len(("x" + chr(0x2028) + "y").splitlines()) == 2 and len(view.splitlines()) == len(comments), "")
    check_eq("K3: the id comes first on every line", [line.split(SEP, 1)[0] for line in physical], [c["id"] for c in comments])
    expected = [(c["id"], c["created"], c["author"] or "", c["text"]) for c in comments]
    check_eq("K3: the parse returns (id, created, author, text) equal to the JSON (a null author is empty)",
             T.parse_comment_lines(view), expected)
    check_eq("K3: the 15045 comment 15923998 round-trips", T.parse_comment_lines(view)[0], expected[0])
    check_eq("K3: `C:" + BS + "new` and `" + BS + "{` survive", [t for _i, _c, _a, t in T.parse_comment_lines(view)][2], comments[2]["text"])
    check_eq("K3: a CRLF-ended file (editor artefact) parses the same", T.parse_comment_lines(view.replace("\n", "\r\n")), expected)
    check_eq("K3: the middle dot is built from its code point", MID, chr(183))
    check_eq("K3: verify_comment_lines finds no problem in an intact view", T.verify_comment_lines(comments, view), [])
    dropped = "\n".join(line for line in physical if not line.startswith("15924002" + SEP))
    problems = T.verify_comment_lines(comments, dropped)
    check("K3 negative: dropping one line fails and the failure names the id",
          len(problems) == 1 and "15924002" in problems[0], str(problems))
    check("K3 negative: reordering fails", T.verify_comment_lines(comments, "\n".join(reversed(physical))) != [])
    check("K3 negative: a changed text fails naming the id and the field",
          any("15924001" in p and "text" in p for p in T.verify_comment_lines(comments, view.replace("line two", "line 2"))))
    check_eq("K3: no comments, no view", (T.comment_lines([]), T.parse_comment_lines("")), ("", []))
    try:
        T.parse_comment_lines("not a comment line")
        got = "no refusal"
    except ValueError as exc:
        got = str(exc)
    check("K3: a line that is not in the form is refused with the line quoted", "not a comment line" in got, got)
    kline("K3", f"{len(comments)} comments round-trip through {len(physical)} lines; first line: {physical[0][:90]}...; "
                f"dropped-line check says: {problems[0] if problems else None}")


# --- K7 -------------------------------------------------------------------------------------

def k7() -> None:
    rest = light()
    person = {"title": rest["title"], "parent": rest["parent"], "comments": rest["comments"],
              "acceptance_criteria": [i.replace(BS + "{", "{") for i in rest["acceptance_criteria"]]}
    check("K7 setup: the person's items differ from the tracker's ONLY by the wiki escape",
          person["acceptance_criteria"] != rest["acceptance_criteria"] and any(BS + "{" in i for i in rest["acceptance_criteria"]))
    same = T.compare_person_vs_rest(person, rest)
    check_eq("K7 negative: `" + BS + "{` against `{` alone is NOT a disagreement", same["disagreements"], [])
    check_eq("K7: authority is the person", same["authority"], "person")
    check("K7: the one line is printed even with no difference and names the person's text as the requirement",
          "\n" not in same["line"] and "person's text is the requirement" in same["line"], same["line"])
    changed = dict(person, acceptance_criteria=person["acceptance_criteria"][:-1] + ["Existing behaviour is not regressed."])
    diff = T.compare_person_vs_rest(changed, rest)
    check_eq("K7: person AC differs from REST AC -> one disagreement on the criteria, naming what is only where",
             [d["field"] for d in diff["disagreements"]], ["acceptance_criteria"])
    d = diff["disagreements"][0]
    check("K7: only_in_person / only_in_rest carry the differing items",
          d["only_in_person"] == ["Existing behaviour is not regressed."] and d["only_in_rest"] == [rest["acceptance_criteria"][-1]], str(d))
    check("K7: ONE line, the authority is the person, REST is shown as 'the tracker now says'",
          "\n" not in diff["line"] and "person's text is the requirement" in diff["line"] and "tracker now says" in diff["line"], diff["line"])
    check("K7: the line says nothing was overridden", "Nothing was changed" in diff["line"], diff["line"])
    multi = T.compare_person_vs_rest(dict(person, title="Other title", parent="TP1-1", comments=[]), rest)
    check_eq("K7: title, comment count and parent are compared too", sorted(d["field"] for d in multi["disagreements"]),
             ["comments", "parent", "title"])
    check_eq("K7: AC as a joined string (the REST snapshot form) compares like the list form",
             T.compare_person_vs_rest(dict(person, acceptance_criteria="\n".join(person["acceptance_criteria"])),
                                      dict(rest, acceptance_criteria="\n".join(rest["acceptance_criteria"])))["disagreements"], [])
    check_eq("K7: runs of whitespace and CRLF are not differences", T.compare_person_vs_rest(
        {"title": "A  title\r\n", "acceptance_criteria": ["x  y"]}, {"title": "A title", "acceptance_criteria": ["x y"]})["disagreements"], [])
    kline("K7", f"escape-only -> disagreements={same['disagreements']}; one item changed -> {[x['field'] for x in diff['disagreements']]}; "
                f"line: {diff['line']}")


# --- K8 -------------------------------------------------------------------------------------

REPOS = [{"repo_id": "testproject1-backend", "role": "review", "local_path": "../../testproject1",
          "remote_identity": "git@gi.example.test:org-cdme/testproject1.git"},
         {"repo_id": "testproject1-ui", "role": "review", "local_path": "../../testproject1-ui",
          "remote_identity": "git@gi.example.test:org-cdme/testproject1-ui.git"}]
HOSTS = ["https://jira.example.test", REPOS[0]["remote_identity"], REPOS[1]["remote_identity"]]


def refs(texts, **kw):
    kw.setdefault("known_prefixes", {"TP1"})
    kw.setdefault("not_tracker_prefixes", TABLE["not_tracker_prefixes"])
    kw.setdefault("reference_kinds", KINDS)
    kw.setdefault("known_hosts", HOSTS)
    kw.setdefault("repos", REPOS)
    kw.setdefault("own_key", "TP1-15045")
    return T.references(texts, **kw)


def by_ref(rows):
    return {r["ref"]: r for r in rows}


def k8() -> None:
    fields = RAW["fields"]
    comment = fields["comment"]["comments"][0]
    texts = {"mention:summary": fields["summary"], "mention:description": fields["description"],
             f"mention:comment:{comment['id']}": comment["body"]}
    seeded = [{"ref": "TP1-14482", "origins": ["field:parent"]}]
    rows = refs(texts, seeded=seeded)
    index = by_ref(rows)
    ticket = index.get("TP1-14482") or {}
    check_eq("K8: TP1-14482 appears ONCE", len([r for r in rows if r["ref"] == "TP1-14482"]), 1)
    check("K8: its origins include field:parent, mention:summary, mention:description",
          {"field:parent", "mention:summary", "mention:description"} <= set(ticket.get("origins", [])), str(ticket))
    check_eq("K8: the ticket row is a ticket of a known prefix, not an other_project one",
             (ticket.get("kind"), ticket.get("prefix_known"), "other_project" in ticket.get("origins", [])), ("ticket", True, False))
    be = index.get("!4214") or {}
    check_eq("K8: MR !4214 is tied to repo testproject1-backend by the matched token `testproject1` (same paragraph)",
             (be.get("repo_id"), be.get("matched_token"), be.get("kind")), ("testproject1-backend", "testproject1", "merge_request"))
    ui = index.get("!1881") or {}
    check_eq("K8: MR !1881 is tied to repo testproject1-ui by the whole token `testproject1-ui`",
             (ui.get("repo_id"), ui.get("matched_token")), ("testproject1-ui", "testproject1-ui"))
    paths = sorted(r["ref"] for r in rows if r["kind"] == "local_path")
    check_eq("K8: the two ~/Projects/... local paths", paths, ["~/Projects/testproject1-dev/testproject1", "~/Projects/testproject1-dev/testproject1-ui"])
    check("K8: a local path is 'local path mention, not fetched'",
          all(r["status"] == "not_fetched:local path mention" for r in rows if r["kind"] == "local_path"))
    mr1924 = next((r for r in rows if r["kind"] == "merge_request" and r["ref"].endswith("/merge_requests/1924")), {})
    check_eq("K8: MR 1924 from comment 15923998 is listed with status `person`, tied to testproject1-ui by its path",
             (mr1924.get("status"), mr1924.get("origins"), mr1924.get("repo_id")),
             ("person", ["mention:comment:15923998"], "testproject1-ui"))
    check_eq("K8: NOTHING ELSE - exactly six rows", sorted((r["kind"], r["ref"]) for r in rows),
             sorted([("ticket", "TP1-14482"), ("merge_request", "!4214"), ("merge_request", "!1881"),
                     ("local_path", "~/Projects/testproject1-dev/testproject1"), ("local_path", "~/Projects/testproject1-dev/testproject1-ui"),
                     ("merge_request", mr1924.get("ref"))]))
    check("K8 negative: `/v1/workflows/\\{id}` is not a reference", not any("/v1/workflows" in r["ref"] or "workflow_id" in r["ref"] for r in rows))
    check("K8: the same MR named twice (goals paragraph has no repo token) merges into the tied row, one !4214 and one !1881",
          sorted(origin for r in rows if r["ref"] in ("!4214", "!1881") for origin in r["origins"]) == ["mention:description"] * 2
          and "repo" not in be, str((be, ui)))
    check_eq("K8: no per-prefix probe is needed on 15045's own text (0 probes, 0 per-key GETs)", T.prefixes_to_probe(rows), [])
    decoy = refs(dict(texts, **{"mention:comment:2": "see TC-001 for the case id"}), seeded=seeded)
    tc = by_ref(decoy).get("TC-001") or {}
    check_eq("K8: the decoy TC-001 is other_project and its prefix is unknown",
             ("other_project" in tc.get("origins", []), tc.get("prefix_known")), (True, False))
    check_eq("K8: ... and costs exactly ONE prefix probe (one per prefix, never per key)",
             T.prefixes_to_probe(refs(dict(texts, **{"mention:comment:2": "TC-001 TC-002 TC-003"}), seeded=seeded)), ["TC"])
    check_eq("K8: the decoy adds exactly one row to 15045's six", len(decoy), 7)
    kline("K8", f"{len(rows)} rows: " + "; ".join(f"{r['ref']} [{r['kind']}, {r['status']}, {','.join(r['origins'])}"
                                                   + (f", repo_id={r['repo_id']}" if r.get("repo_id") else "") + "]" for r in rows)
          + f"; prefix probes needed: {len(T.prefixes_to_probe(rows))} (+1 with the TC-001 decoy), per-key GETs: 0")

    # the key-shape class (C11)
    old_re = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]+-\d+)(?![A-Z0-9])")
    check_eq("K8 control: the PRE-change shape yields PROJ-12 out of MY_PROJ-12 (why the shape changed)",
             [m.group(1) for m in old_re.finditer("see MY_PROJ-12")], ["PROJ-12"])
    check_eq("K8: the single source KEY_RE does not (the whole key is one candidate, never a part of it)",
             [m.group(1) for m in T.KEY_RE.finditer("see MY_PROJ-12 and PROJ-13")], ["MY_PROJ-12", "PROJ-13"])
    keyrows = by_ref(refs({"mention:description": "MY_PROJ-12 tp1-123 TP1-14482. UTF-8 ISO-8601 SHA-256 TP1-15045 (TP1-9)"}))
    check_eq("K8: MY_PROJ-12 is a row, PROJ-12 is not", ("MY_PROJ-12" in keyrows, "PROJ-12" in keyrows), (True, False))
    check_eq("K8: uppercase only (tp1-123 is not a key), not-tracker prefixes and the story's own key are skipped",
             sorted(keyrows), ["MY_PROJ-12", "TP1-14482", "TP1-9"])
    url_rows = refs({"mention:description": "see https://other.example.test/wiki/PROJ-77/page and https://jira.example.test/browse/TP1-8384 "
                                            "and ~/work/TP1-55/notes.txt and C:" + BS + "work" + BS + "TC-009.txt"})
    check("K8: a key inside a URL path or a local path is not a candidate",
          not any(r["ref"] in ("PROJ-77", "TP1-55", "TC-009") for r in url_rows), str([r["ref"] for r in url_rows]))
    kinds = {r["ref"]: (r["kind"], r["status"]) for r in url_rows}
    check_eq("K8: a /browse/ link on the tracker host becomes the ticket row (known host)",
             kinds.get("TP1-8384"), ("ticket", "not_fetched:not read yet"))
    check_eq("K8: a link on an UNKNOWN host is listed for the person, never fetched",
             kinds.get("https://other.example.test/wiki/PROJ-77/page"), ("url", "person"))
    check_eq("K8: a Windows local path is a local_path row", kinds.get("C:" + BS + "work" + BS + "TC-009.txt"),
             ("local_path", "not_fetched:local path mention"))
    more = {r["ref"]: r for r in refs({"mention:description":
            "https://gi.example.test/org-cdme/testproject1/-/merge_requests/77 https://github.com/some/repo/pull/5 "
            "https://figma.com/design/abc/x https://wiki.example.test/display/SPACE/Page https://gi.example.test/org-cdme/testproject1/-/issues/9"})}
    check_eq("K8: kinds come from the data table (GitLab MR, GitHub pull, Figma, Confluence, GitLab issue)",
             sorted((r["kind"], r["status"]) for r in more.values()),
             sorted([("merge_request", "not_fetched:not read yet"), ("pull_request", "person"), ("figma", "person"),
                     ("confluence", "person"), ("gitlab_issue", "not_fetched:not read yet")]))
    check_eq("K8: an MR URL carries its repo_id from the project path", more["https://gi.example.test/org-cdme/testproject1/-/merge_requests/77"].get("repo_id"), "testproject1-backend")

    # !NNN tying (C14)
    tied = lambda text: [(r["ref"], r.get("repo_id"), r.get("repo"), r.get("matched_token")) for r in refs({"mention:description": text}) if r["kind"] == "merge_request"]
    check_eq("C14: whole hyphen-word tokens - `testproject1-uix` is not the repo `testproject1-ui`", tied("in testproject1-uix MR !9"), [("!9", None, "unknown", None)])
    check_eq("C14: the SAME LINE wins over the paragraph", tied("testproject1\nfrontend testproject1-ui, MR !7"), [("!7", "testproject1-ui", None, "testproject1-ui")])
    check_eq("C14: two repos in one line -> `repo: ambiguous`", tied("frontend testproject1-ui and backend testproject1: MR !7"), [("!7", None, "ambiguous", None)])
    check_eq("C14: a different paragraph does not tie", tied("testproject1\n\nMR !7"), [("!7", None, "unknown", None)])
    check_eq("C14: the attached short form `testproject1-ui!1924`", tied("see testproject1-ui!1924 now"), [("!1924", "testproject1-ui", None, "testproject1-ui")])
    check_eq("C14: `!19245` is not `!1924` and `a!=b` is not an MR", tied("MR !19245 and x!=y in testproject1"), [("!19245", "testproject1-backend", None, "testproject1")])
    host, path = T.split_remote_identity("git@gi.example.test:org-cdme/testproject1.git")
    check_eq("C14: the scp-form remote_identity is split by the small splitter", (host, path), ("gi.example.test", "org-cdme/testproject1"))
    check_eq("C14: a URL remote and a Windows path", (T.split_remote_identity("https://gi.example.test/org-cdme/x.git"),
                                                      T.split_remote_identity("C:" + BS + "repo" + BS + "x"), T.split_remote_identity("")),
             (("gi.example.test", "org-cdme/x"), (None, None), (None, None)))
    check_eq("C14: known hosts are read from a bare host, a URL and an scp remote",
             [T.host_of(h) for h in ("jira.example.test", "https://jira.example.test/x", "git@gi.example.test:a/b.git")],
             ["jira.example.test", "jira.example.test", "gi.example.test"])
    # status rules
    comment_only = refs({"mention:comment:1": "MR !4214 in testproject1", "mention:description": "x"})
    check_eq("F18: an MR named only in comments is `person`", [r["status"] for r in comment_only if r["kind"] == "merge_request"], ["person"])
    both = refs({"mention:comment:1": "MR !4214 in testproject1", "mention:description": "MR !4214 in testproject1"})
    check_eq("F18 control: the same MR also named in the description is not comment-only",
             [r["status"] for r in both if r["kind"] == "merge_request"], ["not_fetched:not read yet"])
    check_eq("references: duplicates merge their origins, in order, once each",
             refs({"mention:summary": "TP1-14482 TP1-14482", "mention:description": "TP1-14482"})[0]["origins"],
             ["mention:summary", "mention:description"])
    check_eq("references: no text, no rows", refs({}), [])
    try:
        refs({"a": "x"}, reference_kinds={})
        got = "no refusal"
    except T.TableError as exc:
        got = str(exc)
    check("references: an empty reference-kinds table is refused, not read as 'no kinds'", "reference-kinds.json" in got, got)


def t287_remote_link_and_mention_are_one_row() -> None:
    """t-287 item 4: the comment's `testproject1-ui!1924` and the remote link (the 13797 shape: the merge request's URL
    on the tracker) are ONE row with both origins - with a repo known by its `remote_identity`, and with a repo known
    by its `local_path` only (the URL's repo name is matched against the repos' names when the full path does not)."""
    url = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"
    texts = {"mention:comment:15923998": "Draft MR testproject1-ui!1924 is for evaluation", "field:remotelink": url}
    local_only = [{"repo_id": "testproject1-backend", "local_path": "../../testproject1"}, {"repo_id": "testproject1-ui", "local_path": "../../testproject1-ui"}]
    same_path = [{"repo_id": "testproject1-backend", "local_path": "../../testproject1", "remote_identity": "git@git.example:tp1-group/testproject1.git"},
                 {"repo_id": "testproject1-ui", "local_path": "../../testproject1-ui", "remote_identity": "git@git.example:tp1-group/testproject1-ui.git"}]
    for label, repos in (("remote_identity with the same path", same_path), ("local_path only", local_only), ("remote_identity under another group", REPOS)):
        rows = [r for r in refs(texts, repos=repos, known_hosts=["https://jira.example.test"]) if r["kind"] == "merge_request"]
        check_eq(f"item 4 ({label}): ONE row, both origins in order (mention first, then the remote link), tied to testproject1-ui, listed for S1",
                 [(r.get("repo_id"), r["origins"], r["status"]) for r in rows],
                 [("testproject1-ui", ["mention:comment:15923998", "field:remotelink"], "not_fetched:not read yet")])
    # the same row from the URL form of the comment and the link: one, too
    rows = [r for r in refs({"mention:comment:1": url, "field:remotelink": url}, repos=local_only) if r["kind"] == "merge_request"]
    check_eq("item 4: the same URL in a comment and as a remote link is one row on a local_path-only config",
             [(r.get("repo_id"), r["origins"]) for r in rows], [("testproject1-ui", ["mention:comment:1", "field:remotelink"])])
    # nested groups: the LAST segment is the repo name; the case is folded
    nested = "https://git.example/a/b/Testproject1-UI/-/merge_requests/7"
    rows = [r for r in refs({"field:remotelink": nested}, repos=local_only) if r["kind"] == "merge_request"]
    check_eq("item 4: a nested group path ties by its last segment, case folded", [r.get("repo_id") for r in rows], ["testproject1-ui"])
    # --- negatives: the invariant is "never tie a merge request to a repository the text does not name" ---
    other = "https://git.example/tp1-group/other-tool/-/merge_requests/1924"
    rows = [r for r in refs({"mention:comment:15923998": "testproject1-ui!1924", "field:remotelink": other}, repos=local_only) if r["kind"] == "merge_request"]
    check_eq("item 4 negative: a link whose repo name matches no repo stays its OWN row (the mention keeps its own, tied to testproject1-ui)",
             sorted([(r.get("repo_id"), r["ref"] == other) for r in rows], key=str), sorted([("testproject1-ui", False), (None, True)], key=str))
    twins = [{"repo_id": "ui-a", "local_path": "a/testproject1-ui"}, {"repo_id": "ui-b", "local_path": "b/testproject1-ui"}]
    rows = [r for r in refs({"field:remotelink": url}, repos=twins) if r["kind"] == "merge_request"]
    check_eq("item 4 negative: two repos with that name -> the link is NOT tied to either (no guess), a row of its own",
             [(r.get("repo_id"), r["ref"]) for r in rows], [(None, url)])
    rows = [r for r in refs({"field:remotelink": url}, repos=[]) if r["kind"] == "merge_request"]
    check_eq("item 4 negative: no repos at all -> a row of its own, as before", [(r.get("repo_id"), r["ref"]) for r in rows], [(None, url)])
    # a repo name that only CONTAINS the link's name is not a match
    rows = [r for r in refs({"field:remotelink": "https://git.example/g/testproject1/-/merge_requests/3"},
                            repos=[{"repo_id": "testproject1-ui", "local_path": "../../testproject1-ui"}]) if r["kind"] == "merge_request"]
    check_eq("item 4 negative: `testproject1` is not `testproject1-ui` (whole names only)", [r.get("repo_id") for r in rows], [None])


def keys_of(text):
    return [m.group(1) for m in T.KEY_RE.finditer(text)]


def f11_f7() -> None:
    """t-282: F11 (no letter or digit glued to a key, either side), F7 (a path marker is matched on the path
    SUFFIX, so a tracker behind a context path is still a ticket link; the key shape has one source), and the
    one-row-per-key count of the URL-carries-the-key rule."""
    # --- F11: the key shape, eight inputs, each with the shape it must NOT be ---
    check_eq("K-F11: fooTP1-9 -> nothing (a letter glued in front)", keys_of("fooTP1-9"), [])
    check_eq("K-F11: TP1-9a -> nothing (a lowercase letter glued behind)", keys_of("TP1-9a"), [])
    check_eq("K-F11: MY_PROJ-12 is one whole key", keys_of("MY_PROJ-12"), ["MY_PROJ-12"])
    check_eq("K-F11: (TP1-9) -> TP1-9", keys_of("(TP1-9)"), ["TP1-9"])
    check_eq("K-F11: TP1-9. -> TP1-9", keys_of("see TP1-9."), ["TP1-9"])
    check_eq("K-F11: TP1-9, -> TP1-9", keys_of("TP1-9, and more"), ["TP1-9"])
    check_eq("K-F11: TP1-9 at the end of the text -> TP1-9", keys_of("blocked by TP1-9"), ["TP1-9"])
    check_eq("K-F11: TP1-9/TP1-10 -> both", keys_of("TP1-9/TP1-10"), ["TP1-9", "TP1-10"])
    check_eq("K-F11 controls: a digit run glued behind (TP1-12a), a digit glued in front (9TP1-12) and an underscore in front are not keys",
             (keys_of("TP1-12a"), keys_of("9TP1-12"), keys_of("x_TP1-12")), ([], [], []))
    check("K-F11: _STRICT_KEY_RE is still a whole-string shape of the same key (B-405: now the form's `^(?:...)$`)",
          T._STRICT_KEY_RE.pattern == r"^(?:[A-Z][A-Z0-9_]+-\d+)$")
    note = json.loads((harness.PLUGIN_ROOT / "references" / "jira-fields.json").read_text(encoding="utf-8"))["not_tracker_prefixes_note"]
    check_in("K-F11: the data file's note says no letter or digit is glued on either side", "no letter or digit glued on either side", note)

    # --- F7: the four links ---
    def link_rows(text, **kw):
        return refs({"mention:url": text}, **kw)

    context = by_ref(link_rows("https://jira.example.test/jira/browse/ABC-5"))
    check_eq("K-F7: a /jira/browse/ABC-5 link on the tracker host is a ticket row ABC-5, origin mention:url",
             (sorted(context), (context.get("ABC-5") or {}).get("kind"), (context.get("ABC-5") or {}).get("origins")),
             (["ABC-5"], "ticket", ["mention:url", "other_project"]))
    plain = by_ref(link_rows("https://jira.example.test/browse/ABC-5"))
    check_eq("K-F7: /browse/ABC-5 (no context path) is the same row, unchanged", plain, context)
    wrong = link_rows("https://jira.example.test/browsers/ABC-5")
    check_eq("K-F7 negative: /browsers/ABC-5 is kind url and yields no key",
             [(r["kind"], r["ref"]) for r in wrong], [("url", "https://jira.example.test/browsers/ABC-5")])
    no_key = link_rows("https://jira.example.test/jira/browse/")
    check_eq("K-F7 negative: /jira/browse/ with no key is kind url", [(r["kind"], r["ref"]) for r in no_key],
             [("url", "https://jira.example.test/jira/browse/")])
    glued = link_rows("https://jira.example.test/jira/browse/ABC-5a")
    check_eq("K-F7 negative: a key with a letter glued behind it in the link is not a ticket row",
             [r["kind"] for r in glued], ["url"])
    behind = link_rows("https://wiki.example.test/confluence/display/SPACE/Page https://wiki.example.test/site/pages/viewpage.action?pageId=1")
    check_eq("K-F7: the Confluence markers are suffix rules too (a context path before /display/ and /pages/)",
             sorted(r["kind"] for r in behind), ["confluence", "confluence"])
    check_eq("K-F7 control: a merge-request rule that CAPTURES the project path stays anchored (the repo is found)",
             by_ref(link_rows("https://gi.example.test/org-cdme/testproject1/-/merge_requests/77"))[
                 "https://gi.example.test/org-cdme/testproject1/-/merge_requests/77"].get("repo_id"), "testproject1-backend")
    # the old shape is refused, naming the kind and the key, with the way out
    for old in ("^/browse/", "^/display/", "^/pages/"):
        table = {"kinds": [{"kind": "ticket" if "browse" in old else "confluence", "hosts": [], "path_regexes": [old]}]}
        try:
            T.check_reference_kinds(table, "kinds.json")
            got = "no refusal"
        except T.TableError as exc:
            got = str(exc)
        check(f"K-F7: check_reference_kinds refuses {old!r}, naming the key and kind and the suffix form",
              "`path_regexes`" in got and old in got and "(?:^|/)" in got and "kinds.json" in got, got)
    try:
        T.check_reference_kinds({"kinds": [{"kind": "ticket", "hosts": [], "path_regexes": ["(?:^|/)browse/([A-Z]+-[0-9]+)"]}]})
        got = "no refusal"
    except T.TableError as exc:
        got = str(exc)
    check("K-F7: a ticket rule with a key group of its own (a second key literal) is refused", "KEY_RE" in got and "`ticket`" in got, got)
    for good in ("(?:^|/)browse/", "/wiki/spaces/"):
        T.check_reference_kinds({"kinds": [{"kind": "ticket", "hosts": [], "path_regexes": [good]}]})
    check("K-F7: the shipped table carries the three suffix rules and states the rule shape in its own note",
          all(any(rx == f"(?:^|/){word}/" for e in KINDS["kinds"] for rx in e["path_regexes"]) for word in ("browse", "display", "pages"))
          and "(?:^|/)<marker>/" in KINDS["note"] and "never `^/<marker>/`" in KINDS["note"], str(KINDS["kinds"][0]))
    # one source: the finder is built from the table's ticket rules + KEY_RE
    finder = T.ticket_url_regex(KINDS)
    check_eq("K-F7: ticket_url_regex is the table's marker + the one key shape (group 1 = the key)",
             [m.group(1) for m in finder.finditer("a https://h.example.test/jira/browse/ABC-5 b /browse/XY_Z-77, /browsers/NO-1 /jira/browse/")],
             ["ABC-5", "XY_Z-77"])
    custom = {"kinds": [{"kind": "ticket", "hosts": [], "path_regexes": ["(?:^|/)issue/"]}]}
    check_eq("K-F7: ... and a table that names another marker changes the finder (the marker is data, not code)",
             ([m.group(1) for m in T.ticket_url_regex(custom).finditer("/x/issue/ABC-5 /browse/ABC-6")]),
             ["ABC-5"])
    check_eq("K-F7: a custom ticket marker also changes the kind rule of references()",
             [(r["kind"], r["ref"]) for r in refs({"mention:url": "https://jira.example.test/issue/ABC-5 https://jira.example.test/browse/ABC-6"},
                                                  reference_kinds=custom)],
             [("ticket", "ABC-5"), ("url", "https://jira.example.test/browse/ABC-6")])
    try:
        T.ticket_url_regex({"kinds": [{"kind": "confluence", "hosts": [], "path_regexes": ["(?:^|/)display/"]}]})
        got = "no refusal"
    except T.TableError as exc:
        got = str(exc)
    check("K-F7: a table with no ticket kind is refused, not read as 'no ticket links'", "`ticket`" in got and "reference-kinds.json" in got, got)

    # --- (7): the URL row carries the key; one row per key per origin ---
    both = refs({"mention:url": "see https://jira.example.test/jira/browse/ABC-5 and again ABC-5, also (ABC-5)"})
    rows_of_key = [r for r in both if r.get("ref") == "ABC-5" or r.get("key") == "ABC-5"]
    check_eq("(7): the key named by a link and bare in the same text is ONE row, its origin once",
             (len(rows_of_key), rows_of_key[0]["origins"].count("mention:url")), (1, 1))
    foreign = refs({"mention:url": "https://other.example.test/browse/ABC-5 and ABC-5"})
    link = next(r for r in foreign if r["ref"].startswith("https://"))
    check_eq("(7): a ticket link on an unknown host is listed for the person and CARRIES its key",
             (link["kind"], link["status"], link.get("key")), ("ticket", "person", "ABC-5"))
    check("(7): ... a link on a KNOWN host has no `key` field (its row is the key itself)", "key" not in context["ABC-5"])


GITHUB = {"adapters": {"ticket": {"name": "github"}}}


def b405_forms() -> None:
    """B-405: the key shape is the project's (`adapter_forms`), and `classify_url` is the one reader of what a link
    is. Default behaviour is byte-identical; a prefix-less form (bare numbers) reads only its mentions, probes no
    prefix and tags no other project."""
    default = AF.key_form(None)
    check("B-405: KEY_RE IS the default form's compiled link_key, and the strict one IS its strict",
          T.KEY_RE is default.link_key and T._STRICT_KEY_RE is default.strict)
    check_eq("B-405: the Jira pattern of KEY_RE is byte-identical to the literal it replaced",
             T.KEY_RE.pattern, r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]+-\d+)(?![A-Za-z0-9])")
    check_eq("B-405: a trailing newline or a space is not part of a key (fullmatch)",
             [bool(T._STRICT_KEY_RE.fullmatch(v)) for v in ("PROJ-1", "PROJ-1\n", " PROJ-1")], [True, False, False])

    # prefix-less references: the mentions only, no prefix to know, no other project, no probe
    form = AF.key_form(GITHUB)
    rows = by_ref(refs({"mention:description": "Fixes #12 and Ticket: 7, see repo#5 and &#123; and #12a, bare 456, "
                                               "TP1-9 is no key here"},
                       key_form=form, own_key="99", known_prefixes=set()))
    check_eq("B-405 prefix-less: only the mentions are tickets (#12, Ticket: 7); a bare number and a Jira-shaped word are not",
             sorted(rows), ["12", "7"])
    check_eq("B-405 prefix-less: a row has no prefix to probe (prefix_known True) and is never tagged other_project",
             sorted((r["prefix_known"], "other_project" in r["origins"]) for r in rows.values()),
             [(True, False)] * 2)
    check_eq("B-405 prefix-less: no per-prefix probe is ever asked for", T.prefixes_to_probe(list(rows.values())), [])
    check_eq("B-405 prefix-less: the story's own key is not a row", sorted(by_ref(refs(
        {"mention:description": "Ticket: 99 and #12"}, key_form=form, own_key="99", known_prefixes=set()))), ["12"])
    seeded = {r["ref"]: r["kind"] for r in refs({}, key_form=form, own_key="99", known_prefixes=set(),
                                                seeded=[{"ref": "7", "origins": ["field:parent"]},
                                                        {"ref": "PROJ-5", "origins": ["field:parent"]}])}
    check_eq("B-405 prefix-less: a seeded numeric parent is a ticket row, a Jira-shaped seed is not a key of this form",
             seeded, {"7": "ticket", "PROJ-5": "url"})
    ado = AF.key_form({"adapters": {"ticket": {"name": "ado"}}})
    check_eq("B-405 ado: `AB#123` and `#124` are tickets, `rAB#125` is not",
             sorted(by_ref(refs({"mention:description": "AB#123 and #124 and rAB#125"}, key_form=ado, own_key="1",
                                known_prefixes=set()))), ["123", "124"])
    check_eq("B-405 default: a project with no key form behaves as before (TP1-14482 still a ticket of a known prefix)",
             [(r["ref"], r["prefix_known"]) for r in refs({"mention:description": "see TP1-14482"})],
             [("TP1-14482", True)])
    check_eq("B-405 default: the Jira form is also what an explicit Jira form gives",
             refs({"mention:description": "see TP1-14482 and TC-001"}),
             refs({"mention:description": "see TP1-14482 and TC-001"}, key_form=AF.key_form({})))

    # classify_url: one reader of what a link is; every error direction is toward "not a request"
    kind, host, found = T.classify_url("https://githost.example.test/g/p/-/merge_requests/5")
    check_eq("B-405 classify_url: a merge request, host, number is group 2", (kind, host, found.group(2)),
             ("merge_request", "githost.example.test", "5"))
    kind, _host, found = T.classify_url("https://g.example.test/g/p/-/merge_requests/5/diffs")
    check_eq("B-405 classify_url: /-/merge_requests/5/diffs is request 5, and the character after the number is `/`",
             (kind, found.group(2), found.string[found.end(2)]), ("merge_request", "5", "/"))
    check_eq("B-405 classify_url: the path in a QUERY is no merge request (the old whole-URL search collected it)",
             T.classify_url("https://g.example.test/login?next=/g/p/-/merge_requests/5")[0], "url")
    check_eq("B-405 classify_url: the fragment is no path either",
             T.classify_url("https://g.example.test/login#/g/p/-/merge_requests/5")[0], "url")
    check_eq("B-405 classify_url: a markdown-escaped link is not normalised here (the caller does), so it is no request",
             T.classify_url("https://g.example.test/g/p/-/merge" + BS + "_requests/5")[0], "url")
    check_eq("B-405 classify_url: a user:password in the authority does not hide the host",
             T.classify_url("https://user:pw@g.example.test/g/p/-/merge_requests/5")[:2], ("merge_request", "g.example.test"))
    check_eq("B-405 classify_url: an unparseable link is kind url, never a raise",
             [T.classify_url(u)[0] for u in ("http://", "http://[", "", None)], ["url"] * 4)
    check_eq("B-405 classify_url: github.com/o/r/pull/5 is a pull request; the same path on another host, and a Bitbucket "
             "/pull-requests/5, are not (the table's hosts decide)",
             [T.classify_url(u)[0] for u in ("https://github.com/o/r/pull/5", "https://ghe.example.test/o/r/pull/5",
                                              "https://bitbucket.example.test/o/r/pull-requests/5")],
             ["pull_request", "url", "url"])
    check_eq("B-405 classify_url: the kinds a caller already compiled are used as given",
             T.classify_url("https://g.example.test/g/p/-/issues/5", T._compile_kinds(KINDS))[0], "gitlab_issue")


def battery() -> None:
    """Magnitude, nesting, encoding, empty and broken input: the module reads text nobody vetted."""
    deep = {"type": "text", "text": "leaf"}
    for _ in range(3000):
        deep = {"type": "bulletList", "content": [{"type": "listItem", "content": [deep]}]}
    flat = T.flatten_adf(adf_doc(deep))
    check("battery: an ADF document nested 3000 deep neither crashes nor loses its text", isinstance(flat, str) and "leaf" in flat)
    nested = adf_doc(adf_h(2, "Acceptance Criteria"), {"type": "bulletList", "content": [
        {"type": "listItem", "content": [adf_p("outer"), adf_list("bulletList", "inner one", "inner two")]}]})
    check_eq("battery: nested ADF lists flatten with indentation and every level becomes an item",
             ac(nested), ["outer", "inner one", "inner two"])
    big = "filler line with some words\n" * 40000 + "AC\n1. last item"
    check_eq("battery: a 1 MB description is scanned to its last heading", ac(big), ["last item"])
    spaced = "AC\n1. x" + " " * 60000 + "y"
    check_eq("battery: a line with a 60,000-space run is one item (no quadratic backtracking)", len(ac(spaced)[0]), 60002)
    check_eq("battery: a 200,000-character line with no break is read once", ac("AC\n1. " + "w" * 200000)[0][:3], "www")
    lone = chr(0xD800)
    check("battery: a lone surrogate (broken UTF-16 in a JSON string) does not crash the size line",
          T.description_note(lone * 20000, limit_bytes=32768) is not None)
    check("battery: ... nor the own-words measure", T.own_words_share({"title": lone, "description": "d"})[0] > 0)
    check_eq("battery: a NUL byte and a BOM inside an item are kept", ac("AC\n1. a" + chr(0) + "b" + chr(0xFEFF)), ["a" + chr(0) + "b" + chr(0xFEFF)])
    check_eq("battery: non-text descriptions (None, a number, an empty ADF doc) are []", (ac(None), ac(7), ac(adf_doc())), ([], [], []))
    bare = T.project({"key": "X-1", "fields": {}}, fields_table=TABLE, config_custom_fields=[], acceptance_fields=[],
                     acceptance_headings=HEADINGS, section_names=SECTIONS)
    check_eq("battery: an issue with no fields projects to empty values, every SCHEMA_KEY present",
             (all(k in bare for k in T.SCHEMA_KEYS), bare["title"], bare["description"], bare["acceptance_criteria"], bare["comments"]),
             (True, "", "", [], []))
    for broken in (None, [], "text", {"key": "X-1", "fields": "no"}):
        try:
            T.project(broken, fields_table=TABLE, config_custom_fields=[], acceptance_fields=[],
                      acceptance_headings=HEADINGS, section_names=SECTIONS)
            got = "no refusal"
        except T.TableError as exc:
            got = str(exc)
        check(f"battery: a broken raw issue ({str(broken)[:12]!r}) is refused, with the expected shape named",
              "fields" in got and "issue" in got, got)
    messy = copy.deepcopy(RAW)
    messy["fields"]["comment"]["comments"] = [None, "x", {"id": 5, "body": None, "author": "not a dict"}]
    messy["fields"]["attachment"] = [None, {"id": "1"}]
    messy["fields"]["issuelinks"] = [None, {"type": None}, {"outwardIssue": {"key": "A-1"}}]
    out = light(messy)
    check("battery: malformed comments, attachments and links are skipped, not fatal",
          len(out["comments"]) == 1 and out["comments"][0]["id"] == 5 and out["links"]["issue_links"][0]["key"] == "A-1", str(out["comments"]))
    huge = "word " * 200000 + " TP1-1 !12 ~/x/y"
    check("battery: references over a 1 MB text complete and still find the key, the MR and the path",
          {"ticket", "merge_request", "local_path"} <= {r["kind"] for r in refs({"mention:description": huge})})
    check_eq("battery: references tolerate None and empty texts", refs({"a": None, "b": ""}), [])
    check_eq("battery: an escape-looking tail in a line view is kept (lenient unescape)",
             T.unescape_text("a" + BS + "q" + BS), "a" + BS + "q" + BS)


def t363_b4_one_basename_two_repositories() -> None:
    """t-363 B4 (B-256 c): `take_attached` (`testproject1-ui!1924`) used to take the FIRST repository of a basename silently,
    while the URL form leaves a link tied to none of two same-named repositories. One rule now: a name is a repository
    only when exactly ONE attached repository has it; two or more -> a row that says `ambiguous`, names every candidate
    by its path and the door (name the repository by its path, or by its URL)."""
    twin = [{"repo_id": "ui-main", "local_path": "../../testproject1-ui", "remote_identity": "git@gi.example.test:org-cdme/testproject1-ui.git"},
            {"repo_id": "ui-fork", "local_path": "../../fork/testproject1-ui", "remote_identity": "git@gi.example.test:other/testproject1-ui.git"},
            {"repo_id": "testproject1-backend", "local_path": "../../testproject1"}]
    text = {"mention:comment:1": "Draft MR testproject1-ui!1924 is for evaluation", "mention:description": "x"}
    rows = [r for r in refs(text, repos=twin) if r["kind"] == "merge_request"]
    check_eq("B4: two repositories with one basename: ONE row for !1924, ambiguous, tied to neither",
             [(r["ref"], r.get("repo"), r.get("repo_id"), r.get("matched_token")) for r in rows],
             [("!1924", "ambiguous", None, "testproject1-ui")])
    row = rows[0]
    check_eq("B4: the row names BOTH paths", row["candidates"], ["../../testproject1-ui", "../../fork/testproject1-ui"])
    check("B4: the refusal names both paths and the door",
          all(p in row["refusal"] for p in row["candidates"]) and row["refusal"].endswith("name the repository by its path or URL"),
          row["refusal"])
    check_eq("B4 (t-373 F6): the line is the one the brief prints, without the internal marker keys",
             (row["refusal"], "_candidate_ids" in row),
             ("two repositories carry this name: ../../testproject1-ui; ../../fork/testproject1-ui; name the repository by its path or URL", False))
    # a repository known only by its remote: its remote identity is the path that is named
    remote_only = [{"repo_id": "a", "remote_identity": "git@gi.example.test:one/testproject1-ui.git"},
                   {"repo_id": "b", "remote_identity": "git@gi.example.test:two/testproject1-ui.git"}]
    only = [r for r in refs(text, repos=remote_only) if r["kind"] == "merge_request"][0]
    check_eq("B4: repositories known by their remote only are named by it", only["candidates"],
             ["git@gi.example.test:one/testproject1-ui.git", "git@gi.example.test:two/testproject1-ui.git"])
    # three or more: the same refusal, naming all
    three = twin + [{"repo_id": "ui-third", "local_path": "../../third/testproject1-ui"}]
    many = [r for r in refs(text, repos=three) if r["kind"] == "merge_request"][0]
    check_eq("B4: three repositories of one basename: the same refusal names all three",
             (many["repo"], len(many["candidates"]), "../../third/testproject1-ui" in many["refusal"]), ("ambiguous", 3, True))
    # case: names are compared case-insensitively, so `Testproject1-UI` and `testproject1-ui` are ONE basename (two repositories)
    cased = [{"repo_id": "x", "local_path": "../../Testproject1-UI"}, {"repo_id": "y", "local_path": "../../testproject1-ui"}]
    check_eq("B4: basenames that differ only by case are one basename: ambiguous",
             [r.get("repo") for r in refs(text, repos=cased) if r["kind"] == "merge_request"], ["ambiguous"])
    # exactly one: taken, as before; the same repository listed twice is ONE repository
    one = [r for r in refs(text, repos=REPOS) if r["kind"] == "merge_request"][0]
    check_eq("B4 control: exactly one repository of the name is taken (unchanged)", (one.get("repo_id"), one.get("repo"), "candidates" in one),
             ("testproject1-ui", None, False))
    dup = [r for r in refs(text, repos=[REPOS[1], dict(REPOS[1])]) if r["kind"] == "merge_request"][0]
    check_eq("B4: one repository listed twice under one repo_id is one repository, taken", (dup.get("repo_id"), dup.get("repo")), ("testproject1-ui", None))
    none = [r for r in refs({"mention:description": "see nowhere-ui!7"}, repos=twin) if r["kind"] == "merge_request"][0]
    check_eq("B4 control: no repository of the name: unknown, as before", (none.get("repo"), "candidates" in none), ("unknown", False))
    # the URL form is the rule this one now matches: the same two repositories, the same name, a link tied to neither
    url = {"mention:description": "https://gi.example.test/third/testproject1-ui/-/merge_requests/1924"}
    linked = [r for r in refs(url, repos=twin) if r["kind"] == "merge_request"][0]
    check_eq("B4: the URL form leaves a link of a name two repositories share tied to neither (the rule the attached form now follows)",
             linked.get("repo_id"), None)
    # t-373 F4: the post-pass merges a bare mention into the ONE tied row of its number - never an ambiguous row into a row
    # OUTSIDE its candidates (the refusal would vanish and the mention be credited to a repository the text never named)
    away = twin + [{"repo_id": "z", "local_path": "../../other-repo"}]
    both = [r for r in refs({"mention:comment:1": "see testproject1-ui!1924", "mention:description": "and other-repo!1924"}, repos=away)
            if r["kind"] == "merge_request"]
    check_eq("B4 (t-373 F4, MERGE-AWAY): an ambiguous row is NOT merged into a tied row of another repository: the refusal stays",
             sorted(((r["ref"], r.get("repo_id"), r.get("repo")) for r in both), key=str),
             sorted([("!1924", None, "ambiguous"), ("!1924", "z", None)], key=str))
    inside = [r for r in refs({"mention:comment:1": "see testproject1-ui!1924",
                               "mention:description": "https://gi.example.test/org-cdme/testproject1-ui/-/merge_requests/1924"}, repos=twin)
              if r["kind"] == "merge_request"]
    check_eq("B4 (t-373 F4): ...but a tied row INSIDE its candidates takes it (one merge request is one row)",
             [(r.get("repo_id"), r.get("repo")) for r in inside], [("ui-main", None)])
    # t-373 F5: two ambiguous NAMES with one number are two rows, each with its own candidates
    four = twin[:2] + [{"repo_id": "be-a", "local_path": "../../a/testproject1"}, {"repo_id": "be-b", "local_path": "../../b/testproject1"}]
    names = [r for r in refs({"mention:description": "testproject1-ui!1924 and testproject1!1924"}, repos=four) if r["kind"] == "merge_request"]
    check_eq("B4 (t-373 F5): two ambiguous names with one MR number are two rows, neither loses its candidates",
             sorted((r["matched_token"], len(r["candidates"])) for r in names), [("testproject1", 2), ("testproject1-ui", 2)])


def g10_criteria_section_battery() -> None:
    """G1-0 (D-0050, I4): `criteria_section` is the ONE scanner of the criteria heading and `acceptance_criteria` returns its `items`.
    The expectations come from the requirement - a heading with text under it that read no items is a lost read (a section with
    content), an empty template is not (t-957 F-1/F-2) - never from what the scanner printed. Each row names the side it must land on."""
    heads, names = ["Acceptance Criteria", "What needs to be tested", "AC"], TABLE["section_names"]

    def scan(text, markup="wiki"):
        return T.criteria_section(text, headings=heads, section_names=names, markup=markup)

    def lost(text, markup="wiki"):                     # the direction I4 guards: a section with text and no items
        found = scan(text, markup)
        return bool(found["content_lines"]) and not found["items"]

    check_eq("a bold heading with a colon is found (H)", scan("h3. *Acceptance Criteria:*\n* a\n* b")["items"], ["a", "b"])
    check("F-1: heading, blank line, prose, blank, list -> a section WITH content and no items (the item loop stops at the prose)",
          lost("h3. Acceptance Criteria\n\nThe user can export.\n\n* item"))
    check("F-1: heading, prose at once, no blank -> content, no items", lost("h3. Acceptance Criteria\nThe user can export."))
    check("a table section (||Given||When||) -> content", lost("h3. Acceptance Criteria\n||Given||When||\n|a|b|"))
    check("a section of only `TBD` -> content (a false question on a common template, named: FR-12 forbids a phrase list)",
          lost("h3. Acceptance Criteria\nTBD"))
    check("a Jira template with an EMPTY section before the next heading -> no content (go on with a line)",
          scan("h3. Acceptance Criteria\n\nh3. Notes\nfoo")["content_lines"] == 0 and bool(scan("h3. Acceptance Criteria\n\nh3. Notes\nfoo")["heading"]))
    check("... and before a plain `section_names` line (`Notes`) too", scan("h3. Acceptance Criteria\n\nNotes\nfoo")["content_lines"] == 0)
    two = scan("h3. Acceptance Criteria\n\nh3. Other\n\nh3. Acceptance Criteria\nsome prose")
    check_eq("F-2: two criteria sections, the FIRST empty, the second with text -> BOTH are listed and the second is the lost one",
             ([s["content_lines"] for s in two["sections"]], two["content_lines"], two["first_line"]), ([0, 1], 1, "some prose"))
    check_eq("F-2: ... and the empty first one is not the answer when a later one has text", two["heading"], "h3. Acceptance Criteria")
    check("a heading of a SHALLOWER level ends the section: `h2.` after `h3. AC` -> empty",
          scan("h3. Acceptance Criteria\nh2. Next\nprose")["content_lines"] == 0)
    check("a DEEPER heading stays inside the section: `h4.` under `h3. AC` is content", scan("h3. Acceptance Criteria\nh4. Sub\nprose")["content_lines"] == 2)
    check("markdown: `## AC` + prose, then `## Comments` -> exactly the prose line", scan("## AC\nfoo\n\n## Comments\n- x", "markdown")["content_lines"] == 1)
    check_eq("a heading in another language is not found: NO section (the pass line names the headings looked for; a named residual)",
             scan("h3. Kriterien\n* a")["sections"], [])
    check_eq("`## AC` under WIKI is a nested list item, not a heading: no section (the markdown scan finds it - S0 scans both)",
             (scan("## AC\nfoo")["sections"], bool(scan("## AC\nfoo", "markdown")["sections"])), ([], True))
    check("a heading inside a {code} block is a section like any other here (a false stop at worst: the safe side, pre-existing, queued)",
          bool(scan("{code}\nh3. Acceptance Criteria\nx\n{code}")["sections"]))
    check_eq("no heading at all -> nothing found", (scan("just text")["heading"], scan("just text")["content_lines"], scan("just text")["sections"]), (None, 0, []))
    check_eq("an empty description -> nothing found", scan("")["sections"], [])
    # `items` byte-for-byte what `acceptance_criteria` has always returned: the same function over the same inputs
    for text in ("h3. Acceptance Criteria\n* a\n* b\n\nh3. Notes\n* c", "h3. Acceptance Criteria\n\nprose\n\n* x", "plain", "h3. AC\n# one\n# two"):
        check_eq(f"acceptance_criteria == criteria_section.items ({text[:24]!r})",
                 T.acceptance_criteria(text, headings=heads, section_names=names), scan(text)["items"])
    check_eq("the first occurrence's items are the ones returned (as before): a list only under the second -> []",
             T.acceptance_criteria("h3. AC\n\nh3. Acceptance Criteria\n* a", headings=heads, section_names=names), [])


def main() -> None:
    g10_criteria_section_battery()
    tables()
    k1()
    projection()
    k2()
    k14()
    k3()
    k7()
    k8()
    t287_remote_link_and_mention_are_one_row()
    t363_b4_one_basename_two_repositories()
    f11_f7()
    b405_forms()
    battery()
    finish("ticket_light")


if __name__ == "__main__":
    main()
