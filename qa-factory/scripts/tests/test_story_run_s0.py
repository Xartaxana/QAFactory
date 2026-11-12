"""The S0 scenarios of the story runner (t-017 D1, B-155 piece 2 of the split of test_story_run.py).

S0 by code: the story's one ticket snapshot is `work/ticket-snapshot.json`, the adapter's stdout byte for
byte; a story in flight with only the old `.md` gets it once; and every stop S0 raises is a question with
doors the next entry READS - `go on` passes that block only and is written down, a stand's name or a kept
launch source corrects the launch, a pasted ticket becomes the ticket, and anything else comes back as a
question with a changed body - with no conductor call anywhere on the way. The stub `claude`, the temp-project
builders, the helpers and `run_scenarios` live in `story_run_common.py`.

t-267 / t-278 (D-06): the ticket is read by REST in a light form and never through the tracker agent. A fake Jira
on localhost (`FakeJira`) serves the TP1-15045 fixture to the real adapter in a real driver process; the keys
printed as `K5`, `K6`, `K11`, `K13` (and the person-vs-tracker line, F27) are the spec's own.
"""

import hashlib
import json
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    BOM,
    CUT,
    FIXTURE_TICKET,
    INCOMPLETE_TICKET,
    LOST_READ_TICKET,
    NOT_A_TICKET,
    OTHER_SCRIPT,
    driver_for,
    eq,
    rules_broken,
    s0_answer,
    s0_findings,
    s0_journal,
    s0_pipeline,
    s0_project,
    s0_question,
    s0_run,
    s0_state,
    seed,
    set_control,
    stub_calls,
    run_scenarios,
)


UNREAD_LEAD = "is not one of the answers this question takes, so nothing has moved yet."      # the ONE lead of an unread answer (G17)
# A conductor that gives no usable options (`ask_person` with none): the seam answers with the SITE's own question again (G2).
NO_USABLE = {"conductor": {"action": "ask_person", "question": "", "did": "no options"}}


def conductor_count(root: Path) -> int:
    """The conductor calls the stub saw: D-0041 - every unread `--answer` is exactly one."""
    return len([c for c in stub_calls(root) if c["kind"] == "conductor"])


def price_broken(text: str) -> list:
    """The options of a question's priced section that lack their three price lines (item 6), token or not: [] is clean."""
    import human_text
    return human_text.price_problems(text, None)


FIX = harness.FIXTURES / "ticket-15045"
RAW_15045 = (FIX / "raw-issue.json").read_bytes()
FIELDS_15045 = (FIX / "field.json").read_bytes()
KEY = "TP1-15045"
PERSON_TOKEN_ENV = {"QA_JIRA_EMAIL": "reader@example.invalid", "QA_JIRA_API_TOKEN": "test-only-token"}


class FakeJira:
    """A Jira on localhost for a REAL driver process: the first route whose text is in the request path answers
    (bytes = 200, an int = that status); every request path is logged. `routes` can be swapped between two
    runs (`serve`), which is how a tracker that was down comes back."""

    def __init__(self, routes=()):
        self.routes, self.log = list(routes), []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.log.append(self.path)
                for needle, answer in owner.routes:
                    if needle in self.path:
                        if isinstance(answer, int):
                            self.send_response(answer)
                            self.end_headers()
                            return
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(answer)
                        return
                self.send_response(500)
                self.end_headers()

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def serve(self, routes) -> None:
        self.routes = list(routes)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def direct_api(self, **extra) -> dict:
        return {"base_url": self.base_url, "api_version": "2", "auth_type": "basic_token",
                "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN",
                "acceptance_criteria_fields": [], "custom_fields": [], **extra}


def story_15045(*extra):
    """The routes of a healthy read of the TP1-15045 fixture: the issue with every field, the remote links, `/field`."""
    return [*extra, (f"/issue/{KEY}/remotelink", b"[]"), (f"/issue/{KEY}?fields=*all", RAW_15045), ("/rest/api/2/field", FIELDS_15045)]


def rest_project(jira: "FakeJira", task: str = KEY, *, git: bool = True, method: str = "agent", **adapter):
    """A project whose ticket is read by REST from `jira`, with `method: agent` (the WRITE channel, as on cmp2) beside
    the `direct_api`, and a probe receipt so that readiness finds the tracker proven: S0 can run to its end."""
    ticket_cfg = {"kind": "jira", "method": method, "invoke": "jira-assistant", "direct_api": jira.direct_api(), **adapter}
    root, task_root, env = s0_project(task, git=git, config={"adapters": {"ticket": ticket_cfg}})
    env.update(PERSON_TOKEN_ENV)
    receipt = root / "qa-factory" / "state" / "integrations" / "jira-direct-probe.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    direct = ticket_cfg["direct_api"]
    receipt.write_text(json.dumps({
        "status": "available", "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": direct["base_url"], "auth_type": direct["auth_type"], "secret_ref": direct["secret_ref"],
        "username_ref": direct["username_ref"], "api_version": direct["api_version"],
        "checks": [{"name": name, "status": "available"} for name in
                   ("authenticated_identity", "sample_issue", "paginated_comments", "attachment_original")]}), encoding="utf-8")
    return root, task_root, env


def snapshot_of(task_root: Path) -> dict:
    return json.loads((task_root / "work" / "ticket-snapshot.json").read_text(encoding="utf-8"))


# The S0 scenarios below are functions of their own so that the ones that only start driver
# processes (each a fresh temp project and a full S0 costs ~15 s of readiness probes) can run
# side by side; the three that build a Driver in this process (it changes the working directory)
# run one after another in the main thread. `s0_scenarios` is the runner.
def s0_snapshot() -> None:
    check_eq = eq  # this section always shows the run's output on a failed comparison

    # --- (a)(b)(c) one snapshot: JSON, byte for byte the adapter's stdout, hashed and briefed -------
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        out = s0_run(root, env, task)
        eq("D1(a) a fresh S0 by code exits 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        snapshot = task_root / "work" / "ticket-snapshot.json"
        check("D1(a) the snapshot is work/ticket-snapshot.json", snapshot.is_file())
        check("D1(a) and there is no markdown twin", not (task_root / "work" / "ticket-snapshot.md").exists())
        env_c = dict(env)
        adapter = harness.run_script("ticket_adapter.py", "get", task, "--json", cwd=root, env=env_c)
        check_eq("D1(a) the file holds the adapter's stdout, byte for byte",
                 snapshot.read_bytes(), adapter.stdout.encode("utf-8"))
        parsed = json.loads(snapshot.read_text(encoding="utf-8"))
        check_eq("D1(a) it parses whole, as one JSON object with the ticket in it",
                 (parsed["key"], len(parsed["acceptance_criteria"])), ("QA-1", 5))
        check("D1(a) and the adapter's stderr is not in it (a stderr line would fail the parse above)",
              snapshot.read_text(encoding="utf-8").rstrip().endswith("}"))
        controller = json.loads((task_root / "state" / "controller.json").read_text(encoding="utf-8"))
        check_eq("D1(b) the controller's source_revision is the sha256 of the .json",
                 controller.get("source_revision"), hashlib.sha256(snapshot.read_bytes()).hexdigest())
        brief = harness.run_script("brief_pack.py", "--task", task, "--stage", "S1", "--role", "qa-scout",
                                   "--dispatch", "S1-qa-scout-1", "--json", "--dry-run", cwd=root, env=env)
        check_eq("D1(c) the scout's brief builds", brief.returncode, 0, brief.stderr[-500:])
        markdown = json.loads(brief.stdout)["markdown"]
        check("D1(c) and lists work/ticket-snapshot.json with its size",
              re.search(r"work/ticket-snapshot\.json \(\d+(\.\d+)? (B|KB)\)", markdown) is not None, markdown[-900:])
        check_eq("no conductor or role was called by S0", stub_calls(root), [])
        check_eq("the launch is kept for a later entry", s0_state(task_root).get("launch"), {})
        check("a story with no list is today's story: no record is written and no list line is printed",
              not (task_root / "work" / "source-exclusions.json").exists()
              and "asked me not to read" not in out.stdout and "list of sources" not in out.stdout)
    finally:
        harness.cleanup(root)


def s0_incomplete_ticket() -> None:
    check_eq = eq
    task = "QA-1"

    # --- (f)(g)(m) an incomplete ticket: the person's word is read, not ignored --------------------
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(bad))
        check_eq("D1(f) an incomplete ticket asks the person: exit 3", out.returncode, 3, out.stdout[-800:])
        first = s0_question(task_root)
        check_in("D1(f) the question is of kind halt", "kind: halt", first)
        check_in("D1(f) K13 / D-0050: it names the problem as the FACTORY's reader failing on the section, not the ticket",
                 "this is the factory's reader failing on that section, not your ticket", first)
        check_in("D-0050: and quotes the section's first line, the heading as written",
                 "The operator can tag an item and filter the list by that tag.", first)
        check_in("D-0050: the heading found, in backticks", "a section named `## Acceptance criteria`", first)
        check_not_in("D1(f) F4: it asks nothing about comments or a parent (the old phrase check is retired)", "comments", first)
        check_not_in("t-957 F-4 / FR-2: `retry` is not offered (the reader is deterministic: the same text reads the same)", "`retry`", first)
        check_in("D1(f) with `go on` among the answers", "`go on`", first)
        check_in("D1(f) and `stop`", "`stop`", first)
        details = (task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8")
        check_in("K-F5: the factory's words beside the question name the headings looked for, verbatim, from the merged list (the table's)",
                 "I looked for a section named one of: Acceptance Criteria, What needs to be tested, AC.", details)
        check_not_in("D-0050: the question no longer says the requirements are 'built from the criteria'", "built from the criteria", first)
        check_eq("D1(f) the block is remembered", s0_state(task_root).get("s0_block"), "ticket_incomplete")
        check("D1(f) and no pipeline.json exists", not (task_root / "pipeline.json").exists())
        check_in("the factory's own words are beside the question", "What the check found", details)
        check_in("D-0050: a finding of the factory's own defect is filed the moment the stop is shown (once per story)",
                 "idempotency:s0-criteria-unread:QA-1", s0_findings(root))
        check_eq("the question obeys human-questions.md", rules_broken(first), [])

        # (g) is `s0_reask_battery` below: a question that takes no text is where a stray answer comes back
        # changed. THIS question takes the ticket as text (t-267 C9: any non-empty text), so what the person
        # types here that is not a door is a paste (`s0_pasted_ticket`) - the parser, not a phrase, decides.
        # (f) `go on`: the story goes on; the pass is written down everywhere it must be
        out = s0_answer(root, env, task, "go on")
        check_eq("D1(f) `go on` on a lost read: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-500:])
        pipeline = s0_pipeline(task_root)
        check("D1(f) pipeline.json is written", pipeline["stages"]["S0"]["status"] == "done")
        line = "S0: the criteria-reading check passed by the person's word: \"go on\""
        check_in("D1(f) with the warning line gate A shows", line, pipeline["warnings"])
        check_in("D1(f) and the finding in the person's words (FB row)",
                 "S0 ticket_incomplete passed by the person's word: go on", s0_findings(root))
        check_in("D1(f) filed as a local calibration finding", "local-calibration", s0_findings(root))
        check_in("D1(f) once per story and block", "idempotency:s0-pass:QA-1:ticket_incomplete", s0_findings(root))
        check("D1(f) the answer is a human_answer in the journal",
              any(e.get("event") == "human_answer" and "S0 ticket_incomplete: go on" in str(e.get("notes"))
                  for e in s0_journal(root)))
        check_eq("D1(f) ZERO conductor calls on the whole path", stub_calls(root), [])
        state = s0_state(task_root)
        check("D1(f) the stop's own keys are cleared once pipeline.json is written",
              not any(k in state for k in ("s0_block", "s0_ask", "s0_passes", "s0_answers"))
              and "S0" not in state.get("pending_words", {}))
        check_eq("D1(f) the launch stays, as it was given (the file was named on the first command line only)",
                 state.get("launch"), {"ticket_file": str(bad)})
        check("the snapshot is written, from the ticket the person passed", (task_root / "work" / "ticket-snapshot.json").is_file())
    finally:
        harness.cleanup(root)


def s0_two_passes() -> None:
    check_eq = eq
    task = "QA-1"

    # --- (k)(l) a `go on` belongs to ONE block; a BOM and quotes around it still read as `go on` ------
    root, task_root, env = s0_project(task, git=False)        # no git working tree: readiness stops too
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(bad))
        check_eq("(l) setup: the incomplete ticket asks first", s0_state(task_root).get("s0_block"), "ticket_incomplete")
        out = s0_answer(root, env, task, "go on")
        check_eq("D1(l) after `go on` for the ticket, readiness still asks: exit 3", out.returncode, 3, out.stdout[-800:])
        check_eq("D1(l) the block is readiness - the ticket's word did not pass it", s0_state(task_root).get("s0_block"), "readiness")
        check("D1(l) and nothing was written as a pipeline", not (task_root / "pipeline.json").exists())
        ready = s0_question(task_root)
        check_in("D1(l) it is a refusal-kind question", "kind: refusal", ready)
        check_in("D1(l) with its answers as priced option lines: `retry`", "(a) `retry` — fix what the report names, and I check again", ready)
        check_in("D1(l) and `go on`", "(b) `go on` — start the story anyway", ready)
        check_in("D1(l) and `stop`", "(c) `stop` — stop the story here; nothing runs", ready)
        check_eq("D1(l) every option has its three price lines", price_broken(ready), [])
        check_in("D1(l) the report is beside it, not in it", "vcs",
                 (task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8"))
        check_not_in("D1(l) not in the body", "THIS STORY CANNOT START", ready)
        check_eq("D1(l) the readiness question obeys human-questions.md", rules_broken(ready), [])
        # (the "new problem raises the ticket block again" step is gone with the phrase check, t-267 F4: the one
        # problem the check finds is "no acceptance criteria", so there is no wider set to pass)
        # (k) the second `go on`, with a BOM, quotes and a full stop, is its own pass
        out = s0_answer(root, env, task, BOM + '"Go on."')
        check_eq("D1(k) a `go on` with a BOM, quotes and a full stop is read: exit 0", out.returncode, 0,
                 out.stdout[-1200:] + out.stderr[-500:])
        pipeline = s0_pipeline(task_root)
        passes = [w for w in pipeline["warnings"] if "passed by the person's word" in w]
        check_eq("D1(k) one warning per block passed", len(passes), 2)
        check_in("D1(k) the readiness pass is its own line", "S0: the readiness check passed by the person's word", passes)
        findings = s0_findings(root)
        check_in("D1(k) the readiness pass has its own finding", "idempotency:s0-pass:QA-1:readiness", findings)
        check_in("D1(k) beside the ticket's", "idempotency:s0-pass:QA-1:ticket_incomplete", findings)
        check_eq("D1(k) no conductor at any point", stub_calls(root), [])
        journal = [e for e in s0_journal(root) if e.get("event") == "human_answer"]
        check_eq("D1(k) every answer is a human_answer", len(journal), 2)
    finally:
        harness.cleanup(root)


def s0_pasted_ticket() -> None:
    check_eq = eq
    task = "QA-1"

    # --- (j) a pasted ticket passes the incomplete block, verbatim --------------------------------
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        s0_run(root, env, task, "--ticket-file", str(bad))
        pasted = FIXTURE_TICKET.replace("Items can carry tags", "Items can carry tags (pasted)")
        out = s0_answer(root, env, task, pasted, "--ticket-file", str(bad))
        check_eq("D1(j) a pasted ticket passes the incomplete block: exit 0", out.returncode, 0, out.stdout[-1200:] + out.stderr[-500:])
        saved = task_root / "state" / "driver-tmp" / "ticket-QA-1.md"
        check_eq("D1(j) it was kept verbatim", saved.read_text(encoding="utf-8"), pasted.strip())
        snapshot = json.loads((task_root / "work" / "ticket-snapshot.json").read_text(encoding="utf-8"))
        check_eq("D1(j) and the snapshot is made from it, not from the file the flag named", snapshot["title"], "Items can carry tags (pasted)")
        check("D1(j) no pass was recorded - nothing was passed",
              not [w for w in s0_pipeline(task_root)["warnings"] if "passed by the person's word" in w])
        check_not_in("D1(j) and no finding", "s0-pass", s0_findings(root))
        check_eq("D1(j) no conductor", stub_calls(root), [])
        check_eq("K4: the paste is labelled `person_pasted` by the route, never by the text", snapshot["provenance"]["source"], "person_pasted")
    finally:
        harness.cleanup(root)

    # --- C9: any non-empty text is the ticket; the parser decides what it found ------------------------
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(bad))
        first = s0_question(task_root)
        typed = "# " + NOT_A_TICKET + "\n\n## Acceptance criteria\n\nNo criteria in what I typed."
        out = s0_answer(root, env, task, typed)
        check_eq("C9: words that are no door are taken as the pasted ticket: a criteria heading with prose under it reads no criteria, so exit 3",
                 out.returncode, 3, out.stdout[-800:])
        check_eq("C9: the paste was kept as typed", (task_root / "state" / "driver-tmp" / f"ticket-{task}.md").read_text(encoding="utf-8"), typed)
        again = s0_question(task_root)
        stored = "qa-factory/artifacts/QA-1/state/driver-tmp/ticket-QA-1.md"
        check_eq("C9: it is the ticket now: the same block asks again",
                 (s0_state(task_root).get("s0_block"), "ticket_incomplete" in s0_state(task_root).get("s0_block")), ("ticket_incomplete", True))
        # t-287 item 6: the question names the file actually read. The first one named the flag's file, this one names the
        # stored paste (what `retry` re-reads): the text CHANGED, so the "answered this exact question before" note is not
        # owed here (FR-7: it moves or comes back changed); it is owed on the next ask, whose text is this one's.
        check_eq("t-287 item 6: the first question names the file the flag gave, the second the stored paste - the file a retry reads",
                 (f"`{bad.name}`" in first, f"`{stored}`" in first, f"`{stored}`" in again, "incomplete-ticket" in again),
                 (True, False, True, False))
        check_not_in("C9: and nothing was read for a phrase", "mentions acceptance criteria", again)
        check_eq("K13: the re-asked question obeys human-questions.md", rules_broken(first) + rules_broken(again), [])
        out = s0_answer(root, env, task, "# " + NOT_A_TICKET + "\n\n## Acceptance criteria\n\nNo criteria in what I typed.\n\nStill nothing else.")
        third = s0_question(task_root)
        check_eq("C9 / FR-7: the third ask is the second one's text: the person's earlier answer is shown",
                 (out.returncode, s0_state(task_root).get("s0_block"), third.count("You have answered this exact question before")), (3, "ticket_incomplete", 1))
        check_eq("K13: and it obeys the rules", rules_broken(third), [])
    finally:
        harness.cleanup(root)


def s0_ticket_units() -> None:
    """The pieces of the S0 ticket route that need a Driver in this process: what is a pasted text (K6 negative), the
    one structural check (F4, F5), a snapshot already on disk (K11 temporal, F3's partial read), the tracker's door."""
    import contextlib
    import io
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}]})
    try:
        driver = driver_for(root, env, task)
        eq("C9: `go on`, `retry`, `not needed`, `stop`, a stand's name are no text; a title line is; white space is not",
           [driver.s0_is_text(w) for w in ("go on", " Retry. ", "`not needed`", "local", "# A title", "go on and fix it", "", "  \n",
                                           "stop", " `Stop.` ", "stop and fix it")],
           [False, False, False, False, True, True, False, False, False, False, True])
        # F4: a ticket with no title is refused, with what was expected and the way on (FR-1); one with a title and criteria passes in silence
        try:
            driver.s0_criteria({"key": task, "title": task, "acceptance_criteria": ["one"]}, "from the ticket file")
            check("F4: a ticket whose title is only its key is refused", False)
        except story_run.Person as person:
            # P05 (C1-3 F2 a): the `ticket_no_title` question with the paste door, never a Refusal that says "run the story again"
            eq("F4: the ticket with no title is the `ticket_no_title` question (halt, exit 3)", (person.kind, person.code, driver.state.get("s0_block")),
               ("halt", 3, "ticket_no_title"))
            check_in("F4: it names what is wrong and what is expected", "carries no title. The story needs a ticket with a title", person.text)
            check_not_in("F4: and puts no command to the person", "run the story again", person.text)
            check_not_in("F4: nor a flag", "--ticket-file", person.text)
            check_in("F4: the answers are priced, `stop` among them", "`stop`", person.text)
            eq("F4: its doors are `retry` and `stop`, and the paste", (sorted(driver.state["s0_ask"]["doors"]), driver.state["s0_ask"]["paste"]),
               (["retry", "stop"], True))
            driver.state.pop("s0_block", None)
            driver.state.pop("s0_ask", None)
        driver.s0_criteria({"key": task, "title": "Titled", "acceptance_criteria": ["one"]}, "from the ticket file")
        check("F4: a titled ticket with criteria passes in silence (no question, no state)", not driver.state.get("s0_block"))

        # K11 (temporal): a snapshot of the routes before D-06 is read as it is, labelled, never rewritten
        work = task_root / "work"
        work.mkdir(parents=True, exist_ok=True)
        path = work / "ticket-snapshot.json"
        for label, said in (("file", "file (route before D-06 unknown)"), ("jira_direct_api", "fetched (older label)"),
                            ("fetched", "fetched"), ("person_pasted", "person_pasted"), ("agent", "agent (route removed by D-06)"),
                            (None, "unknown (no provenance recorded)")):
            old = {"key": task, "title": "Old", "acceptance_criteria": ["one"], "comments": [],
                   "provenance": {"source": label, "fetched_at": None} if label else {}}
            path.write_text(json.dumps(old, indent=2), encoding="utf-8")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                ticket, text, how, kept = driver.s0_ticket(None)
            eq(f"K11: a snapshot labelled `{label}` is kept as it is (one line, no read, the file's own text)",
               (kept, ticket["title"], text == path.read_bytes().decode("utf-8"), hashlib.sha256(path.read_bytes()).hexdigest() == before,
                printed.getvalue().strip()),
               (True, "Old", True, True, f"S0: work/ticket-snapshot.json is already there ({said}); it is read as it is and not written again"))
        # F3: "not needed" with a snapshot already there goes on with it, said in words
        driver.state["s0_answers"] = {"ticket_read": "not needed"}
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.s0_ticket(None)
        check_in("F3: `not needed` with a part already read: the story goes on with it, and says so",
                 "you said the ticket is not needed, so the story goes on with it", printed.getvalue())
        # ... and without one the story ends, honestly, with the reason and the door (FR-57), and nothing is read
        path.unlink()
        calls = []
        driver.py_stdout = lambda *a, **k: calls.append(a) or (0, "{}", "")
        try:
            driver.s0_ticket(None)
            check("F3: `not needed` with nothing read ends the story", False)
        except story_run.Person as person:
            # P01 (C1-3 F2 a): the question again with its way on - `retry` drops the earlier `not needed`, the paste, `stop` - and no
            # command to run by hand; nothing was read (no adapter call)
            eq("F3: it is the `ticket_read` question (halt, exit 3) and nothing was read",
               (person.kind, person.code, driver.state.get("s0_block"), calls), ("halt", 3, "ticket_read", []))
            check_in("F3: it says what was not written", "nothing was written", person.text)
            check_not_in("F3: and names no flag and no command to run again", "--ticket-file", person.text)
            check_not_in("F3: no hand command", "run the same command again", person.text)
            eq("F3: its doors are `retry` and `stop`; the paste is a door", (sorted(driver.state["s0_ask"]["doors"]), driver.state["s0_ask"]["paste"]),
               (["retry", "stop"], True))
            driver.state.pop("s0_block", None)
            driver.state.pop("s0_ask", None)
        driver.state.pop("s0_answers")
        # F-1 (critic t-689, G19): `retry` drops the earlier `not needed` ONLY at the ticket's own question; at any other block the
        # person's word about the ticket survives (and `launch.ticket_not_needed` is still set where the ticket is read)
        for block, survives in (("readiness", True), ("ticket_incomplete", True), ("source_list", True), ("ticket_read", False)):
            driver.state["s0_answers"] = {"ticket_read": "not needed"}
            driver.state["pending_words"] = {"S0": "retry"}
            driver.state["s0_block"], driver.state["s0_ask"] = block, {"kind": "halt", "text": "q", "doors": {"retry": "retry"}}
            driver.s0_read_word()
            eq(f"F-1: `retry` at `{block}` " + ("keeps" if survives else "drops") + " the earlier `not needed`",
               (driver.state["s0_answers"].get("ticket_read") == "not needed"), survives)
        driver.state.pop("s0_answers")
        # a read that comes back forgets the failure remembered from a moment ago (it would otherwise hide a later comparison)
        driver.state["s0_rest_failed"] = "an earlier failure"
        driver.py_stdout = lambda *a, **k: (0, json.dumps({"key": task, "title": "T", "acceptance_criteria": ["one"]}), "")
        got = driver.s0_rest_read()
        eq("the tracker answered: the remembered failure is forgotten, the ticket is returned",
           ("s0_rest_failed" in driver.state, got[0]["title"]), (False, "T"))

        # C4/C5: the tracker's lost login is an infrastructure stop that names the door (the token variable the config names)
        driver.config["adapters"] = {"ticket": {"kind": "jira", "method": "agent", "invoke": "jira-assistant",
                                                "direct_api": {"base_url": "https://jira.example.test", "auth_type": "basic_token",
                                                               "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN"}}}
        driver.py_stdout = lambda *a, **k: (5, "", "ticket_adapter: Jira stopped accepting the token (HTTP 401 while reading the ticket X-1)")
        printed = io.StringIO()
        try:
            with contextlib.redirect_stdout(printed):
                driver.s0_rest_read()
            check("C4: exit 5 stops the run", False)
        except story_run.Person as person:
            # F3 (a) (C1-3): the lost tracker login is the `ticket_auth` question (exit 3), not `claude -p`'s infrastructure (exit 5)
            eq("C4: exit 5 is the `ticket_auth` question (halt, exit 3), never the `ticket_read` one and never InfraStop",
               (person.kind, person.code, driver.state.get("s0_block")), ("halt", 3, "ticket_auth"))
            check_in("C4: it says nothing was recorded as not found", "nothing was recorded as not found", person.text)
            check_not_in("C4: the variable is not in the body", "QA_JIRA_API_TOKEN", person.text)
            check_in("C4: it is in the answer block, the one place an instruction may stand", "QA_JIRA_API_TOKEN", person.answer_note)
            eq("C4: its doors are `retry`, `not needed` and `stop`; the paste is a door",
               (sorted(driver.state["s0_ask"]["doors"]), driver.state["s0_ask"]["paste"]), (["not needed", "retry", "stop"], True))
        except story_run.InfraStop:
            check("C4: a lost tracker login is no longer an infrastructure stop", False)
        driver.state.pop("s0_block", None)
        driver.state.pop("s0_ask", None)
    finally:
        harness.cleanup(root)


def s0_reask_battery() -> None:
    """(g)(m) and the edges of the person's word, on a stop that takes NO text (the launch flags): what is not one of its
    answers comes back as the SAME question with a changed body (FR-7); the quote is cut at 300 characters, visibly; the
    journal keeps the words whole (t-208 / FR-8); an empty file is today's Stop; a token inside other words is not the token
    (FR-12); another script and 10 000 characters ask again without a crash. (Until t-267 this ran on `ticket_incomplete`,
    which now takes any non-empty text as the pasted ticket, C9.)"""
    import story_run
    check_eq = eq
    task = "QA-1"
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}]})
    mr = "https://githost.example.invalid/g/a/-/merge_requests/1"
    try:
        out = s0_run(root, env, task, "--mr", mr, "--branch", "feature/x")
        first = s0_question(task_root)
        check_eq("setup: two launch sources ask which to keep", s0_state(task_root).get("s0_block"), "flags")
        set_control(root, NO_USABLE)
        # D-0041: a rerun with NO `--answer` is not new words - the open question comes back and no conductor is called
        out = s0_run(root, env, task, "--mr", mr, "--branch", "feature/x")
        eq("D-0041: a rerun with no `--answer` asks again (exit 3) and calls no conductor", (out.returncode, conductor_count(root)), (3, 0))
        check_in("D-0041: and it is the same priced question", "## What each answer costs and does", s0_question(task_root))

        # (g) not one of the answers: the SAME question comes back with a changed body - and the conductor read the words first
        out = s0_answer(root, env, task, NOT_A_TICKET)
        check_eq("D1(g) an unrecognised answer asks again: exit 3", out.returncode, 3, out.stdout[-800:])
        again = s0_question(task_root)
        check_in("D1(g) the body opens with the changed sentence (the ONE lead of an unread answer)",
                 f'Your answer "{NOT_A_TICKET}" {UNREAD_LEAD}', again)
        check_not_in("D1(g) the old 'nothing moved, it takes only' lead is gone", "it takes only", again)
        check_in("D1(g) and offers the answers again, priced, `stop` among them", "(b) `branch` — keep a branch and drop the other one", again)
        check_in("D1(g) the held `stop` door is in it", "`stop` — stop the story here; nothing runs", again)
        eq("D1(g) every option of the re-ask has its three price lines", price_broken(again), [])
        check_in("D1(g) followed by the question as it was", "more than one place to take the code from", again)
        check("D1(g) FR-7: the body is not the one already answered",
              story_run.question_body_sha(first) != story_run.question_body_sha(again))
        eq("D-0041: an unread `--answer` is exactly ONE conductor call", conductor_count(root), 1)
        check_eq("D1(g) the block stays open", s0_state(task_root).get("s0_block"), "flags")
        check_eq("D1(g) the re-asked question obeys human-questions.md", rules_broken(again), [])
        check("D1(g) the answer is on the journal as a human_answer",
              any(e.get("event") == "human_answer" and "S0 flags: " + NOT_A_TICKET in str(e.get("notes"))
                  for e in s0_journal(root)), str(s0_journal(root))[-400:])
        # the quote's limit: 300 characters whole, 301 cut, and the cut is visible
        out = s0_answer(root, env, task, "x" * 300)
        check_in("D1(g) a 300-character answer is quoted whole", 'Your answer "' + "x" * 300 + '" is not one', s0_question(task_root))
        out = s0_answer(root, env, task, "x" * 301)
        long_q = s0_question(task_root)
        check_in("D1(g) a 301-character answer is cut at 300, visibly", 'Your answer "' + "x" * 300 + CUT + '" is not one', long_q)
        check_not_in("D1(g) and not quoted past it", "x" * 301, long_q)
        out = s0_answer(root, env, task, "y" * 10000)
        check_eq("D1(g) a 10 000-character answer asks again without a crash", out.returncode, 3, out.stderr[-500:])
        check_in("D1(g) quoting 300 of it", 'Your answer "' + "y" * 300 + CUT + '"', s0_question(task_root))
        # t-208 / FR-8: the quote above is the QUESTION's limit; the journal note is the person's words,
        # and every later brief reads it - it carries them whole, not cut at 1,500 (cmp2, 01.10)
        notes = [str(e.get("notes")) for e in s0_journal(root) if e.get("event") == "human_answer"]
        check("t-208 a 10 000-character S0 answer is in its human_answer note whole",
              "S0 flags: " + "y" * 10000 in notes, str([len(n) for n in notes]))
        check("t-208 and so is the 301-character one (past the quote's 300)",
              "S0 flags: " + "x" * 301 in notes, str([len(n) for n in notes]))
        # an answer file with nothing in it, or only white space, is today's Stop: nothing is asked
        # again and nothing is consumed - the question stays open for a real answer
        for empty in ("", "  \n\t "):
            out = s0_answer(root, env, task, empty)
            check_eq("edge: an empty answer file stops with the existing error", out.returncode, story_run.EXIT_ERROR, out.stdout[-300:])
            check_in("edge: and says the file is empty", "is empty", out.stdout)
        check_eq("edge: the block is still open after an empty answer", s0_state(task_root).get("s0_block"), "flags")
        # FR-12, behaviourally: an offered token INSIDE other words is not the token. The code
        # reads no phrase; "please branch now" is not `branch`, so nothing moves and it is asked again.
        out = s0_answer(root, env, task, "please branch now")
        check_eq("FR-12: an answer that merely contains an offered token is asked again: exit 3", out.returncode, 3, out.stdout[-300:])
        check_in("FR-12: with the changed sentence", 'Your answer "please branch now" is not one of the answers',
                 s0_question(task_root))
        check("FR-12: and it passed nothing", not (task_root / "pipeline.json").exists()
              and not s0_state(task_root).get("s0_passes"))
        # (m) an answer written with \u escapes (a person's own language) is asked again, not a crash
        out = s0_answer(root, env, task, OTHER_SCRIPT)
        check_eq("D1(m) an answer in another script asks again: exit 3", out.returncode, 3, out.stderr[-500:])
        check_in("D1(m) and quotes it back", OTHER_SCRIPT, s0_question(task_root))
        check("D1(m) with no traceback", "Traceback" not in out.stderr and "Traceback" not in out.stdout)
        # the same words twice: the second question is the first one's twin, and says it was answered before
        out = s0_answer(root, env, task, "retry")
        out = s0_answer(root, env, task, "retry")
        check_in("FR-7: the second identical re-ask says it was answered before", "You have answered this exact question before",
                 s0_question(task_root))
        # D-0041: the unread answers of the whole path (NOT_A_TICKET, x300, x301, y10000, "please branch now", the other script, `retry` twice;
        # the two empty files are today's Stop, `stop` is held) were exactly one conductor call each; the rerun at the top made none
        eq("D-0041: one conductor call per unread `--answer` on the whole path (8 unread answers)", conductor_count(root), 8)
        # G1: a conductor that returns `continue` leaves no stored block behind, and the caller runs the step again (the same question)
        set_control(root, {"conductor": {"action": "continue"}})
        before = conductor_count(root)
        out = s0_answer(root, env, task, "an answer the conductor lets pass")
        state = s0_state(task_root)
        eq("G1: a conductor `continue` -> the step runs again and S0 asks its question once more (exit 3), one call",
           (out.returncode, conductor_count(root) - before, state.get("s0_block")), (3, 1, "flags"))
        check("G1: and nothing was passed or decided by it", not (task_root / "pipeline.json").exists() and not state.get("s0_passes"))
    finally:
        harness.cleanup(root)


def s0_launch_flags() -> None:
    check_eq = eq
    task = "QA-1"

    # --- (i) flags: keep one launch source; `go on` and a stand name are not answers here -----------
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}]})
    try:
        out = s0_run(root, env, task, "--mr", "https://githost.example.invalid/g/a/-/merge_requests/1", "--branch", "feature/x")
        check_eq("D1(i) two launch sources ask which to keep: exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        check_in("D1(i) in the story's words, with the two doors as priced option lines", "(a) `mr` — keep a merge request and drop the other one", ask)
        check_in("D1(i) the second door", "(b) `branch` — keep a branch and drop the other one", ask)
        check_in("D1(i) and `stop`", "(c) `stop` — stop the story here; nothing runs", ask)
        check_eq("D1(i) every option has its three price lines", price_broken(ask), [])
        check_not_in("D1(i) never offering the one that was not given", "`commit`", ask)
        check_eq("D1(i) the flags question obeys human-questions.md", rules_broken(ask), [])
        check_eq("D1(i) the block is remembered", s0_state(task_root).get("s0_block"), "flags")
        set_control(root, NO_USABLE)                 # a conductor with no usable options: the seam shows the SITE's question again
        out = s0_answer(root, env, task, "go on")
        check_in("D1(i) `go on` is not offered here, so it is asked again, changed",
                 UNREAD_LEAD, s0_question(task_root))
        out = s0_answer(root, env, task, "local")
        check_in("D1(i) a stand's name on a block that is not about a stand is not an answer either",
                 'Your answer "local" ' + UNREAD_LEAD, s0_question(task_root))
        eq("D-0041: each of the two unread answers was one conductor call", conductor_count(root), 2)
        # C1-3 (P04): `stop` is a door of every S0 question and has its executor here: the question is HELD (exit 3), changed
        # in its first line (FR-7), with no conductor, nothing written, nothing kept for the next step, the block still open.
        out = s0_answer(root, env, task, "stop")
        eq("S0 stop: a whole-answer `stop` holds the question: exit 3", out.returncode, 3, out.stdout[-800:])
        held = s0_question(task_root)
        check_in("S0 stop: the first line says nothing runs and nothing is spent", "You said to stop. Nothing runs and nothing is spent.", held)
        check_in("S0 stop: and how to go on after all, naming the other doors", "answer `mr` or `branch`.", held)
        check_in("S0 stop: followed by the question as it was", "more than one place to take the code from", held)
        check_not_in("S0 stop: it is not the 'not one of the answers' re-ask", "is not one of the answers", held)
        check_eq("S0 stop: the held question obeys human-questions.md", rules_broken(held), [])
        check_eq("S0 stop: every option of the held question has its three price lines", price_broken(held), [])
        stopped = s0_state(task_root)
        check("S0 stop: the block stays open and no words are kept (`pending_words` has no S0)",
              stopped.get("s0_block") == "flags" and "S0" not in (stopped.get("pending_words") or {}), str(stopped.get("pending_words")))
        check("S0 stop: nothing was written and the stop made no conductor call (the two before it are the unread answers)",
              not (task_root / "pipeline.json").exists() and conductor_count(root) == 2)
        check("S0 stop: the word is on the journal as a human_answer",
              any(e.get("event") == "human_answer" and "S0 flags: stop" in str(e.get("notes")) for e in s0_journal(root)))
        # `stop please` is other words: the re-ask of any unread answer, not the stop (FR-12: the code reads the whole token only)
        out = s0_answer(root, env, task, "stop please")
        again = s0_question(task_root)
        check_in("S0 stop: `stop please` takes the unread road (the re-ask)", 'Your answer "stop please" ' + UNREAD_LEAD, again)
        check_not_in("S0 stop: and is not the held question", "You said to stop", again)
        eq("D-0041: `stop please` is other words: exactly one more conductor call", conductor_count(root), 3)
        # a stop answered with an `s0_ask` that an older driver stored (its doors lack `stop`) is still the stop (read-time door)
        old = s0_state(task_root)
        check("S0 stop: setup: the stored ask carries `stop` among its doors", "stop" in old["s0_ask"]["doors"])
        old["s0_ask"]["doors"].pop("stop")
        (task_root / "state" / "driver-state.json").write_text(json.dumps(old), encoding="utf-8")
        out = s0_answer(root, env, task, ' "Stop." ')
        check_in("S0 stop: quoted and full-stopped it is the same stop, on the old driver's ask", "You said to stop. Nothing runs and nothing is spent.",
                 s0_question(task_root))
        out = s0_answer(root, env, task, "`branch`",
                        "--mr", "https://githost.example.invalid/g/a/-/merge_requests/1", "--branch", "feature/x")
        # the stand: one configured stand is selected and probed, and this project has no
        # environment block for the probe - which is a warning since D2, not a stop.
        state = s0_state(task_root)
        check_eq("D1(i) `branch` keeps only branch, over the command line that still says both",
                 {k: v for k, v in state["launch"].items() if k in ("mr", "branch", "commit")}, {"branch": "feature/x"})
        check("D1(i) the flags block is behind us", state.get("s0_block") != "flags")
        eq("D1(i) the doors (`branch`, `stop`) made no conductor call: only the three unread answers did", conductor_count(root), 3)
    finally:
        harness.cleanup(root)


def k5_the_agent_is_never_called() -> None:
    """K5: zero agent calls (the stub's count is 0) with `method: agent` and a usable `direct_api`, AND with an
    unusable one; the removed names are nowhere in the driver (grep, with a positive control of the same form)."""
    # a usable direct_api: the ticket comes by REST, the agent stays a write channel
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira)
    try:
        out = s0_run(root, env, KEY)
        eq("K5: `method: agent` + a usable direct_api: S0 reads the ticket by REST and finishes: exit 0", out.returncode, 0,
           out.stdout[-1500:] + out.stderr[-800:])
        snapshot = snapshot_of(task_root)
        eq("K5: the snapshot is the light form of the tracker's answer (15 criteria, the parent), `fetched`",
           (len(snapshot["acceptance_criteria"]), snapshot["parent"], snapshot["provenance"]["source"]), (15, "TP1-14482", "fetched"))
        eq("K5: ONE read of the tracker: the issue with every field, `/field`, the remote links (3 requests), no per-key GET",
           sorted(jira.log), sorted([f"/rest/api/2/issue/{KEY}?fields=*all", "/rest/api/2/field", f"/rest/api/2/issue/{KEY}/remotelink"]))
        eq("K5: stub count 0: no agent, no conductor, no model at all", stub_calls(root), [])
        check("K5: the raw folder and the role's files are beside the snapshot (the adapter's own files)",
              all((task_root / "work" / name).exists() for name in ("ticket-raw/issue.json", "ticket-raw/issue.pretty.json", "ticket-view.md", "ticket-references.json")))
        check("K5: and no tracker-agent line is printed", "tracker agent" not in out.stdout)
        view_text = (task_root / "work" / "ticket-view.md").read_bytes().decode("utf-8")
        check("t-281: on the REST leg the view is the story's own text: no comparison line", "read for comparison" not in view_text and view_text.startswith(KEY), view_text[:200])
        # the revision the controller keeps is the hash of that one snapshot (stable: the file is never rewritten)
        controller = json.loads((task_root / "state" / "controller.json").read_text(encoding="utf-8"))
        eq("K5: source_revision is the sha256 of the snapshot", controller.get("source_revision"),
           hashlib.sha256((task_root / "work" / "ticket-snapshot.json").read_bytes()).hexdigest())
    finally:
        jira.stop()
        harness.cleanup(root)
    # an unusable one: no direct_api at all - the question, and still no agent
    root, task_root, env = s0_project("QA-1", config={"adapters": {"ticket": {"kind": "jira", "method": "agent", "invoke": "jira-assistant"}}})
    try:
        out = s0_run(root, env, "QA-1")
        eq("K5: `method: agent` with no direct_api: the person is asked: exit 3", out.returncode, 3, out.stdout[-800:])
        eq("K5: the block is `ticket_read`, stub count 0", (s0_state(task_root).get("s0_block"), stub_calls(root)), ("ticket_read", []))
        ask = s0_question(task_root)
        check_in("K5: the question says no way to read is set up, and that the assistant only writes",
                 "the Jira assistant is not used to read tickets - it only writes to them", ask)
        check_in("K5: and 'how to get it' names recording the tracker's address and token for the project",
                 "record the tracker's address and token for this project (onboarding does it)", ask)
    finally:
        harness.cleanup(root)
    src = harness.driver_text()
    pattern = r"ticket_incomplete|ticket_by_agent|TICKET_SHAPE|\"ticket_agent\"|ticket_problems|check_ticket"
    found = sorted(set(re.findall(pattern, src)))
    eq("K5: grep of the driver set: the removed names have 0 hits, and the same pattern finds the surviving `ticket_incomplete` (positive control)",
       found, ["ticket_incomplete"])
    print(f"K5: grep -E '{pattern}' driver set -> {sorted(set(re.findall(pattern, src)))} ({len(re.findall(pattern, src))} hits, all of them the control)")


def k6_ticket_read_question() -> None:
    """K6: the tracker cannot be read: the `ticket_read` question carries FR-50's three answers and obeys the rules;
    `retry` reads again; the ticket as text becomes the snapshot; `go on` is not one of its answers; `not needed`
    with nothing read ends the story honestly."""
    jira = FakeJira([(f"/issue/{KEY}", 404), ("/myself", {"accountId": "x"})])
    root, task_root, env = rest_project(jira)
    try:
        out = s0_run(root, env, KEY)
        eq("K6: a 404 on the story's own key asks the person (never a stop for the login): exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        eq("K6: the block is `ticket_read`", s0_state(task_root).get("s0_block"), "ticket_read")
        check("K6: three answers are present as priced option lines: `not needed`, `retry` (after fixing the way in), and the ticket as text, then `stop`",
              all(word in ask for word in ("(a) `not needed` — the story can go without this ticket", "(b) `retry` — ",
                                           ", and I read the ticket again", "(c) paste the ticket here as text",
                                           "(d) `stop` — stop the story here; nothing runs")), ask)
        eq("K6: every option has its three price lines", price_broken(ask), [])
        check_in("K6: the priced section is in the body, above the answer block", "## What each answer costs and does", ask.split("\n---\n")[0])
        check_not_in("K6: the hand command is gone from the question", "run the same command again", ask)
        eq("K6: rules_broken == []", rules_broken(ask), [])
        check_in("K6: the question names the route tried and why it failed, in the story's words",
                 f"I asked the tracker for {KEY} through its web interface, with the account recorded for this project, and it answered "
                 "that there is no such ticket, or that this account may not see it.", ask)
        check_not_in("K6: no agent is offered or named as a way to read", "assistant", ask)
        details = (task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8")
        check_in("K6: the adapter's own words are beside it, not in it", "was not found (HTTP 404)", details)
        check_not_in("K6: and not in the body", "HTTP 404", ask)
        eq("K6: nothing was written for the story yet, and nobody was called", ((task_root / "pipeline.json").exists(),
                                                                             (task_root / "work" / "ticket-snapshot.json").exists(), stub_calls(root)),
           (False, False, []))
        # negative: `go on` is not one of the answers
        set_control(root, NO_USABLE)
        out = s0_answer(root, env, KEY, "go on")
        again = s0_question(task_root)
        check_in("K6 negative: `go on` gets the 'not one of the answers' re-ask (the one lead), then the question itself",
                 f'Your answer "go on" {UNREAD_LEAD}', again)
        check("K6 negative: ... with its four answers as priced option lines, `retry`, `not needed`, the ticket as text, `stop`",
              all(word in again for word in ("(a) `not needed` — ", "(b) `retry` — ", "(c) paste the ticket here as text", "(d) `stop` — ")), again)
        eq("K6 negative: every option of the re-ask has its three price lines", price_broken(again), [])
        eq("K6 negative: the block stays open, the re-ask obeys the rules, nothing moved",
           (s0_state(task_root).get("s0_block"), rules_broken(again), (task_root / "pipeline.json").exists()), ("ticket_read", [], False))
        eq("D-0041: the unread `go on` was exactly one conductor call", conductor_count(root), 1)
        asked_before = len(jira.log)
        # `retry` re-reads: the tracker came back
        jira.serve(story_15045())
        out = s0_answer(root, env, KEY, "retry")
        eq("K6: `retry` reads the ticket again, and S0 finishes: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        check("K6: the read was made again (the tracker was asked after the answer)", len(jira.log) > asked_before)
        eq("K6: and the snapshot is the tracker's (`fetched`)", snapshot_of(task_root)["provenance"]["source"], "fetched")
        eq("K6: no agent; the conductor was called for the unread `go on` only, never for `retry`",
           [c["kind"] for c in stub_calls(root)], ["conductor"])
    finally:
        jira.stop()
        harness.cleanup(root)
    # the ticket as text: the paste becomes the snapshot, `person_pasted`; the tracker, known to be down, is not asked again
    jira = FakeJira([(f"/issue/{KEY}", 404)])
    root, task_root, env = rest_project(jira)
    try:
        s0_run(root, env, KEY)
        asked_before = len(jira.log)
        pasted = FIXTURE_TICKET.replace("QA-1", KEY)
        out = s0_answer(root, env, KEY, pasted)
        eq("K6: the ticket as text ends the question: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        snapshot = snapshot_of(task_root)
        eq("K6: paste -> snapshot, provenance `person_pasted`, the paste kept as typed",
           (snapshot["provenance"]["source"], (task_root / "state" / "driver-tmp" / f"ticket-{KEY}.md").read_text(encoding="utf-8")),
           ("person_pasted", pasted.strip()))
        lines = [ln for ln in out.stdout.splitlines() if "could not be read for comparison" in ln]
        eq("C6: the tracker could not be read for comparison: ONE line, never a question, and no new request (it was down a moment ago)",
           (len(lines), len(jira.log) == asked_before, "disagreements" in snapshot), (1, True, False))
        print("C6 line: " + lines[0])
        eq("K6: no agent, no conductor", stub_calls(root), [])
    finally:
        jira.stop()
        harness.cleanup(root)
    # `not needed` with nothing read (P01, C1-3 F2 a): not an exit with a command to run by hand but the `ticket_read` question again,
    # with its way on in it - `retry` (the earlier `not needed` is dropped), the ticket as text, `stop` (FR-57: a ban has a door)
    jira = FakeJira([(f"/issue/{KEY}", 404)])
    root, task_root, env = rest_project(jira)
    try:
        s0_run(root, env, KEY)
        out = s0_answer(root, env, KEY, "Not needed.")
        held = s0_question(task_root)
        eq("P01: `not needed` with nothing read is a question: exit 3, nothing written, nobody called",
           (out.returncode, "story_run: stopped" in out.stdout, (task_root / "pipeline.json").exists(),
            (task_root / "work" / "ticket-snapshot.json").exists(), stub_calls(root)), (3, False, False, False, []), out.stdout[-900:])
        check_in("P01: it says nothing was written, in the story's words", "nothing was written", held)
        check_not_in("P01: and names no flag and no command to run by hand", "--ticket-file", held)
        check_not_in("P01: no 'run the same command again'", "run the same command again", held)
        check("P01: its three answers are priced option lines: `retry`, the ticket as text, `stop`",
              all(word in held for word in ("(a) `retry` — ", "(b) paste the ticket here as text", "(c) `stop` — ")), held)
        eq("P01: every option has its three price lines, the text obeys the rules", (price_broken(held), rules_broken(held)), ([], []))
        eq("P01: the block is `ticket_read`", s0_state(task_root).get("s0_block"), "ticket_read")
        seen = len(jira.log)
        out = s0_run(root, env, KEY)
        eq("P01/FR-7: a rerun with no `--answer` asks the same question again without reading the tracker, and calls no conductor",
           (out.returncode, len(jira.log) == seen, stub_calls(root)), (3, True, []))
        ticket = root / "ticket.md"
        ticket.write_text(FIXTURE_TICKET.replace("QA-1", KEY), encoding="utf-8")
        out = s0_run(root, env, KEY, "--ticket-file", str(ticket))
        eq("P01: a `--ticket-file` on the command line still reads: S0 finishes", out.returncode, 0, out.stdout[-900:] + out.stderr[-500:])
    finally:
        jira.stop()
        harness.cleanup(root)
    # P01 `retry`: the earlier `not needed` is dropped and the ticket is read again; the paste: G19 - an earlier `not needed` is dropped too
    for door in ("retry", "paste"):
        jira = FakeJira([(f"/issue/{KEY}", 404)])
        root, task_root, env = rest_project(jira)
        try:
            s0_run(root, env, KEY)
            s0_answer(root, env, KEY, "Not needed.")
            asked_before = len(jira.log)
            if door == "retry":
                jira.serve(story_15045())
                out = s0_answer(root, env, KEY, "retry")
            else:
                out = s0_answer(root, env, KEY, FIXTURE_TICKET.replace("QA-1", KEY))
            eq(f"P01 `{door}`: S0 finishes (exit 0)", out.returncode, 0, out.stdout[-900:] + out.stderr[-500:])
            snapshot = snapshot_of(task_root)
            eq(f"P01 `{door}`: the ticket is read, not skipped",
               (snapshot["provenance"]["source"], (s0_state(task_root).get("launch") or {}).get("ticket_not_needed")),
               ("fetched" if door == "retry" else "person_pasted", None))
            eq(f"P01 `{door}`: no conductor", stub_calls(root), [])
            if door == "retry":
                check("P01 `retry`: the tracker was asked again", len(jira.log) > asked_before)
        finally:
            jira.stop()
            harness.cleanup(root)


def k6_retry_after_and_other_failures() -> None:
    """A tracker that asks to be asked again later: the question names the time (the adapter's `retry_at`, read from
    its error OBJECT - t-281 F3: no sentence is searched for it)."""
    jira = FakeJira([])
    root, task_root, env = rest_project(jira)
    try:
        import story_run
        driver = driver_for(root, env, KEY)
        said = ("ticket_adapter: the tracker could not be read for TP1-15045 (server requested delayed retry); the tracker asked "
                "to be tried again at 2026-10-01T12:30:00Z - retry, or hand the ticket over as text (--ticket-file).")
        failure = {"owner": "tracker", "status": 429, "retry_at": "2026-10-01T12:30:00Z", "message": "x", "file": None, "from_object": True}
        try:
            driver.s0_ticket_read_question(3, said, failure)
            check("retry_at: a question was raised", False)
        except story_run.Person as person:
            check_in("retry_at: the question names the time the tracker asked for", "it asked to be asked again at 2026-10-01T12:30:00Z.", person.text)
            check_in("retry_at: and says it did not answer in a way the factory can use", "did not answer in a way I can use", person.text)
            # (`no_how_to_answer` is the block `ask()` appends under the text; this reads the text before it)
            eq("retry_at: it obeys human-questions.md", [r for r in rules_broken(person.text) if r != "no_how_to_answer"], [])
        try:
            driver.s0_ticket_read_question(3, "ticket_adapter: the tracker could not be read for X (HTTP 503) - retry, or hand it over.",
                                           {"owner": "tracker", "status": 503, "retry_at": None, "message": "x", "file": None, "from_object": True})
        except story_run.Person as person:
            check_not_in("503 with no time named: no time is invented", "asked to be asked again", person.text)
        # t-281 F3, negative control: a sentence that carries a time and an object that does not -> no time (nothing is read from the words)
        try:
            driver.s0_ticket_read_question(3, said, {"owner": "tracker", "status": 503, "retry_at": None, "message": "x", "file": None, "from_object": True})
        except story_run.Person as person:
            check_not_in("F3 negative control: the time in the SENTENCE is not read when the object names none", "2026-10-01T12:30:00Z", person.text)
        # (the source check that RETRY_AT_RE is gone and `def ticket_failure` stands was a source pin of one member: deleted by TD-11 phase 0, F3)
    finally:
        jira.stop()
        harness.cleanup(root)


def k_comparison_person_vs_tracker() -> None:
    """F27 / C6 / FR-25: `--ticket-file` given and REST set up: the person's text is the requirement, the tracker is
    read BESIDE it; both present -> ONE line and `disagreements[]` in the snapshot; the tracker failing -> ONE line, no question."""
    person = ("---\nkey: TP1-15045\ntype: Sub-task\nstatus: Ready for Review\nparent: TP1-14482\n---\n\n"
              "# Testing TP1-14482 Visual Workflow Diff for Revisions\n\nThe person's own copy of the description.\n\n"
              "## Acceptance criteria\n\n1. Visual revision diff opens from workflow version history.\n2. A single graph represents the target revision.\n\n"
              "## Comments\n\n- **po** (2026-09-18): one comment.\n")
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira)
    try:
        file = root / "person.md"
        file.write_text(person, encoding="utf-8")
        out = s0_run(root, env, KEY, "--ticket-file", str(file))
        eq("F27: the person's file and a tracker that says more: S0 finishes, exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        snapshot = snapshot_of(task_root)
        lines = [ln for ln in out.stdout.splitlines() if ln.startswith("The person's text is the requirement for this story.")]
        eq("F27: ONE FR-25 line, naming the authority (the person) and the gap", len(lines), 1, out.stdout[-1500:])
        print("FR-25 line (person vs tracker): " + lines[0])
        fields = {d["field"]: d for d in snapshot["disagreements"]}
        eq("F27/K7: `disagreements[]` is in the snapshot: the criteria differ (2 against 15), the comments differ (1 against 1 is equal, so absent)",
           (sorted(fields), (fields["acceptance_criteria"]["person"], fields["acceptance_criteria"]["rest"])), (["acceptance_criteria"], (2, 15)))
        eq("F27: the requirement stays the person's: the snapshot holds their two criteria and `person_pasted`",
           (len(snapshot["acceptance_criteria"]), snapshot["provenance"]["source"]), (2, "person_pasted"))
        eq("F27 / t-281 F4: the comparison read passes the same `--raw-dir` as the REST read: the raw folder, the view and the references are there",
           sorted(p.name for p in (task_root / "work").iterdir() if p.name.startswith("ticket-") and p.name != "ticket-snapshot.json"),
           ["ticket-raw", "ticket-references.json", "ticket-view.md"])
        view_lines = (task_root / "work" / "ticket-view.md").read_bytes().decode("utf-8").split("\n")
        eq("t-281: on the comparison leg `ticket-view.md` opens with ONE line that says it is the tracker's text, read for comparison, "
           "and that the requirement is the person's snapshot; the view's own first line follows",
           (view_lines[0], view_lines[1].startswith(KEY), sum(1 for ln in view_lines if ln.startswith("The tracker's text, read for comparison"))),
           ("The tracker's text, read for comparison; the story's requirement is the text the person gave (ticket-snapshot.json)", True, 1))
        references = json.loads((task_root / "work" / "ticket-references.json").read_text(encoding="utf-8"))
        refs = [row["ref"] for row in references["rows"]]
        eq("F4: the tracker read SUCCEEDED, so the references are the tracker's: one row per reference (the person's text is not scanned twice), "
           "no `unproven` row, written_by [S0]",
           (len(refs) == len(set(refs)), [r for r in references["rows"] if r.get("status") == "unproven"], references["written_by"],
            "TP1-14482" in refs), (True, [], ["S0"], True), json.dumps(references["rows"])[:600])
        eq("F27: no agent, no conductor", stub_calls(root), [])
    finally:
        jira.stop()
        harness.cleanup(root)
    # the tracker says the same: the line says so, and `disagreements` is present and empty (compared: not "unknown")
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira)
    try:
        out = s0_run(root, env, KEY, "--ticket-file", str(_write_same_as_tracker(root, env)))
        snapshot = snapshot_of(task_root)
        eq("K7 negative: the tracker says the same: `disagreements` is [] (compared and equal), and the line says so",
           (snapshot.get("disagreements"), "The tracker now says the same about the title, the acceptance criteria, the number of comments and the parent." in out.stdout),
           ([], True), out.stdout[-900:])
    finally:
        jira.stop()
        harness.cleanup(root)
    # the tracker failing: ONE line, no question, no disagreements (unknown, not "same")
    jira = FakeJira([(f"/issue/{KEY}", 404)])
    root, task_root, env = rest_project(jira)
    try:
        file = root / "person.md"
        file.write_text(person, encoding="utf-8")
        out = s0_run(root, env, KEY, "--ticket-file", str(file))
        lines = [ln for ln in out.stdout.splitlines() if "could not be read for comparison" in ln]
        snapshot = snapshot_of(task_root)
        eq("C6: the comparison read fails: ONE line, never a question: exit 0, `disagreements` absent (unknown is not `same`)",
           (out.returncode, len(lines), "disagreements" in snapshot), (0, 1, False), out.stdout[-1200:])
        print("C6 line: " + lines[0])
        references = json.loads((task_root / "work" / "ticket-references.json").read_text(encoding="utf-8"))
        eq("F4: with no tracker read the references are the PERSON's text: written_by [S0], the ticket row `unproven` - no tracker read at S0",
           (references["written_by"], [(r["ref"], r["status"], r["reason"]) for r in references["rows"] if r["kind"] == "ticket"]),
           (["S0"], [("TP1-14482", "unproven", "no tracker read at S0")]), json.dumps(references)[:500])
        check("F4: and no raw folder was made (no tracker response to keep)", not (task_root / "work" / "ticket-raw").exists())
    finally:
        jira.stop()
        harness.cleanup(root)


def _write_same_as_tracker(root: Path, env: dict) -> Path:
    """The person's file with exactly the tracker's title, criteria (read through the adapter's own light form), comment
    count and parent: what 'the same' looks like (the description is not compared, so it is a short one)."""
    light = harness.run_script("ticket_adapter.py", "get", KEY, "--json", cwd=root, env=env)
    snap = json.loads(light.stdout)
    items = "\n".join(f"{n}. {item}" for n, item in enumerate(snap["acceptance_criteria"], 1))
    comments = "\n".join(f"- **{c['author']}** ({c['date']}): {c['text']}" for c in snap["comments"])
    path = root / "same.md"
    path.write_text(f"---\nkey: {KEY}\nparent: {snap['parent']}\n---\n\n# {snap['title']}\n\nThe person's own copy.\n\n"
                    f"## Acceptance criteria\n\n{items}\n\n## Comments\n\n{comments}\n", encoding="utf-8")
    return path


def k11_a_snapshot_on_disk_is_never_rewritten() -> None:
    """K11 (temporal): a snapshot of the routes before D-06 - the cmp2 `source: file` one, a `jira_direct_api` one - is
    read as it is at S0 and never rewritten; the tracker is not asked; its sha256 is the same after an S0 resume."""
    for label, said in (("file", "file (route before D-06 unknown)"), ("jira_direct_api", "fetched (older label)")):
        jira = FakeJira(story_15045())
        root, task_root, env = rest_project(jira, git=False)            # no git: readiness stops S0 once, so there is a resume
        try:
            old = {"key": KEY, "type": "Sub-task", "status": "Ready for Review", "title": "Testing TP1-14482 Visual Workflow Diff for Revisions",
                   "description": "Purpose: validate TP1-14482.", "acceptance_criteria": ["Visual revision diff opens from workflow version history."],
                   "comments": [{"author": "Test User 7", "date": "2026-09-18T08:20:40.161+0000", "text": "Draft MR"}],
                   "parent": "TP1-14482", "subtasks": [], "links": {"merge_request": None, "branch": None},
                   "provenance": {"source": label, "fetched_at": None}}
            path = task_root / "work" / "ticket-snapshot.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            out = s0_run(root, env, KEY)
            eq(f"K11: S0 over a `{label}` snapshot stops at readiness (the setup of the resume): exit 3", out.returncode, 3, out.stdout[-900:])
            line = f"S0: work/ticket-snapshot.json is already there ({said}); it is read as it is and not written again"
            check_in(f"K11: the label is reported as `{said}`", line, out.stdout)
            out = s0_answer(root, env, KEY, "go on")
            eq("K11: the S0 resume finishes: exit 0", out.returncode, 0, out.stdout[-900:] + out.stderr[-400:])
            after = hashlib.sha256(path.read_bytes()).hexdigest()
            eq(f"K11: the sha256 of the `{label}` snapshot is unchanged after the S0 resume", after, before)
            eq("K11: the tracker was not asked at all (nothing to read: the snapshot is the ticket)", jira.log, [])
            controller = json.loads((task_root / "state" / "controller.json").read_text(encoding="utf-8"))
            eq("K11: and source_revision is that hash (stable across resumes)", controller.get("source_revision"), before)
            print(f"K11: {label}: sha256 {before} before == {after} after the S0 resume; {said}")
        finally:
            jira.stop()
            harness.cleanup(root)
    # a fresh REST snapshot is not read again at a resume either: the read is one, the hash is stable
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira, git=False)
    try:
        s0_run(root, env, KEY)
        path = task_root / "work" / "ticket-snapshot.json"
        before, asked = hashlib.sha256(path.read_bytes()).hexdigest(), len(jira.log)
        out = s0_answer(root, env, KEY, "go on")
        eq("K11: a fresh REST snapshot over an S0 resume: exit 0, the same bytes, no second read",
           (out.returncode, hashlib.sha256(path.read_bytes()).hexdigest() == before, len(jira.log) == asked == 3), (0, True, True), out.stdout[-900:])
        check_in("K11: and it is reported as `fetched`", "is already there (fetched)", out.stdout)
    finally:
        jira.stop()
        harness.cleanup(root)


def k13_no_criteria_section_goes_on_with_a_line() -> None:
    """K13 / D-0050 / P23 (the old K13 asked here): a ticket with NO criteria section (on the tracker route) is no question - S0 goes
    on to its next stop (readiness: no git here), and the story's record carries ONE line, the FIRST of the warnings, that names the
    headings looked for, in at most 180 characters (gate A shows five, each cut there). No finding, no conductor, no agent."""
    issue = {"id": "1", "key": "APP-1", "fields": {"summary": "Items can be tagged", "updated": "2026-09-01T10:00:00.000+0000",
                                                    "description": "A story whose description names no criteria.",
                                                    "comment": {"total": 0, "comments": []}}}
    jira = FakeJira([("/issue/APP-1/remotelink", b"[]"), ("/issue/APP-1?fields=*all", json.dumps(issue).encode("utf-8")), ("/rest/api/2/field", b"[]")])
    root, task_root, env = rest_project(jira, "APP-1", git=False)
    try:
        out = s0_run(root, env, "APP-1")
        eq("K13 / D-0050: 0 criteria and no criteria section: NO ticket question - the first stop is readiness (no git here): exit 3",
           (out.returncode, s0_state(task_root).get("s0_block")), (3, "readiness"), out.stdout[-900:])
        check_not_in("K13: and nothing was asked about criteria", "criteria", s0_question(task_root))
        out = s0_answer(root, env, "APP-1", "go on")
        eq("K13: the `go on` (readiness) finishes S0: exit 0", out.returncode, 0, out.stdout[-900:] + out.stderr[-400:])
        check_not_in("K13: no finding about the ticket (nothing was passed, nothing lost)", "ticket_incomplete", s0_findings(root))
        warnings = s0_pipeline(task_root)["warnings"]
        eq("K13 / t-957 F-6: the line is the FIRST of the story's warnings and names the headings looked for",
           warnings[0], "S0: ticket APP-1 has no section named Acceptance Criteria, What needs to be tested, AC; "
                        "the requirements are read from its description, comments, attachments and linked tickets")
        check("K13: and fits the 180 characters gate A cuts each warning at", len(warnings[0]) <= 180, str(len(warnings[0])))
        eq("K13: the snapshot is the tracker's, with no criteria", (snapshot_of(task_root)["acceptance_criteria"], snapshot_of(task_root)["provenance"]["source"]),
           ([], "fetched"))
        eq("K13: no agent, no conductor", stub_calls(root), [])
    finally:
        jira.stop()
        harness.cleanup(root)


def s0_list_applied_before_the_seed() -> None:
    """The tracker read of S0 seeds `work/source-inventory.json` (the `/field` ids and the prefix probes S1 reuses): that is no
    source collected. A list applied BEFORE the read (its record is on disk, the same bytes) must not meet the "too late"
    question at a later entry of S0 (after a readiness answer); a list the record does not hold still does."""
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira, git=False)             # no git: readiness stops S0 once, so there is a later entry
    try:
        listed = root / "list.txt"
        listed.write_text(f"testproject1-ui!1924 {EM} {DRAFT}\n", encoding="utf-8")
        out = s0_run(root, env, KEY, "--skip-sources", str(listed))
        eq("seed: the list is applied, the tracker is read (it seeds the inventory), readiness asks: exit 3",
           (out.returncode, s0_state(task_root).get("s0_block"), (task_root / "work" / "source-inventory.json").is_file(), _no_record(task_root)),
           (3, "readiness", True, False))
        out = s0_answer(root, env, KEY, "go on")
        eq("seed: at the next entry the list is NOT 'too late' (its record is the same bytes): S0 finishes, exit 0",
           (out.returncode, s0_state(task_root).get("s0_block")), (0, None), out.stdout[-900:])
        check_not_in("seed: and nothing says the sources were already collected", "were already collected", out.stdout)
        eq("seed: the record of the list is untouched", [e["as_written"] for e in _record(task_root)["exclusions"]], ["testproject1-ui!1924"])
    finally:
        jira.stop()
        harness.cleanup(root)
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira, git=False)
    try:
        listed = root / "list.txt"
        listed.write_text(f"testproject1-ui!1924 {EM} {DRAFT}\n", encoding="utf-8")
        s0_run(root, env, KEY, "--skip-sources", str(listed))
        listed.write_text(f"testproject1-ui!1881 {EM} another word\n", encoding="utf-8")       # other bytes than the record holds
        out = s0_answer(root, env, KEY, "go on")
        eq("seed negative: OTHER bytes than the record holds, with an inventory on disk, still ask 'too late': exit 3",
           (out.returncode, s0_state(task_root).get("s0_block")), (3, "source_list"), out.stdout[-900:])
        check_in("seed negative: in the same words as before", "were already collected on", s0_question(task_root))
    finally:
        jira.stop()
        harness.cleanup(root)


def k10_a_dry_run_asks_and_reads_nothing() -> None:
    """`--dry-run` skips S0 altogether, the question included, like every other S0 stop: it prints the S0 route and the
    tracker is not asked."""
    jira = FakeJira(story_15045())
    root, task_root, env = rest_project(jira)
    try:
        out = harness.run_script("story_run.py", "--project", str(root), "--task", KEY, "--dry-run", cwd=root, env=env)
        eq("dry run: exit 0", out.returncode, 0, out.stdout[-600:] + out.stderr[-400:])
        check_in("dry run: it names the REST read of S0 and that a failed read is asked, a lost login stops, no model is called",
                 "ticket_adapter get --raw-dir (the tracker by REST; a read that fails is asked of the person, a lost login stops the run, "
                 "no model is called; a dry run asks nothing and reads nothing)", out.stdout)
        eq("dry run: nothing was asked of the tracker, no question was written, nothing was called",
           (jira.log, (task_root / "state" / "driver-question.md").exists(), stub_calls(root)), ([], False, []))
        print("dry run prints: " + next(ln for ln in out.stdout.splitlines() if ln.startswith("pipeline.json is absent")))
    finally:
        jira.stop()
        harness.cleanup(root)


def s0_py_stdout_unit() -> None:
    import contextlib
    import io
    import tempfile
    import story_run
    check_eq = eq
    task = "QA-1"

    # D1(a) as a unit: stderr is printed and never part of what a caller writes to a file.
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "noisy.py").write_text(
                "import sys\nprint('{\"key\": \"QA-1\"}')\nprint('WARN: probing the tracker', file=sys.stderr)\n",
                encoding="utf-8")
            driver.scripts = Path(tmp)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                code, stdout, stderr = driver.py_stdout("noisy.py")
        check_eq("D1(a) py_stdout returns stdout alone", stdout, '{"key": "QA-1"}\n')
        check_in("D1(a) and stderr apart", "WARN: probing the tracker", stderr)
        check_in("D1(a) and prints the stderr line for the log", "WARN: probing the tracker", printed.getvalue())
        # exit 0 with something that is not one JSON object: a refusal that names the call and the
        # head of what it printed, and no snapshot - never a halt for the person.
        driver = driver_for(root, env, task)
        driver.py_stdout = lambda script, *a, **k: (0, "this is prose, not a ticket\n", "")
        try:
            driver.s0()
            check("D1(a) exit 0 with prose stdout refuses", False)
        except story_run.Refusal as refusal:
            check_in("D1(a) the refusal names the adapter call", "ticket_adapter get QA-1", refusal.text)
            check_in("D1(a) and the head of its stdout", "this is prose, not a ticket", refusal.text)
        except story_run.Person:
            check("D1(a) it is never a question for the person", False)
        check("D1(a) and no snapshot was written", not (task_root / "work" / "ticket-snapshot.json").exists())
    finally:
        harness.cleanup(root)


def s0_fenced_decision_notice() -> None:
    """t-278 (the coordinator's one-liner for t-271): a decision token inside a fenced block is ANNOUNCED at a question stop and never
    applied; the same token outside a fence is read as before, and a stop with no fence says nothing about one."""
    import contextlib
    import io
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        (task_root / "work").mkdir(parents=True, exist_ok=True)
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps({"verdict": "blocked", "open_questions": [
            {"id": "Q1", "question": "Which?", "severity": "major",
             "readings": [{"reading": "r0", "from": "description", "if_chosen": "x"}, {"reading": "r1", "from": "description", "if_chosen": "x"}]}]}),
            encoding="utf-8")
        driver = driver_for(root, env, task)
        driver.py = lambda script, *a, **k: (0, "")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.take_question_answer("S3", "S3-qa-test-strategist-1", "```\nQ1: a\n```\n")
        out = printed.getvalue()
        check_in("fence: the decision inside the fenced block is announced, with the line", "S3: a decision inside a code block is not read: Q1: a", out)
        check_in("fence: and applied to nothing", "no question answered by a token", out)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.take_question_answer("S3", "S3-qa-test-strategist-1", "Q1: b\n")
        out = printed.getvalue()
        check_not_in("fence control: the same token outside a fence is read, and no notice is printed", "inside a code block", out)
        check_in("fence control: ... it is recorded", "recorded by code — Q1: b", out)
    finally:
        harness.cleanup(root)


def s0_legacy_snapshot() -> None:
    import contextlib
    import io
    check_eq = eq

    # --- (e) a story in flight with a legacy .md gets its .json once -----------------------------
    root, task_root, env = seed("QA-9")
    try:
        legacy = task_root / "work" / "ticket-snapshot.md"
        adapter_json = json.dumps({"key": "QA-9", "type": "Story", "status": "Open", "title": "Legacy",
                                   "description": "d", "acceptance_criteria": ["one"], "comments": [],
                                   "parent": None, "subtasks": [],
                                   "links": {"merge_request": None, "branch": None}}, indent=2)
        legacy.write_text(adapter_json + "\nWARN: the tail the old driver glued on\n", encoding="utf-8")
        out = s0_run(root, env, "QA-9")
        canon = task_root / "work" / "ticket-snapshot.json"
        check_eq("D1(e) a legacy .md holding JSON is taken: exit 0", out.returncode, 0, out.stdout[-800:] + out.stderr[-500:])
        check("D1(e) the .json exists and is the adapter's clean output", canon.is_file()
              and json.loads(canon.read_text(encoding="utf-8"))["title"] == "Legacy"
              and "WARN" not in canon.read_text(encoding="utf-8"))
        check_in("D1(e) one line says so", "ticket-snapshot.json", out.stdout)
        check("D1(e) the .md stays", legacy.is_file())
        before = (canon.read_bytes(), canon.stat().st_mtime_ns)
        out = s0_run(root, env, "QA-9")
        check_eq("D1(e) a second run leaves the .json as it was",
                 (canon.read_bytes(), canon.stat().st_mtime_ns), before)
        check_not_in("D1(e) and says nothing about it", "ticket-snapshot.json", out.stdout)
        # a markdown .md is converted the same way; a failed conversion is one line and writes nothing
        canon.unlink()
        legacy.write_text(FIXTURE_TICKET.replace("QA-1", "QA-9"), encoding="utf-8")
        driver = driver_for(root, env, "QA-9")
        driver.adopt_legacy_snapshot()
        check_eq("D1(e) a markdown .md is converted too", json.loads(canon.read_text(encoding="utf-8"))["key"], "QA-9")
        canon.unlink()
        driver.py_stdout = lambda script, *a, **k: (3, "", "no adapter")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.adopt_legacy_snapshot()
        check("D1(e) a failed conversion writes nothing", not canon.exists())
        check_eq("D1(e) and prints one line", len(printed.getvalue().strip().splitlines()), 1)
        check_in("D1(e) which says the brief will show it as not written", "not written yet", printed.getvalue())
        # no pipeline.json yet: this is S0's own business, not a legacy story
        fresh = task_root.parent / "QA-NEW"
        (fresh / "work").mkdir(parents=True)
        (fresh / "work" / "ticket-snapshot.md").write_text("x", encoding="utf-8")
        other = driver_for(root, env, "QA-NEW")
        other.adopt_legacy_snapshot()
        check("D1(e) a story with no pipeline.json is left to S0", not (fresh / "work" / "ticket-snapshot.json").exists())
    finally:
        harness.cleanup(root)


def s0_door_invariant() -> None:
    task = "QA-1"

    # --- the closed set: the S0 door is read only while S0 has no pipeline.json --------------------------
    root, task_root, env = seed(task)
    try:
        driver = driver_for(root, env, task)
        set_control(root, {"conductor": {"action": "continue", "did": "recorded", "text": "Recorded."}})
        for kind, stage in (("halt", "S0"), ("refusal", "S0")):
            driver.state["asked"] = {"kind": kind, "stage": stage, "dispatch": ""}
            driver.state["s0_block"] = "readiness"
            driver.save_state()
            (task_root / "state" / "driver-question.md").write_text("# q\nkind: halt\n", encoding="utf-8")
            answer = root / "a.md"
            answer.write_text("go on", encoding="utf-8")
            before = len(stub_calls(root))
            driver = driver_for(root, env, task)
            driver.take_answer(answer)
            # today's paths, unchanged: a halt goes to the conductor; a refusal at a stage that is
            # already done is recorded and the loop goes on
            old_way = len(stub_calls(root)) > before if kind == "halt" else len(stub_calls(root)) == before
            check(f"invariant: with pipeline.json present a `{kind}` at S0 goes the old way",
                  old_way and "S0" not in driver.state["pending_words"])
        driver.state.pop("s0_block", None)
        driver.state["asked"] = {"kind": "gate_A", "stage": "S0", "dispatch": ""}
        (task_root / "pipeline.json").unlink()
        driver.state["s0_block"] = "readiness"
        driver.save_state()
        (task_root / "state" / "driver-question.md").write_text("# q\nkind: gate_A\n", encoding="utf-8")
        driver = driver_for(root, env, task)
        driver.take_answer(answer)
        check("invariant: a gate kind never enters the S0 branch, even at S0 with no pipeline.json",
              "S0" not in driver.state["pending_words"])
    finally:
        harness.cleanup(root)


def s0_stale_block() -> None:
    """A block open at one entry must not capture the answer to a LATER stop at S0 (critic t-028).
    RUN1 stops on the incomplete ticket; the person mends the file; RUN2 (no answer) stops on a halt
    that is none of the five blocks; RUN3 answers THAT halt. The answer must take the old conductor
    route and must not be journalled against the ticket block.

    Since t-017 D2 the stand probe no longer halts S0, which is what RUN2 used to meet - so the
    unrelated halt is raised here, in this process, out of the ticket read. An in-process scenario:
    it runs after the pool (a Driver changes the working directory)."""
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Local"}]})
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(bad))
        eq("stale block: RUN1 asks about the incomplete ticket", (out.returncode, s0_state(task_root).get("s0_block")),
           (3, "ticket_incomplete"), out.stdout[-500:])
        bad.write_text(FIXTURE_TICKET, encoding="utf-8")
        driver = driver_for(root, env, task, max_boundaries=0)

        def unrelated(*_args, **_kwargs):
            raise story_run.Person("halt", "Something at the start of the story stopped it, and it is none "
                                   "of the questions S0 keeps a door for. What should happen next?", "S0")
        driver.ticket_get = unrelated
        eq("stale block: RUN2 (no answer) meets the unrelated halt", driver.run(), 3)
        state = s0_state(task_root)
        check("stale block: no S0 block is open any more", not state.get("s0_block") and not state.get("s0_ask"),
              str(state.get("s0_block")))
        set_control(root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        answer = root / "answer.md"
        answer.write_text("the stand is fine, use Local anyway", encoding="utf-8")
        driver = driver_for(root, env, task, answer=str(answer), max_boundaries=0)
        driver.run()
        eq("stale block: RUN3 goes to the conductor (old route)", [c["kind"] for c in stub_calls(root)], ["conductor"])
        check("stale block: the journal does not say ticket_incomplete",
              not any("ticket_incomplete" in str(e.get("notes")) for e in s0_journal(root)), str(s0_journal(root))[-400:])
        check("stale block: the incomplete-ticket question is not shown again",
              not (task_root / "state" / "driver-question.md").exists()
              or "incomplete" not in s0_question(task_root))
    finally:
        harness.cleanup(root)


# --- the person's list of sources not to read, before the run (t-172 / B-231, wave B: P4, C1, C2, C5) --------------
EM = chr(0x2014)      # the dash the owner types between a source and why: `testproject1-ui!1924 - Draft MR ...`
DRAFT = "Draft MR of an earlier factory run, not a product change"
DRAFT_BRANCH = "TP1-15045-visual-workflow-diff-validation"


def _config(root: Path, **blocks) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(blocks)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


UI_REPO = {"repo_id": "testproject1-ui", "local_path": "app", "remote_identity": "git.example/tp1-group/testproject1-ui"}


def _record(task_root: Path) -> dict:
    return json.loads((task_root / "work" / "source-exclusions.json").read_text(encoding="utf-8"))


def _no_record(task_root: Path) -> bool:
    return not (task_root / "work" / "source-exclusions.json").exists()


def s0_source_list_clean() -> None:
    """The cmp2 shape: a list naming `testproject1-ui!1924` and a `ref`, given from ANOTHER folder than the project's
    (the driver changes into the project, so a relative path must have been made absolute first)."""
    from test_story_run_refusals import git_fixture
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        app, sha = git_fixture(root)
        _config(root, implementation_repos=[UI_REPO])
        sub = root / "where-the-person-stands"
        sub.mkdir()
        listed = f"# sources the person left out\ntestproject1-ui!1924 {EM} {DRAFT}\nbranch:{DRAFT_BRANCH} - the branch of that draft MR\n\n"
        (sub / "list.txt").write_bytes(listed.encode("utf-8"))
        out = harness.run_script("story_run.py", "--project", str(root), "--task", task, "--max-boundaries", "0",
                                 "--skip-sources", "list.txt", cwd=sub, env=env)
        eq("list_clean_writes_record_and_lines: S0 goes through: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-800:])
        lines = [ln for ln in out.stdout.splitlines() if ln.startswith("Before the run you asked me not to read")]
        for line in lines:
            print("S0 console: " + line)
        eq("list_clean: one console line per exclusion", len(lines), 2, out.stdout[-800:])
        eq("list_clean: the line for the merge request, in the person's words", lines[0],
           f'Before the run you asked me not to read: testproject1-ui!1924 {EM} "{DRAFT}". Nothing of it is fetched; the source review '
           "and gate A list it.")
        check_in("list_clean: and for the branch", f"branch:{DRAFT_BRANCH}", lines[1])
        record = _record(task_root)
        eq("list_clean: the record holds both words, X1 and X2", [(e["id"], e["as_written"], e["target"]["kind"]) for e in record["exclusions"]],
           [("X1", "testproject1-ui!1924", "mr"), ("X2", f"branch:{DRAFT_BRANCH}", "ref")])
        eq("list_clean: the record's reason is the person's, whole", record["exclusions"][0]["reason"], DRAFT)
        eq("list_clean: C2: the head of the request was asked of the remote and is in the record",
           record["exclusions"][0]["target"]["head_sha"], sha["C"])
        eq("list_clean: the record holds the bytes that were read (list_sha256)", record["list_sha256"],
           hashlib.sha256(listed.encode("utf-8")).hexdigest())
        eq("list_clean: and where the list was read from (absolute: the driver moved to the project)",
           Path(record["list_file"]), (sub / "list.txt").resolve())
        state = s0_state(task_root)
        eq("list_clean: C5a: the flag is kept in the launch", state["launch"].get("skip_sources"), record["list_file"])
        check_eq = eq
        check_eq("list_clean: S0 is done", s0_pipeline(task_root)["stages"]["S0"]["status"], "done")
        findings = s0_findings(root)
        check("C5e: no finding per exclusion (an exclusion is the person's word, not a defect of ours) and no pass finding for a clean list",
              "source-exclusion" not in findings and "source_list" not in findings, findings[-400:])
        check_eq("list_clean: no conductor and no role was called", stub_calls(root), [])
        check("list_clean: nothing outward: the record lives under the story's work/ only",
              (task_root / "work" / "source-exclusions.json").is_file() and not list((root / "qa-factory").glob("*exclusion*")))
        check("list_clean: the pipeline carries no pass for the list (nothing was passed)",
              not any("list of sources" in w for w in s0_pipeline(task_root).get("warnings") or []))
    finally:
        harness.cleanup(root)


def s0_source_list_stops() -> None:
    """A missing file, 11 and 10 problem lines, `retry` after the file changed, and `go on`."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        listed = root / "list.txt"
        out = s0_run(root, env, task, "--skip-sources", str(listed))
        eq("list_missing_file_stops: exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        check_in("list_missing: in the story's words - it cannot be opened", "I cannot open", ask)
        check_in("list_missing: the two doors", "`retry`", ask)
        check_in("list_missing: and `go on`", "`go on`", ask)
        eq("list_missing: the question obeys human-questions.md", rules_broken(ask), [])
        eq("list_missing: the block is remembered", s0_state(task_root).get("s0_block"), "source_list")
        check("list_missing: nothing was fetched and nothing written", not (task_root / "pipeline.json").exists() and _no_record(task_root))
        eq("list_missing: the launch keeps the flag for the entry that follows the answer",
           Path(s0_state(task_root).get("launch", {}).get("skip_sources")).resolve(), listed.resolve())
        out = s0_answer(root, env, task, "retry")
        eq("list_missing: `retry` with the file still missing asks again: exit 3", out.returncode, 3, out.stdout[-500:])

        junk = lambda n: [f"junk{i} {EM} not a source" for i in range(1, n + 1)]
        good = f"testproject1-ui!1924 {EM} {DRAFT}"
        listed.write_text("\n".join(junk(11) + [good]) + "\n", encoding="utf-8")
        out = s0_answer(root, env, task, "retry")
        eq("list_malformed_stops_10_and_11_lines: 11 problems: exit 3", out.returncode, 3, out.stdout[-500:])
        ask = s0_question(task_root)
        eq("list_malformed: 11 problems: ten are listed", len([ln for ln in ask.splitlines() if ln.startswith("- line ")]), 10)
        check_in("list_malformed: and the eleventh is 'and 1 more'", "- and 1 more (all of them are in the file named below)", ask)
        check_in("list_malformed: the fix and the `go on` that applies what could be read", "start the story with the lines I could read", ask)
        check_in("list_malformed: one line of the list is usable", "1 line of the list I can use", ask)
        check_in("list_malformed: all of them are in the details file", "line 11:",
                 (task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8"))
        eq("list_malformed: the question obeys human-questions.md", rules_broken(ask), [])
        listed.write_text("\n".join(junk(10) + [good]) + "\n", encoding="utf-8")
        out = s0_answer(root, env, task, "retry")
        ask = s0_question(task_root)
        eq("list_malformed: 10 problems: exit 3, all ten listed", (out.returncode, len([ln for ln in ask.splitlines() if ln.startswith("- line ")])), (3, 10))
        check_not_in("list_malformed: and no 'and N more'", "more (all of them", ask)
        check_not_in("list_malformed: the file was re-read on `retry` (the 11th line is no longer a problem)", "line 11:", ask)

        out = s0_answer(root, env, task, "go on")
        eq("list_go_on_applies_valid_only: `go on` starts the story: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        record = _record(task_root)
        eq("list_go_on: only the line that read is applied", [(e["as_written"], e["line"]) for e in record["exclusions"]],
           [("testproject1-ui!1924", 11)])
        check("list_go_on: the pass is on the record as the person's word",
              any("list of sources not to read passed by the person's word" in w for w in s0_pipeline(task_root)["warnings"]),
              str(s0_pipeline(task_root)["warnings"]))
        check("list_go_on: and filed as a finding, once (the S0 pass machinery)", s0_findings(root).count("s0-pass:QA-1:source_list") <= 1
              and "source_list passed by the person's word" in s0_findings(root), s0_findings(root)[-600:])
        eq("list_go_on: no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)


def s0_source_list_kinds() -> None:
    """C5 (c)(d): `go on` applies the lines whose TARGET read, even with no reason or a reason that starts like a
    target; a separator makes the reason a reason; the story's own ticket and a bare `!N` are never applied."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        listed = root / "list.txt"
        listed.write_text("\n".join([
            "testproject1-ui!1924",                                                # 1: no reason
            "testproject1-ui!1881 TP1-13289 - x",                              # 2: a reason that starts like a target
            f"QA-1 {EM} the ticket itself",                                   # 3: the story's own ticket
            f"testproject1-ui!1700 {EM} testproject1-ui!1701 was the old one",          # 4: the separator makes it a reason
            f"!4243 {EM} no project",                                         # 5: bare !N
            f"TP1-99 {EM} fine",                                          # 6
            f"1234abcd {EM} a commit id shorter than 12 characters",          # 7: could name other commits (C2)
        ]) + "\n", encoding="utf-8")
        out = s0_run(root, env, task, "--skip-sources", str(listed))
        eq("list_ticket_itself_stops: exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        eq("list_kinds: five problems are listed", len([ln for ln in ask.splitlines() if ln.startswith("- line ")]), 5, ask)
        check_in("list_kinds: C2: a commit id shorter than 12 characters is a problem, never a match", "line 7:", ask)
        check_in("list_ticket_itself_stops: the ticket itself is named as one", "line 3:", ask)
        check_in("list_kinds: the bare `!N` asks for its project", "line 5:", ask)
        check_not_in("list_kinds: line 4 is no problem (the separator was there)", "line 4:", ask)
        check_in("list_kinds: four of the seven lines are usable (the ones whose target read)", "4 lines of the list I can use", ask)
        eq("list_kinds: the question obeys human-questions.md", rules_broken(ask), [])
        out = s0_answer(root, env, task, "go on")
        eq("list_kinds: `go on`: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        rows = [(e["as_written"], e["reason"]) for e in _record(task_root)["exclusions"]]
        eq("list_kinds: applied are the lines whose target read, in line order, with the reasons whole", rows, [
            ("testproject1-ui!1924", ""), ("testproject1-ui!1881", "TP1-13289 - x"), ("testproject1-ui!1700", "testproject1-ui!1701 was the old one"),
            ("TP1-99", "fine")])
        check("list_kinds: the story's own ticket and the bare !N are in no exclusion",
              not any(e["as_written"] in ("QA-1", "!4243") for e in _record(task_root)["exclusions"]))
        check("list_kinds: C2: no checkout is configured, and that is PRINTED for each merge request (the word is kept without a head)",
              out.stdout.count("no local checkout of `testproject1-ui` is configured") == 3, out.stdout[-900:])
        check("list_kinds: the heads stay null", all(e["target"].get("head_sha") is None
                                                     for e in _record(task_root)["exclusions"] if e["target"]["kind"] == "mr"))
    finally:
        harness.cleanup(root)


def s0_source_list_mr_flag() -> None:
    """F10 / C5b: `--mr` naming a merge request the list leaves out is its own question, `read` or `skip`."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        listed = root / "list.txt"
        listed.write_text(f"testproject1-ui!1924 {EM} {DRAFT}\n", encoding="utf-8")
        out = s0_run(root, env, task, "--skip-sources", str(listed), "--mr", "!1924")
        eq("list_mr_flag_conflict_stops: a bare --mr !N equal to the word's number: exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        check_in("list_mr_flag: the question names both words", "testproject1-ui!1924", ask)
        check_in("list_mr_flag: its own two doors", "`read`", ask)
        check_in("list_mr_flag: (b)", "`skip`", ask)
        check_not_in("list_mr_flag: never `go on` - the two words of one person do not resolve silently", "`go on`", ask)
        eq("list_mr_flag: the question obeys human-questions.md", rules_broken(ask), [])
        check("list_mr_flag: nothing was written before the answer", _no_record(task_root) and not (task_root / "pipeline.json").exists())
        set_control(root, NO_USABLE)
        out = s0_answer(root, env, task, "go on", "--mr", "!1924")
        asked = s0_question(task_root)
        check_in("list_mr_flag: `go on` is not one of its answers: asked again, changed (the one lead, then the question as it was)",
                 'Your answer "go on" ' + UNREAD_LEAD, asked)
        check("list_mr_flag: ... with its own two doors as priced option lines, and `go on` offered nowhere",
              "`read` — " in asked and "`skip` — " in asked and "`go on`" not in asked.split("## What each answer costs and does")[-1]
              and price_broken(asked) == [], asked[-700:])
        eq("list_mr_flag: ... after exactly one conductor call (D-0041)", conductor_count(root), 1)
        out = s0_answer(root, env, task, "`skip`", "--mr", "!1924")
        eq("list_mr_flag: `skip`: the story goes on: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        eq("list_mr_flag: `skip`: the word stays", [e["as_written"] for e in _record(task_root)["exclusions"]], ["testproject1-ui!1924"])
        launch = s0_state(task_root)["launch"]
        check("list_mr_flag: `skip` drops the flag (kept apart, so the scout's launch flags do not show it)",
              "mr" not in launch and launch.get("mr_dropped") == "!1924", str(launch))
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project(task)
    try:
        listed = root / "list.txt"
        listed.write_text(f"testproject1-ui!1924 {EM} {DRAFT}\n", encoding="utf-8")
        out = s0_run(root, env, task, "--skip-sources", str(listed), "--mr",
                     "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924")
        eq("list_mr_flag: the same request as a link: exit 3", out.returncode, 3, out.stdout[-500:])
        out = s0_answer(root, env, task, "read", "--mr", "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924")
        eq("list_mr_flag: `read`: exit 0", out.returncode, 0, out.stdout[-1500:] + out.stderr[-600:])
        eq("list_mr_flag: `read`: its line of the list is not applied", _record(task_root)["exclusions"], [])
        check_in("list_mr_flag: and the person is told so", "you chose to read it, so its line of the list is not applied", out.stdout)
        check_not_in("list_mr_flag: not 'the list names no source', which would be untrue", "the list names no source", out.stdout)
        check("list_mr_flag: `read` keeps the flag", s0_state(task_root)["launch"].get("mr", "").endswith("/1924"))
    finally:
        harness.cleanup(root)


def s0_source_list_inventory() -> None:
    """C1: the flag on a story whose inventory exists is a question, never a line in passing - at S0 (no
    pipeline.json yet) and after S0; a resume WITHOUT the flag is unchanged; with no inventory the flag prints."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        listed = root / "list.txt"
        listed.write_text(f"testproject1-ui!1924 {EM} {DRAFT}\n", encoding="utf-8")
        (task_root / "work").mkdir(parents=True)
        inventory = task_root / "work" / "source-inventory.json"
        inventory.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        out = s0_run(root, env, task, "--skip-sources", str(listed))
        eq("list_flag_with_inventory_asks (at S0): exit 3", out.returncode, 3, out.stdout[-800:])
        ask = s0_question(task_root)
        check_in("list_flag_with_inventory: says the sources were already collected", "were already collected on", ask)
        check_in("list_flag_with_inventory: and what a person can do now: name them at the source review", "source review", ask)
        check_in("list_flag_with_inventory: the one door is `go on`", "`go on`", ask)
        check_not_in("list_flag_with_inventory: `retry` is no door here (the file changes nothing)", "`retry`", ask)
        eq("list_flag_with_inventory: the question obeys human-questions.md", rules_broken(ask), [])
        check("list_flag_with_inventory: nothing is written", _no_record(task_root) and not (task_root / "pipeline.json").exists())
        check_in("list_flag_with_inventory: option (b) is the `stop` door, as a priced option line",
                 "(b) `stop` — stop here and start the story again from a fresh copy", ask)
        eq("list_flag_with_inventory: every option has its three price lines", price_broken(ask), [])
        out = s0_answer(root, env, task, "stop")
        eq("list_flag_with_inventory: `stop` holds the question: exit 3", out.returncode, 3, out.stdout[-800:])
        held = s0_question(task_root)
        check_in("list_flag_with_inventory: the first line says nothing runs", "You said to stop. Nothing runs and nothing is spent.", held)
        check_in("list_flag_with_inventory: and the question is the same one", "were already collected on", held)
        check("list_flag_with_inventory: stop: the block is open, no words kept, nothing written, no conductor",
              s0_state(task_root).get("s0_block") == "source_list" and "S0" not in (s0_state(task_root).get("pending_words") or {})
              and _no_record(task_root) and not (task_root / "pipeline.json").exists() and stub_calls(root) == [])
        out = s0_answer(root, env, task, "go on")
        eq("list_flag_with_inventory: `go on`: the list is ignored and S0 goes through: exit 0", out.returncode, 0,
           out.stdout[-1200:] + out.stderr[-500:])
        check_in("list_flag_with_inventory: and says so", "the list of sources not to read is ignored for this story", out.stdout)
        check("list_flag_with_inventory: still no record", _no_record(task_root))
        check("list_flag_with_inventory: the pass is on the pipeline's warnings",
              any("list of sources not to read passed by the person's word" in w for w in s0_pipeline(task_root)["warnings"]))

        # S0 is over and the inventory is there: the same flag on a command line is the same question (C1)
        out = s0_run(root, env, task, "--skip-sources", str(listed))
        eq("list_flag_after_s0 (inventory exists): exit 3, not a line in passing", out.returncode, 3, out.stdout[-800:])
        eq("list_flag_after_s0: the block is the same one", s0_state(task_root).get("s0_block"), "source_list")
        check_in("list_flag_after_s0: the same question", "were already collected on", s0_question(task_root))
        out = s0_answer(root, env, task, "stop")
        eq("list_flag_after_s0: `stop` is read by `skip_sources_late` (S0 is over): the question is held, exit 3", out.returncode, 3, out.stdout[-800:])
        check_in("list_flag_after_s0: with the first line that says nothing runs", "You said to stop. Nothing runs and nothing is spent.", s0_question(task_root))
        eq("list_flag_after_s0: the block is still `source_list` and no conductor was called",
           (s0_state(task_root).get("s0_block"), stub_calls(root)), ("source_list", []))
        out = s0_answer(root, env, task, "go on")
        eq("list_flag_after_s0: `go on` is read (no conductor): exit 0", out.returncode, 0, out.stdout[-800:] + out.stderr[-400:])
        check_not_in("list_flag_after_s0: no conductor was called", "conductor", json.dumps(stub_calls(root)))
        eq("list_flag_after_s0: the block is closed", s0_state(task_root).get("s0_block"), None)
        check("list_flag_after_s0: still no record, and the answer is on the pipeline's warnings",
              _no_record(task_root) and any("passed by the person's word" in w for w in s0_pipeline(task_root)["warnings"]))
        out = s0_run(root, env, task, "--skip-sources", str(listed))
        eq("list_flag_after_s0: asked and answered once: the same flag again asks nothing", out.returncode, 0, out.stdout[-600:])
        out = s0_run(root, env, task)
        eq("a resume WITHOUT the flag is unchanged: exit 0, no question", out.returncode, 0, out.stdout[-600:])
        check_not_in("a resume without the flag says nothing about the list", "list of sources", out.stdout)

        # no inventory yet: one printed line, nothing written (the list is read only when a story starts)
        inventory.unlink()
        out = s0_run(root, env, task, "--skip-sources", str(listed))
        eq("list_flag_after_s0 (no inventory): exit 0", out.returncode, 0, out.stdout[-600:])
        check_in("list_flag_after_s0_prints_only: the line says it is read only when a story starts",
                 "is read only when a story starts; this story started", out.stdout)
        check_in("list_flag_after_s0_prints_only: and names the door", "at the source review, name the sources to leave out", out.stdout)
        check("list_flag_after_s0_prints_only: nothing is written and nothing is asked", _no_record(task_root)
              and s0_state(task_root).get("s0_block") is None)
    finally:
        harness.cleanup(root)


def s0_source_list_units() -> None:
    """The pieces of P4 in this process: the head lookup (C2) and what it prints when it fails, the `--mr`
    comparison, and the entries' merge."""
    import contextlib
    import io
    import os
    import subprocess
    import story_run
    from test_story_run_refusals import git_fixture
    check_eq = eq
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        app, sha = git_fixture(root)
        _config(root, implementation_repos=[UI_REPO, {"repo_id": "testproject1", "local_path": "app",
                                                      "remote_identity": "git.example/tp1-group/testproject1"}])
        driver = driver_for(root, env, task)
        check_eq("C2: one ask of the remote, ten seconds at most", story_run.Driver.LS_REMOTE_SECONDS, 10)

        def head(project="tp1-group/testproject1-ui", iid="1924"):
            entry = {"as_written": f"{project.rsplit('/', 1)[-1]}!{iid}", "target": {"kind": "mr", "host": None, "project": project,
                                                                                      "iid": iid, "head_sha": None, "branch": None}}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                driver.s0_resolve_head(entry)
            return entry["target"]["head_sha"], out.getvalue()

        check_eq("C2: ls-remote against the local bare remote resolves the head commit", head()[0], sha["C"])
        value, printed = head(iid="999")
        check("C2: a request the remote does not list: no head, printed, the word is kept",
              value is None and "could not be looked up" in printed and "holds by the number" in printed, printed)
        value, printed = head(project="tp1-group/unknown-repo")
        check("C2: no checkout of that project: no head, printed", value is None and "no local checkout of `unknown-repo`" in printed, printed)
        check_eq("C2: the tail is compared WHOLE: `testproject1` is not `testproject1-ui` (its own entry answers for it)",
                 driver.repo_of_project("tp1-group/testproject1")[0], "testproject1")
        check_eq("C2: and the ui project finds the ui entry", driver.repo_of_project("testproject1-ui")[0], "testproject1-ui")

        # B-231 fix 3: a `branch:` word is resolved to the commit of that branch on the remote, in the same way
        subprocess.run(["git", "-C", str(app), "branch", "feature/x", sha["B"]], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(app), "push", "-q", "origin", "feature/x"], check=True, capture_output=True)

        def branch_sha(name, d=None):
            entry = {"as_written": f"branch:{name}", "target": {"kind": "ref", "sha": None, "branch": name}}
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                (d or driver).s0_resolve_branch(entry)
            return entry["target"]["sha"], out.getvalue()

        check_eq("branch word: a branch of the remote resolves to its commit", branch_sha("feat")[0], sha["C"])
        check_eq("branch word: a name with a slash is passed as refs/heads/feature/x", branch_sha("feature/x")[0], sha["B"])
        value, printed = branch_sha("nope")
        check("branch word: a branch the remote does not list: no commit, one line, the word kept",
              value is None and "could not be looked up" in printed and "holds by the branch name" in printed, printed)
        value, printed = branch_sha("x")
        check("branch word: the last segment of another branch's name (`x` of `feature/x`) is not that branch",
              value is None and "could not be looked up" in printed, printed)
        entry = {"as_written": "a" * 12, "target": {"kind": "ref", "sha": "a" * 40, "branch": None}}
        with contextlib.redirect_stdout(io.StringIO()):
            driver.s0_resolve_branch(entry)
        check_eq("branch word: a commit word is left as it is", entry["target"]["sha"], "a" * 40)
        # two repositories that keep different commits under one branch name: in doubt, no commit
        git_env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        remote2, app2 = root / "remote2.git", root / "app2"
        for args in (["init", "-q", "--bare", str(remote2)], ["init", "-q", str(app2)]):
            subprocess.run(["git", *args], check=True, capture_output=True)
        for args in (["checkout", "-q", "-b", "feat"], ["remote", "add", "origin", str(remote2)]):
            subprocess.run(["git", "-C", str(app2), *args], check=True, capture_output=True)
        (app2 / "other.txt").write_text("other", encoding="utf-8")
        for args in (["add", "-A"], ["commit", "-q", "-m", "another repository"], ["push", "-q", "origin", "feat"]):
            subprocess.run(["git", "-C", str(app2), *args], check=True, capture_output=True, env=git_env)
        _config(root, implementation_repos=[UI_REPO, {"repo_id": "other", "local_path": "app2", "remote_identity": "x/other"}])
        driver_two = driver_for(root, env, task)
        value, printed = branch_sha("feat", driver_two)
        check("branch word: two repositories with different commits under one name: no commit, printed",
              value is None and "different commit" in printed, printed)
        check_eq("branch word: a name only one of the two repositories lists resolves to that one", branch_sha("feature/x", driver_two)[0], sha["B"])
        _config(root, implementation_repos=[UI_REPO, {"repo_id": "testproject1", "local_path": "app",
                                                      "remote_identity": "git.example/tp1-group/testproject1"}])
        # the wiring: S0 writes the record with the commit of the branch word (not only a helper that nobody calls)
        import source_exclusions as SE
        text_word = f"branch:feat {EM} the branch of that draft MR\n".encode("utf-8")
        entries_word, _p = SE.parse_bytes(text_word, task)
        with contextlib.redirect_stdout(io.StringIO()):
            driver.s0_write_list(SE, entries_word, "w.txt", text_word)
        check_eq("branch word: S0 writes the record with the commit of the branch (it is wired in, not just written)",
                 SE.read_record(task_root / "work")["exclusions"][0]["target"]["sha"], sha["C"])

        driver.LS_REMOTE_SECONDS = 0.001
        value, printed = head()
        check("C2: a remote that does not answer in time: printed, no head, the word kept",
              value is None and "did not answer within" in printed, printed)
        value, printed = branch_sha("feat")
        check("branch word: a remote that does not answer in time: printed, no commit, the word kept",
              value is None and "did not answer within" in printed and "holds by the branch name" in printed, printed)
        driver.LS_REMOTE_SECONDS = 10
        subprocess.run(["git", "-C", str(app), "remote", "set-url", "origin", str(root / "no-such-remote.git")], check=True, capture_output=True)
        value, printed = head()
        check("C2: a remote that fails: printed with its own words, no head", value is None and "could not be looked up (" in printed, printed)
        value, printed = branch_sha("feat")
        check("branch word: a remote that fails: printed with its own words, no commit", value is None and "could not be looked up (" in printed, printed)
        subprocess.run(["git", "-C", str(app), "remote", "remove", "origin"], check=True, capture_output=True)
        value, printed = branch_sha("feat")
        check("branch word: no remote at all in the implementation repository: no commit, printed, never a refusal",
              value is None and "could not be looked up (" in printed, printed)

        # s0_write_list: one record per list. The same bytes on a later S0 entry are a no-op (no second head lookup);
        # other bytes (the person edited the file between two stops) REPLACE an unrevoked record - S0 is the only
        # writer and nothing has been read yet, so the `--load` refusal for "another list" does not apply here;
        # a record that holds a revocation is kept and the person is told.
        import source_exclusions as SE
        asked = []
        driver.s0_resolve_head = lambda entry: asked.append(entry["as_written"])
        text_a, text_b = f"testproject1-ui!1924 {EM} first\n".encode("utf-8"), f"testproject1-ui!1881 {EM} second\n".encode("utf-8")
        entries_a, _p = SE.parse_bytes(text_a, task)
        entries_b, _p = SE.parse_bytes(text_b, task)
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            driver.s0_write_list(SE, entries_a, "a.txt", text_a)
            driver.s0_write_list(SE, entries_a, "a.txt", text_a)
        check_eq("s0_write_list: the same bytes twice: one write, one head lookup, one console line",
                 (asked, shown.getvalue().count("Before the run you asked me not to read")), (["testproject1-ui!1924"], 1))
        with contextlib.redirect_stdout(io.StringIO()):
            driver.s0_write_list(SE, entries_b, "b.txt", text_b)
        record = SE.read_record(task_root / "work")
        check_eq("s0_write_list: other bytes replace an unrevoked record (no ListRefused, no stale word)",
                 ([e["as_written"] for e in record["exclusions"]], record["list_sha256"]),
                 (["testproject1-ui!1881"], hashlib.sha256(text_b).hexdigest()))
        SE.revoke(task_root, "X1", "I want it read after all")
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            driver.s0_write_list(SE, entries_a, "a.txt", text_a)
        check("s0_write_list: a record that holds a revocation is kept as it is, and the person is told",
              SE.read_record(task_root / "work")["list_sha256"] == hashlib.sha256(text_b).hexdigest()
              and "holds a word you took back" in shown.getvalue(), shown.getvalue())

        # mr_conflicts: F10 / C5b
        entries = [{"as_written": "testproject1-ui!1924", "target": {"kind": "mr", "host": None, "project": "testproject1-ui", "iid": "1924"}, "reason": "x"},
                   {"as_written": "TP1-9", "target": {"kind": "ticket", "key": "TP1-9", "host": None}, "reason": "y"}]
        hit = lambda value: [e["as_written"] for e in story_run.Driver.mr_conflicts(value, entries)]
        check_eq("mr_conflicts: a bare !N equal by number", hit("!1924"), ["testproject1-ui!1924"])
        check_eq("mr_conflicts: a bare number with no bang", hit("1924"), ["testproject1-ui!1924"])
        check_eq("mr_conflicts: leading zeros are the same number", hit("!01924"), ["testproject1-ui!1924"])
        check_eq("mr_conflicts: the link of the same request", hit("https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"),
                 ["testproject1-ui!1924"])
        check_eq("mr_conflicts: the short form of the same request", hit("tp1-group/testproject1-ui!1924"), ["testproject1-ui!1924"])
        check_eq("mr_conflicts: another number is no conflict", hit("!19"), [])
        check_eq("mr_conflicts: a number inside a longer number is no conflict", hit("!19240"), [])
        check_eq("mr_conflicts: another project's short form is no conflict", hit("testproject1!1924"), [])
        check_eq("mr_conflicts: another request's link is no conflict", hit("https://git.example/tp1-group/testproject1-ui/-/merge_requests/1881"), [])
        check_eq("mr_conflicts: a ticket word is no merge request", hit("TP1-9"), [])

        # merge_list_entries: the same thing named twice keeps every reason and every line
        clean = [{"line": 3, "as_written": "testproject1-ui!1924", "target": dict(entries[0]["target"]), "reason": "first"}]
        loose = [{"line": 7, "as_written": "testproject1-ui!1924", "target": dict(entries[0]["target"]), "reason": "second"},
                 {"line": 1, "as_written": "TP1-9", "target": dict(entries[1]["target"]), "reason": ""}]
        merged = story_run.Driver.merge_list_entries(clean, loose)
        check_eq("merge_list_entries: line order, one entry per thing", [e["as_written"] for e in merged], ["TP1-9", "testproject1-ui!1924"])
        check_eq("merge_list_entries: both reasons and both lines are kept", (merged[1]["reason"], merged[1]["line"]), ("first | second", [3, 7]))
        check_eq("merge_list_entries: the clean entry passed in is not changed", clean[0]["reason"], "first")
    finally:
        harness.cleanup(root)


def s0_excluded_heads() -> None:
    """B-231 fix 3: `excluded_heads` holds only real commits. A null head (the lookup failed) is no head - it
    once became the word 'None' and `git_route` ran a rev-parse of it for every commit it listed."""
    import source_exclusions as SE
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        check_eq = eq
        check_eq("excluded_heads_null_head: no record: no heads", driver.excluded_heads(), [])
        one, two = "a" * 40, "b" * 40

        def write(text, heads):
            entries, problems = SE.parse_bytes(text.encode("utf-8"), task)
            check_eq("excluded_heads fixture: the list reads clean", problems, [])
            for entry in entries:
                if entry["target"]["kind"] == "mr":
                    entry["target"]["head_sha"] = heads.get(entry["as_written"])
            record = SE.record_path(task_root / "work")
            if record.exists():
                record.unlink()
            SE.write_record(task_root, entries, "list.txt", text.encode("utf-8"))

        write(f"testproject1-ui!1924 {EM} a\n", {"testproject1-ui!1924": None})
        check_eq("excluded_heads_null_head: a merge request whose head is null gives no head at all", driver.excluded_heads(), [])
        write(f"{two} {EM} a commit\n", {})
        check_eq("excluded_heads_null_head: a commit word gives its commit", driver.excluded_heads(), [two])
        write(f"testproject1-ui!1924 {EM} a\nbranch:feat {EM} b\ntestproject1-ui!1881 {EM} c\n",
              {"testproject1-ui!1924": None, "testproject1-ui!1881": one})
        check_eq("excluded_heads_null_head: a branch word with no commit (still null) and a null head are skipped, the real head stays",
                 driver.excluded_heads(), [one])
        write(f"testproject1-ui!1924 {EM} a\ntestproject1-ui!1881 {EM} b\n{two} {EM} c\ntestproject1-ui!1700 {EM} d\nbranch:feat {EM} e\n",
              {"testproject1-ui!1924": None, "testproject1-ui!1881": one, "testproject1-ui!1700": one})
        heads = driver.excluded_heads()
        check_eq("excluded_heads_null_head: in record order, a head shared by two requests once, never the word 'None'",
                 (heads, "None" in heads), ([one, two], False))
    finally:
        harness.cleanup(root)


def s0_source_list_texts() -> None:
    """B-231 fixes 4 and 6: what the two questions say is what `go on` does (FR-10), and the question of a story
    whose source review is over does not promise that review."""
    import source_exclusions as SE
    import story_run
    check_eq = eq
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)

        def ask(text):
            listed = root / "q-list.txt"
            listed.write_text(text, encoding="utf-8")
            try:
                driver.s0_source_list({"skip_sources": str(listed), "mr": None})
            except story_run.Person as person:
                return person.text
            return ""

        no_reason = "testproject1-ui!1924\n"
        unread = f"junk {EM} not a source\n"
        a, b, c = ask(no_reason), ask(unread), ask(no_reason + unread + f"TP1-99 {EM} fine\n")
        check_eq("list_no_reason_text: (a) a line with a target and no reason: it IS applied on `go on`, and the question says so",
                 ("1 line names a source I can read but has a problem" in a, "applied anyway and the problem is noted" in a,
                  "no source I can read" in a), (True, True, False))
        check_eq("list_no_reason_text: (b) a line whose target could not be read: it is NOT applied, and the question says so",
                 ("1 line names no source I can read: it is not applied" in b, "applied anyway" in b), (True, False))
        check_eq("list_no_reason_text: (c) both groups, each with its own count",
                 ("1 line names no source I can read: it is not applied" in c,
                  "1 line names a source I can read but has a problem" in c, "2 lines of the list I can use" in c), (True, True, True))
        # (`no_how_to_answer` is the block `ask()` appends under the text; this reads the text before it)
        body_problems = lambda text: [r for r in rules_broken(text) if r != "no_how_to_answer"]
        check_eq("list_no_reason_text: the questions obey human-questions.md", [body_problems(t) for t in (a, b, c)], [[], [], []])
        many = "".join(f"junk{i} {EM} x\n" for i in range(11)) + "testproject1-ui!1\ntestproject1-ui!2\n"
        d = ask(many)
        check_eq("list_no_reason_text: the counts are of ALL the lines, the list shown is capped at ten",
                 (len([ln for ln in d.splitlines() if ln.startswith("- line ")]), "11 lines name no source I can read" in d,
                  "2 lines name a source I can read but have a problem" in d), (10, True, True))
        check_eq("list_no_reason_text: the `go on` door is unchanged", ("`retry`" in a, "`go on`" in a), (True, True))

        # fix 6: the list after the inventory exists
        inventory = task_root / "work" / "source-inventory.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        inventory.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")

        def too_late():
            try:
                driver.s0_list_too_late()
            except story_run.Person as person:
                return person.text, person.details
            return "", ""

        open_text, open_details = too_late()
        check_in("list_too_late_after_s1: S1 still open: the source review is promised (today's text)", "at the source review", open_text)
        check_eq("list_too_late_after_s1: S1 still open: no details file", open_details, "")
        state = task_root / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "controller.json").write_text(json.dumps({"stages": {"S1": {"status": "completed"}}}), encoding="utf-8")
        done_text, done_details = too_late()
        check("list_too_late_after_s1: S1 completed: the text differs", done_text != open_text)
        check_not_in("list_too_late_after_s1: S1 completed: the review is not promised", "at the source review", done_text)
        check_in("list_too_late_after_s1: and it says nothing already read is un-read", "Nothing that was already read is un-read", done_text)
        check_in("list_too_late_after_s1: and where the person's word can still go: gate A, in their own words", "at gate A", done_text)
        check_in("list_too_late_after_s1: the `go on` door is still there, as a priced option line", "(a) `go on` — the story goes on and the list is ignored", done_text)
        check_in("list_too_late_after_s1: and the 'start again from a fresh copy' option is now the `stop` door (it had none)",
                 "(b) `stop` — stop here and start the story again from a fresh copy", done_text)
        check_in("list_too_late_after_s1: with the sentence that a list is read only when a story starts", "a list is read only when a story starts", done_text)
        check_eq("list_too_late_after_s1: every option has its three price lines", price_broken(done_text), [])
        check_eq("list_too_late_after_s1: the doors the next answer reads are `go on` and `stop`", sorted(driver.state["s0_ask"]["doors"]), ["go on", "stop"])
        check_eq("list_too_late_after_s1: S1 completed: the question obeys human-questions.md (no script, no flag in its body)",
                 body_problems(done_text), [])
        check_in("list_too_late_after_s1: the exact command that records the person's word is in the details file - the remark door "
                 "(C1-4b: the conductor never records a gate decision, I6)", f"waiver.py --task {driver.task} --remark --stage S0", done_details)
        check_not_in("list_too_late_after_s1: and it no longer sends the conductor to the gate decision", "--operation gate-decision", done_details)
        original = SE.s1_completed

        def broken(_task_root):
            raise ValueError("pipeline unreadable")
        SE.s1_completed = broken
        try:
            raised_text, _d = too_late()
        finally:
            SE.s1_completed = original
        check_eq("list_too_late_after_s1: a pipeline that cannot be read is not 'completed': today's text", raised_text, open_text)
    finally:
        harness.cleanup(root)


# --- t-281: the paste leg (F1, F2, F4, F5) and the owners of a failed read (F3) ----------------------------------------
BROWSER_COPY = ("Items can carry tags\n\nAs a warehouse operator I want tags (see QA-77).\n\nAcceptance criteria\n\n"
                "- A tag can be added to an item.\n- A tag can be removed from an item.\n")


def s0_title_question() -> None:
    """K-F2: a text with NO `# ` line (what a browser copy is) is not a dead end: the adapter takes the first line as the
    title and the driver asks the person ONCE (`ticket_title`); `go on` is a pass recorded once and a rerun is silent;
    `retry` after they added a title line reads the file again and asks nothing."""
    task = "QA-1"
    root, task_root, env = s0_project(task, git=False)          # no git: readiness stops S0 once, so there is a rerun
    try:
        browser = root / "browser-copy.md"
        browser.write_bytes(BROWSER_COPY.encode("utf-8"))
        out = s0_run(root, env, task, "--ticket-file", str(browser))
        eq("K-F2: a text with no `# ` line asks about the title (never a refusal): exit 3, block `ticket_title`",
           (out.returncode, s0_state(task_root).get("s0_block"), "carries no title" in out.stdout), (3, "ticket_title", False), out.stdout[-900:])
        ask = s0_question(task_root)
        check("K-F2: the question says what was taken as the title, that `go on` keeps it, and the way to add a title line and `retry`",
              all(part in ask for part in ('"Items can carry tags"', "I took its first line as the title",
                                           "(a) `go on` — that line will do as the title", "line that starts with `# `",
                                           "(b) `retry` — put the title ", "(c) paste the ticket again with a title",
                                           "(d) `stop` — stop the story here; nothing runs")), ask)
        eq("K-F2: every option has its three price lines", price_broken(ask), [])
        eq("K-F2: the question obeys human-questions.md", rules_broken(ask), [])
        eq("K-F2: nothing is written before the person answers", ((task_root / "pipeline.json").exists(), (task_root / "work" / "ticket-snapshot.json").exists()), (False, False))
        out = s0_answer(root, env, task, "go on")
        eq("K-F2: `go on` keeps the title; S0 goes on and readiness (no git here) asks next: exit 3", (out.returncode, s0_state(task_root).get("s0_block")), (3, "readiness"), out.stdout[-900:])
        snapshot = snapshot_of(task_root)
        eq("K-F2: the snapshot has the first line as its title, `title_from` first_line, and the 2 criteria of the paste (read by the same parser)",
           (snapshot["title"], snapshot["provenance"].get("title_from"), snapshot["acceptance_criteria"]),
           ("Items can carry tags", "first_line", ["A tag can be added to an item.", "A tag can be removed from an item."]))
        out = s0_answer(root, env, task, "go on")
        eq("K-F2: the rerun after the readiness answer does NOT ask about the title again (the pass survives the rerun): exit 0", out.returncode, 0, out.stdout[-900:] + out.stderr[-400:])
        passes = [w for w in s0_pipeline(task_root)["warnings"] if "passed by the person's word" in w]
        check_in("K-F2: the pass is a line of the story's record, once", "S0: the ticket-title check passed by the person's word: \"go on\"", passes)
        eq("K-F2: and filed once as a finding in the person's words (FR-4)", s0_findings(root).count("idempotency:s0-pass:QA-1:ticket_title"), 1)
        eq("K-F2: no conductor", stub_calls(root), [])
    finally:
        harness.cleanup(root)
    # the door `retry`: they add the title line to their file and the question does not come back
    root, task_root, env = s0_project(task)
    try:
        browser = root / "browser-copy.md"
        browser.write_bytes(BROWSER_COPY.encode("utf-8"))
        s0_run(root, env, task, "--ticket-file", str(browser))
        eq("K-F2 setup: asked about the title", s0_state(task_root).get("s0_block"), "ticket_title")
        browser.write_bytes(("# Items can carry tags\n\n" + BROWSER_COPY.split("\n\n", 1)[1]).encode("utf-8"))
        out = s0_answer(root, env, task, "retry", "--ticket-file", str(browser))
        eq("K-F2: after a `# ` title line is added, `retry` reads the file again, asks nothing and finishes: exit 0", out.returncode, 0, out.stdout[-900:] + out.stderr[-400:])
        snapshot = snapshot_of(task_root)
        eq("K-F2: the title is the `# ` line now, with no `title_from`; no pass was recorded",
           ("title_from" in snapshot["provenance"], "ticket_title" in s0_findings(root)), (False, False))
    finally:
        harness.cleanup(root)


def s0_pasted_description_15045() -> None:
    """K-F1 through the driver: the real 15045 description pasted as the answer of the incomplete-ticket question gives its
    15 criteria (item 1 and 15 verbatim) - the same parser as the tracker's description. A heading-less paste stays 0."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        s0_run(root, env, task, "--ticket-file", str(bad))
        issue = json.loads(RAW_15045.decode("utf-8"))["fields"]
        out = s0_answer(root, env, task, "# " + issue["summary"] + "\n\n" + issue["description"], "--ticket-file", str(bad))
        eq("K-F1: the 15045 description pasted as the answer: S0 finishes, exit 0 (the criteria are found, so there is no question)", out.returncode, 0, out.stdout[-900:] + out.stderr[-400:])
        snapshot = snapshot_of(task_root)
        items = snapshot["acceptance_criteria"]
        eq("K-F1: 15 criteria, item 1 and item 15 verbatim, `person_pasted`", (len(items), items[0], items[-1], snapshot["provenance"]["source"]),
           (15, "Visual revision diff opens from workflow version history.", "Existing workflow versioning/text diff behavior is not regressed.", "person_pasted"))
        check("K-F1: no glue of the next section into item 15", "QA Factory evaluation goals" not in items[-1])
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        s0_run(root, env, task, "--ticket-file", str(bad))
        out = s0_answer(root, env, task, "# A title\n\nA story.\n\n- one\n- two\n", "--ticket-file", str(bad))
        eq("K-F1n / D-0050: a heading-less paste has no criteria section: S0 goes on, no question (the lost-read ticket asked first; the paste answers it)",
           (out.returncode, s0_state(task_root).get("s0_block")), (0, None), out.stdout[-600:])
        check_in("K-F1n: and the story's first line says no section was found", "S0: ticket QA-1 has no section named", s0_pipeline(task_root)["warnings"][0])
    finally:
        harness.cleanup(root)


def s0_ticket_file_precedence() -> None:
    """K-F2c: a `--ticket-file` on the command line that is NEWER than the stored paste wins; the stored paste wins when the
    command line carries none (or only the flag it was answered under)."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        newer = root / "newer.md"
        newer.write_text(FIXTURE_TICKET.replace("Items can carry tags", "Items carry tags (the newer file)"), encoding="utf-8")
        s0_run(root, env, task, "--ticket-file", str(bad))
        out = s0_answer(root, env, task, "# A pasted title\n\n## Acceptance criteria\n\nNo criteria in what I typed.\n", "--ticket-file", str(bad))
        eq("K-F2c setup: the paste (with the launch flag repeated beside it) is the ticket now; it has no criteria, so the same block asks again",
           (out.returncode, s0_state(task_root).get("s0_block"), (s0_state(task_root).get("s0_answers") or {}).get("ticket_file_cli")), (3, "ticket_incomplete", str(bad)))
        eq("t-287 item 6 (end to end): that entry said ONCE that the stored paste is read, with its file and the door that replaces it",
           out.stdout.count("reading the ticket text you gave earlier (qa-factory/artifacts/QA-1/state/driver-tmp/ticket-QA-1.md); give a different --ticket-file to replace it"), 1, out.stdout[-900:])
        out = s0_run(root, env, task, "--ticket-file", str(newer))
        check_not_in("t-287 item 6 (end to end): a NEW flag is the newer word and the line is not said", "reading the ticket text you gave earlier", out.stdout)
        eq("K-F2c: a NEW `--ticket-file` on the command line wins over the stored paste: S0 finishes with the newer file's ticket",
           (out.returncode, snapshot_of(task_root)["title"]), (0, "Items carry tags (the newer file)"), out.stdout[-900:] + out.stderr[-400:])
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project(task)
    try:
        bad = root / "incomplete-ticket.md"
        bad.write_text(LOST_READ_TICKET, encoding="utf-8")
        s0_run(root, env, task, "--ticket-file", str(bad))
        pasted = FIXTURE_TICKET.replace("Items can carry tags", "Items carry tags (typed)")
        out = s0_answer(root, env, task, pasted)
        eq("K-F2c: the stored paste wins when the command line carries no flag: S0 finishes with the paste's ticket",
           (out.returncode, snapshot_of(task_root)["title"]), (0, "Items carry tags (typed)"), out.stdout[-900:] + out.stderr[-400:])
    finally:
        harness.cleanup(root)


def s0_paste_only_references() -> None:
    """K-F4, the paste-only leg end to end: no tracker is set up, the person's text is scanned and `work/ticket-references.json`
    says which leg wrote it; no reference in the text is an empty list, recorded."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        paste = root / "with-refs.md"
        paste.write_text(FIXTURE_TICKET.replace("As a warehouse operator", "As a warehouse operator (see QA-77)", 1), encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(paste))
        eq("K-F4: a paste with no tracker beside it: S0 finishes, exit 0", out.returncode, 0, out.stdout[-900:] + out.stderr[-400:])
        references = json.loads((task_root / "work" / "ticket-references.json").read_text(encoding="utf-8"))
        tickets = {r["ref"]: r for r in references["rows"] if r["kind"] == "ticket"}
        eq("K-F4: written_by [S0]; the mentioned key is a ticket row `unproven` with the reason; every ticket row says so",
           (references["written_by"], tickets["QA-77"]["status"], tickets["QA-77"]["reason"], {r["status"] for r in tickets.values()}),
           (["S0"], "unproven", "no tracker read at S0", {"unproven"}), json.dumps(references)[:600])
        eq("K-F4: the key stands once, with the origin of the person's text", (len([r for r in references["rows"] if r["ref"] == "QA-77"]), "mention:description" in tickets["QA-77"]["origins"]), (1, True))
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project(task)
    try:
        plain = root / "plain.md"
        plain.write_text("# A title\n\nA story that points at nothing.\n\n## Acceptance criteria\n\n1. It works.\n", encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(plain))
        references = json.loads((task_root / "work" / "ticket-references.json").read_text(encoding="utf-8"))
        eq("K-F4 / FR-23: nothing referenced is still a recorded result: the file is there with an empty list", (out.returncode, references["rows"]), (0, []))
    finally:
        harness.cleanup(root)


def _run_adapter_in_process(root: Path, *args) -> tuple:
    """`ticket_adapter.main()` in this process, over `root`: (exit code, stdout, stderr) - the way the driver sees a child."""
    import contextlib
    import io
    import ticket_adapter
    harness.use_project(root)
    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv
    sys.argv = ["ticket_adapter.py", *[str(a) for a in args]]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ticket_adapter.main()
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


def s0_owners_of_a_failed_read() -> None:
    """K-F3 at the driver: exit 4 (the factory's) is a REFUSAL naming the file and never a question; exit 3 (the tracker's) is
    the `ticket_read` question with `retry_at` from the error object; exit 5 is the stop; a `--json` call whose stdout is not an
    object is the factory's too. K-F4: one place builds the raw flags for the REST read, the comparison read and the paste read."""
    import contextlib
    import io
    import story_run
    import ticket_light
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        direct = {"base_url": "https://jira.example.test", "auth_type": "basic_token", "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN"}
        driver.config["adapters"] = {"ticket": {"kind": "jira", "method": "agent", "invoke": "jira-assistant", "direct_api": direct}}
        # the REAL adapter, over a corrupted COPY of jira-fields.json under this test's tmp dir (never the package's file)
        bad = root / "jira-fields.json"
        bad.write_text(json.dumps(dict(ticket_light.load_fields_table(), standard=[])), encoding="utf-8")
        saved = ticket_light.FIELDS_TABLE_PATH
        ticket_light.FIELDS_TABLE_PATH = bad
        try:
            code, out, err = _run_adapter_in_process(root, "get", task, "--json")
        finally:
            ticket_light.FIELDS_TABLE_PATH = saved
        eq("K-F3 setup: the adapter exits 4 over the corrupted copy and prints ONE error object", (code, json.loads(out)["owner"], json.loads(out)["file"]), (4, "factory", "jira-fields.json"))
        driver.py_stdout = lambda *a, **k: (code, out, err)
        try:
            driver.s0_rest_read()
            check("K-F3: exit 4 is a refusal", False)
        except story_run.Refusal as refusal:
            check("K-F3: exit 4 -> a Refusal that names `jira-fields.json`, says it is the factory's own and what is expected (FR-1, FR-3)",
                  "`jira-fields.json`" in refusal.text and "the cause is the factory's own" in refusal.text and "Expected:" in refusal.text, refusal.text)
        except story_run.Person:
            check("K-F3: exit 4 is never a question", False)
        check("K-F3: no question was left open and nothing was written", not driver.state.get("s0_block") and not (task_root / "work" / "ticket-snapshot.json").exists())
        # an adapter that printed no object under --json: the factory's, with its message - never a question
        for said in ("", "<html>an old adapter's prose</html>", "[1, 2]"):
            driver.py_stdout = lambda *a, said=said, **k: (3, said, "ticket_adapter: something went wrong")
            try:
                driver.s0_rest_read()
                check("K-F3: no error object -> a refusal", False)
            except story_run.Refusal as refusal:
                check_in(f"K-F3: stdout {said[:20]!r} under --json -> the exit-4 handling with the message `the adapter printed no error object`",
                         "the adapter printed no error object", refusal.text)
            except story_run.Person:
                check("K-F3: no error object is never a question", False)
        # the tracker's: the question, the time from the OBJECT (the sentence on stderr names another time on purpose)
        tracker = json.dumps({"ok": False, "owner": "tracker", "status": 429, "retry_at": "2026-10-01T12:30:00Z", "message": "the tracker could not be read"})
        driver.py_stdout = lambda *a, **k: (3, tracker, "ticket_adapter: the tracker asked to be tried again at 2026-10-01T09:00:00Z - retry")
        try:
            driver.s0_rest_read()
            check("K-F3: exit 3 is the question", False)
        except story_run.Person as person:
            check_in("K-F3: exit 3 -> the `ticket_read` question with the time read from the object", "it asked to be asked again at 2026-10-01T12:30:00Z.", person.text)
            check_not_in("K-F3: and not the time that stood in the sentence", "09:00:00Z", person.text)
            eq("K-F3: the block is `ticket_read`", driver.state.get("s0_block"), "ticket_read")
        # auth: the `ticket_auth` question (C1-3 F3 a), with or without the object - never an InfraStop
        auth = json.dumps({"ok": False, "owner": "auth", "status": 401, "retry_at": None, "message": "Jira stopped accepting the token"})
        for stdout in (auth, ""):
            driver.state.pop("s0_block", None)
            driver.py_stdout = lambda *a, stdout=stdout, **k: (5, stdout, "ticket_adapter: Jira stopped accepting the token (HTTP 401)")
            printed = io.StringIO()
            try:
                with contextlib.redirect_stdout(printed):
                    driver.s0_rest_read()
                check("K-F3: exit 5 asks the `ticket_auth` question", False)
            except story_run.InfraStop:
                check("K-F3: exit 5 is no longer an infrastructure stop", False)
            except story_run.Person as person:
                eq(f"K-F3: exit 5 (object {'present' if stdout else 'absent'}) -> the `ticket_auth` question (halt, exit 3), the door in the answer block",
                   ((person.kind, person.code), driver.state.get("s0_block"), "QA_JIRA_API_TOKEN" in person.answer_note), (("halt", 3), "ticket_auth", True))
        # the comparison leg: the factory's fault is REPORTED in the one line and the person's text goes on (C6)
        driver.state.pop("s0_block", None)
        driver.state.pop("s0_rest_failed", None)          # the `ticket_read` question above remembered a failure; the comparison would skip its read
        factory = json.dumps({"ok": False, "owner": "factory", "status": None, "retry_at": None, "message": "refused - jira-fields.json: key `standard` is empty", "file": "jira-fields.json"})
        driver.py_stdout = lambda *a, **k: (4, factory, "ticket_adapter: refused - jira-fields.json: key `standard` is empty")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            kept = driver.s0_compare({"key": task, "title": "T", "acceptance_criteria": ["x"]}, "the snapshot's text")
        eq("K-F3 / C6: a factory fault on the comparison leg is ONE line naming the file, the story goes on with the person's text, nothing asked",
           (kept, printed.getvalue().count("\n"), "`jira-fields.json`" in printed.getvalue(), bool(driver.state.get("s0_block"))), ("the snapshot's text", 1, True, False))

        # --- K-F4: ONE place builds the raw flags; the REST read, the comparison read and the paste read pass the same ---
        calls = []
        snap = {"key": task, "title": "T", "description": "d", "acceptance_criteria": ["x"], "comments": [], "parent": None, "subtasks": [],
                "links": {"merge_request": None, "branch": None}, "provenance": {"source": "fetched"}}

        def record(script, *args, **kw):
            calls.append([str(a) for a in args])
            return 0, json.dumps(snap), ""
        driver.py_stdout = record
        driver.state.pop("s0_block", None)
        driver.s0_rest_read()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.s0_ticket("a-paste.md")
        flags = driver.s0_raw_flags()
        rest_call, paste_call, compare_call = calls[0], calls[1], calls[2]
        eq("K-F4: the REST leg's flags are the raw-dir flags of the one builder", rest_call, ["get", task, *flags, "--json"])
        eq("K-F4: the comparison leg's flags ARE the REST leg's flags (one builder function)", compare_call, rest_call)
        eq("K-F4: and the paste read names the same folder beside --ticket-file", paste_call, ["get", task, "--ticket-file", "a-paste.md", *flags, "--json"])
        check("K-F4: the folder is the story's work/ticket-raw",
              flags[0] == "--raw-dir" and Path(flags[1]).resolve() == (task_root / "work" / "ticket-raw").resolve(), str(flags))
        # K-F10: the source check that the driver calls the public name of the adapter's check was a source pin: deleted by TD-11 phase 0 (F3)
        eq("K-F10: and the check still answers through the driver", driver.direct_api_usable(), True)
    finally:
        harness.cleanup(root)


def t287_config_owner_is_the_ticket_read_question() -> None:
    """t-287 item 2 at the driver: the adapter's error object with owner `config` (a recorded `direct_api` that lacks keys) is
    the `ticket_read` question with FR-50's three answers and the adapter's sentence VERBATIM (FR-8) - never the factory's
    refusal ("Restore what the message names"), never the network advice."""
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["adapters"] = {"ticket": {"kind": "jira", "method": "api", "direct_api": {"custom_fields": [], "acceptance_headings": []}}}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, err = _run_adapter_in_process(root, "get", task, "--json")      # the REAL adapter over the stub
        obj = json.loads(out)
        eq("item 2 setup: the real adapter over the template stub: exit 3, owner `config`", (code, obj["owner"]), (3, "config"))
        driver = driver_for(root, env, task)
        driver.config["adapters"] = cfg["adapters"]
        driver.py_stdout = lambda *a, **k: (code, out, err)
        asked = None
        try:
            driver.s0_rest_read()
            got = ("returned", "")
        except story_run.Person as person:
            got = ("Person", person.text)
            asked = person
        except story_run.Refusal as refusal:
            got = ("Refusal", refusal.text)
        eq("item 2: owner `config` is a QUESTION (never the factory's refusal): the `ticket_read` block", (got[0], driver.state.get("s0_block")), ("Person", "ticket_read"))
        text = got[1]
        # t-363 B3 (B-256 g): the adapter's sentence - the key names and the onboarding command - is an instruction, so it
        # stands in the answer block, WHOLE (FR-8); the body says "the setting named below" and carries neither.
        keys = [f"adapters.ticket.direct_api.{k}" for k in ("base_url", "auth_type", "secret_ref", "username_ref")]
        check("B3: the body carries no key path and no plugin command, and says where the setting is named",
              not any(k in text for k in keys) and "/qa-factory:" not in text and "adapters." not in text
              and "the setting named below" in text and "named above" not in text, text)
        check("B3: the answer block carries the adapter's sentence WHOLE: every missing key and the onboarding door",
              obj["message"] in " ".join(asked.answer_note.split()) and all(k in asked.answer_note for k in keys)
              and "/qa-factory:qa-onboarding" in asked.answer_note, asked.answer_note)
        import human_text
        from story_run_common import jsonl
        driver.ask(asked)
        full = driver.question_path().read_text(encoding="utf-8")
        check("B3: in the question file the keys stand below the answer marker, not above it",
              all(k in full.split("Answer: write your words")[1] for k in keys)
              and not any(k in full.split("Answer: write your words")[0] for k in keys), full)
        eq("B3: the whole question as the person reads it passes the text rules (the block aside, the body clean)",
           human_text.problems(full), [])
        eq("B3: ...and the driver's own judgement of it recorded no broken rule",
           [r.get("problems") for r in jsonl(task_root / "state" / "driver-questions.jsonl")][-1:], [[]])
        eq("B3 control: the OLD body (the adapter's sentence pasted above the block) breaks the new rules",
           sorted({p["rule"] for p in human_text.problems("What stands in the way: " + obj["message"] + " " + "x" * 80 + "\n---\nAnswer: write your words to a file and run\n  python story_run.py --task QA-1 --answer <file>\n")}),
           ["config_key", "plugin_command"])
        driver.state["asked"] = {}
        driver.question_path().unlink()
        check("item 2: FR-50's three answers stay: `not needed`, fix and `retry`, or the ticket as text",
              all(part in text for part in ("(a) `not needed` — ", "(b) `retry` — record the setting named below for this project","(c) paste the ticket here as text")), text)
        check("item 2: and it does not send the person to the network or the VPN, nor say 'Restore'",
              "VPN" not in text and "network" not in text and "Restore" not in text, text)
        eq("item 2: the text obeys human-questions.md (the block `ask()` appends under it aside)", [r for r in rules_broken(text) if r != "no_how_to_answer"], [])
        eq("item 2: the question takes a paste (the door of answer (c))", driver.state["s0_ask"]["paste"], True)
        eq("item 2: no snapshot was written", (task_root / "work" / "ticket-snapshot.json").exists(), False)
        # control of the same call: a tracker-owned failure is the same question WITHOUT that sentence
        driver.state.pop("s0_block", None)
        tracker = json.dumps({"ok": False, "owner": "tracker", "status": 503, "retry_at": None, "message": "the tracker could not be read"})
        driver.py_stdout = lambda *a, **k: (3, tracker, "ticket_adapter: the tracker could not be read")
        try:
            driver.s0_rest_read()
            other = ""
        except story_run.Person as person:
            other = person.text
        check("item 2 (control): an exit-3 `tracker` object is the same question without the config sentence", "What stands in the way" not in other and "ticket_read" == driver.state.get("s0_block"), other)
    finally:
        harness.cleanup(root)


def t287_texts_name_the_file_read() -> None:
    """t-287 item 6 (and the wiki leg of item 1) at the driver: the title and the no-criteria questions name the file actually
    read, relative to the project; a stored paste that wins over the same flag says so once on entry; a wiki text
    has its own title question (`# ` is a list item there); an older snapshot with no `markup` is read as markdown."""
    import contextlib
    import io
    import story_run
    task = "QA-1"
    stored = "qa-factory/artifacts/QA-1/state/driver-tmp/ticket-QA-1.md"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        # --- the texts, at the unit: file named / not named; markdown / wiki / older snapshot ---
        def ask_of(ticket, file, how="from the ticket file"):
            try:
                driver.s0_criteria(ticket, how, file)
            except story_run.Person as person:
                return person.text
            return ""
        driver.state.pop("s0_block", None)
        titled = {"title": "Items can carry tags", "acceptance_criteria": ["a"], "provenance": {"source": "person_pasted", "title_from": "first_line"}}
        text = ask_of(titled, stored)
        check("item 6: the title question names the file read (relative to the project) twice: where it was read and where to put the title",
              text.count(f"`{stored}`") == 2 and "(the file" in text, text)
        check("item 6: ... and an older snapshot (no `markup`) reads as markdown: the `# ` wording, not the wiki one",
              "no line starts with `# `" in text and "`title:" not in text, text)
        eq("item 6: the title question obeys human-questions.md", [r for r in rules_broken(text) if r != "no_how_to_answer"], [])
        driver.state.pop("s0_block", None)
        text = ask_of(titled, None)
        check("item 6: with no file (nothing was read from one) the wording is as it was: `at the top of your text`, no file named",
              "at the top of your text" in text and "the file" not in text, text)
        driver.state.pop("s0_block", None)
        wiki = {"title": "Items can carry tags", "acceptance_criteria": ["a"], "provenance": {"source": "person_pasted", "title_from": "first_line", "markup": "wiki"}}
        text = ask_of(wiki, stored)
        check("item 1 (wiki): the title question for a wiki text says a `# ` line is an item there and asks for a `title:` line of the header, naming the file",
              "a line that starts with `# ` is a list item in this kind of text" in text and "`title: <the title>`" in text and text.count(f"`{stored}`") == 2
              and "no line starts with `# `" not in text, text)
        eq("item 1 (wiki): that text obeys human-questions.md", [r for r in rules_broken(text) if r != "no_how_to_answer"], [])
        driver.state.pop("s0_block", None)
        lost = "## Acceptance criteria\n\nThe operator can tag an item."
        text = ask_of({"title": "T", "description": lost, "acceptance_criteria": [], "provenance": {"source": "person_pasted"}}, stored)
        check("item 6: the lost-read question says it read THAT file (D-0050: no `retry`, so no 'add it to the file')",
              f"from the ticket file `{stored}`" in text and "add the criteria to" not in text and "`retry`" not in text, text)
        eq("item 6: ... and obeys human-questions.md", [r for r in rules_broken(text) if r != "no_how_to_answer"], [])
        driver.state.pop("s0_block", None)
        text = ask_of({"title": "T", "description": lost, "acceptance_criteria": [], "provenance": {"source": "fetched"}}, None, "through the tracker")
        check("item 6 (control): a ticket read through the tracker names no file", "I read ticket QA-1 through the tracker and" in text and "`qa-factory/artifacts" not in text, text)
        # --- the line on entry, at the unit ---
        def entry_line(cli, stored_cli, answered="/p/paste.md"):
            driver.state["launch"] = {"ticket_file": "/p/orig.md"}
            driver.state["s0_answers"] = {"ticket_file": answered, **({"ticket_file_cli": stored_cli} if stored_cli is not None else {})}
            driver.flags.ticket_file = cli
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                chosen = driver.s0_flags()["ticket_file"]
            return chosen, printed.getvalue()
        chosen, said = entry_line("/p/orig.md", "/p/orig.md")
        eq("item 6: the stored paste wins over the SAME flag repeated: ONE line names the file and the door",
           (chosen, said), ("/p/paste.md", "reading the ticket text you gave earlier (/p/paste.md); give a different --ticket-file to replace it\n"))
        chosen, said = entry_line(None, "/p/orig.md")
        eq("item 6: no flag on the command line -> the paste is read and nothing is said", (chosen, said), ("/p/paste.md", ""))
        chosen, said = entry_line("/p/new.md", "/p/orig.md")
        eq("item 6: a DIFFERENT flag is the newer word: it wins, and nothing is said about a stored paste", (chosen, said), ("/p/new.md", ""))
        chosen, said = entry_line("/p/orig.md", None)
        eq("item 6: a paste stored by an older driver (no `ticket_file_cli`) keeps its precedence and says so too", (chosen, said.count("reading the ticket text you gave earlier")), ("/p/paste.md", 1))
        chosen, said = entry_line("/p/paste.md", "/p/paste.md")
        eq("item 6: the flag IS the stored file -> nothing to explain", (chosen, said), ("/p/paste.md", ""))
        driver.state["s0_answers"] = {"ticket_file": str(root / stored), "ticket_file_cli": "/p/orig.md"}
        driver.state["launch"] = {}
        driver.flags.ticket_file = "/p/orig.md"
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            driver.s0_flags()
        eq("item 6: the file in the line is relative to the project, with forward slashes",
           printed.getvalue(), f"reading the ticket text you gave earlier ({stored}); give a different --ticket-file to replace it\n")
    finally:
        harness.cleanup(root)
    # --- end to end: a wiki paste asks its own title question, and `go on` reads its 2 criteria ---
    root, task_root, env = s0_project(task)
    try:
        wiki = root / "wiki-paste.md"
        wiki.write_text("Items can carry tags\n\nAs a warehouse operator I want tags.\n\nh2. Acceptance Criteria\n# A tag can be added.\n# A tag can be removed.\n", encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(wiki))
        eq("item 1 (wiki, end to end): the text has no title line: the `ticket_title` question, exit 3", (out.returncode, s0_state(task_root).get("s0_block")), (3, "ticket_title"), out.stdout[-900:])
        ask = s0_question(task_root)
        check("item 6 / item 1: it names the file the flag gave and the wiki wording",
              "(the file `wiki-paste.md`)" in ask and "a list item in this kind of text" in ask and "\"Items can carry tags\"" in ask, ask)
        eq("item 1: the question obeys human-questions.md", rules_broken(ask), [])
        out = s0_answer(root, env, task, "go on", "--ticket-file", str(wiki))
        snapshot = snapshot_of(task_root)
        eq("item 1 (wiki, end to end): `go on` keeps the title; the snapshot has the 2 `# ` items as criteria, markup wiki, the sentence below the title in the description",
           (out.returncode, snapshot["title"], snapshot["acceptance_criteria"], snapshot["provenance"]["markup"], snapshot["description"].startswith("As a warehouse operator")),
           (0, "Items can carry tags", ["A tag can be added.", "A tag can be removed."], "wiki", True), out.stdout[-900:] + out.stderr[-400:])
    finally:
        harness.cleanup(root)
    # a header `title:` is a title: no question at all
    root, task_root, env = s0_project(task)
    try:
        titled = root / "titled-wiki.md"
        titled.write_text("---\ntitle: Items can carry tags\n---\nh2. Acceptance Criteria\n# A tag can be added.\n# A tag can be removed.\n", encoding="utf-8")
        out = s0_run(root, env, task, "--ticket-file", str(titled))
        snapshot = snapshot_of(task_root)
        eq("item 1 (wiki with a header title): no question, exit 0, the title and 2 criteria", (out.returncode, snapshot["title"], len(snapshot["acceptance_criteria"])),
           (0, "Items can carry tags", 2), out.stdout[-900:] + out.stderr[-400:])
    finally:
        harness.cleanup(root)


def s0_flags_precedence_unit() -> None:
    """K-F2c at the unit: `s0_flags` for a stored paste against the command line."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        driver.state["launch"] = {"ticket_file": "/p/orig.md"}
        driver.state["s0_answers"] = {"ticket_file": "/p/paste.md", "ticket_file_cli": "/p/orig.md"}
        driver.flags.ticket_file = None
        eq("K-F2c: no flag on the command line -> the stored paste wins", driver.s0_flags()["ticket_file"], "/p/paste.md")
        driver.flags.ticket_file = "/p/orig.md"
        eq("K-F2c: the flag the paste was answered under, repeated by the continue command -> the paste stays", driver.s0_flags()["ticket_file"], "/p/paste.md")
        driver.flags.ticket_file = "/p/new.md"
        eq("K-F2c: a different `--ticket-file` -> the command line wins (the newer word)", driver.s0_flags()["ticket_file"], "/p/new.md")
        eq("K-F2c: and the older paste is dropped, so a later entry with no flag does not go back to it",
           (driver.state["s0_answers"].get("ticket_file"), driver.state["launch"]["ticket_file"]), (None, "/p/new.md"))
        driver.flags.ticket_file = None
        eq("K-F2c: that later entry with no flag reads the newer launch flag", driver.s0_flags()["ticket_file"], "/p/new.md")
        driver.state["s0_answers"] = {"ticket_file": "/p/old-paste.md"}                 # stored by an older driver: no `ticket_file_cli`
        driver.flags.ticket_file = "/p/other.md"
        eq("K-F2c / builder rule 9: a paste stored before this change keeps its old precedence (the flag does not drop it)", driver.s0_flags()["ticket_file"], "/p/old-paste.md")
        # F-5 (critic t-689): the scout's "Ticket source" line reads the KEPT launch too - an `--answer` process carries no `--ticket-file`
        driver.flags.ticket_file = None
        driver.state["launch"] = {"ticket_file": "/p/kept.md"}
        check_in("F-5: no flag on this command line, a kept `--ticket-file`: the scout is told the file", "Ticket source: --ticket-file /p/kept.md",
                 driver.role_lines("S1", "qa-scout"))
        driver.state["launch"] = {}
        check_in("F-5: neither flag nor kept file: the configured adapter", "Ticket source: the project's tracker, by the route below", driver.role_lines("S1", "qa-scout"))
        driver.flags.ticket_file = "/p/now.md"
        check_in("F-5: this command line's flag still wins", "Ticket source: --ticket-file /p/now.md", driver.role_lines("S1", "qa-scout"))
    finally:
        harness.cleanup(root)


def g10_s0_criteria_table() -> None:
    """G1-0 (D-0050, I1-I4, t-957 F-1..F-3): the S0 decision table at the unit, in-process. The expectations come from the requirement
    (a ticket with no criteria section goes on with ONE line; a criteria heading with TEXT under it that read no criteria stops, as the
    factory's own defect; an empty template goes on), not from what the code printed."""
    import ticket_adapter
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        driver._s0_passed = []                       # `s0()` makes it at its start; a pass applied below appends to it

        def meet(ticket):
            """(what the check raised or returned): ('line', text) or ('stop', question text)."""
            driver.state.pop("s0_block", None)
            try:
                return ("line", driver.s0_criteria(ticket, "through the tracker"))
            except story_run.Person as person:
                return ("stop", person.text)

        def snap(text, **extra):
            return {"title": "T", "description": text, "acceptance_criteria": [], "provenance": extra}

        qa2 = ticket_adapter.parse_ticket_markdown((harness.PLUGIN_ROOT / "evals" / "fixtures" / "tickets" / "QA-2.md").read_text(encoding="utf-8"), "QA-2")
        eq("QA-2 (the fixture without AC): the snapshot carries `acceptance_criteria: []`", qa2["acceptance_criteria"], [])
        kind, line = meet(qa2)
        eq("I1 / D-0050: a ticket with no criteria section goes on - no question - with ONE line naming the headings looked for",
           (kind, line), ("line", "S0: ticket QA-1 has no section named Acceptance Criteria, What needs to be tested, AC; "
                                  "the requirements are read from its description, comments, attachments and linked tickets"))
        check("F-6: and the line fits what gate A shows of a warning (180 characters)", len(line) <= 180, str(len(line)))
        driver.config["adapters"] = {"ticket": {"kind": "jira", "direct_api": {"acceptance_headings": ["A project heading " * 12]}}}
        kind, line = meet(qa2)
        check("F-6: with a long project heading the names are cut, never the sentence: still <= 180 and still ends with the sources",
              kind == "line" and len(line) <= 180 and line.endswith("linked tickets"), line)
        driver.config.pop("adapters", None)
        kind, line = meet(ticket_adapter.parse_ticket_markdown(INCOMPLETE_TICKET, "QA-1"))
        check("F-1: an EMPTY template (heading, nothing under it) goes on, and the line says the section was found empty",
              kind == "line" and "has a section `## Acceptance criteria` with nothing under it" in line, str((kind, line)))
        eq("an absent/empty description is nothing to read: goes on with the line", [meet(snap(None))[0], meet(snap(""))[0]], ["line", "line"])
        for label, text in (("markdown heading + prose", "## Acceptance criteria\n\nThe operator can tag an item."),
                            ("wiki heading + blank + prose + list (the item loop stops at the prose)", "h3. Acceptance Criteria\n\nThe operator can tag.\n\n* item"),
                            ("two sections, the first empty (F-2)", "h3. Acceptance Criteria\n\nh3. Other\n\nh3. AC\nsome prose"),
                            ("a table", "h3. Acceptance Criteria\n||Given||When||\n|a|b|")):
            kind, text_out = meet(snap(text))
            check(f"I2/I4: {label} -> STOP, the factory's reader failing and not the ticket",
                  kind == "stop" and "this is the factory's reader failing on that section, not your ticket" in text_out, str((kind, text_out[:200])))
        kind, text_out = meet(snap("## Acceptance criteria\n\nThe operator can tag an item."))
        check("F-4: the stop offers `go on`, the ticket as text and `stop` - and not `retry`",
              "`go on`" in text_out and "`stop`" in text_out and "`retry`" not in text_out, text_out)
        eq("FR-6: it obeys human-questions.md", [r for r in rules_broken(text_out) if r != "no_how_to_answer"], [])
        # F-3: the snapshot does not always say how it was read; a REST snapshot never does. Both markups are scanned.
        eq("F-3: a REST-like snapshot (no provenance at all) with a MARKDOWN heading and prose still stops", meet(snap("## Acceptance criteria\n\nprose"))[0], "stop")
        eq("F-3: an old paste (provenance without `markup`) with a WIKI heading and prose still stops", meet(snap("h3. Acceptance Criteria\nprose", source="person_pasted"))[0], "stop")
        eq("F-3: the heading the reader took as the TITLE (first line) is put back for the scan",
           meet({"title": "Acceptance criteria", "description": "prose under the heading", "acceptance_criteria": [],
                 "provenance": {"title_from": "first_line"}})[0], "stop")
        eq("n >= 1: a ticket that read criteria never meets the check", driver.s0_criteria({"title": "T", "acceptance_criteria": ["a"]}, "x"), None)
        # temporal (§4.4/§4.5): a pass stored BEFORE D-0050 for the old problem covers the new one; the person is not asked twice
        driver.state["s0_passes"] = {"ticket_incomplete": {"words": "go on", "at": "t", "problems": ["no acceptance criteria"], "recorded": True, "witness": "w"}}
        eq("I3 (§4.5): a saved `go on` with the OLD problem word passes the lost read - no question again",
           meet(snap("## Acceptance criteria\n\nprose")), ("line", None))
        driver.state["s0_passes"] = {"ticket_incomplete": {"words": "go on", "at": "t", "problems": ["unrelated"], "recorded": True, "witness": "w"}}
        eq("... and a pass for another problem covers nothing", meet(snap("## Acceptance criteria\n\nprose"))[0], "stop")
        driver.state.pop("s0_passes", None)
    finally:
        harness.cleanup(root)


def g10_s0_headings_unreadable() -> None:
    """M2 of t-984 (FR-59, FR-46, FR-2): the list of names the criteria are looked for under cannot be built - the project's
    `config.json` key is a string, or the factory's own table is gone. The stop (1) tells whose it is, in the words of the cause;
    (2) never offers the paste (it reads the same text against the same list and comes back here); (3) has its OWN problem word, so
    a `go on` given here never lets a later REAL lost read through, and the reverse; (4) obeys human-questions.md. The expected
    texts come from the requirement (an owner named correctly, no door back to the same stop), not from the code's output."""
    import story_run
    import ticket_light
    task = "QA-1"
    root, task_root, env = s0_project(task)
    real_table = ticket_light.load_fields_table
    try:
        driver = driver_for(root, env, task)
        driver._s0_passed = []
        driver.s0_file_pass = lambda *a, **k: None          # the finding is the filing script's business; this pins the question

        def snap(text):
            return {"title": "T", "description": text, "acceptance_criteria": [], "provenance": {}}

        def meet(ticket):
            driver.state.pop("s0_block", None)
            try:
                return ("line", driver.s0_criteria(ticket, "through the tracker"))
            except story_run.Person as person:
                return ("stop", person)

        lost_ticket = snap("## Acceptance criteria\n\nThe operator can tag an item.")
        plain_ticket = snap("some prose without a criteria section")

        # --- (a) the project's key is the cause: a string where a list of strings belongs
        driver.config["adapters"] = {"ticket": {"kind": "jira", "direct_api": {"acceptance_headings": "Acceptance Criteria"}}}
        kind, person = meet(plain_ticket)
        text, note, ask = person.text, person.answer_note, driver.state.get("s0_ask") or {}
        check("config cause: a stop, not a pass and not a line (FR-59)", kind == "stop", str(kind))
        check_in("config cause: the lead blames the project's setting", "This is the project's setting, not your ticket.", text)
        check_not_in("config cause: ... and does not blame the factory's file", "a file of the factory's own", text)
        check_not_in("config cause: the paste is not offered (it would come back to this stop)", "the ticket itself as text", text)
        check("config cause: the stop is stored without the paste door", ask.get("paste") is False, str(ask.get("paste")))
        check("config cause: only `go on` and `stop` are offered, and no `retry`",
              "`go on`" in text and "`stop`" in text and "`retry`" not in text, text)
        check_in("config cause: the key and its fix reach the answer block whole (the error's own sentence, FR-8)",
                 "direct_api.acceptance_headings must be a list of strings, got str; fix it in qa-factory/config.json", note)
        check_not_in("config cause: ... and not the body (human-questions.md rule 5)", "config.json", text)
        eq("config cause: the text obeys human-questions.md", [r for r in rules_broken(text) if r != "no_how_to_answer"], [])
        eq("config cause: the problem word is the unreadable-list word, not the lost-read word",
           ask.get("problems"), [driver.S0_HEADINGS_UNREADABLE])
        unreadable_problems = list(ask.get("problems") or [])

        # --- (b) the factory's own table is the cause
        driver.config.pop("adapters", None)

        def gone(*a, **k):
            raise ticket_light.TableError("jira-fields.json: missing; restore references/jira-fields.json from the plugin package")
        ticket_light.load_fields_table = gone
        kind, person = meet(plain_ticket)
        text, note, ask = person.text, person.answer_note, driver.state.get("s0_ask") or {}
        check_in("factory cause: the lead blames the factory", "This is the factory failing, not your ticket.", text)
        check_not_in("factory cause: the paste is not offered", "the ticket itself as text", text)
        check_in("factory cause: the file and how to restore it reach the answer block whole",
                 "jira-fields.json: missing; restore references/jira-fields.json from the plugin package", note)
        eq("factory cause: the text obeys human-questions.md", [r for r in rules_broken(text) if r != "no_how_to_answer"], [])
        eq("factory cause: the same unreadable-list problem word", ask.get("problems"), [driver.S0_HEADINGS_UNREADABLE])
        ticket_light.load_fields_table = real_table

        # --- (c) one problem word per fact: a `go on` given to one stop covers nothing of the other
        pass_of = lambda problems: {"ticket_incomplete": {"words": "go on", "at": "t", "problems": problems, "recorded": True, "witness": "w"}}
        driver.state["s0_passes"] = pass_of(unreadable_problems)
        eq("a `go on` given to the unreadable-list stop does NOT let a later REAL lost read through (the person never saw that section)",
           meet(lost_ticket)[0], "stop")
        driver.config["adapters"] = {"ticket": {"kind": "jira", "direct_api": {"acceptance_headings": "Acceptance Criteria"}}}
        eq("... and the same pass still covers the unreadable list it was given for", meet(plain_ticket), ("line", None))
        lost_problems = [driver.S0_LOST_READ]
        driver.state["s0_passes"] = pass_of(lost_problems)
        eq("the reverse: a `go on` given to a lost-read stop does not cover an unreadable list", meet(plain_ticket)[0], "stop")
        driver.config.pop("adapters", None)
        eq("... and still covers the lost read it was given for", meet(lost_ticket), ("line", None))
        eq("the two problem words differ", driver.S0_LOST_READ != driver.S0_HEADINGS_UNREADABLE, True)
        driver.state.pop("s0_passes", None)
    finally:
        ticket_light.load_fields_table = real_table
        harness.cleanup(root)


def s0_headings_sentence_unit() -> None:
    """K-F5 at the unit: the sentence lists the MERGED headings (the table's + the project's), verbatim, and names the setting's door."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        base = driver.s0_headings_looked_for()
        check_in("K-F5: the table's headings, verbatim, in the table's order", "one of: Acceptance Criteria, What needs to be tested, AC.", base)
        driver.config["adapters"] = {"ticket": {"kind": "jira", "direct_api": {"acceptance_headings": ["Things to verify", "ac"]}}}
        merged = driver.s0_headings_looked_for()
        check_in("K-F5: the project's own headings join the list (a name the table already holds, in another case, is not repeated)",
                 "one of: Acceptance Criteria, What needs to be tested, AC, Things to verify.", merged)
        check_in("K-F5: and the door is named", "`direct_api.acceptance_headings` in `qa-factory/config.json`", merged)
        # (`no_how_to_answer` is the block `ask()` appends under the text; this reads the sentence alone)
        eq("K-F5: the sentence obeys human-questions.md (the text a person reads)", [r for r in rules_broken(merged) if r != "no_how_to_answer"], [])
    finally:
        harness.cleanup(root)


def s0_prices_unreadable() -> None:
    """C1-3 (G8, FR-41): a price row an S0 site needs that the data does not have. The question is STILL asked - its option lines
    without the price lines - and ONE `defect_found` (owner: factory) names the key; the answers it takes are the same. In-process
    (a Driver changes the working directory)."""
    import no_move as NM
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        inventory = task_root / "work" / "source-inventory.json"
        inventory.parent.mkdir(parents=True, exist_ok=True)
        inventory.write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
        driver = driver_for(root, env, task)
        real = NM.load_question_prices
        NM.load_question_prices = lambda: {key: rows for key, rows in real().items() if key != "s0.source_list.late"}
        try:
            try:
                driver.s0_list_too_late()
                text = ""
            except story_run.Person as person:
                text, priced = person.text, person.priced
        finally:
            NM.load_question_prices = real
        check_in("prices unreadable: the question is still asked, with its option lines", "(a) `go on` — the story goes on and the list is ignored", text)
        check_in("prices unreadable: `stop` among them", "(b) `stop` — stop here and start the story again from a fresh copy", text)
        check_not_in("prices unreadable: no price line is shown", "the factory:", text)
        eq("prices unreadable: and no token is claimed as priced", priced, ())
        defects = [e for e in s0_journal(root) if e.get("event") == "defect_found"]
        eq("prices unreadable: exactly one defect_found, owner factory, naming the key",
           (len(defects), "owner: factory" in str(defects[0].get("notes")) if defects else False,
            "s0.source_list.late" in str(defects[0].get("notes")) if defects else False), (1, True, True))
        eq("prices unreadable: the doors the next answer reads are the same", sorted(driver.state["s0_ask"]["doors"]), ["go on", "stop"])
        # the control: the real data, the same call - priced, and no defect
        before = len(defects)
        try:
            driver.s0_list_too_late()
        except story_run.Person as person:
            control, claimed = person.text, person.priced
        check_in("prices unreadable, control: with the data the price lines are there", "the factory: a record only; no agent works", control)
        eq("prices unreadable, control: the priced tokens are claimed, and no new defect",
           (claimed, len([e for e in s0_journal(root) if e.get("event") == "defect_found"])), (("go on", "stop"), before))
    finally:
        harness.cleanup(root)


def s0_stand_named_like_an_answer() -> None:
    """G7 / F4 at the process: a stand named `Stop` cannot be chosen by name (one word, two readings - code never guesses which): it is
    LEFT OUT of the stand question's doors and options and ONE finding names it (owner: environment); the other stands and `stop`
    stay; the word `Stop` is the stop door (held), never the stand."""
    task = "QA-1"
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Stop"}, {"name": "Local"}]})
    try:
        out = s0_run(root, env, task, "--env", "nosuch")
        eq("G7: an unmatched `--env` with a stand named `Stop` still asks the stand question: exit 3", out.returncode, 3, out.stdout[-800:])
        ask, state = s0_question(task_root), s0_state(task_root)
        eq("G7: the doors are `local`, `go on` and `stop` -> `stop` (the stand `Stop` is not one of them)",
           state["s0_ask"]["doors"], {"stop": "stop", "local": "Local", "go on": "go on"})
        check("G7: the options offer `Local`, `go on`, `stop` as priced lines and never the stand `Stop`",
              "`Local` — " in ask and "`go on` — " in ask and "`stop` — " in ask and "`Stop` — " not in ask and price_broken(ask) == [], ask[-900:])
        check_in("F-3: the question names the left-out stand and says it needs renaming (FR-3: the person is told why a stand is missing)",
                 "This stand is named like an answer to this question, so it cannot be chosen by name: `Stop`. It needs renaming in the project's list of stands.", ask)
        check_not_in("F-3: and the configured stands it still offers are named as before", "no stand configured", ask)
        check_in("F-3: some clash: the remaining stand is still named", "The configured stands are `Local`.", ask)
        eq("F-3: the text still obeys the rules of the file for a person (no path, no field name)", rules_broken(ask), [])
        found = [e for e in s0_journal(root) if e.get("event") == "defect_found" and "`Stop`" in str(e.get("notes"))]
        eq("G7/G8: ONE finding names the stand, owner: environment",
           (len(found), str(found[0].get("notes", "")).startswith("owner: environment — the stand(s) `Stop` ") if found else None), (1, True))
        out = s0_answer(root, env, task, "Stop", "--env", "nosuch")
        check("G7: the word `Stop` is the stop door: the question is held (exit 3), no stand was chosen",
              out.returncode == 3 and "You said to stop." in s0_question(task_root) and "env" not in (s0_state(task_root).get("s0_answers") or {}),
              out.stdout[-500:])
    finally:
        harness.cleanup(root)
    # F-3 (critic t-689): EVERY configured stand clashes -> the person is not told "no stand configured" (false, FR-41); the question
    # names the left-out stands and says they need renaming, offers no stand, and still has `go on` and `stop`
    root, task_root, env = s0_project(task, config={"environments": [{"name": "Stop"}, {"name": "Retry"}]})
    try:
        out = s0_run(root, env, task, "--env", "nosuch")
        eq("F-3: all stands clash: still the stand question (exit 3)", out.returncode, 3, out.stdout[-800:])
        ask, state = s0_question(task_root), s0_state(task_root)
        check_not_in("F-3: all clash: it never says no stand is configured", "no stand configured", ask)
        check_in("F-3: all clash: it says none of the configured stands can be chosen by name", "none of the stands this project has configured can be chosen by name.", ask)
        check_in("F-3: all clash: it names the left-out stands and that they need renaming",
                 "These stands are named like an answer to this question, so they cannot be chosen by name: `Stop`, `Retry`. They need renaming in the project's list of stands.", ask)
        check("F-3: all clash: no stand option, only `go on` and `stop`, priced",
              "`Stop` — " not in ask and "`Retry` — " not in ask and "`go on` — " in ask and "`stop` — " in ask and price_broken(ask) == [], ask[-900:])
        eq("F-3: all clash: the doors are `go on` and `stop` only", state["s0_ask"]["doors"], {"stop": "stop", "go on": "go on"})
        eq("F-3: all clash: the text obeys the rules of the file for a person", rules_broken(ask), [])
    finally:
        harness.cleanup(root)


def s0_unread_road_units() -> None:
    """G1 and F4 in-process: after a conductor `continue` / `retry` at S0 the stored block is ABSENT and `s0_read_word` returns None (the
    callers run the step again); on a raise the block is stored again ONLY on that path; `s0_doors` never replaces a door held
    under `stop` (a stand named `Stop`); both callers use `s0_read_word` as a statement (None = nothing decided)."""
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        ask = {"kind": "halt", "text": "Which one?", "details": "d", "doors": {"mr": "mr", "branch": "branch"}, "paste": False, "problems": []}
        for verdict in ("continue", "retry"):
            driver = driver_for(root, env, task)
            driver.state.update(s0_block="flags", s0_ask=dict(ask), pending_words={"S0": "something else"})
            driver.unread = lambda *a, verdict=verdict, **k: verdict
            got = driver.s0_read_word()
            kept = s0_state(task_root)
            eq(f"G1: a conductor `{verdict}` -> None to the caller, `s0_block` / `s0_ask` absent in memory and on disk, the words consumed",
               (got, "s0_block" in driver.state, "s0_ask" in driver.state, "s0_block" in kept, "s0_ask" in kept, "S0" in (kept.get("pending_words") or {})),
               (None, False, False, False, False, False))
            check_not_in(f"G1: `{verdict}` passes nothing and decides nothing", "s0_passes", json.dumps(kept))
        driver = driver_for(root, env, task)
        driver.state.update(s0_block="flags", s0_ask=dict(ask), pending_words={"S0": "something else"})

        def asks(*a, **k):
            raise story_run.Person("halt", "again", "S0")
        driver.unread = asks
        try:
            driver.s0_read_word()
            check("G1: a question raised by the seam leaves the block stored", False)
        except story_run.Person:
            kept = s0_state(task_root)
            eq("G1: a RAISE stores the block again (memory and disk): the next answer is read against the same doors",
               (driver.state.get("s0_block"), kept.get("s0_block"), sorted((kept.get("s0_ask") or {}).get("doors") or {})), ("flags", "flags", ["branch", "mr"]))
        eq("F4: `s0_doors` never replaces a door held under `stop` (a stand named `Stop`)",
           story_run.Driver.s0_doors({"stop": "Stop", "go on": "go on"}), {"stop": "Stop", "go on": "go on"})
        eq("F4: and adds `stop` when the block holds none", story_run.Driver.s0_doors({"retry": "retry"}), {"stop": "stop", "retry": "retry"})
        # (the source check that the two callers use `s0_read_word()` as a bare statement was a source pin: deleted by TD-11 phase 0, F3)
    finally:
        harness.cleanup(root)


# --- C2-9 (D-0043): the factory does not ask about the known-impossible, and does not re-ask per instance -----------------------
C29_MR = "https://git.example.com/team/sdk/-/merge_requests/510"
C29_SHARE = "https://share.example.com/sites/x/video.mp4"


def c29_source(sid="SRC-1", media=(), **over):
    item = {"source_id": sid, "canonical_ref": f"https://jira.example.invalid/browse/APP-{sid[-1]}", "relation": "referenced",
            "relevance": "relevant", "required": True, "status": "read", "inspection_status": "read", "revision": "r1",
            "human_review": {"words": "ok", "shown": {"relevance": "relevant"}},
            "materials": {"comments": {"status": "read"}, "attachments": {"status": "read", "items": []},
                          "external_media": {"status": "unavailable" if media else "read", "items": list(media)}}}
    item.update(over)
    return item


def c29_write(task_root: Path, *sources) -> Path:
    path = task_root / "work" / "source-inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "sources": list(sources)}), encoding="utf-8")
    return path


def c29_s1_gap_question() -> None:
    """T9 (the text), T9b (`ask` writes what the question named, for `s1_gap` alone), T19 (`causes`)."""
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        asked_row = {"url": C29_MR, "status": "unavailable", "cause": "auth_required", "access_problem": True,
                     "error": "auth_required: 302 to the SSO login"}
        by_default = {"url": C29_SHARE, "status": "unavailable", "cause": "no_tool", "error": "no_tool: no browser"}
        c29_write(task_root, c29_source("SRC-1", [asked_row, by_default]))
        driver = driver_for(root, env, task)
        gap_ref = "source material unavailable and not accepted by a person: SRC-1"
        text = driver.s1_gap_text(gap_ref)
        check_in("T9 the asked point is listed with its cause", "auth_required: 302 to the SSO login", text)
        check_eq("T9 the point the factory itself established is not among the asked lines",
                 [line for line in str(text).splitlines() if line.startswith("- ") and C29_SHARE in line], [])
        check_in("T9 one line says it was recorded without a question", "Already recorded as gaps, without a question", text)
        check_in("T9 the access paragraph is for the asked point", "dropped VPN or an expired login", text)
        check_eq("T9 `not needed` and `skip all like these` are tokens when a cause is asked", tuple(text.priced),
                 ("not needed", "skip all like these"))
        check_eq("T9 the question names its source and its cause", (text.sources, text.classes), (("SRC-1",), ("auth_required",)))
        check_eq("T9 and every option has its price lines", price_broken(text + "\n---\nAnswer: x"), [])
        c29_write(task_root, c29_source("SRC-1", [by_default]))
        text = driver.s1_gap_text(gap_ref)
        check_eq("T9 nothing asked: no kind token, no source", (tuple(text.priced), text.sources, text.classes), (("not needed",), (), ()))
        check_not_in("T9 and no access paragraph", "lost access", text)
        # the limit: 60 sources, the body at most 6000 bytes, the rest in the details, the tokens name ALL of them
        many = [c29_source(f"SRC-{n:02x}", [dict(asked_row, url=f"https://git.example.com/team/sdk/-/merge_requests/{n}")]) for n in range(60)]
        c29_write(task_root, *many)
        ref = "; ".join(f"source material unavailable and not accepted by a person: SRC-{n:02x}" for n in range(60))
        text = driver.s1_gap_text(ref)
        body = str(text)[:str(text).index("## What each answer")]
        check("T9 60 sources: the body is at most 6000 bytes", len(body.encode("utf-8")) <= driver.GAP_TEXT_MAX, str(len(body.encode("utf-8"))))
        check_in("T9 and says how many it did not print", "more sources - the whole list is in the file named below", text)
        check_eq("T9 the details hold the whole list of 60; the tokens name all 60", (text.details.count("(SRC-"), len(text.sources)), (60, 60))
        three = [c29_source(f"SRC-a{n}", [dict(asked_row, url=f"https://git.example.com/team/sdk/-/merge_requests/{n}")]) for n in range(3)]
        c29_write(task_root, *three)
        small = driver.s1_gap_text("; ".join(f"source material unavailable and not accepted by a person: SRC-a{n}" for n in range(3)))
        check_not_in("T9 three sources: all printed, no `more`", "more sources", small)
        # T9b / T19
        driver.ask(story_run.Person("s1_gap", small, "S1", "S1-qa-scout-1"))
        asked = driver.state["asked"]
        check_eq("T9b `ask` writes what the s1_gap question named", (asked.get("sources"), asked.get("classes")),
                 (["SRC-a0", "SRC-a1", "SRC-a2"], ["auth_required"]))
        rows = [json.loads(l) for l in (driver.state_dir / "driver-questions.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("T19 the detector row of an s1_gap carries the causes", rows[-1].get("causes"), ["auth_required"])
        other = story_run.Person("halt", "The conductor needs your word.", "S3")
        other.sources, other.classes = ("SRC-9",), ("auth_required",)
        driver.ask(other)
        rows = [json.loads(l) for l in (driver.state_dir / "driver-questions.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("T9b a question of another kind never carries the fields", ("sources" in driver.state["asked"], "classes" in driver.state["asked"]),
                 (False, False))
        check_eq("T19 and its detector row has no `causes`", "causes" in rows[-1], False)
    finally:
        harness.cleanup(root)


def c29_gap_body(text) -> str:
    """The BODY of an `s1_gap` question: everything before the options (the blank line included)."""
    return str(text)[:str(text).index("## What each answer")]


def c29_s1_gap_cap() -> None:
    """T9 F-2 (the access paragraph names the real answer, the count is the options') and F-3 (the 6000-byte cap bounds the body:
    AT 6000 printed whole, 6001 cut with `+K more`; the access list is bounded; 150 sources keep a line)."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        mr = "https://git.example.com/team/sdk/-/merge_requests/510"
        auth = {"url": mr, "status": "unavailable", "cause": "auth_required", "access_problem": True, "error": "auth_required: SSO"}
        ref = lambda ids: "; ".join(f"source material unavailable and not accepted by a person: {i}" for i in ids)    # noqa: E731
        # F-2: the paragraph names the answer by its words; the count is the count of the answers offered
        c29_write(task_root, c29_source("SRC-1", [auth]))
        text = driver.s1_gap_text(ref(["SRC-1"]))
        check_in("F-2 the access paragraph names the route answer by its words", 'give the answer "here is how to reach it"', text)
        check_not_in("F-2 and no longer by a position", "second answer", text)
        check_in("F-2 four answers are offered (not needed, skip all like these, route, content): the count says Four", "Four answers work", text)
        check_eq("F-2 the words it quotes are the words of an option offered below", str(text).count("(c) here is how to reach it"), 1)
        c29_write(task_root, c29_source("SRC-1", [dict(auth, cause="transient", error="transient: timeout")]))
        text = driver.s1_gap_text(ref(["SRC-1"]))
        check_eq("F-2 an asked cause that is not about access: four answers, and no access paragraph",
                 ("Four answers work" in str(text), "lost access" in str(text)), (True, False))
        c29_write(task_root, c29_source("SRC-1", [{"url": C29_SHARE, "status": "unavailable", "cause": "no_tool", "error": "no_tool: x"}]))
        text = driver.s1_gap_text(ref(["SRC-1"]))
        check_eq("F-2 with nothing asked (no kind to offer) there are three answers: Three",
                 ("Three answers work" in str(text), tuple(text.priced)), (True, ("not needed",)))
        # F-3: 150 sources, each asked about lost access: the body stays inside the cap, a line is shown, the lists say `+K more`
        for count, pad in ((60, 0), (150, 0), (150, 80)):
            rows = [c29_source(f"SRC-{n:03x}", [dict(auth, url=f"https://share.example.com/sites/{'x' * pad}/doc-{n}.pdf")])
                    for n in range(count)]
            c29_write(task_root, *rows)
            text = driver.s1_gap_text(ref([f"SRC-{n:03x}" for n in range(count)]))
            body = c29_gap_body(text)
            shown = [line for line in body.splitlines() if line.startswith("- ")]
            check(f"F-3 {count} sources (names {pad}): the body is at most 6000 bytes ({len(body.encode('utf-8'))}) and shows a source line",
                  len(body.encode("utf-8")) <= driver.GAP_TEXT_MAX and len(shown) >= 1, str(len(shown)))
            check_eq(f"F-3 {count} sources: the access list is bounded and says how many it left out",
                     ("(+%d more)" % (count - driver.GAP_NAMES_SHOWN) in body, len(text.sources), text.details.count("(SRC-")),
                     (True, count, count))
            check_in(f"F-3 {count} sources: the line says how many sources it did not print",
                     "more sources - the whole list is in the file named below", body)
        # AT and BEYOND the cap: one source line grows a byte at a time (a cause that is not about access, so the tail is fixed)
        transient = {"url": mr, "status": "unavailable", "cause": "transient", "error": "transient: timeout"}

        def render(fixed: int, pad: int):
            rows = [c29_source(f"SRC-{n:02x}", [dict(transient, url=f"{mr}?{n}")]) for n in range(fixed)]
            rows.append(c29_source("SRC-ff", [dict(transient, url=f"{mr}?{'y' * pad}")]))
            c29_write(task_root, *rows)
            return driver.s1_gap_text(ref([f"SRC-{n:02x}" for n in range(fixed)] + ["SRC-ff"]))

        fixed = 20          # as many fixed lines as leave room for one line to grow the body from ~5700 to past 6000
        while len(c29_gap_body(render(fixed, 1)).encode("utf-8")) < 5700 and "more sources" not in c29_gap_body(render(fixed, 1)):
            fixed += 1
        last_whole = None
        for pad in range(1, 380):
            text = render(fixed, pad)
            body = c29_gap_body(text)
            if "more sources" in body:
                break
            last_whole = (pad, len(body.encode("utf-8")), text)
        check("AT: some body was printed whole before the cut", last_whole is not None)
        check_eq("AT: the largest body printed whole is exactly 6000 bytes, every source line in it, no details file",
                 (last_whole[1], last_whole[2].details), (driver.GAP_TEXT_MAX, ""))
        check_eq("BEYOND: the next byte (6001) is cut: `+1 more sources`, the whole list in the details, the body inside the cap",
                 ("(+1 more sources - the whole list is in the file named below)" in body, len(body.encode("utf-8")) <= driver.GAP_TEXT_MAX,
                  text.details.count("(SRC-")), (True, True, fixed + 1))
        check_eq("BEYOND: the tokens still name every source", len(text.sources), fixed + 1)
    finally:
        harness.cleanup(root)


def c29_s1_gap_answer() -> None:
    """T10 (the tokens have their executor and read ONLY tokens), T10b (an answer to another kind is not taken here)."""
    import source_inventory as SI
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        auth = {"url": C29_MR, "status": "unavailable", "cause": "auth_required", "error": "auth_required: SSO"}
        transient = {"url": C29_SHARE, "status": "unavailable", "cause": "transient", "error": "transient: timeout"}
        c29_write(task_root, c29_source("SRC-1", [auth, transient]))
        driver = driver_for(root, env, task)
        classes_file = task_root / "work" / "gap-classes.json"
        asked = {"kind": "s1_gap", "stage": "S1", "dispatch": "S1-qa-scout-1", "sources": ["SRC-1"], "classes": ["auth_required"]}
        taken = driver._answer_s1_gap("go on without it", asked, "- a\n", "S1", "S1-qa-scout-1")
        check_eq("T10 a phrase is not a token: not taken, nothing written", (taken, classes_file.exists()), (False, False))
        taken = driver._answer_s1_gap("skip all like these", dict(asked, classes=[]), "- a\n", "S1", "S1-qa-scout-1")
        check_eq("T10 the kind token with no kind offered goes to the conductor", (taken, classes_file.exists()), (False, False))
        taken = driver._answer_s1_gap("skip all like these", dict(asked, sources=[]), "- a\n", "S1", "S1-qa-scout-1")
        check_eq("T10 a token with no source named goes to the conductor", (taken, classes_file.exists()), (False, False))
        taken = driver._answer_s1_gap("skip all like these", asked, "- SRC-1 line\n", "S1", "S1-qa-scout-1")
        rows = json.loads(classes_file.read_text(encoding="utf-8"))["classes"] if classes_file.exists() else []
        check_eq("T10 the kind token records exactly the kinds the question OFFERED (not `transient`, which the inventory also holds)",
                 (taken, [(r["id"], r["cause"], r["words"]) for r in rows]), (True, [("GC-1", "auth_required", "skip all like these")]))
        check_eq("T10 and the point of that cause is now closed by the kind",
                 SI.completeness(SI.load_inventory(task_root / "work" / "source-inventory.json"), **SI.class_kwargs(task_root))["closed_by_class"],
                 {"SRC-1": {SI._media_id(auth, 0): "GC-1"}})
        c29_write(task_root, c29_source("SRC-2", [dict(transient)]))
        taken = driver._answer_s1_gap("not needed", {"sources": ["SRC-2"], "classes": []}, "- a\n", "S1", "S1-qa-scout-1")
        item = json.loads((task_root / "work" / "source-inventory.json").read_text(encoding="utf-8"))["sources"][0]
        check_eq("T10 `not needed` accepts the sources the question NAMED, in the person's words",
                 (taken, item.get("gap_acceptance", {}).get("words")), (True, "not needed"))
        # T10b the branch belongs to the kind
        called = []
        driver._answer_s1_gap = lambda *args: called.append(args) or True
        driver.state["asked"] = {"kind": "conductor", "stage": "S3", "dispatch": "", "classes": ["auth_required"], "sources": ["SRC-1"]}
        driver.state["pending_words"] = {}
        driver.state_dir.mkdir(parents=True, exist_ok=True)
        (driver.state_dir / "driver-question.md").write_text("---\nkind: conductor\n---\nQuestion?\n", encoding="utf-8")
        sent = root / "answer.md"
        sent.write_bytes(b"skip all like these")
        try:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                driver.take_answer(sent)
        except Exception:
            pass            # what the conductor does with the words is not this test's business
        check_eq("T10b an answer to a question of another kind is not taken by the s1_gap branch", called, [])
    finally:
        harness.cleanup(root)


def c29_partial_accept() -> None:
    """T10 F-5: the kinds are written, a later call is refused - the text says the kinds were recorded, never `nothing was accepted`."""
    import story_run
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        auth = {"url": C29_MR, "status": "unavailable", "cause": "auth_required", "error": "auth_required: SSO"}
        bare = {"url": C29_SHARE, "status": "unavailable", "error": "no cause recorded"}
        c29_write(task_root, c29_source("SRC-1", [auth, bare]))
        driver = driver_for(root, env, task)
        real = driver.py

        def py(script, *args, **kw):
            if script == "ticket_adapter.py" and "--point" in args:
                return 1, "ticket_adapter: gap acceptance rejected: the disk is full"
            return real(script, *args, **kw)
        driver.py = py
        asked = {"kind": "s1_gap", "stage": "S1", "dispatch": "S1-qa-scout-1", "sources": ["SRC-1"], "classes": ["auth_required"]}
        try:
            driver._answer_s1_gap("skip all like these", asked, "- SRC-1 line\n", "S1", "S1-qa-scout-1")
            raised = details = None
        except story_run.Person as person:
            raised, details = str(person.text), str(person.details)
        check("F-5 a refusal of the second call raises the person's own question", raised is not None)
        check_eq("F-5 the kinds are on disk", (task_root / "work" / "gap-classes.json").is_file(), True)
        check_in("F-5 and the text says the kinds were recorded and covers the later ones", "recorded for the kinds of gap (auth_required)", raised or "")
        check_not_in("F-5 and never `nothing was accepted` after a write", "nothing was accepted", raised or "")
        check_in("F-5 and carries the recorded kinds and the refusal's own words in the details", "the disk is full", details or "")
        # the first call refused: nothing is written, and the text may say so
        (task_root / "work" / "gap-classes.json").unlink()
        driver.py = lambda script, *args, **kw: (1, "refused") if script == "ticket_adapter.py" else real(script, *args, **kw)
        try:
            driver._answer_s1_gap("skip all like these", asked, "- SRC-1 line\n", "S1", "S1-qa-scout-1")
            raised = None
        except story_run.Person as person:
            raised = str(person.text)
        check_in("F-5 when the FIRST call is refused nothing was recorded, and the text says so", "nothing was accepted", raised or "")
    finally:
        harness.cleanup(root)


def c29_class_problem_defect() -> None:
    """T-F4 (L-2 V-5 b): a damaged record of kinds after S1 closed is ONE finding of the factory, once per problem text."""
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        driver = driver_for(root, env, task)
        filed = []
        driver.file_defect = lambda ref, notes: filed.append(notes)
        driver.state_dir.mkdir(parents=True, exist_ok=True)

        def controller(s1: str, problem: str) -> None:
            (driver.state_dir / "controller.json").write_text(json.dumps(
                {"stages": {"S1": {"status": s1}}, "source_completeness": {"gap_class_problem": problem}}), encoding="utf-8")
        controller("completed", "")
        driver.report_gap_class_problem()
        controller("pending", "work/gap-classes.json cannot be read: bad json")
        driver.report_gap_class_problem()
        check_eq("F-4 no problem, or S1 not closed yet (the question carries the line): no finding", filed, [])
        controller("completed", "work/gap-classes.json cannot be read: bad json")
        driver.report_gap_class_problem()
        driver.report_gap_class_problem()
        check_eq("F-4 a damaged record after S1 closed: ONE finding, owner factory, naming the problem",
                 (len(filed), (filed or [""])[0].startswith("owner: factory"), "gap-classes.json cannot be read: bad json" in (filed or [""])[0]),
                 (1, True, True))
        controller("completed", "work/gap-classes.json cannot be read: another")
        driver.report_gap_class_problem()
        check_eq("F-4 a different problem is a new finding", len(filed), 2)
    finally:
        harness.cleanup(root)


def c29_unreachable_mr() -> None:
    """T8 (the code writes the verdict of an unreachable merge request, with its carrier) and T14 (`handoff` collects again for a gap by
    default, with no error)."""
    import source_inventory as SI
    task = "QA-1"
    root, task_root, env = s0_project(task)
    try:
        def story(code: str):
            c29_write(task_root, c29_source("SRC-1", [{"url": C29_MR, "status": "pending"}]))
            driver = driver_for(root, env, task)
            driver.git_route = lambda *a, **k: ""
            real = driver.py

            def py(script, *args, **kw):
                if script == "vcs_evidence.py":
                    out = Path(args[args.index("--output") + 1])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps({"url": C29_MR, "status": "unavailable", "error": code} if code else
                                              {"url": C29_MR, "status": "unavailable"}), encoding="utf-8")
                    return 1, ""
                return real(script, *args, **kw)
            driver.py = py
            return driver

        def row():
            return json.loads((task_root / "work" / "source-inventory.json").read_text(encoding="utf-8"))["sources"][0][
                "materials"]["external_media"]["items"][0]

        driver = story("host_unreachable")
        got = driver.close_vcs_gaps([])
        summary = SI.completeness(SI.load_inventory(task_root / "work" / "source-inventory.json"))
        check_eq("T8 a receipt that says host_unreachable is written by CODE: unavailable, its cause, its carrier, collected",
                 (got, row().get("status"), row().get("cause"), row().get("probe_code"), bool(row().get("probe_sha256"))),
                 (True, "unavailable", "host_unreachable", "host_unreachable", True))
        check_eq("T8 and it is a gap by default: no question is born", (summary["defaulted_gaps"], summary["unavailable_materials"]),
                 (["SRC-1"], []))
        check_eq("T14 the condition `handoff` collects by sees it", driver._defaulted_vcs(), True)
        check_eq("T8 a second run over the same verdict changes nothing the caller must re-read", driver.close_vcs_gaps([]), False)
        driver = story("unauthenticated")
        got = driver.close_vcs_gaps([])
        summary = SI.completeness(SI.load_inventory(task_root / "work" / "source-inventory.json"))
        check_eq("T8 `unauthenticated` is an access problem the person is asked about, never a default",
                 (row().get("cause"), summary["defaulted_gaps"], summary["unavailable_materials"]), ("auth_required", [], ["SRC-1"]))
        for code in ("brand_new_code", ""):
            driver = story(code)
            got = driver.close_vcs_gaps([])
            check_eq(f"T8 a code the table does not know ({code or 'none'}) writes nothing: the item stays pending",
                     (got, row().get("status")), (False, "pending"))
        # T14 handoff reaches the collector although the gate has no error
        driver = story("host_unreachable")
        driver.close_vcs_gaps([])
        calls = []

        class Stop(Exception):
            pass

        def stub(errors):
            calls.append(list(errors))
            raise Stop()
        driver.close_vcs_gaps = stub
        driver.exit_errors = lambda role, digest, dispatch=None: []
        driver.form_errors = lambda dispatch: []
        driver.revoke_passes_of_dead = lambda: None
        try:
            driver.handoff("qa-scout", "S1", "S1-qa-scout-1", {"is_error": False, "result": "ok", "exit_code": 0, "stderr": ""})
        except Stop:
            pass
        except Exception:       # a handoff that never reached the collector goes on and dies elsewhere: the check below names it
            pass
        check_eq("T14 handoff calls the collector for a gap by default even with no error", calls, [[]])
    finally:
        harness.cleanup(root)


def main() -> None:
    run_scenarios(
        [s0_snapshot,
         s0_incomplete_ticket,
         s0_two_passes,
         s0_pasted_ticket,
         s0_reask_battery,
         s0_launch_flags,
         s0_stand_named_like_an_answer,
         s0_title_question,
         s0_pasted_description_15045,
         s0_ticket_file_precedence,
         s0_paste_only_references,
         k5_the_agent_is_never_called,
         k6_ticket_read_question,
         k_comparison_person_vs_tracker,
         k11_a_snapshot_on_disk_is_never_rewritten,
         k13_no_criteria_section_goes_on_with_a_line,
         k10_a_dry_run_asks_and_reads_nothing,
         s0_list_applied_before_the_seed,
         s0_source_list_clean,
         s0_source_list_stops,
         s0_source_list_kinds,
         s0_source_list_mr_flag,
         s0_source_list_inventory],
        [s0_py_stdout_unit,
         s0_ticket_units,
         s0_owners_of_a_failed_read,
         t287_config_owner_is_the_ticket_read_question,
         t287_texts_name_the_file_read,
         s0_flags_precedence_unit,
         g10_s0_criteria_table,
         g10_s0_headings_unreadable,
         s0_headings_sentence_unit,
         k6_retry_after_and_other_failures,
         s0_fenced_decision_notice,
         s0_legacy_snapshot,
         s0_door_invariant,
         s0_stale_block,
         s0_source_list_units,
         s0_excluded_heads,
         s0_source_list_texts,
         s0_prices_unreadable,
         s0_unread_road_units,
         c29_s1_gap_question,
         c29_s1_gap_cap,
         c29_s1_gap_answer,
         c29_partial_accept,
         c29_class_problem_defect,
         c29_unreachable_mr],
    )
    harness.finish("test_story_run_s0")


if __name__ == "__main__":
    main()
