"""SS1-15 (t-545): a tracker the factory holds no client for is read by the ROLE through the route onboarding recorded.

General rules, no per-tracker code (the owner, 31.10.2026): the code only SHOWS the route and records the snapshot S0 made; it never
parses or runs the route (AR-2). What is proved, and the mutation each part kills (this file kills them unless another is named):
  reads_by_role ............ every input both ways: a Jira with a usable direct_api is False whatever else is recorded (`JIRA`, ` jira `,
                             method agent, a `cli` row), a Jira without one is True only with a route, any other kind is True
                             [mutation: only `kind` is read]
  tracker_route ............ first qualifying row, unavailable / empty ref / non-text skipped, write channels are no route (a word added to a COPY
                             of the table with no code change), a credential-like ref is withheld, 200/201 cut, the secret checked BEFORE the cut
                             [mutation: a literal list in code; the cut before the check; the limit changed]
  the main key ............. `kind: github` (and `linear`, an empty kind): collect --relation task records the S0 snapshot as the task source,
                             record-source the parent, review --record, source_inputs, validate_inventory, verify_inventory_files, the bundle;
                             a client stub that fails when called is never called, and `subprocess.run` is never called [mutation: the branch removed
                             or put after require_direct_read; the route executed]
  refusals ................. a snapshot of another key and no snapshot are exit 3 (the inventory is not created); peek and another relation are exit 3
                             naming record-source; a Jira with a broken direct_api and no route keeps today's refusal [mutation: the key check removed]
  readiness / guard ........ `unknown` + `route: role` for a recorded route, the earlier verdicts for the rest; the guard lets `route: role` through and
                             refuses everything else, an old readiness.json included [mutation: the guard reads only `status`]
  the scout's brief ........ Driver.role_lines in every world of t-545 section 4; a Jira with a client gets no new line (and keeps "read through
                             collect/peek"); the Ticket source line; the S0 ticket_read question names the route in its answer block only
                             [mutation: the call removed (the file of that node: test_story_run_words.py is not in this node's owns)]
  the rules ................ TRACKER_RULES <= 900 bytes (900 passes, 901 does not), each line is in s1.md word for word, qa-scout.md did not grow, no
                             tracker name in the branch code (with a positive control of the same call)
Runnable on its own: `python -B scripts/tests/test_tracker_route.py`."""
import contextlib
import copy
import inspect
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import config_contract as CC  # noqa: E402
import source_inventory as SI  # noqa: E402
import ticket_adapter as TA  # noqa: E402

VALID_API = {"base_url": "https://jira.example.com", "auth_type": "bearer", "secret_ref": "JIRA_TOKEN"}
ROUTE = {"source_id": "gh", "kind": "tracker", "locator": "https://git.example.com/o/r/issues", "status": "verified",
         "method": "cli", "invoke_or_command_ref": "gh issue view {key} --comments"}
KEY = "PROJ-9"
SNAPSHOT = {"key": KEY, "type": "story", "title": "Add to cart", "description": "A reader adds a book to the cart.",
            "acceptance_criteria": [], "comments": [{"author": "a", "body": "see the price rules"}]}


def cfg_of(kind="github", direct_api=None, rows=None, **adapter) -> dict:
    ticket = dict({"kind": kind} if kind is not None else {}, **adapter)
    if direct_api is not None:
        ticket["direct_api"] = direct_api
    out = {"adapters": {"ticket": ticket}}
    if rows is not None:
        out["requirements_sources"] = rows
    return out


def row(**fields) -> dict:
    out = dict(ROUTE)
    out.update(fields)
    return {k: v for k, v in out.items() if v is not None}


def with_table(table, fn):
    """Run `fn` with the kinds table read from a COPY (CC.REQUIREMENT_SOURCE_KINDS_PATH moved for the call)."""
    saved = CC.REQUIREMENT_SOURCE_KINDS_PATH
    folder = Path(tempfile.mkdtemp(prefix="qa-kinds-"))
    path = folder / "requirement-source-kinds.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    CC.REQUIREMENT_SOURCE_KINDS_PATH = path
    try:
        return fn()
    finally:
        CC.REQUIREMENT_SOURCE_KINDS_PATH = saved
        harness.cleanup(folder)


def table_copy(**more) -> dict:
    table = json.loads(SI_TABLE.read_text(encoding="utf-8"))
    table.update(more)
    return table


SI_TABLE = CC.REQUIREMENT_SOURCE_KINDS_PATH


def _raises(fn) -> str:
    """The text of the ValueError `fn` raises ('' when it raises none)."""
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return ""


# --- reads_by_role --------------------------------------------------------------------------------------------------------

def reads_by_role_table() -> None:
    check_eq("fixture: the valid direct_api is usable (the cases below stand on it)", TA.has_usable_direct_api({"direct_api": VALID_API}), True)
    cases = [
        ("jira + usable direct_api, no row", cfg_of("jira", VALID_API), False),
        ("`JIRA` + usable direct_api", cfg_of("JIRA", VALID_API), False),
        ("` jira ` + usable direct_api", cfg_of(" jira ", VALID_API), False),
        ("jira + usable direct_api + method agent", cfg_of("jira", VALID_API, method="agent", invoke="jira-assistant"), False),
        ("jira + usable direct_api + a `cli` row", cfg_of("jira", VALID_API, rows=[row()]), False),
        ("jira, no direct_api, no row (today's refusal)", cfg_of("jira"), False),
        ("jira, a stub direct_api, no row (today's refusal)", cfg_of("jira", {"custom_fields": [], "acceptance_headings": []}), False),
        ("jira, no direct_api, a route row", cfg_of("jira", rows=[row()]), True),
        ("jira, a stub direct_api, a route row", cfg_of("jira", {"custom_fields": []}, rows=[row()]), True),
        ("jira, no direct_api, a row `unavailable`", cfg_of("jira", rows=[row(status="unavailable")]), False),
        ("jira, no direct_api, a row naming an agent (a write channel)", cfg_of("jira", rows=[row(method="agent")]), False),
        ("jira, no direct_api, a row with no ref", cfg_of("jira", rows=[row(invoke_or_command_ref=None)]), False),
        ("github with a direct_api field (not this system's client)", cfg_of("github", VALID_API), True),
        ("github", cfg_of("github"), True),
        ("linear (in no table)", cfg_of("linear"), True),
        ("no kind at all", cfg_of(None), True),
        ("an empty adapters", {"adapters": {}}, True),
        ("no adapters key", {}, True),
        ("adapters.ticket is not an object", {"adapters": {"ticket": None}}, True),
        ("kind file", cfg_of("file", path="tickets"), True),
        ("config is not an object", None, True),
    ]
    for name, cfg, want in cases:
        check_eq(f"reads_by_role: {name} (mutation: only `kind` read)", TA.reads_by_role(cfg), want)


# --- tracker_route --------------------------------------------------------------------------------------------------------

def route_of(rows) -> dict | None:
    return SI.tracker_route({"requirements_sources": rows})


def tracker_route_inputs() -> None:
    got = route_of([row()])
    check_eq("tracker_route: a row with a ref is the route", (got or {}).get("method"), "cli")
    check_eq("tracker_route: the ref is shown whole under the limit", (got or {}).get("ref"), "gh issue view {key} --comments")
    check_eq("tracker_route: no rows, an empty list, a non-list, a non-object row: None",
             [route_of([]), SI.tracker_route({}), SI.tracker_route({"requirements_sources": "x"}), route_of(["x", 5, None])], [None] * 4)
    check_eq("tracker_route: the FIRST qualifying row leads, the others are ordinary rows",
             route_of([row(invoke_or_command_ref="first {key}"), row(invoke_or_command_ref="second {key}")])["ref"], "first {key}")
    check_eq("tracker_route: `unavailable`, no ref, a blank ref and a non-text ref are skipped to the next row",
             route_of([row(status="unavailable"), row(invoke_or_command_ref=None), row(invoke_or_command_ref="   "),
                       row(invoke_or_command_ref=7), row(invoke_or_command_ref="third {key}")])["ref"], "third {key}")
    check_eq("tracker_route: a row of another kind is no route", route_of([row(kind="wiki")]), None)
    check_eq("tracker_route: an unhashable kind does not crash", route_of([row(kind=["tracker"])]), None)
    check_eq("tracker_route: no method, a ref: a route (method empty)", (route_of([row(method=None)]) or {}).get("method"), "")
    check_eq("tracker_route: method 5 is read as no method, the route stands (the validator judges the form)",
             (route_of([row(method=5)]) or {}).get("method"), "")
    check_eq("tracker_route: status unknown with a ref: a route", (route_of([row(status="unknown")]) or {}).get("status"), "unknown")
    check_eq("tracker_route: whitespace in the ref is one space", route_of([row(invoke_or_command_ref="gh  issue\nview {key}")])["ref"], "gh issue view {key}")
    for word in ("agent", "Agent", " skill ", "MCP_TOOL", "mcp"):
        check_eq(f"tracker_route: method {word!r} is a write channel, no route", route_of([row(method=word)]), None)
    check_eq("not_read_routes: read from the table, by its ONE reader", CC.requirement_source_kinds()["not_read_routes"],
             ["agent", "skill", "mcp_tool", "mcp"])
    new = table_copy(not_read_routes=["agent", "browserbot"])
    check_eq("not_read_routes: a word added to a COPY of the table is a write channel with no code change (mutation: a literal in code)",
             with_table(new, lambda: route_of([row(method="Browserbot")])), None)
    check_eq("... and the shipped words are the table's only: `skill` is then a route", with_table(new, lambda: (route_of([row(method="skill")]) or {}).get("method")), "skill")
    # t-586 F-7 (AR-6): a table without the list is DAMAGED, never "an agent is a read route"
    nolist = {k: v for k, v in table_copy().items() if k != "not_read_routes"}
    check_eq("not_read_routes: a table without the list: no route for an agent row (mutation: absent read as [])",
             with_table(nolist, lambda: route_of([row(method="agent")])), None)
    check_eq("... and no route for a cli row either: the table is damaged", with_table(nolist, lambda: route_of([row()])), None)
    check_in("... and the reader names the file", "requirement-source-kinds.json", with_table(nolist, lambda: _raises(CC.requirement_source_kinds)))
    check_eq("not_read_routes: a non-text word is a damaged table", with_table(table_copy(not_read_routes=["agent", 5]), lambda: route_of([row()])), None)
    check_eq("not_read_routes: a damaged table: no route", with_table({"kinds": 5}, lambda: route_of([row()])), None)
    check_eq("pointer_ref_prefixes: read from the table", CC.requirement_source_kinds()["pointer_ref_prefixes"], ["adapters."])
    # t-586 F-6: an old `direct_api` row (template note, R11 config) points to a setting; it is no route
    pointer = row(method="direct_api", invoke_or_command_ref="adapters.ticket.direct_api")
    check_eq("pointer ref: the R11 row is no route", route_of([pointer]), None)
    check_eq("... in any case and with spaces", route_of([row(method="direct_api", invoke_or_command_ref="  Adapters.ticket.direct_api")]), None)
    check_eq("... a Jira with no direct_api keeps today's refusal (reads_by_role False; mutation: the prefix list removed)",
             TA.reads_by_role(cfg_of("jira", rows=[pointer])), False)
    check_eq("... a prefix is a prefix: `adapters` alone / a command naming adapters. later is a route",
             [(route_of([row(invoke_or_command_ref=text)]) or {}).get("ref") for text in ("adapters", "run adapters.x {key}")],
             ["adapters", "run adapters.x {key}"])
    hint = SI.tracker_route_lines(cfg_of("github", rows=[pointer]), by_role=True)[0]
    check_in("... the brief says the recorded route points to a setting", "points to a setting of the config", hint)
    new_prefix = table_copy(pointer_ref_prefixes=["settings:"])
    check_eq("... a prefix added to a COPY of the table is a pointer with no code change",
             with_table(new_prefix, lambda: route_of([row(invoke_or_command_ref="settings:x")])), None)


def route_limits() -> None:
    ref = "x" * 200
    check_eq("route ref: 200 characters stay whole (limit AT)", route_of([row(invoke_or_command_ref=ref)])["ref"], ref)
    got = route_of([row(invoke_or_command_ref=ref + "y")])["ref"]
    check_eq("route ref: 201 characters are cut to 200 and say so (limit BEYOND; mutation: the limit changed)", got, ref + SI.ROUTE_CUT)
    check_in("the cut says the whole is in config.json", "whole in config.json", got)
    for name, text in (("at the 200th character", "x" * 195 + "token=abc" + "y" * 10), ("beyond the 200th", "x" * 250 + "secret=abc"),
                       ("at the 190th", "x" * 190 + "password=abc"), ("key=", "run key=abc {key}")):
        cfg = cfg_of("github", rows=[row(invoke_or_command_ref=text)])
        shown = "\n".join(SI.tracker_route_lines(cfg, by_role=True) + SI.requirement_source_lines(cfg, local=False, by_role=True))
        check_eq(f"secret {name}: no route (mutation: the cut before the check)", SI.tracker_route(cfg), None)
        check_not_in(f"secret {name}: the value is never printed", "abc", shown)
        check_in(f"secret {name}: the line says the route is withheld", "route withheld: it holds a credential-like field", shown)


# --- the lines the scout is given -----------------------------------------------------------------------------------------

def route_lines() -> None:
    cfg = cfg_of("github", rows=[row()])
    lines = SI.tracker_route_lines(cfg, by_role=True)
    check_eq("tracker_route_lines: by_role False is []", SI.tracker_route_lines(cfg, by_role=False), [])
    check_eq("tracker_route_lines: the head, then the six rules", (len(lines), lines[1:]), (7, list(SI.TRACKER_RULES)))
    check_eq("tracker_route_lines: the head names the system, the method and the ref",
             lines[0], "Tracker: github, read by this route: cli: gh issue view {key} --comments. <KEY> stands for a key.")
    unknown = SI.tracker_route_lines(cfg_of("github", rows=[row(status="unknown")]), by_role=True)[0]
    check_in("a route not proven yet says: try it once", "Not proven yet: try it once.", unknown)
    check_not_in("a verified route does not say it", "Not proven yet", lines[0])
    nomethod = SI.tracker_route_lines(cfg_of("github", rows=[row(method=None)]), by_role=True)[0]
    check_in("no method: the ref alone follows the colon", "read by this route: gh issue view", nomethod)
    agent = SI.tracker_route_lines(cfg_of("github", rows=[row(method="agent")]), by_role=True)
    check_in("a write channel: the head says it is not a read route", "agent is not a read route (FR-50)", agent[0])
    check_in("... and the same world as no route (the door)", "no read route is recorded for this tracker", agent[0])
    check_eq("... and the six rules still stand", agent[1:], list(SI.TRACKER_RULES))
    none = SI.tracker_route_lines(cfg_of("github"), by_role=True)
    check_eq("no route, no command: the door to onboarding, the rules stand",
             (none[0], none[1:]), ("Tracker: github: no read route is recorded for this tracker: parents and links in the text are named gaps; "
                                   "/qa-factory:qa-onboarding records one", list(SI.TRACKER_RULES)))
    command = SI.tracker_route_lines(cfg_of("github", command="gh issue view {key} --json body", status="configured"), by_role=True)[0]
    check_eq("no route, a configured command: try it once", command,
             "Tracker: github: no route is recorded; adapters.ticket names github: try gh issue view {key} --json body once")
    check_in("a command not configured is not offered", "no read route is recorded",
             SI.tracker_route_lines(cfg_of("github", command="gh x {key}", status="detected"), by_role=True)[0])
    check_not_in("a command with a credential-like field is not offered", "abc",
                 SI.tracker_route_lines(cfg_of("github", command="curl x?token=abc", status="configured"), by_role=True)[0])
    check_in("no kind: the head says `unnamed`", "Tracker: unnamed:", SI.tracker_route_lines(cfg_of(None), by_role=True)[0])


def rows_lines() -> None:
    tracker_only = {"requirements_sources": [row()]}
    check_in("requirement_source_lines: a client reads it: the line says collect/peek (by_role False)",
             "read through collect/peek", SI.requirement_source_lines(tracker_only, local=False, by_role=False))
    check_eq("by_role False is today's output (the default)", SI.requirement_source_lines(tracker_only, local=False),
             SI.requirement_source_lines(tracker_only, local=False, by_role=False))
    check_eq("by_role True: the leading row is the route block's, and nothing else is left: no lines (mutation: by_role not passed)",
             SI.requirement_source_lines(tracker_only, local=False, by_role=True), [])
    second = {"requirements_sources": [row(), row(source_id="other", invoke_or_command_ref="b {key}"), dict(row(), source_id="wiki-1", kind="wiki",
                                                                                                          locator="https://w.example/q")]}
    got = SI.requirement_source_lines(second, local=False, by_role=True)
    check_not_in("by_role True: no row says `read through collect/peek` (the role reads it)", "read through collect/peek", got)
    check_in("by_role True: a second tracker row is not lost: the role-read line", "other: read it yourself if you can reach it", got)
    check_in("by_role True: the other kinds are unchanged", "wiki-1: read it yourself", got)
    check_not_in("by_role True: the leading row has no line of its own", "gh:", got)
    local = SI.requirement_source_lines(tracker_only, local=True, by_role=True)
    check_in("a story with no key keeps its `not queried` line", "gh (tracker): not queried:", local)


# --- the CLI, a project on disk ---------------------------------------------------------------------------------------------

class NoClient:
    """Every road to a tracker client raises: the role reads this tracker, the factory never does."""
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append(a)
        raise AssertionError("a tracker client was asked for")


class NoRun:
    """subprocess.run is the one way code could EXECUTE a recorded route: it must never be called."""
    def __init__(self):
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append(a)
        raise AssertionError("a recorded route was executed")


@contextlib.contextmanager
def no_client_no_run():
    stub, run = NoClient(), NoRun()
    names = ("traced_client", "get_ticket", "require_direct_read", "collect_jira_source", "peek_jira_source")
    saved = {name: getattr(TA, name) for name in names}
    saved_run = subprocess.run
    for name in names:
        setattr(TA, name, stub)
    subprocess.run = run
    try:
        yield SimpleNamespace(client=stub, run=run)
    finally:
        for name, value in saved.items():
            setattr(TA, name, value)
        subprocess.run = saved_run


def cli(root: Path, *args) -> SimpleNamespace:
    harness.use_project(root)
    out, err = io.StringIO(), io.StringIO()
    saved, code = sys.argv, 0
    sys.argv = ["ticket_adapter.py", *[str(a) for a in args]]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = TA.main()
    except SystemExit as exc:
        code = 0 if exc.code is None else (exc.code if isinstance(exc.code, int) else 1)
    finally:
        sys.argv = saved
    return SimpleNamespace(code=code if isinstance(code, int) else 0, out=out.getvalue(), err=err.getvalue())


def project(cfg: dict) -> tuple:
    root = harness.temp_project("qa-tracker-route-")
    path = root / "qa-factory" / "config.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    current.update(copy.deepcopy(cfg))
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    work = root / "qa-factory" / "artifacts" / KEY / "work"
    work.mkdir(parents=True)
    return root, work


def put_snapshot(work: Path, snapshot=None) -> Path:
    path = work / "ticket-snapshot.json"
    path.write_text(json.dumps(snapshot or SNAPSHOT, indent=2), encoding="utf-8")
    return path


def words(root: Path, text: str) -> str:
    path = root / "words.txt"
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def the_main_key() -> None:
    """kind: github / linear / no kind, a recorded route, the S0 snapshot of PROJ-9: the whole road with no client and nothing executed."""
    for label, kind in (("github", "github"), ("linear (in no table)", "linear"), ("no kind", None)):
        root, work = project(cfg_of(kind, rows=[row()]))
        try:
            inventory = work / "source-inventory.json"
            put_snapshot(work)
            with no_client_no_run() as stub:
                got = cli(root, "collect", KEY, "--output", inventory, "--relation", "task", "--summary")
                check_eq(f"{label}: collect --relation task records the S0 snapshot, exit 0 (mutation: the branch removed)", got.code, 0)
                data = json.loads(inventory.read_text(encoding="utf-8")) if inventory.is_file() else {"sources": []}
                item = (data["sources"] or [{}])[0]
                check_eq(f"{label}: ONE source, the task, read, a text source, required",
                         (len(data["sources"]), item.get("relation"), item.get("status"), item.get("text_source"), item.get("required")),
                         (1, "task", "read", True, True))
                check_eq(f"{label}: the source is named by the key", item.get("canonical_ref"), KEY)
                snapshot_file = work / item.get("snapshot_ref", "missing")
                check_eq(f"{label}: the recorded snapshot is the one S0 made (title, comment)",
                         [json.loads(snapshot_file.read_text(encoding="utf-8")).get(k) for k in ("title", "comments")] if snapshot_file.is_file() else None,
                         [SNAPSHOT["title"], SNAPSHOT["comments"]])
                if kind != "github":
                    check_eq(f"{label}: stubs never called", (stub.client.calls, stub.run.calls), ([], []))
                    continue
                parent = root / "parent.txt"
                parent.write_text("# The epic\nCart rules: the price shows two decimals.\n", encoding="utf-8")
                got = cli(root, "record-source", "--output", inventory, "--ref", "https://git.example.com/o/r/issues/1", "--file", parent,
                          "--relation", "parent")
                check_eq("github: record-source of the parent read by the route: exit 0", got.code, 0)
                got = cli(root, "review", "--output", inventory, "--record", "--words-file", words(root, "go on"))
                check_eq("github: review --record needs no tracker", got.code, 0)
                data = json.loads(inventory.read_text(encoding="utf-8"))
                check_eq("github: the task and the parent are in the inventory",
                         sorted((s["relation"], s["status"]) for s in data["sources"]), [("parent", "read"), ("task", "read")])
                check_eq("github: validate_inventory finds nothing", SI.validate_inventory(data), [])
                check_eq("github: verify_inventory_files: valid", SI.verify_inventory_files(work.parent, data)["valid"], True)
                check_eq("github: completeness does not block", SI.completeness(data)["gate_blocked"], False)
                from controller import Controller
                controller = Controller(work.parent)
                controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(work.parent)},
                                                "idempotency_key": "init"})
                inputs = controller.source_inputs()
                check_eq("github: Controller.source_inputs does not raise and does not block", inputs["source_completeness"]["gate_blocked"], False)
                import context_bundle
                manifest = {"ticket": KEY, "implementations": [{"repo_id": "app", "source_sha": "abc", "diff_path": "d.diff"}],
                            "changed_areas": ["src"], "existing_coverage": [{"test": "t.py"}], "constraints": [],
                            "requirement_sources": [], "coverage_search": [], "existing_test_candidates": [],
                            "unresolved_facts": [{"id": "PROJ-12: the route answered 404", "reason": "missing_evidence"}]}
                (work.parent / "d.diff").write_text("+x\n", encoding="utf-8")
                bundle = context_bundle.build(manifest, work.parent)
                check_eq("github: the bundle carries both texts in requirement_sources (task has no AC: no question about AC)",
                         sorted((s["relation"], s["status"]) for s in bundle["requirement_sources"]), [("parent", "read"), ("task", "read")])
                check_eq("a gap (rule 5) reaches the bundle as unresolved_facts (mutation: not read)",
                         bundle["unresolved_facts"], [{"id": "PROJ-12: the route answered 404", "reason": "missing_evidence"}])
                check_eq("github: the client was never asked for and the route was never executed", (stub.client.calls, stub.run.calls), ([], []))
        finally:
            harness.cleanup(root)


def the_refusals() -> None:
    root, work = project(cfg_of("github", rows=[row()]))
    try:
        inventory = work / "source-inventory.json"
        with no_client_no_run():
            got = cli(root, "collect", KEY, "--output", inventory, "--relation", "task")
            check_eq("no snapshot: exit 3", got.code, 3)
            # the driver's name is not spelled here: a literal of it is a source-pinning site the layer map (L8) must declare
            check_in("no snapshot: the sentence names the way (FR-1)", f"S0 holds no text of {KEY}: run ", got.err + got.out)
            check_in("... the driver and the text file", ", or give the text with --ticket-file", got.err + got.out)
            check_eq("no snapshot: the inventory is not created", inventory.exists(), False)
            put_snapshot(work, dict(SNAPSHOT, key="OTHER-1"))
            got = cli(root, "collect", KEY, "--output", inventory, "--relation", "task")
            check_eq("a snapshot of another key: exit 3 (mutation: the key check removed)", got.code, 3)
            check_in("... and the sentence names both keys", f"work/ticket-snapshot.json holds OTHER-1, not {KEY}: one story has one task source", got.err + got.out)
            check_eq("... the inventory is not created", inventory.exists(), False)
            put_snapshot(work, dict(SNAPSHOT, key=KEY.lower()))
            check_eq("a snapshot of the same key in other case is the key", cli(root, "collect", KEY, "--output", inventory, "--relation", "task").code, 0)
            for args in (("peek", KEY, "--output", inventory), ("collect", "PROJ-10", "--output", inventory, "--relation", "parent"),
                         ("collect", "PROJ-10", "--output", inventory, "--relation", "referenced")):
                got = cli(root, *args)
                text = got.err + got.out
                check_eq(f"{args[0]} {args[-1] if args[0] == 'collect' else ''}: exit 3 (mutation: `requires a Jira` back)", got.code, 3)
                check_in("... the sentence names record-source with the inventory and the relations (the door, FR-2)",
                         f"ticket_adapter.py record-source --output {inventory} --ref {args[1]} --file <file> --relation subject|parent|normative|referenced", text)
                check_not_in("... and no longer says a Jira is required", "requires a Jira", text)
    finally:
        harness.cleanup(root)
    # method agent with a snapshot: the task is recorded (a text), nothing is read; with no snapshot: exit 3
    root, work = project(cfg_of("github", rows=[row()], method="agent", invoke="gh-assistant"))
    try:
        with no_client_no_run() as stub:
            check_eq("method agent, no snapshot: no reading happens, exit 3", cli(root, "collect", KEY, "--output", work / "i.json", "--relation", "task").code, 3)
            put_snapshot(work)
            check_eq("method agent, a snapshot: the task is recorded; require_direct_read is not reached (mutation: the branch after it)",
                     cli(root, "collect", KEY, "--output", work / "i.json", "--relation", "task").code, 0)
            check_eq("... and no client was asked for", stub.client.calls, [])
    finally:
        harness.cleanup(root)
    # a Jira: with a usable direct_api and a `cli` row the CLIENT is asked (the route is never first); broken and no row: today's refusal
    root, work = project(cfg_of("jira", VALID_API, rows=[row()]))
    try:
        stub = NoClient()
        saved = TA.traced_client
        TA.traced_client = stub
        try:
            cli(root, "collect", KEY, "--output", work / "i.json", "--relation", "task")
        finally:
            TA.traced_client = saved
        check_eq("a Jira with a usable direct_api and a cli row: the client road is taken (mutation: the route first)", len(stub.calls), 1)
    finally:
        harness.cleanup(root)
    root, work = project(cfg_of("jira", {"custom_fields": []}))
    try:
        put_snapshot(work)
        got = cli(root, "collect", KEY, "--output", work / "i.json", "--relation", "task")
        check("a Jira with a broken direct_api and no row keeps today's refusal (not the text path; mutation: the row condition removed)",
              got.code != 0 and not (work / "i.json").exists(), f"{got.code} {got.err[:200]}")
        check_in("... and it names the missing fields", "requires base_url, explicit auth_type, secret_ref", got.err + got.out)
    finally:
        harness.cleanup(root)
    root, work = project(cfg_of("jira", {"custom_fields": []}, rows=[row()]))
    try:
        put_snapshot(work)
        check_eq("the same Jira WITH a recorded route: the task is recorded from the snapshot",
                 cli(root, "collect", KEY, "--output", work / "i.json", "--relation", "task").code, 0)
        check_eq("record-source --relation task is still refused (the pin of N2a)",
                 cli(root, "record-source", "--output", work / "i.json", "--ref", "docs/x.md", "--file", words(root, "y"), "--relation", "task").code, 2)
    finally:
        harness.cleanup(root)


# --- readiness and the guard ------------------------------------------------------------------------------------------------

def readiness_and_guard() -> None:
    import readiness
    import runtime_paths as RP
    import stage_guard
    root = harness.temp_project("qa-tracker-ready-")
    try:
        harness.use_project(root)
        def rate(cfg):
            return readiness.check_ticket_adapter(cfg, root)
        got = rate(cfg_of("github", rows=[row()]))
        check_eq("readiness: a recorded route is `unknown`, owner role, route role, never `ok` (mutation: ok)",
                 (got["status"], got["owner"], got.get("route")), (readiness.UNKNOWN, "role", "role"))
        check_eq("readiness: a route and a configured command: still the route", rate(cfg_of("github", rows=[row()], command="gh x {key}", status="configured"))["status"], readiness.UNKNOWN)
        check_eq("readiness: a configured command with no route: `ok` as before (the executable is found: python)",
                 rate(cfg_of("github", command=f"{Path(sys.executable).name} {{key}}", status="configured"))["status"] in (readiness.OK, readiness.MISSING), True)
        check_eq("readiness: no route, an MCP tool: the earlier verdict, no `route` field",
                 [rate(cfg_of("github", method="mcp_tool", mcp_tool="gh_get", status="configured")).get("route")], [None])
        check_eq("readiness: a write-channel row is no route: the earlier verdict, no `route` field",
                 rate(cfg_of("github", rows=[row(method="agent")], method="mcp_tool", mcp_tool="gh_get", status="configured")).get("route"), None)
        check_eq("readiness: a Jira with a usable direct_api and a row: the Jira check", rate(cfg_of("jira", VALID_API, rows=[row()])).get("route"), None)
        check_eq("readiness: no route, nothing configured: not configured, as before", rate(cfg_of("github"))["status"], readiness.NOT_CONFIGURED)
        (root / "tickets").mkdir(exist_ok=True)
        check_eq("readiness: the file adapter is `ok`", rate(cfg_of("file", path=str(root / "tickets")))["status"], readiness.OK)
        path = RP.readiness(root)
        path.parent.mkdir(parents=True, exist_ok=True)

        def guard(entry):
            path.write_text(json.dumps({"capabilities": {"ticket_adapter": entry}}), encoding="utf-8")
            return stage_guard.rule_tracker_route("PROJ-1", "qa-scout", "S1", {})
        check_eq("guard: `unknown` + route role is let through (mutation: reads only `status`)",
                 guard(readiness.cap(readiness.UNKNOWN, "role", "x", route="role")), None)
        check("guard: `unknown` with no route field is refused as before", bool(guard(readiness.cap(readiness.UNKNOWN, "orchestrator", "x"))))
        check("guard: an MCP tool route (session_route) is refused as before", bool(guard(readiness.session_route("github", "mcp_tool", "gh_get"))))
        check("guard: `not_configured` is refused", bool(guard(readiness.cap(readiness.NOT_CONFIGURED, "user", "x"))))
        check("guard: `not_configured` with route role is refused (only `unknown` + role)", bool(guard(readiness.cap(readiness.NOT_CONFIGURED, "user", "x", route="role"))))
        check_eq("guard: `ok` passes", guard(readiness.cap(readiness.OK, "factory", "x")), None)
        path.write_text(json.dumps({"capabilities": {"ticket_adapter": {"status": "unknown", "owner": "orchestrator", "note": "n"}}}), encoding="utf-8")
        check("guard: an old readiness.json (no route field) is refused with its door", "readiness.py --write" in (stage_guard.rule_tracker_route("PROJ-1", "qa-scout", "S1", {}) or ""))
    finally:
        harness.cleanup(root)


# --- the driver ------------------------------------------------------------------------------------------------------------

def the_scouts_brief() -> None:
    from story_run_common import driver_for, s0_project
    worlds = [
        ("github with a route", {"adapters": {"ticket": {"kind": "github"}}, "requirements_sources": [dict(ROUTE)]}),
        ("github with no route", {"adapters": {"ticket": {"kind": "github"}}, "requirements_sources": []}),
        ("a Jira with a broken direct_api and a route", {"adapters": {"ticket": {"kind": "jira", "direct_api": {"custom_fields": []}}},
                                                         "requirements_sources": [dict(ROUTE)]}),
        ("a Jira with a usable direct_api and a cli row", {"adapters": {"ticket": {"kind": "jira", "direct_api": VALID_API}},
                                                           "requirements_sources": [dict(ROUTE)]}),
        ("a Jira with a broken direct_api and no row", {"adapters": {"ticket": {"kind": "jira", "direct_api": {"custom_fields": []}}}}),
    ]
    got = {}
    for label, config in worlds:
        root, _task_root, env = s0_project("PROJ-1", config=config)
        try:
            harness.use_project(root)
            driver = driver_for(root, env, "PROJ-1")
            got[label] = driver.role_lines("S1", "qa-scout")
            if label == "github with a route":
                check_eq("role_lines: other roles get none of it", [l for l in driver.role_lines("S2", "qa-requirements-tester") if "Tracker" in l], [])
        finally:
            harness.cleanup(root)
    lines = got["github with a route"]
    check_in("role_lines: the Tracker head is in the brief (mutation: the call removed)", "Tracker: github, read by this route: cli: gh issue view {key} --comments.", lines)
    check_eq("role_lines: and the six rules, in the order", [l for l in lines if l in SI.TRACKER_RULES], list(SI.TRACKER_RULES))
    check_in("role_lines: the Ticket source line points at the route", "Ticket source: the project's tracker, by the route below; the task's text is the snapshot S0 made", lines)
    check_eq("role_lines: the tracker block follows the Ticket source line", lines[lines.index(next(l for l in lines if l.startswith("Ticket source:"))) + 1].startswith("Tracker:"), True)
    check_not_in("role_lines: no `read through collect/peek` when the role reads", "read through collect/peek", lines)
    check_in("no route (github): the head says so and names the door", "Tracker: github: no read route is recorded for this tracker", got["github with no route"])
    check_eq("no route (github): the six rules stand", [l for l in got["github with no route"] if l in SI.TRACKER_RULES], list(SI.TRACKER_RULES))
    check_in("a Jira, broken direct_api, a route: the role reads it", "Tracker: jira, read by this route: cli:", got["a Jira with a broken direct_api and a route"])
    for label in ("a Jira with a usable direct_api and a cli row", "a Jira with a broken direct_api and no row"):
        check_eq(f"{label}: no new line (a client reads it; mutation: the route first)",
                 [l for l in got[label] if l.startswith("Tracker:") or l in SI.TRACKER_RULES or l.startswith("Ticket source: the project")], [])
        check_in(f"{label}: the Ticket source line is today's", "Ticket source: the configured ticket adapter", got[label])
    check_in("a Jira with a usable direct_api and a cli row: the tracker row keeps `read through collect/peek`", "gh (tracker): read through collect/peek, as the ticket",
             got["a Jira with a usable direct_api and a cli row"])
    s0_question()


def s0_question() -> None:
    from story_run_common import driver_for, s0_project
    seen = {}
    for label, rows in (("with a route", [dict(ROUTE)]), ("without", [])):
        root, _task_root, env = s0_project("PROJ-1", config={"adapters": {"ticket": {"kind": "github"}}, "requirements_sources": rows})
        try:
            harness.use_project(root)
            driver = driver_for(root, env, "PROJ-1")
            captured = []
            driver.s0_stop = lambda *a, **k: captured.append((a, k))
            driver.s0_ticket_read_question(3, "no way to read", None)
            seen[label] = captured[0]
        finally:
            harness.cleanup(root)
    with_route, without = seen["with a route"], seen["without"]
    note = with_route[1].get("answer_note") or ""
    check_in("s0 ticket_read: the route stands in the answer block (mutation: the condition removed)",
             "The project's recorded route: cli, gh issue view {key} --comments. The conductor reads the ticket by it, saves the text and answers with the ticket file.", note)
    check_eq("s0 ticket_read: without a route the note is as before", without[1].get("answer_note"), "")
    check_eq("s0 ticket_read: the question, its answers and its key are the same (FR-7, FR-50)", with_route[0], without[0])
    check_not_in("s0 ticket_read: the route is not in the question body", "gh issue view", json.dumps(with_route[0], default=str))


# --- the rules --------------------------------------------------------------------------------------------------------------

def the_rules() -> None:
    block = "\n".join(SI.TRACKER_RULES).encode("utf-8")
    check_eq("TRACKER_RULES: the limit is 900 bytes", SI.TRACKER_RULES_LIMIT, 900)
    check(f"TRACKER_RULES: {len(block)} bytes, at most 900 (a rule added past 900 fails HERE, not in a run)", len(block) <= SI.TRACKER_RULES_LIMIT)
    check_eq("TRACKER_RULES: six lines", len(SI.TRACKER_RULES), 6)
    check_eq("the limit AT 900 passes and BEYOND (901) fails", [len(("x" * n).encode()) <= SI.TRACKER_RULES_LIMIT for n in (900, 901)], [True, False])
    check("TRACKER_RULES: English only (FR-30)", all(ord(c) < 128 for c in "".join(SI.TRACKER_RULES)))
    s1 = (harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s1.md").read_text(encoding="utf-8")
    for rule in SI.TRACKER_RULES:
        check_in(f"s1.md carries rule {rule[:2]} word for word (mutation: one rewritten)", rule, s1)
    check("qa-scout.md: the replaced sentence did not grow (A25)", len(("You read the tracker by the route your dispatch names (ticket_adapter.py with a client, else the recorded "
                                                                       "route and record-source); a route only the orchestrator holds is refused - never work around it.").encode()) <= 204)
    # no tracker is named in the code of the branch (AR-5), with a positive control of the SAME call
    names = re.compile(r"\b(github|gitlab|linear|youtrack|asana|trello|bitbucket)\b", re.IGNORECASE)
    code = "\n".join(inspect.getsource(f) for f in (TA.reads_by_role, TA._collect_by_role, TA._refuse_by_role, TA._record_task_source,
                                                    SI.tracker_route, SI.tracker_route_lines, SI._tracker_state))
    check_eq("control: the same search finds a tracker name in a sample", bool(names.search("if kind == 'GitHub':")), True)
    check_eq("no tracker is named in the code of the branch (mutation: a branch by name)", names.findall(code), [])
    kinds = json.loads(SI_TABLE.read_text(encoding="utf-8"))
    check_eq("requirement-source-kinds.json: the write channels are data", kinds.get("not_read_routes"), ["agent", "skill", "mcp_tool", "mcp"])


def left_out_on_the_role_route() -> None:
    """t-586 F-3 (FR-36, AR-24): a source the person left out before the run is not recorded by `record-source` either, by key or by link."""
    import source_exclusions as SE
    root, work = project(cfg_of("github", rows=[row()]))
    try:
        listing = "PROJ-5 - the old spec\nhttps://jira.example.com/browse/PROJ-6 - not this one\n"
        entries, problems = SE.parse_bytes(listing.encode("utf-8"), KEY)
        check_eq("fixture: the list reads clean", problems, [])
        SE.write_record(work.parent, entries, "list.txt", listing.encode("utf-8"))
        inventory = work / "source-inventory.json"
        text = work / "raw.txt"
        text.write_text("# the spec\nThe price shows two decimals.\n", encoding="utf-8")
        for ref in ("PROJ-5", "proj-5", "https://jira.example.com/browse/PROJ-6"):
            got = cli(root, "record-source", "--output", inventory, "--ref", ref, "--file", text, "--relation", "parent")
            check_eq(f"record-source --ref {ref}: refused (exit 2; mutation: the guard removed)", got.code, 2)
            check_in("... naming the person's word and the door (the handoff)", "asked before the run not to read", got.err)
            check_in("... with the handoff as the door", "say so in your handoff", got.err)
            check_eq("... and the inventory is not created", inventory.exists(), False)
        got = cli(root, "record-source", "--output", inventory, "--ref", "PROJ-7", "--file", text, "--relation", "parent")
        check_eq("another key is recorded (the guard is not a blanket)", got.code, 0)
        got = cli(root, "record-source", "--output", inventory, "--ref", "docs/spec.md", "--file", text, "--relation", "normative")
        check_eq("a path is recorded", got.code, 0)
    finally:
        harness.cleanup(root)


def task_record_counts() -> None:
    """t-586 F-4 (FR-41, AR-27): the task record counts what the SNAPSHOT holds; an attachment it names is a gap, never `read`."""
    folder = Path(tempfile.mkdtemp(prefix="qa-task-record-"))
    try:
        snapshot = dict(SNAPSHOT, comments=[{"author": "a", "body": "x"}, {"author": "b", "body": "y"}],
                        attachments=[{"id": "7", "filename": "price.png", "size": 10, "mimeType": "image/png"}])
        record = SI.record_text_source(folder / "inv-a.json", relation="task", ref=KEY, snapshot=snapshot, required=True)
        materials = record["materials"]
        check_eq("comments: the count is the snapshot's (mutation: a literal 0)", materials["comments"], {"status": "read", "count": 2})
        block = materials["attachments"]
        check_eq("attachments: counted, and not `read`", (block["count"], block["status"]), (1, "unavailable"))
        check_eq("... the row names the file and is a gap for S2",
                 [(r["filename"], r["status"], r["analysis_status"]) for r in block["items"]], [("price.png", "unavailable", "unavailable")])
        inventory = SI.load_inventory(folder / "inv-a.json")
        check_eq("... the inventory stays valid", SI.validate_inventory(inventory), [])
        completeness = SI.completeness(inventory)
        check_in("... and the completeness check opens a point for the attachment (it is no silent loss)", "attachment:7",
                 list(completeness["open_points"].values())[0])
        check_eq("... and the source is in unavailable_materials", len(completeness["unavailable_materials"]), 1)
        local = SI.record_text_source(folder / "inv-b.json", relation="task", ref="LOCAL-1",
                                      snapshot=SI.text_snapshot("LOCAL-1", "text"), required=True)
        check_eq("a local text has none: the counts stay 0, read",
                 (local["materials"]["comments"], local["materials"]["attachments"]),
                 ({"status": "read", "count": 0}, {"status": "read", "count": 0, "items": []}))
        odd = SI.record_text_source(folder / "inv-c.json", relation="task", ref=KEY,
                                    snapshot=dict(SNAPSHOT, comments="x", attachments=["y", 5]), required=True)
        check_eq("a damaged snapshot (non-lists, non-objects) counts 0 and does not raise",
                 (odd["materials"]["comments"]["count"], odd["materials"]["attachments"]["count"]), (0, 0))
    finally:
        harness.cleanup(folder)


def role_route_pairs_and_lines() -> None:
    """t-586 F-8 (the pair is intended), F-9 (one brief does not contradict itself), F-10 (ready commands)."""
    import readiness
    root = harness.temp_project("qa-tracker-pair-")
    try:
        harness.use_project(root)
        for label, cfg in (("a Jira with a partial direct_api and a route", cfg_of("jira", {"custom_fields": []}, rows=[row()])),
                           ("an empty kind with a route", cfg_of(None, rows=[row()]))):
            check_eq(f"F-8 {label}: the role reads it (CLI half; the text path)", TA.reads_by_role(cfg), True)
            check_eq(f"F-8 {label}: readiness refuses it - intended: the guard stops S1 with a door, the other direction is the unsafe one",
                     readiness.check_ticket_adapter(cfg, root)["status"], readiness.NOT_CONFIGURED)
    finally:
        harness.cleanup(root)
    # F-9a: no route -> the tracker row is not told twice
    cfg = cfg_of("github", rows=[row(invoke_or_command_ref=None)])
    got = SI.requirement_source_lines(cfg, local=False, by_role=True)
    check_not_in("F-9a: the tracker row with no route has no `read it yourself` line beside the head that says `gaps`", "read it yourself", got)
    check_in("... and the head says the gaps", "named gaps", SI.tracker_route_lines(cfg, by_role=True)[0])
    # F-9b: a second tracker row keeps ITS route
    second = cfg_of("github", rows=[row(), row(source_id="other", invoke_or_command_ref="glab issue view {key}")])
    check_in("F-9b: a second tracker row shows its own route", "other: read it yourself if you can reach it", SI.requirement_source_lines(second, local=False, by_role=True))
    check_in("... the route itself", "its route: glab issue view {key}", " ".join(SI.requirement_source_lines(second, local=False, by_role=True)))
    secret = cfg_of("github", rows=[row(), row(source_id="other", invoke_or_command_ref="curl x?token=abc")])
    check_not_in("... a secret in it is never printed", "abc", " ".join(SI.requirement_source_lines(secret, local=False, by_role=True)))
    # F-10a: the ready commands carry --output
    check_in("F-10a: rule 2 names --output", "collect <KEY> --relation task --output <INV>", " ".join(SI.TRACKER_RULES))
    check_in("F-10a: rule 3 names --output", "<parent|subject|normative|referenced> --output <INV>", " ".join(SI.TRACKER_RULES))
    # F-10b: a withheld or cut locator is a placeholder in `--ref`
    grep_rows = lambda locator: SI.requirement_source_lines({"requirements_sources": [dict(source_id="g", kind="repository", status="verified", locator=locator)]}, local=False)
    whole = " ".join(grep_rows("docs/specs"))
    check_in("F-10b: a whole locator is the ref", "--ref docs/specs --file", whole)
    withheld = " ".join(grep_rows("https://h.example/x?token=abc"))
    check_in("F-10b: a withheld locator is `<locator>`", "--ref <locator> --file", withheld)
    check_not_in("... and not the cut text", "--ref locator withheld", withheld)
    cut = " ".join(grep_rows("d/" + "x" * 250))
    check_in("F-10b: a cut locator is `<locator>`", "--ref <locator> --file", cut)
    # F-10c: a placeholder value is no secret in a ROUTE; a real value is
    for text, want in (("issue_key={key}", True), ("curl x?token=$JIRA_TOKEN", True), ("curl x?token=${JIRA_TOKEN}", True), ("curl x?token=abc", False),
                       ("a key={key}&token=abc", False), ("key=", False)):
        route = SI.tracker_route(cfg_of("github", rows=[row(invoke_or_command_ref=text)]))
        check_eq(f"F-10c route {text!r}: a route is {want} (mutation: SECRET_QUERY_RE whole)", route is not None, want)


def main():
    reads_by_role_table()
    tracker_route_inputs()
    route_limits()
    route_lines()
    rows_lines()
    the_main_key()
    the_refusals()
    readiness_and_guard()
    the_scouts_brief()
    the_rules()
    left_out_on_the_role_route()
    task_record_counts()
    role_route_pairs_and_lines()
    harness.finish("tracker route (SS1-15)")


if __name__ == "__main__":
    main()
