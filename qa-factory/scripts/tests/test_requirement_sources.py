"""OH3-39 (t-526 section 9, t-508 N4): `requirements_sources` has a producer (onboarding) and a reader (the scout's brief).

What is proved:
  * the table `references/requirement-source-kinds.json` is the ONE source of kinds, statuses and routes: `config_contract`
    reads it (`requirement_source_kinds`), the validator and the reader both call that, a kind added to a COPY of the table with
    `route: grep` is accepted and routed with no code change, a damaged table is an error naming the file (never "no kinds");
  * `source_inventory.requirement_source_lines(cfg, local=...)`: every row of the reader table, status before route, a
    credential-like locator never printed, the limits AT and BEYOND (20/21 sources, 200/201 characters), an empty list or an
    old config (no key) one line, a row that is not an object skipped by name;
  * the names `auth_type`, `secret_ref`, `username_ref` are variable NAMES (`bearer`, `API_TOKEN` pass; `abc def`, `a`, a number
    refused), optional when absent;
  * the reader reaches the scout: `Driver.role_lines("S1", "qa-scout")` carries the lines, `local` follows the story;
  * what a role records with `ticket_adapter.py record-source` reaches `requirement_sources` of the context bundle (AR-22);
  * the producer text (phases p1, p3, p4, the notes section, s1.md, qa-scout.md) says the sentences the roles are held to.

Mutations (each killed by this file): the literal kind list back in `validate` (`a kind of the table copy` check), a damaged table
read as an empty one (`damaged table` check), "not queried" replaced by "unavailable" (`local tracker` check), the line limit
changed (`20/21` check), the locator cut changed (`200/201` check), the name check removed (`names` check), the call removed from
`role_lines` (`role_lines` check; the file of this node, test_story_run_words.py is not in its owns), the secret check removed
(`secret` check).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import config_contract as CC  # noqa: E402
import source_inventory as SI  # noqa: E402

EMPTY = SI.NO_REQUIREMENT_SOURCES
TRACKER = {"source_id": "jira-x", "kind": "tracker", "locator": "https://jira.example/projects/X", "status": "verified"}
WIKI = {"source_id": "wiki-1", "kind": "wiki", "locator": "https://wiki.example/space/QA", "status": "verified"}
FILE = {"source_id": "spec-1", "kind": "file", "locator": "docs/openapi.yaml", "status": "verified"}
REPO = {"source_id": "repo-docs", "kind": "repository", "locator": "docs/", "status": "verified"}


def lines_of(rows, local=False) -> list:
    return SI.requirement_source_lines({"requirements_sources": rows}, local=local)


def errors_of(rows) -> list:
    return [e for e in CC.validate({"schema_version": 1, "requirements_sources": rows}) if "requirements_sources" in e]


def with_table(table, fn):
    """Run `fn` with the kinds table read from a COPY (`table`: a dict, a text, or None for no file)."""
    saved = CC.REQUIREMENT_SOURCE_KINDS_PATH
    folder = Path(tempfile.mkdtemp(prefix="qa-kinds-"))
    path = folder / "requirement-source-kinds.json"
    if table is not None:
        path.write_text(table if isinstance(table, str) else json.dumps(table), encoding="utf-8")
    CC.REQUIREMENT_SOURCE_KINDS_PATH = path
    try:
        return fn()
    finally:
        CC.REQUIREMENT_SOURCE_KINDS_PATH = saved


def the_table() -> None:
    table = CC.requirement_source_kinds()
    check_eq("the table: the five kinds", sorted(table["kinds"]), ["file", "other", "repository", "tracker", "wiki"])
    check_eq("the table: the routes", {k: v["route"] for k, v in table["kinds"].items()},
             {"tracker": "adapter", "wiki": "role", "repository": "grep", "file": "grep", "other": "role"})
    check_eq("the table: the statuses", table["statuses"], ["verified", "unavailable", "unknown"])
    check_eq("the validator takes every kind and status of the table", errors_of([dict(TRACKER), dict(WIKI), dict(FILE), dict(REPO)]), [])
    check("a kind outside the table is refused", any("kind is invalid" in e for e in errors_of([dict(WIKI, kind="sharepoint")])))
    check("a status outside the table is refused", any("status is invalid" in e for e in errors_of([dict(WIKI, status="maybe")])))
    check("a locator with a credential-like field is refused",
          any("credential-like" in e for e in errors_of([dict(WIKI, locator="https://w.example/p?token=abc")])))

    copy = {"schema_version": 1, "kinds": dict(table["kinds"], confluence={"route": "grep"}), "statuses": table["statuses"],
            "not_read_routes": table["not_read_routes"], "pointer_ref_prefixes": table["pointer_ref_prefixes"]}
    row = dict(WIKI, kind="confluence", source_id="conf-1", locator="docs/conf")
    check_eq("a kind of the table copy: the validator takes it (mutation: the literal kinds back in validate)",
             with_table(copy, lambda: errors_of([row])), [])
    got = with_table(copy, lambda: lines_of([row]))
    check("a kind of the table copy: routed by its `route: grep`, no code change", any("with Grep" in l and "conf-1" in l for l in got), str(got))
    check("the same kind without the copy is refused", any("kind is invalid" in e for e in errors_of([row])))

    expect = "requirement-source-kinds.json"
    for name, damaged in (("absent", None), ("not JSON", "{nope"), ("not an object", "[]"),
                          ("no kinds", json.dumps({"statuses": ["verified"]})),
                          ("kind without a route", json.dumps({"kinds": {"a": {}}, "statuses": ["verified"]})),
                          ("empty kinds", json.dumps({"kinds": {}, "statuses": ["verified"]}))):
        errs = with_table(damaged, lambda: errors_of([dict(WIKI)]))
        check(f"damaged table ({name}): an error naming the file, not an empty list of kinds", any(expect in e for e in errs), str(errs))
        try:
            with_table(damaged, CC.requirement_source_kinds)
            raised = False
        except ValueError as exc:
            raised = expect in str(exc)
        check(f"damaged table ({name}): the reader raises, naming the file", raised)
    damaged_lines = with_table("{nope", lambda: lines_of([dict(FILE)]))
    check("damaged table: the brief still goes out, the role reads the source itself (FR-59)",
          any("read it yourself" in l for l in damaged_lines), str(damaged_lines))
    check_eq("no `requirements_sources` and a damaged table: nothing to check, no error",
             with_table("{nope", lambda: [e for e in CC.validate({"schema_version": 1}) if "requirements_sources" in e]), [])


def the_reader_table() -> None:
    check_eq("no key: one line", SI.requirement_source_lines({}, local=False), [EMPTY])
    check_eq("an empty list: one line", lines_of([]), [EMPTY])
    check_eq("not a list: one line", lines_of("x"), [EMPTY])
    check_eq("not a config: one line", SI.requirement_source_lines(None, local=False), [EMPTY])
    check_in("the one line says the ticket and its links are the sources", "the ticket and its links are the sources", EMPTY)

    got = lines_of([TRACKER])
    check_eq("a tracker, verified, a story with a key: the heading and one line", got,
             ["Requirement sources:", "jira-x (tracker): read through collect/peek, as the ticket"])
    got = lines_of([TRACKER], local=True)
    check("local tracker: `not queried` (mutation: `unavailable`)", len(got) == 2 and "jira-x (tracker): not queried:" in got[1], str(got))
    check_in("local tracker: the reason to record", '"not queried: search needed"', got)
    check_not_in("local tracker: the word `unreachable` is only told as forbidden, never as the reason", "is unreachable", got)
    check_not_in("local tracker: not `unavailable`", "unavailable", got)

    got = lines_of([FILE])
    check_eq("a file: Grep and the record-source command",
             got[1], "spec-1: search docs/openapi.yaml for the story's words with Grep; what you read is recorded with "
                     "ticket_adapter.py record-source --ref docs/openapi.yaml --file <file> --relation normative; it reaches the "
                     "manifest from the inventory")
    check_eq("a repository: the same route", lines_of([REPO])[1].split(":")[0], "repo-docs")
    check_in("a repository: Grep", "with Grep", lines_of([REPO]))
    got = lines_of([WIKI])
    check_eq("a wiki: the role reads it itself", got[1],
             "wiki-1: read it yourself if you can reach it: https://wiki.example/space/QA; save what you read under work/raw/, "
             "record it with ticket_adapter.py record-source; otherwise record it as a gap with the reason")
    check_in("a kind outside the table: the role", "read it yourself", lines_of([dict(WIKI, kind="sharepoint")]))
    check_in("no kind at all: the role", "read it yourself", lines_of([{"source_id": "x", "locator": "y", "status": "verified"}]))

    check_eq("unavailable with evidence: the first of evidence_refs", lines_of([dict(WIKI, status="unavailable", evidence_refs=["probe.json:3", "b"])])[1],
             "wiki-1: unavailable: probe.json:3; a gap by default, not a question (D-0043)")
    check_in("unavailable without evidence_refs", "unavailable: no evidence recorded;", lines_of([dict(WIKI, status="unavailable")]))
    check_in("unavailable with an empty evidence_refs", "unavailable: no evidence recorded;", lines_of([dict(WIKI, status="unavailable", evidence_refs=[])]))
    check_in("unavailable with evidence_refs of the wrong shape", "unavailable: no evidence recorded;",
             lines_of([dict(WIKI, status="unavailable", evidence_refs="probe.json")]))
    check_eq("unknown: not established", lines_of([dict(WIKI, status="unknown")])[1],
             "wiki-1: not established: try the route once; a failed probe is a gap with its reason")
    check_eq("status first: an unavailable tracker is not routed by its kind", lines_of([dict(TRACKER, status="unavailable")], local=True)[1][:20],
             "jira-x: unavailable:")
    check_in("status first: an unknown file is not searched", "not established", lines_of([dict(FILE, status="unknown")]))
    check_not_in("status first: an unknown file is not searched (no Grep)", "Grep", lines_of([dict(FILE, status="unknown")]))
    check_in("a status that is not a word of the table reads as not established", "not established", lines_of([dict(FILE, status="maybe")]))

    got = lines_of([WIKI, "text", 7, None, dict(FILE)])
    check_eq("a row that is not an object is skipped by position, the others stay",
             [got[2], got[3], got[4]], ["requirements_sources[1] is unreadable and was skipped"] * 1 +
             ["requirements_sources[2] is unreadable and was skipped", "requirements_sources[3] is unreadable and was skipped"])
    check_in("... and the file after them is read", "spec-1: search", got[5])


def secrets_are_not_printed() -> None:
    secret = "https://w.example/p?token=abc123"
    for kind in ("tracker", "wiki", "file"):
        got = lines_of([dict(WIKI, kind=kind, locator=secret)])
        check_not_in(f"secret ({kind}): the value is not printed (mutation: the check removed)", "abc123", got)
        if kind != "tracker":
            check_in(f"secret ({kind}): says the locator is withheld", "locator withheld: it holds a credential-like field", got)
    got = lines_of([dict(FILE, locator="docs/x?password=hunter2"), dict(WIKI, source_id="k", status="unavailable", evidence_refs=["a?secret=zzz"]),
                    dict(WIKI, source_id="id?key=ttt")])
    check_not_in("secret: neither a grep line, an evidence line nor an id prints a value", "hunter2", got)
    check_not_in("secret: evidence", "zzz", got)
    check_not_in("secret: id", "ttt", got)


def the_limits() -> None:
    def rows(n):
        return [dict(WIKI, source_id=f"w-{i}", locator=f"docs/{i}") for i in range(n)]
    for n, more in ((19, None), (20, None), (21, 1), (25, 5)):
        got = lines_of(rows(n))
        shown = [l for l in got[1:] if l.startswith("w-")]
        check_eq(f"20/21: {n} sources show {min(n, 20)}", len(shown), min(n, 20))
        tail = [l for l in got if l.startswith("and ")]
        check_eq(f"20/21: {n} sources: the rest is one line", tail, [f"and {more} more in config.json"] if more else [])
    check_not_in("21: the 21st source is not shown", "w-20:", lines_of(rows(21)))
    check_in("20: the 20th source is shown", "w-19:", lines_of(rows(20)))

    for n, kept in ((199, 199), (200, 200), (201, 200)):
        locator = "d" * n
        got = lines_of([dict(WIKI, locator=locator)])[1]
        check(f"200/201: a locator of {n} characters is shown with {kept} (mutation: the cut changed)",
              ("d" * kept + ";") in got and ("d" * (kept + 1)) not in got, got[:120])
    got = lines_of([dict(FILE, locator="p" * 201)])[1]
    check("201: the cut holds in the Grep line, and the command's `--ref` is a placeholder, never the cut text (t-586 F-10b)",
          got.count("p" * 200) == 1 and "p" * 201 not in got and "--ref <locator> --file" in got, got[:160])


def the_names() -> None:
    check_eq("names: `bearer` and `API_TOKEN` pass (m6)",
             errors_of([dict(TRACKER, auth_type="bearer", secret_ref="API_TOKEN", username_ref="JIRA_USER")]), [])
    check_eq("names: absent, None and empty are no name given", errors_of([dict(TRACKER, auth_type=None, secret_ref="", username_ref=None)]), [])
    for field in CC.REQUIREMENT_SOURCE_NAME_FIELDS:
        for bad in ("abc def", "a", "tok=1", "with-dash", 5, ["A"]):
            errs = errors_of([dict(TRACKER, **{field: bad})])
            check(f"names: {field}={bad!r} is refused (mutation: the check removed)", any(f"{field} must be a variable NAME" in e for e in errs), str(errs))
    # t-586 F-2: the route fields of a tracker row are text or absent; a secret in the ref is refused like the locator's
    check_eq("route fields: text, absent, None and empty pass",
             errors_of([dict(TRACKER, method="cli", invoke_or_command_ref="gh issue view {key}"), dict(TRACKER, method=None, invoke_or_command_ref=""),
                        dict(TRACKER)]), [])
    for field in ("method", "invoke_or_command_ref"):
        for bad in (5, ["a"], {"a": 1}, True):
            errs = errors_of([dict(TRACKER, **{field: bad})])
            check(f"route fields: {field}={bad!r} is refused (mutation: the type check removed)", any(f"{field} must be text" in e for e in errs), str(errs))
    for bad in ("curl x?token=abc", "run secret=abc", "x?password=p&a=1", "x?key=abc"):
        errs = errors_of([dict(TRACKER, invoke_or_command_ref=bad)])
        check(f"route ref {bad!r}: a credential-like field is refused (mutation: no check on the ref)",
              any("invoke_or_command_ref contains a credential-like query field" in e for e in errs), str(errs))
        check_not_in("... and the value is not in the error", "abc", " ".join(errs))
    check_eq("route ref: a placeholder value is no secret", errors_of([dict(TRACKER, invoke_or_command_ref="curl x?issue_key={key}&token=$JIRA_TOKEN")]), [])
    check_eq("an old config has no key: the default is []", CC.effective_config({"schema_version": 1}).get("requirements_sources"), [])
    check_eq("an old config validates as before", errors_of([]), [])


def the_template_and_notes() -> None:
    template = json.loads((harness.PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    sources = template.get("requirements_sources")
    check_eq("the template rows validate (a row `method` and `invoke_or_command_ref` stay valid)", errors_of(sources if isinstance(sources, list) else []), [])
    notes = json.loads((harness.PLUGIN_ROOT / "references" / "onboarding-notes.json").read_text(encoding="utf-8"))
    check_in("onboarding notes: the discovery section", "requirements_sources", notes["discovery_sections"])
    check_eq("onboarding notes: the section is named once", notes["discovery_sections"].count("requirements_sources"), 1)


def what_a_role_records_reaches_the_bundle() -> None:
    """record-source (the command the grep and role lines name) -> the inventory -> `requirement_sources` of the context bundle."""
    import context_bundle
    folder = Path(tempfile.mkdtemp(prefix="qa-reqsrc-"))
    try:
        work = folder / "work"
        work.mkdir()
        inventory = work / "source-inventory.json"
        text = folder / "found.txt"
        text.write_text("The price is shown with two decimals.\n", encoding="utf-8")
        run = subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "ticket_adapter.py"), "record-source", "--output", str(inventory),
                              "--ref", FILE["locator"], "--file", str(text), "--relation", "normative"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(folder), timeout=120)
        check_eq("record-source: exit 0", run.returncode, 0)
        manifest = {"ticket": "QA-1", "implementations": [{"repo_id": "app", "source_sha": "abc", "diff_path": "d.diff"}],
                    "changed_areas": ["src"], "existing_coverage": [{"test": "t.py"}], "constraints": [],
                    "requirement_sources": [], "coverage_search": [], "existing_test_candidates": []}
        (folder / "d.diff").write_text("+x\n", encoding="utf-8")
        bundle = context_bundle.build(manifest, folder)
        got = [(s["ref"], s["relation"], s["status"]) for s in bundle["requirement_sources"]]
        check_eq("the bundle holds the recorded source: ref, relation, status", got, [(FILE["locator"], "normative", "read")])
        line = lines_of([FILE])[1]
        check_in("and the grep line names that very command and relation", "record-source --ref docs/openapi.yaml --file <file> --relation normative", line)
        required = [s for s in json.loads(inventory.read_text(encoding="utf-8"))["sources"] if s.get("required")]
        check_eq("the record is not required: finding nothing is no gap", required, [])
    finally:
        harness.cleanup(folder)


def role_lines_carry_the_lines() -> None:
    from story_run_common import driver_for, s0_project
    import local_keys
    root, _task_root, env = s0_project("PROJ-1")
    try:
        harness.use_project(root)
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        # SS1-15: a client reads this tracker (a Jira with a usable direct_api), so the row says "read through collect/peek"
        cfg["adapters"] = {"ticket": {"kind": "jira", "direct_api": {"base_url": "https://jira.example.com", "auth_type": "bearer",
                                                                      "secret_ref": "JIRA_TOKEN"}}}
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        driver = driver_for(root, env, "PROJ-1")
        lines = driver.role_lines("S1", "qa-scout")
        check("role_lines: a config without the key gets the one line (old config, default [])", EMPTY in lines, str(lines))
        cfg["requirements_sources"] = [dict(TRACKER), dict(FILE)]
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        driver = driver_for(root, env, "PROJ-1")
        lines = driver.role_lines("S1", "qa-scout")
        check("role_lines: the scout is told the sources (mutation: the call removed)", "Requirement sources:" in lines, str(lines))
        check_in("role_lines: a story with a key reads the tracker source as the ticket", "jira-x (tracker): read through collect/peek", lines)
        check_in("role_lines: and the file by Grep", "spec-1: search docs/openapi.yaml", lines)
        check_eq("role_lines: other roles get none", [l for l in driver.role_lines("S2", "qa-requirements-tester") if "Requirement source" in l], [])
        key, _rel = local_keys.mint("A story text.\n", cfg, root)
        driver = driver_for(root, env, key)
        lines = driver.role_lines("S1", "qa-scout")
        check_in("role_lines: a local story: the tracker source is not queried", "jira-x (tracker): not queried:", lines)
        check_not_in("role_lines: ... and the tracker read line is gone", "read through collect/peek", lines)
    finally:
        harness.cleanup(root)


def main():
    the_table()
    the_reader_table()
    secrets_are_not_printed()
    the_limits()
    the_names()
    the_template_and_notes()
    what_a_role_records_reaches_the_bundle()
    role_lines_carry_the_lines()
    harness.finish("requirement sources (OH3-39)")


if __name__ == "__main__":
    main()
