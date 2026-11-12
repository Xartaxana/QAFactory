#!/usr/bin/env python3
"""conductor tracker: a part of test_infra_failure.py, split by tools/test_split.py (TD-11c). The shared helpers are in infra_failure_common."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402
from infra_failure_common import (  # noqa: E402
    AUTH, MALFORMED, calls, control, done, entry, project_of, scenario,
)


# --- K9, K10, K11, K15 ----------------------------------------------------------------------------
def k9_the_conductor_meets_auth():
    import story_run
    root, task_root, env, driver, delays = project_of(control([entry(AUTH)]))
    try:
        def unknown():
            raise story_run.Refusal("controller: the moon is down and nobody knows why")
        driver.where = unknown
        code = driver.run()
        check_eq("K9: a conductor call that meets auth ends the run with 5", code, 5)
        check("K9: no question file", not (task_root / "state/driver-question.md").exists())
        check("K9: no conductor row", not (task_root / "state/conductor.jsonl").exists())
        check_eq("K9: the conductor call is not remembered as an interrupted dispatch", driver.state["interrupted"], {})
    finally:
        done(root)


def k10_the_tracker_meets_auth():
    """t-267 C4 / t-278: the tracker is read by REST and not through the tracker agent (D-06), so the lost login S0 can meet
    is the adapter's exit 5 (a 401, a 403 or a login page that a re-read confirms). C1-3 F3 (a): it is the `ticket_auth` QUESTION (exit
    3: the person can renew the token, paste the ticket or say it is not needed; the variable stands in the answer block), never the
    `ticket_read` question and no longer an infrastructure stop - the exit-5 `InfraStop` of THIS file belongs to `claude -p` alone."""
    import story_run
    root, task_root, env, driver, delays = project_of(control())
    try:
        driver.config.setdefault("adapters", {})["ticket"] = {"kind": "jira", "method": "agent", "invoke": "jira-assistant", "direct_api": {
            "base_url": "https://jira.example.test", "auth_type": "basic_token", "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN"}}
        driver.py_stdout = lambda *a, **k: (5, "", "ticket_adapter: Jira stopped accepting the token (HTTP 401 while reading the ticket QA-1)")
        try:
            driver.s0_rest_read()
            said = "returned"
        except story_run.InfraStop as stop:
            said = "InfraStop:" + stop.kind
        except story_run.Person as person:
            said = "Person:" + person.kind
        # F3 (a) (C1-3 node B): the tracker's lost login is the `ticket_auth` QUESTION (exit 3), not `claude -p`'s infrastructure (exit 5)
        check_eq("K10: the adapter's exit 5 is the `ticket_auth` halt question (the person can renew, paste or say not needed), not a stop",
                 said, "Person:halt")
        check_eq("K10: its block is `ticket_auth`", driver.state.get("s0_block"), "ticket_auth")
    finally:
        done(root)
    # the whole S0, as a process against a Jira that refuses the token: the launch flags come back in the command
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    hits = []

    class Refuses(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(401)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Refuses)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    direct = {"base_url": f"http://127.0.0.1:{server.server_address[1]}", "api_version": "2", "auth_type": "basic_token",
              "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN"}
    root, task_root, env = T.s0_project("QA-1", config={"adapters": {"ticket": {
        "kind": "jira", "method": "agent", "invoke": "jira-assistant", "direct_api": direct}}})
    env.update(QA_JIRA_EMAIL="reader@example.invalid", QA_JIRA_API_TOKEN="test-only-token")
    try:
        out = T.run_driver(root, env, "--task", "QA-1", "--max-boundaries", "0", "--mr", "12", "--branch-suffix", "my suffix",
                           "--env", "local", "--ungrounded")
        T.eq("K10: S0 asks the `ticket_auth` question: exit 3, not the infrastructure stop 5", out.returncode, 3, out.stdout[-1500:] + out.stderr[-800:])
        ask = T.s0_question(task_root)
        for flag in ('--mr 12', '--branch-suffix "my suffix"', "--env local", "--ungrounded"):
            check_not_in(f"K10: no flag is repeated for the person to retype ({flag})", flag, ask)
        check("K10: the answer block exists (the body is what stands above the rule line)", "\n---\n" in ask)
        check_in("K10: the token variable the config names stands in the answer block (the one place an instruction may)", "QA_JIRA_API_TOKEN",
                 ask.split("\n---\n", 1)[-1])
        check_not_in("K10: and not in the body", "QA_JIRA_API_TOKEN", ask.split("\n---\n")[0])
        check_eq("K10: the block is `ticket_auth`, not `ticket_read`, and no agent or conductor was called",
                 (T.s0_state(task_root).get("s0_block"), (root / "stub-log.jsonl").exists()), ("ticket_auth", False))
        check("K10: its answers are priced option lines: `retry`, `not needed`, the ticket as text, `stop`",
              all(word in ask for word in ("`retry` — ", "`not needed` — ", "paste the ticket here as text", "`stop` — ")), ask)
        check("K10: nothing was written for the story: no snapshot, no pipeline", not (task_root / "work/ticket-snapshot.json").exists()
              and not (task_root / "pipeline.json").exists())
        check("K10 (control for the next run): with the variable SET the tracker was asked", len(hits) > 0, str(hits))
    finally:
        harness.cleanup(root)
    # t-287 item 3: the same S0, the variable that holds the token NOT SET in the shell and everything else fine. It is the
    # login's stop as well - the door names THE VARIABLE, there is no "network or VPN" sentence, no `ticket_read` question -
    # and not one request reaches the tracker (the server above counted the first run's and sees none from this one).
    hits.clear()
    root, task_root, env = T.s0_project("QA-1", config={"adapters": {"ticket": {
        "kind": "jira", "method": "agent", "invoke": "jira-assistant", "direct_api": direct}}})
    env.update(QA_JIRA_EMAIL="reader@example.invalid")
    env.pop("QA_JIRA_API_TOKEN", None)
    try:
        out = T.run_driver(root, env, "--task", "QA-1", "--max-boundaries", "0", "--mr", "12", "--branch-suffix", "my suffix",
                           "--env", "local", "--ungrounded")
        T.eq("K10 (item 3): a token variable the shell lacks: the same `ticket_auth` question (exit 3)", out.returncode, 3, out.stdout[-1500:] + out.stderr[-800:])
        ask = T.s0_question(task_root)
        details = (task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8")
        check_eq("K10 (item 3): it is the `ticket_auth` block, no agent called", (T.s0_state(task_root).get("s0_block"), (root / "stub-log.jsonl").exists()),
                 ("ticket_auth", False))
        check("K10 (item 3): the question names the VARIABLE - in the answer block and in the adapter's own sentence beside it - and never a value",
              ask.count("QA_JIRA_API_TOKEN") + details.count("QA_JIRA_API_TOKEN") >= 2 and "reader@example.invalid" not in ask + details
              and "test-only-token" not in ask + details, ask[-900:] + details[-400:])
        check("K10 (item 3): and says the shell lacks it (in the factory's own words): no 'network or VPN' advice, no `ticket_read` question",
              "VPN" not in ask and "not set in this shell" in details, details[-500:])
        T.eq("K10 (item 3): not one request reached the tracker (the first run's control counted them)", hits, [])
        check("K10 (item 3): nothing was written for the story", not (task_root / "work/ticket-snapshot.json").exists() and not (task_root / "pipeline.json").exists())
    finally:
        server.shutdown()
        server.server_close()
        harness.cleanup(root)


def k10b_the_tracker_is_behind_a_protection_page():
    """B-408 (AK5): the whole S0 as a process against a tracker whose address answers 403 with a protection layer's HTML
    page (Cloudflare headers, a title) to every request - the answer a colleague's machine met on 06.10.2026 and the
    driver turned into "renew the token". It is the `ticket_read` question (exit 3), never `InfraStop:auth` (exit 5):
    the body asserts no author and no token claim, the title and the check command stand in the answer block only,
    and the token's value is nowhere."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import http_client

    page = (b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>"
            b"<body>Sorry, you have been blocked</body></html>")
    hits = []

    class Blocks(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.path, self.headers.get("User-Agent", "")))
            self.send_response(403)
            self.send_header("Server", "cloudflare")
            self.send_header("CF-RAY", "8a1b2c3d4e5f-AMS")
            self.send_header("Content-Type", "text/html; charset=UTF-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Blocks)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    direct = {"base_url": base, "api_version": "2", "auth_type": "basic_token",
              "username_ref": "QA_JIRA_EMAIL", "secret_ref": "QA_JIRA_API_TOKEN"}
    root, task_root, env = T.s0_project("QA-1", config={"adapters": {"ticket": {
        "kind": "jira", "method": "agent", "invoke": "jira-assistant", "direct_api": direct}}})
    env.update(QA_JIRA_EMAIL="reader@example.invalid", QA_JIRA_API_TOKEN="test-only-token")
    env["no_proxy"] = env["NO_PROXY"] = "127.0.0.1,localhost"
    try:
        out = T.run_driver(root, env, "--task", "QA-1", "--max-boundaries", "0", "--ungrounded", "--env", "local")
        T.eq("K10b: S0 asks the `ticket_read` question (exit 3), it does not stop as a lost login (exit 5)", out.returncode, 3,
             out.stdout[-1500:] + out.stderr[-800:])
        ask = T.s0_question(task_root)
        body, _, block = ask.partition("\n---\n")
        T.eq("K10b: the block is `ticket_read`", T.s0_state(task_root).get("s0_block"), "ticket_read")
        check_in("K10b: the body is the critic's `tried` text: something between this machine and the tracker answered, or the "
                 "answer could not be read, and the token was not checked",
                 "the answer did not come from the tracker in a form I can read: something between this machine and the tracker "
                 "(a firewall, a proxy or a protection service) answered instead, or the answer could not be read. I could not "
                 "check whether the account's token works.", body)
        check_in("K10b: ... and the `fix` text: check the address from this machine, outside the factory, with the command below",
                 "check the tracker's address from this machine, outside the factory, with the command below", body)
        check("K10b: the body carries neither the title nor any claim about the token",
              "Attention Required" not in body and "Cloudflare" not in body and "renew" not in body.lower()
              and "stopped accepting" not in body, body)
        check_in("K10b: the answer block holds what answered, in the factory's own words, with the title",
                 "What answered, in the factory's own words:", block)
        check_in("K10b: ... the title", "Attention Required! | Cloudflare", block)
        check_in("K10b: ... and the check, a GET to the tracker's own address with no credential",
                 "Check: " + http_client.curl_line(base + "/rest/api/2/serverInfo"), block)
        check("K10b: no token value or user anywhere in the question", "test-only-token" not in ask and "reader@example.invalid" not in ask)
        T.eq("K10b: the rules of the text a person reads hold", T.rules_broken(ask), [])
        check("K10b: the factory's User-Agent reached the server, never urllib's",
              bool(hits) and all(ua.startswith("qa-factory/") for _path, ua in hits), str(hits))
        check("K10b: nothing was written for the story, and no agent was called", not (task_root / "pipeline.json").exists()
              and not (task_root / "work/ticket-snapshot.json").exists() and not (root / "stub-log.jsonl").exists())
    finally:
        server.shutdown()
        server.server_close()
        harness.cleanup(root)


def k15_a_retry_is_not_a_conductor_call():
    root, task_root, env, driver, delays = project_of(control([entry(MALFORMED, turns=1)]))
    try:
        driver.boundary = "S1:S1-qa-scout-1"
        verdict = driver.conductor("controller: the moon is down and nobody knows why")
        check_eq("K15: the conductor's own answer comes back after the retry", verdict.get("action"), "continue")
        check_eq("K15: one call counted for the boundary, not two", driver.conductor_calls, {"S1:S1-qa-scout-1": 1})
        check_eq("K15: the wait was taken once", delays, [5])
        check_eq("K15: two claude calls made", len(calls(root)), 2)
    finally:
        done(root)


SCENARIOS = (
    k9_the_conductor_meets_auth,
    k10_the_tracker_meets_auth,
    k10b_the_tracker_is_behind_a_protection_page,
    k15_a_retry_is_not_a_conductor_call,
)


# split: runner piece 1
# `test_infra_failure.py k2_auth_stops_the_driver k5_transient_three_times` runs only those (a mutation
# control names the one scenario it targets); with no names, all of them run - the witness is that run.
for _fn in SCENARIOS:
    if not sys.argv[1:] or _fn.__name__ in sys.argv[1:]:
        scenario(_fn)


finish("test_infra_failure_conductor_tracker")
