"""F01/F23 canonical inventory and original Jira material collection."""
import hashlib
import io
import json
import os
import sys
import urllib.error
from pathlib import Path

from harness import (FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish,
                     run_script, temp_dir)

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from source_inventory import (AuthLost, JiraClient, canonical_ticket, collect_jira_source, completeness,
                              jira_ticket, peek_jira_source, probe_jira_direct,
                              record_attachment_inspection,
                              normalize_url, record_external_media, record_relevance_assessment,
                              runtime_credential_values, stable_source_id, VCS_URL_RE,
                              update_inventory, validate_inventory,
                              verify_inventory_files, FetchError)  # noqa: E402
import ticket_light as TL  # noqa: E402


class Response:
    def __init__(self, data, content_type="application/json", headers=None, url=None):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.url = url

    def read(self):
        return self.data

    def geturl(self):
        return self.url or "https://jira.example.invalid/fixture"


def main():
    root = temp_dir("qa-source-inventory-")
    old_email, old_token = os.environ.get("QA_JIRA_EMAIL"), os.environ.get("QA_JIRA_TOKEN")
    os.environ["QA_JIRA_EMAIL"] = "reader@example.invalid"
    os.environ["QA_JIRA_TOKEN"] = "test-only-token"
    calls, sleeps = [], []
    issue = {"id": "101", "key": "APP-1", "fields": {
        "summary": "Render graph", "issuetype": {"name": "Story"},
        "status": {"name": "Open"}, "updated": "2026-09-19T10:00:00Z",
        "customfield_54321": "Graph must retain colors",
        "description": {"content": [{"content": [{"text": "See BUG-2",
                                                     "attrs": {"url": "https://share.example.invalid/demo.mp4"}}]}]},
        "parent": {"key": "PARENT-9"},
        "issuelinks": [{"inwardIssue": {"key": "INC-4"}}],
        "attachment": [{"id": "55", "filename": "../graph dark.png",
                                             "mimeType": "image/png", "size": 3,
                                             "content": "https://jira.example.invalid/file/55"}],
        "comment": {"startAt": 0, "total": 2, "comments": [
            {"id": "1", "author": {"displayName": "A"}, "body": "first", "created": "x"}]}}}

    def opener(request, timeout=0):
        calls.append((request.full_url, request.headers.get("Authorization")))
        if "/issue/APP-1?" in request.full_url:
            return Response(issue)
        if "/comment?" in request.full_url:
            return Response({"startAt": 1, "total": 2, "comments": [
                {"id": "2", "author": {"displayName": "B"}, "body": "INC-3 detail", "created": "y"}]})
        if request.full_url.endswith("/file/55"):
            return Response(b"PNG", "image/png")
        # APP (task), PARENT-9 (parent) and INC-4 (issuelinks) are known prefixes at
        # no extra cost; BUG is not, and its lone probe (not one per key) says it is real.
        if request.full_url.endswith("/project/BUG"):
            return Response({"key": "BUG"})
        raise AssertionError(request.full_url)

    try:
        client = JiraClient("https://jira.example.invalid", "QA_JIRA_EMAIL", "QA_JIRA_TOKEN",
                            api_version="3", acceptance_criteria_fields=["customfield_54321"],
                            opener=opener, sleeper=sleeps.append)
        normalized = jira_ticket(client, "APP-1")
        check_eq("direct API serves legacy get without assistant", normalized["key"], "APP-1")
        check_eq("direct get paginates comments", len(normalized["comments"]), 2)
        check_eq("configured AC field is preserved", normalized["acceptance_criteria"],
                 ["Graph must retain colors"])
        output = root / "work" / "source-inventory.json"
        record = collect_jira_source(client, "APP-1", output, fetched_at="2026-09-19T12:00:00Z")
        inventory = update_inventory(output, record)
        check_eq("full source is read", record["status"], "read")
        check_eq("linked media is not hidden by successful issue fetch",
                 record["materials"]["external_media"]["status"], "pending")
        check_eq("all comment pages are collected", record["materials"]["comments"]["count"], 2)
        check_eq("references in description and comments are discovered", record["mentioned_ticket_keys"],
                 ["BUG-2", "INC-3", "INC-4", "PARENT-9"])
        attachment = record["materials"]["attachments"]["items"][0]
        check_eq("original attachment is read", attachment["status"], "read")
        check("attachment path follows canonical safe layout",
              attachment["local_ref"] == "blobs/" + attachment["content_hash"])
        check("original bytes persist", (output.parent / attachment["local_ref"]).read_bytes() == b"PNG")
        check_eq("fresh inventory validates", validate_inventory(inventory), [])
        check_eq("mentioned sources become visible pending records", len(inventory["sources"]), 5)
        check_eq("mentioned sources block completion until assessed", completeness(inventory)["gate_blocked"], True)
        bug = next(s for s in inventory["sources"] if s["canonical_ref"].endswith("/BUG-2"))
        inventory = record_relevance_assessment(output, bug["source_id"], "not_relevant",
                                                "read issue concerns an unrelated service",
                                                "work/evidence/BUG-2-assessment.json")
        excluded = next(s for s in inventory["sources"] if s["source_id"] == bug["source_id"])
        check_eq("content-based relevance exclusion is persisted", excluded["status"], "excluded")
        inventory = record_relevance_assessment(output, record["source_id"], "relevant",
                                                "full ticket text and comments inspected",
                                                "work/evidence/APP-1-source-inspection.json")
        record = next(s for s in inventory["sources"] if s["source_id"] == record["source_id"])
        check_eq("fetch and semantic source inspection are separate receipts",
                 record["inspection_status"], "read")
        material_inventory = {"schema_version": 1, "sources": [record]}
        check_eq("downloaded but unanalyzed media remains incomplete", completeness(material_inventory)["complete"], False)
        check("attachment analysis gap is visible",
              record["source_id"] in completeness(material_inventory)["incomplete_materials"])
        inventory = record_attachment_inspection(output, record["source_id"], "55", "read",
                                                 "work/evidence/graph-observation.json")
        record = next(s for s in inventory["sources"] if s["source_id"] == record["source_id"])
        attachment = record["materials"]["attachments"]["items"][0]
        material_inventory = {"schema_version": 1, "sources": [record]}
        # Attachment inspection alone cannot complete a linked document/video outcome.
        check_eq("linked media keeps source incomplete", completeness(material_inventory)["complete"], False)
        # A cause from the closed list, then the fact observed. TP1-13797, 26.09: four MR pages
        # were filed unavailable with "superseded ... already captured from ticket text" — a
        # judgement about relevance in the field that means "I could not get it", and any non-empty
        # string passed, so nothing was ever red.
        try:
            record_external_media(output, record["source_id"], "https://share.example.invalid/demo.mp4",
                                  "unavailable", "Superseded, already captured from the ticket text")
            check("a judgement is refused as a cause", False)
        except ValueError as exc:
            check_in("the refusal prints the closed list", "auth_required", str(exc))
            check_in("and names where a relevance judgement belongs", "not_relevant", str(exc))
        try:
            record_external_media(output, record["source_id"], "https://share.example.invalid/demo.mp4",
                                  "unavailable", "auth_required")
            check("a cause with no observed fact is refused", False)
        except ValueError as exc:
            check_in("the refusal asks for the fact", "after the colon", str(exc))
        inventory = record_external_media(output, record["source_id"],
                                          "https://share.example.invalid/demo.mp4", "unavailable",
                                          "auth_required: SharePoint SSO, no configured route")
        record = next(s for s in inventory["sources"] if s["source_id"] == record["source_id"])
        media_item = record["materials"]["external_media"]["items"][0]
        check_eq("the cause is recorded as a word", media_item["cause"], "auth_required")
        check_eq("an access cause is marked as one", media_item["access_problem"], True)
        material_inventory = {"schema_version": 1, "sources": [record]}
        check("explicit linked-media failure is a visible gap",
              record["source_id"] in completeness(material_inventory)["unavailable_materials"])
        # A merge request is not a web page the run cannot open: the factory collects it with
        # vcs_evidence.py, so `no_tool` is never true for one.
        mr_url = "https://githost.example.invalid/group/app/-/merge_requests/3890"
        raw = json.loads(output.read_text(encoding="utf-8"))
        for source in raw["sources"]:
            if source["source_id"] == record["source_id"]:
                source["materials"]["external_media"]["items"].append(
                    {"url": mr_url, "status": "pending", "error": None, "local_ref": None})
        output.write_text(json.dumps(raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")
        try:
            record_external_media(output, record["source_id"], mr_url, "unavailable",
                                  "no_tool: this run has no browser")
            check("no_tool on a merge request is refused", False)
        except ValueError as exc:
            check_in("the refusal names the collector", "vcs_evidence.py --url", str(exc))
            check_in("and the cause to use if it fails too", "host_unreachable", str(exc))
        inventory = record_external_media(output, record["source_id"], mr_url, "unavailable",
                                          "host_unreachable: could not resolve githost.example.invalid")
        mr_item = next(i for i in next(s for s in inventory["sources"]
                                       if s["source_id"] == record["source_id"]
                                       )["materials"]["external_media"]["items"] if i["url"] == mr_url)
        check_eq("the collector's own cause is accepted", mr_item["cause"], "host_unreachable")
        check_eq("a dropped VPN reads as an access problem", mr_item["access_problem"], True)
        check_eq("a markdown-escaped URL is still a merge request",
                 bool(VCS_URL_RE.search(normalize_url(
                     "https://githost.example.invalid/g/a/-/merge\\_requests/3890"))), True)
        # The same rule for an attachment: a receipt that says "unavailable" and nothing else told
        # the person "attachment: ? — no cause recorded".
        try:
            record_attachment_inspection(output, record["source_id"], "55", "unavailable",
                                         "work/evidence/graph-observation.json")
            check("an uninspected attachment with no cause is refused", False)
        except ValueError as exc:
            check_in("the refusal offers the same closed list", "no_tool", str(exc))
        inventory = record_attachment_inspection(output, record["source_id"], "55", "unavailable",
                                                 "work/evidence/graph-observation.json",
                                                 "no_tool: a png needs a reader this run has not got")
        attachment = next(s for s in inventory["sources"]
                          if s["source_id"] == record["source_id"])["materials"]["attachments"]["items"][0]
        check_eq("the attachment's cause is a word too", attachment["analysis_cause"], "no_tool")
        check_eq("empty inventory cannot fabricate complete", completeness({"schema_version": 1, "sources": []})["complete"], False)
        check_eq("persisted source hashes verify", verify_inventory_files(root, inventory)["valid"], True)
        # `accept-gap` prints what an earlier acceptance already closed on its own line, on a copy so
        # the inventory the rest of this test reads stays as it is.
        copy_dir = root / "accept-copy"
        copy_dir.mkdir()
        copy_path = copy_dir / "source-inventory.json"
        copy_path.write_bytes(output.read_bytes())
        first = run_script("ticket_adapter.py", "accept-gap", "--output", copy_path,
                           "--source-id", record["source_id"], "--words", "go on without it")
        first_lines = first.stdout.splitlines()
        check("accept-gap first call: exits 0 and prints an accepted line",
              first.returncode == 0 and any(line.startswith("accepted: APP-1:") for line in first_lines))
        check("accept-gap negative control: nothing accepted before, no already-accepted line",
              not any(line.startswith("already accepted:") for line in first_lines))
        again = run_script("ticket_adapter.py", "accept-gap", "--output", copy_path,
                           "--source-id", record["source_id"], "--words", "same again")
        again_lines = again.stdout.splitlines()
        check("accept-gap repeat: points already accepted print as `already accepted: <KEY>:`",
              again.returncode == 0 and any(line.startswith("already accepted: APP-1:") for line in again_lines))
        check("accept-gap repeat: nothing newly accepted, so no `accepted:` line",
              not any(line.startswith("accepted:") for line in again_lines))
        old_snapshot = output.parent / record["snapshot_ref"]
        old_snapshot_bytes = old_snapshot.read_bytes()
        output.read_bytes()
        calls_before = len(calls)
        reused = collect_jira_source(client, "APP-1", output, existing_record=record)
        check_eq("incomplete refresh retries metadata/comments but reuses original bytes", len(calls) - calls_before, 2)
        check_eq("an unchanged revision whose files verify reports unchanged, even when incomplete",
                 reused["_refresh_result"], "unchanged")
        check_eq("and its open gaps stay open: the reused source is not silently complete",
                 completeness({"schema_version": 1, "sources": [reused]})["complete"], False)
        update_inventory(output, reused)
        check_eq("retry preserves downloaded attachment inspection", reused["materials"]["attachments"]["items"][0]["analysis_status"], "read")
        issue["fields"]["updated"] = "2026-09-19T11:00:00Z"
        calls_before = len(calls)
        changed_record = collect_jira_source(client, "APP-1", output, existing_record=record,
                                             fetched_at="2026-09-19T13:00:00Z")
        check_eq("changed revision fetches issue, comments and original", len(calls) - calls_before, 3)
        check_eq("changed revision rebuilds source", changed_record["_refresh_result"], "changed")
        check_eq("changed revision invalidates semantic inspection", changed_record["inspection_status"], "pending")
        inventory = update_inventory(output, changed_record)
        record = next(s for s in inventory["sources"] if s["source_id"] == record["source_id"])
        check("prior immutable snapshot remains readable", old_snapshot.read_bytes() == old_snapshot_bytes)
        check("prior revision lineage is retained", any(h["revision"] == "2026-09-19T10:00:00Z"
                                                        for h in record.get("prior_revisions", [])))
        attachment = record["materials"]["attachments"]["items"][0]
        (output.parent / attachment["local_ref"]).write_bytes(b"changed")
        changed = verify_inventory_files(root, inventory)
        check_eq("changed original requires refresh", changed["requires_refresh"], True)
        check("changed source id is reported", record["source_id"] in changed["invalid_source_ids"])
        check("authorization never appears in persisted inventory", "test-only-token" not in output.read_text())
        check("deterministic source identity ignores revision",
              record["source_id"] == stable_source_id(client.base_url,
                                                       canonical_ticket(client.base_url, "APP-1")))
        update_inventory(output, record)
        check_eq("same canonical ref and revision deduplicates", len(json.loads(output.read_text())["sources"]), 5)

        def forbidden(request, timeout=0):
            if "fields=updated" in request.full_url:
                # t-267 C5: a 403 is first checked against the login - one re-read of a ticket this run
                # already read. Here the login works, so the 403 is about APP-9 alone.
                return Response({"key": "APP-1"}, url=request.full_url)
            raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, None)

        blocked = collect_jira_source(JiraClient(client.base_url, "QA_JIRA_EMAIL", "QA_JIRA_TOKEN",
                                                  opener=forbidden), "APP-9", output)
        check_eq("403 is explicit unavailable", blocked["status"], "unavailable")
        check_eq("403 is not blindly retryable", blocked["retryable"], False)
        pending_inventory = {"schema_version": 1, "sources": [{**record, "status": "pending"}]}
        check_eq("pending required source blocks gate", completeness(pending_inventory)["gate_blocked"], True)

        try:
            client.get_bytes("https://evil.example.invalid/steal")
            check("cross-origin attachment refuses auth forwarding", False)
        except FetchError as exc:
            check("cross-origin attachment refuses auth forwarding", "cross-origin" in exc.reason)

        probe_path = root / "work" / "jira-direct-probe.json"
        # Add the read-only serverInfo response used by the reusable readiness probe.
        original_opener = client.opener
        client.opener = lambda request, timeout=0: (
            Response({"serverTitle": "Fixture Jira"}) if request.full_url.endswith("/serverInfo") else
            Response({"accountId": "reader-1"}) if request.full_url.endswith("/myself") else
            original_opener(request, timeout))
        probe = probe_jira_direct(client, probe_path, "APP-1")
        check_eq("direct probe records available", probe["status"], "available")
        check_eq("probe proves identity, issue, comments and an original",
                 [c["name"] for c in probe["checks"]],
                 ["server_info", "authenticated_identity", "sample_issue",
                  "paginated_comments", "attachment_original"])
        check_eq("probe attachment original is read", probe["checks"][-1]["status"], "available")
        check("probe persists only secret reference", "test-only-token" not in probe_path.read_text())
        no_sample = probe_jira_direct(client, probe_path)
        check_eq("probe without selected sample cannot claim available", no_sample["status"], "unavailable")
        mockup_client = JiraClient(client.base_url, "QA_JIRA_EMAIL", "QA_JIRA_TOKEN",
                                   opener=lambda request, timeout=0: Response(
                                       b"<html><body><form>login password mockup</form></body></html>", "text/html",
                                       url=request.full_url))
        check_eq("legitimate HTML attachment remains valid original bytes",
                 mockup_client.get_bytes(client.base_url + "/secure/mockup.html"),
                 b"<html><body><form>login password mockup</form></body></html>")
        ok_html = b"<html>original workflow mockup</html>"
        for reason in ("OK", " ok "):
            ok_client = JiraClient(client.base_url, "QA_JIRA_EMAIL", "QA_JIRA_TOKEN",
                                  opener=lambda request, timeout=0: Response(
                                      ok_html, "text/html;charset=UTF-8",
                                      {"X-Seraph-LoginReason": reason}, request.full_url))
            check_eq("authenticated HTML attachment preserves original bytes: " + reason,
                     ok_client.get_bytes(client.base_url + "/secure/mockup.html"), ok_html)
        for headers, final_url in (
                ({"X-Seraph-LoginReason": "OK", "X-Authentication-Denied-Reason": "denied"},
                 client.base_url + "/secure/mockup.html"),
                ({"X-Seraph-LoginReason": "OK"}, client.base_url + "/login.jsp")):
            denied_client = JiraClient(client.base_url, "QA_JIRA_EMAIL", "QA_JIRA_TOKEN",
                                       opener=lambda request, timeout=0: Response(
                                           b"<html>login</html>", "text/html", headers, final_url))
            try:
                denied_client.get_bytes(client.base_url + "/secure/mockup.html")
                check("OK does not override explicit denial or login redirect", False)
            except FetchError as exc:
                check("OK does not override explicit denial or login redirect", "HTML login" in exc.reason)
        html_client = JiraClient(client.base_url, "QA_JIRA_EMAIL", "QA_JIRA_TOKEN",
                                 opener=lambda request, timeout=0: Response(
                                     b"<html>login</html>", "text/html",
                                     {"X-Seraph-LoginReason": "AUTHENTICATION_DENIED"},
                                     request.full_url))
        try:
            html_client.get_bytes(client.base_url + "/secure/file")
            check("HTML login is rejected as original content", False)
        except FetchError as exc:
            check("HTML login is rejected as original content", "HTML login" in exc.reason)
    finally:
        if old_email is None:
            os.environ.pop("QA_JIRA_EMAIL", None)
        else:
            os.environ["QA_JIRA_EMAIL"] = old_email
        if old_token is None:
            os.environ.pop("QA_JIRA_TOKEN", None)
        else:
            os.environ["QA_JIRA_TOKEN"] = old_token
        cleanup(root)
    test_post_json()
    test_the_ticket_by_rest()
    test_configured_env_file_credentials()
    test_gap_defaults()
    test_gap_words_and_basis()
    test_media_refusal()
    finish("test_source_inventory")


def test_configured_env_file_credentials():
    """M10: a direct tracker read took credentials from the process environment only, while
    `env_probe` also read the project's configured env file - so a project that kept its
    tracker token there was told "credentials missing" by the very reader that needed it.
    Fixture values are made up; none of them may reach an error message."""
    import base64
    root = temp_dir("qa-source-credentials-")
    try:
        (root / ".env").write_text("JIRA_TOKEN=from-config-file\nJIRA_USER=file-user\n", encoding="utf-8")
        (root / "second.env").write_text("JIRA_TOKEN=from-second-file\nONLY_SECOND=second-only\n", encoding="utf-8")
        cfg = {"environment": {"env_file": ".env"}}
        from_file = runtime_credential_values(cfg, root, {"PATH": "fixture"})
        check_eq("configured env file supplies a missing tracker credential", from_file["JIRA_TOKEN"], "from-config-file")
        process_wins = runtime_credential_values(cfg, root, {"JIRA_TOKEN": "from-process"})
        check_eq("process credential takes precedence over configured env file", process_wins["JIRA_TOKEN"], "from-process")
        check_eq("a name only the file holds is still filled next to a process one", process_wins["JIRA_USER"], "file-user")
        empty = runtime_credential_values(cfg, root, {"JIRA_TOKEN": ""})
        check_eq("an empty process value counts as missing and is filled from the file",
                 empty["JIRA_TOKEN"], "from-config-file")
        gone = {"environment": {"env_file": "no-such.env", "env_files": ["also-missing.env", "."]}}
        check_eq("an absent or unreadable env file is skipped: the process environment alone",
                 runtime_credential_values(gone, root, {"JIRA_TOKEN": "p"}), {"JIRA_TOKEN": "p"})
        check_eq("no environment block: the process environment alone",
                 runtime_credential_values({}, root, {"A": "1"}), {"A": "1"})
        check_eq("no config at all (None, root given): the process environment alone",
                 runtime_credential_values({"environment": None}, root, {"A": "1"}), {"A": "1"})
        many = runtime_credential_values({"environment": {"env_file": ".env", "env_files": ["second.env"]}},
                                         root, {})
        check_eq("env_file is read before env_files: the first file defining a name wins",
                 many["JIRA_TOKEN"], "from-config-file")
        check_eq("a later env_files entry still supplies what the first lacks", many["ONLY_SECOND"], "second-only")
        listed = runtime_credential_values({"environment": {"env_files": ["second.env", ".env"]}}, root, {})
        check_eq("env_files keep their listed order", listed["JIRA_TOKEN"], "from-second-file")
        (root / "sub").mkdir()
        (root / "sub" / ".env").write_text("SUB_ONLY=in-sub\n", encoding="utf-8")
        check_eq("paths are relative to the project root, not the cwd",
                 runtime_credential_values({"environment": {"env_file": "sub/.env"}}, root, {}),
                 {"SUB_ONLY": "in-sub"})

        # The client itself: names that the process does not hold, a file that does.
        for name in ("QA_FILE_USER", "QA_FILE_TOKEN"):
            check(name + " is not in the process environment for this fixture", name not in os.environ)
        (root / "client.env").write_text("QA_FILE_USER=reader\nQA_FILE_TOKEN=file-secret-value\n", encoding="utf-8")
        client_cfg = {"environment": {"env_file": "client.env"}}
        client = JiraClient("https://jira.example.invalid", "QA_FILE_USER", "QA_FILE_TOKEN",
                            config=client_cfg, root=root)
        expected = "Basic " + base64.b64encode(b"reader:file-secret-value").decode("ascii")
        check_eq("the client builds its header from the configured env file",
                 client._headers()["Authorization"], expected)
        os.environ["QA_FILE_TOKEN"] = "process-secret-value"
        try:
            got = client._headers()["Authorization"]
            check_eq("a non-empty process value wins inside the client",
                     got, "Basic " + base64.b64encode(b"reader:process-secret-value").decode("ascii"))
            os.environ["QA_FILE_TOKEN"] = ""
            check_eq("an empty process value is filled from the file inside the client",
                     client._headers()["Authorization"], expected)
        finally:
            os.environ.pop("QA_FILE_TOKEN", None)

        # Missing everywhere: the refusal names the NAMES, never a value from the file.
        (root / "partial.env").write_text("QA_FILE_USER=reader-partial\n", encoding="utf-8")
        partial = JiraClient("https://jira.example.invalid", "QA_FILE_USER", "QA_FILE_TOKEN",
                             config={"environment": {"env_file": "partial.env"}}, root=root)
        try:
            partial._headers()
            check("a credential missing everywhere still refuses", False)
        except FetchError as exc:
            check_in("the refusal names the missing credential", "QA_FILE_TOKEN", exc.reason)
            check_not_in("the refusal never carries a file value", "reader-partial", exc.reason)
        unreadable = JiraClient("https://jira.example.invalid", "QA_FILE_USER", "QA_FILE_TOKEN",
                                config={"environment": {"env_file": "no-such.env"}}, root=root)
        try:
            unreadable._headers()
            check("an absent env file does not invent credentials", False)
        except FetchError as exc:
            check_in("an absent env file leaves the plain missing-credential refusal",
                     "missing credential environment reference(s)", exc.reason)
    finally:
        cleanup(root)


def test_post_json():
    """`post_json` — 's one write verb, added next to `get_json` for
    `external_writes.py`'s `adapters.ticket.direct_api` delivery. One attempt, no retry loop
    (see the method's own docstring: a retried POST can create the issue twice); a rejected
    write surfaces the tracker's own error text, never the token."""
    calls = []

    def opener(request, timeout=0):
        calls.append((request.get_method(), request.full_url, request.data,
                      request.headers.get("Content-type")))
        if request.full_url.endswith("/issue"):
            return Response({"key": "BUG-42", "id": "9001"})
        if request.full_url.endswith("/comment"):
            return Response({"id": "555"})
        if request.full_url.endswith("/bad"):
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {},
                io.BytesIO(json.dumps({"errorMessages": ["summary is required"]}).encode()))
        raise AssertionError(request.full_url)

    client = JiraClient("https://jira.example.invalid", "QA_JIRA_EMAIL", "SECRET_TOKEN_VAR",
                        opener=opener)
    os.environ["SECRET_TOKEN_VAR"] = "s3cr3t-do-not-print"
    os.environ.setdefault("QA_JIRA_EMAIL", "reader@example.invalid")
    try:
        created = client.post_json("/rest/api/2/issue", {"fields": {"project": {"key": "APP"}}})
        check_eq("post_json returns the parsed response body", created.get("key"), "BUG-42")
        check_eq("post_json sends POST, never GET", calls[-1][0], "POST")
        check("post_json sends the body as JSON", b'"project"' in calls[-1][2])
        check_eq("post_json sets a JSON content type", calls[-1][3], "application/json")

        commented = client.post_json("/rest/api/2/issue/BUG-42/comment", {"body": "seen again"})
        check_eq("a comment post returns its own response", commented.get("id"), "555")

        try:
            client.post_json("/rest/api/2/bad", {"fields": {}})
            check("a rejected write raises FetchError", False)
        except FetchError as exc:
            check_eq("the tracker's HTTP status is carried", exc.status, 400)
            check_in("the tracker's own message reaches the caller",
                     "summary is required", exc.reason)
            check_not_in("the token never appears in the failure", "s3cr3t-do-not-print",
                         exc.reason)
        # B-408 (E25): a page in place of the tracker's JSON error is DESCRIBED, never relayed raw
        page = (b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>"
                b"<body>blocked</body></html>")
        client.opener = lambda request, timeout=0: (_ for _ in ()).throw(urllib.error.HTTPError(
            request.full_url, 403, "blocked", {"Server": "cloudflare", "Content-Type": "text/html"}, io.BytesIO(page)))
        try:
            client.post_json("/rest/api/2/issue", {"fields": {}})
            check("a blocked write raises FetchError", False)
        except FetchError as exc:
            check("E25: an HTML error body is described (the title), never relayed raw",
                  "Attention Required! | Cloudflare" in exc.reason and "<html" not in exc.reason.lower()
                  and "<body" not in exc.reason.lower(), exc.reason)
            check_eq("E25: the answer rides on the error, classified intermediary", exc.answer.verdict["kind"], "intermediary")
    finally:
        os.environ.pop("SECRET_TOKEN_VAR", None)


# ---- t-267: the ticket by REST, in a light form (K8, K8b, K10, K12, K15) --------------------------------------
# The fixture is TP1-15045 as Jira answers it (fixtures/ticket-15045/, synthetic, example.test hosts):
# the description string is the owner's own test ticket, copied verbatim. Every request goes through ONE fake
# transport that logs it, so the request counts below are counted, not estimated.

FIX = FIXTURES / "ticket-15045"
KEY = "TP1-15045"
BASE = "https://jira.example.test"
RAW = (FIX / "raw-issue.json").read_bytes()
FIELDS = (FIX / "field.json").read_bytes()
REMOTE = (FIX / "remotelink.json").read_bytes()
REPOS = [{"repo_id": "testproject1-backend", "role": "review", "local_path": "../../testproject1",
          "remote_identity": "git@gi.example.test:org-cdme/testproject1.git"},
         {"repo_id": "testproject1-ui", "role": "review", "local_path": "../../testproject1-ui",
          "remote_identity": "git@gi.example.test:org-cdme/testproject1-ui.git"}]
HOSTS = [r["remote_identity"] for r in REPOS]
# a text attachment a person wrote: one key of the story's own project (known, no probe) and a /browse/ link
NOTES_TXT = b"See TP1-8384 and https://jira.example.test/browse/TP1-8384 here.".ljust(2048, b" ")
# the same ticket with one more key-shaped token in its comment: TC-001, a project the run does not know
DECOY = RAW.replace(b"merge_requests/1924", b"merge_requests/1924 see TC-001")
BEFORE_ENV = {}


def kline(label: str, text: str) -> None:
    print(f"{label}: {text}")


class Transport:
    """A fake Jira. The first route whose text is in the URL answers: bytes or a dict (200), an int (that
    HTTP status), a Response, an exception to raise, or a function of the request returning one of those.
    Every request is logged."""

    def __init__(self, routes):
        self.routes, self.log = list(routes), []

    def __call__(self, request, timeout=0):
        url = request.full_url
        self.log.append(url)
        for needle, answer in self.routes:
            if needle not in url:
                continue
            if callable(answer):
                answer = answer(request)
            if isinstance(answer, Exception):
                raise answer
            if isinstance(answer, int):
                raise urllib.error.HTTPError(url, answer, "status", {}, None)
            return answer if isinstance(answer, Response) else Response(answer, url=url)
        raise AssertionError("unexpected request: " + url)

    def count(self, needle: str) -> int:
        return sum(1 for url in self.log if needle in url)


def story_routes(issue=RAW, notes=NOTES_TXT, extra=()):
    return Transport([*extra,
                      ("/issue/TP1-15045/remotelink", REMOTE),
                      ("/issue/TP1-15045?fields=*all", issue),
                      ("/rest/api/2/field", FIELDS),
                      ("/secure/attachment/30001/", b"P" * 1048576),
                      ("/secure/attachment/30002/", notes)])


def client_for(transport, sleeps=None, **kw) -> JiraClient:
    kw.setdefault("custom_fields", ["customfield_20001"])
    # M10 (H20): a client with no `config` looks a missing credential up in the AMBIENT project's env
    # file; the item 3 checks unset the variables on purpose, so no test client reads the project.
    kw.setdefault("config", {})
    return JiraClient(BASE, "QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN", api_version="2", opener=transport,
                      sleeper=(sleeps if sleeps is not None else []).append, **kw)


def app_issue(**fields) -> dict:
    base = {"summary": "Render graph", "issuetype": {"name": "Story"}, "status": {"name": "Open"},
            "updated": "2026-09-19T10:00:00Z", "description": "plain text", "attachment": [],
            "comment": {"startAt": 0, "total": 0, "comments": []}}
    base.update(fields)
    return {"id": "101", "key": "APP-1", "fields": base}


def attachment(number: int, name: str = "a.png") -> dict:
    return {"id": str(number), "filename": name, "mimeType": "image/png", "size": 3,
            "content": f"{BASE}/file/{number}"}


def refused(call):
    try:
        call()
    except AuthLost as exc:
        return exc
    return None


def k8_requests(root: Path) -> None:
    for label, issue, extra, probes in (("without the decoy", RAW, (), 0),
                                        ("with the TC-001 decoy", DECOY, [("/project/TC", 404)], 1)):
        work = root / ("decoy" if probes else "plain") / "work"
        # --- S0: `ticket_adapter get --raw-dir` ---
        t0, said = story_routes(issue, extra=extra), []
        snapshot = jira_ticket(client_for(t0), KEY, work / "ticket-raw", say=said.append,
                               context={"repos": REPOS, "known_hosts": HOSTS})
        if not probes:
            plain_snapshot = snapshot
        s0 = {"issue": t0.count("?fields=*all"), "field": t0.count("/rest/api/2/field"),
              "remotelink": t0.count("/remotelink"), "comments": t0.count("/comment?"),
              "project probes": t0.count("/project/")}
        check_eq(f"K8 ({label}): S0 costs issue 1 + field 1 + remotelink 1 + comments 0 (embedded), no probe",
                 s0, {"issue": 1, "field": 1, "remotelink": 1, "comments": 0, "project probes": 0})
        check_eq(f"K8 ({label}): ... three requests in all", len(t0.log), 3)
        rows = json.loads((work / "ticket-references.json").read_text(encoding="utf-8"))["rows"]
        index = {r["ref"]: r for r in rows}
        parent = index.get("TP1-14482") or {}
        check(f"K8 ({label}): TP1-14482 once, origins hold field:parent, mention:summary, mention:description",
              [r["ref"] for r in rows].count("TP1-14482") == 1
              and {"field:parent", "mention:summary", "mention:description"} <= set(parent.get("origins", [])), str(parent))
        want = 6 + (1 if probes else 0)
        check_eq(f"K8 ({label}): the S0 references are exactly {want} rows (attachments are NOT scanned at S0)",
                 len(rows), want)
        check_eq(f"K8 ({label}): MR !4214 -> testproject1-backend, MR !1881 -> testproject1-ui",
                 ((index.get("!4214") or {}).get("repo_id"), (index.get("!1881") or {}).get("repo_id")),
                 ("testproject1-backend", "testproject1-ui"))
        mr1924 = [r for r in rows if r["kind"] == "merge_request" and r["ref"].endswith("/merge_requests/1924")]
        check_eq(f"K8 ({label}) / t-287 item 4: MR 1924 - the comment's URL AND the remote link (another host and group, the same repository "
                 "name) - is ONE row: origins in order, tied to testproject1-ui, `not_fetched` for S1 (not `person`)",
                 [(r.get("repo_id"), r["origins"], r["status"]) for r in mr1924],
                 [("testproject1-ui", ["mention:comment:15923998", "field:remotelink"], "not_fetched:not read yet")])
        check_eq(f"K8 ({label}) / t-287 item 4: the snapshot's merge request link is the remote link's URL",
                 snapshot["links"]["merge_request"], "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924")
        check_eq(f"K8 ({label}): the 15045 text names no ticket of another project, so S0 asks no probe",
                 sorted(r["ref"] for r in rows if r["kind"] == "ticket"),
                 (["TC-001"] if probes else []) + ["TP1-14482"])
        seeded = json.loads((work / "source-inventory.json").read_text(encoding="utf-8"))
        check_eq(f"K8 ({label}): S0 seeds the inventory: Epic Link ids, the proven prefixes, the proof key",
                 (seeded["field_ids"]["epic_link"], sorted(seeded["prefix_probes"]), seeded["proof_key"]),
                 (["customfield_10014", "customfield_10015"], ["TP1"], KEY))
        check_eq(f"K8 ({label}): the story's own prefix is recorded as a tracker project, not probed",
                 seeded["prefix_probes"]["TP1"]["result"], "tracker")
        # --- S1: `ticket_adapter collect` on the same story, another process ---
        output = work / "source-inventory.json"
        t1 = story_routes(issue, extra=extra)
        record = collect_jira_source(client_for(t1), KEY, output)
        update_inventory(output, record)
        s1 = {"issue": t1.count("?fields=*all"), "attachments": t1.count("/secure/attachment/"),
              "field": t1.count("/rest/api/2/field"), "project probes": t1.count("/project/"),
              "remotelink": t1.count("/remotelink")}
        check_eq(f"K8 ({label}): S1 collect = issue 1 + 2 attachments + {probes} project probe(s); no second /field",
                 s1, {"issue": 1, "attachments": 2, "field": 0, "project probes": probes, "remotelink": 0})
        total = len(t0.log) + len(t1.log)
        check(f"K8 ({label}): S0 + S1 cost {total} requests in all, at most 12", record["status"] == "read" and total <= 12)
        after = json.loads((work / "ticket-references.json").read_text(encoding="utf-8"))
        check_eq(f"K8 ({label}): S1 appended the text attachment's key and says it scanned attachments",
                 (sorted(r["ref"] for r in after["rows"] if r["kind"] == "ticket" and r["ref"] == "TP1-8384"),
                  "attachments" in after["scanned"], after["written_by"]),
                 (["TP1-8384"], True, ["S0", "S1"]))
        if probes:
            tc = next(r for r in after["rows"] if r["ref"] == "TC-001")
            check(f"K8 ({label}): the decoy TC-001 is settled by the one probe: listed with the reason, not fetched",
                  tc["status"].startswith("not_fetched:not found (404)") and "tracker project 'TC'" in tc["status"], tc["status"])
        kline("K8", f"{label}: S0 = {len(t0.log)} requests (issue {s0['issue']}, field {s0['field']}, remotelink "
                    f"{s0['remotelink']}, comments {s0['comments']}, project probes {s0['project probes']}); S1 collect = "
                    f"{len(t1.log)} (issue {s1['issue']}, attachments {s1['attachments']}, field {s1['field']}, project "
                    f"probes {s1['project probes']}); total {total} <= 12; per-key GETs 0")
    # --- the raw folder, byte for byte (C8) ---
    raw_dir = root / "plain" / "work" / "ticket-raw"
    check_eq("C8: the raw FOLDER holds every response, byte for byte, and the readable copy",
             sorted(p.name for p in raw_dir.iterdir()),
             ["field.json", "issue.json", "issue.pretty.json", "remotelink.json"])
    check("C8: issue.json is the response exactly as it came", (raw_dir / "issue.json").read_bytes() == RAW)
    check("C8: field.json and remotelink.json are the responses exactly as they came",
          (raw_dir / "field.json").read_bytes() == FIELDS and (raw_dir / "remotelink.json").read_bytes() == REMOTE)
    pretty = (raw_dir / "issue.pretty.json").read_bytes()
    check("C8: issue.pretty.json is the same issue, indented (a one-line JSON cannot be sliced)",
          json.loads(pretty) == json.loads(RAW) and pretty.count(b"\n") > 20 and b"\n  " in pretty)
    check("C8 negative control: the verbatim file is NOT the pretty one", (raw_dir / "issue.json").read_bytes() != pretty)
    prov = plain_snapshot["provenance"]
    check_eq("K4 (library): provenance is by code, from the route: fetched, *all, the bytes and the hash of issue.json",
             (prov["source"], prov["fields_requested"], prov["bytes"], prov["sha256"] == hashlib.sha256(RAW).hexdigest(),
              bool(prov["fetched_at"])),
             ("fetched", "*all", len(RAW), True, True))
    view = (root / "plain" / "work" / "ticket-view.md").read_text(encoding="utf-8")
    check("the line view carries the title, the whole description, 15 numbered criteria and the comment id first",
          "Testing TP1-14482 Visual Workflow Diff" in view and "QA Factory evaluation goals" in view
          and "15. Existing workflow versioning/text diff behavior is not regressed." in view
          and "\n15923998 " + TL.MID_DOT + " " in view)


def auth_loss(root: Path) -> None:
    lines = []
    # --- A: a 401 mid-collect (an attachment), the login check re-reads the ticket and is refused too ---
    out = root / "a" / "work" / "source-inventory.json"
    t = Transport([("fields=updated", 401), ("/issue/APP-1?fields=*all", app_issue(attachment=[attachment(55), attachment(56, "b.png")])),
                   ("/file/55", 401)])
    c = client_for(t, custom_fields=[])
    exc = refused(lambda: collect_jira_source(c, "APP-1", out))
    check("K8b: a 401 mid-collect stops the run (AuthLost), it is not booked as an unavailable attachment", exc is not None)
    text = str(exc)
    check_in("K8b: the ONE refusal names the token's environment variable", "QA_JIRA_API_TOKEN", text)
    check_eq("K8b: ... as one line", len(text.splitlines()), 1)
    check("K8b: ... and says nothing after it was attempted or booked as not found",
          "nothing after this point was attempted" in text and "not found" in text)
    inventory = json.loads(out.read_text(encoding="utf-8"))
    check_eq("K8b: zero unavailable rows", [s for s in inventory["sources"] if s["status"] == "unavailable"], [])
    check_eq("K8b: the inventory marks the stop point",
             (inventory["auth_stop"]["stopped_at"], inventory["auth_stop"]["status"], inventory["auth_stop"]["door"]),
             ("attachment a.png of APP-1", 401, "QA_JIRA_API_TOKEN"))
    asked = len(t.log)
    check("K8b: the second attachment was never asked for", t.count("/file/56") == 0)
    again = refused(lambda: c.get_bytes(BASE + "/rest/api/2/issue/APP-2"))
    check("K8b: after the stop NOTHING is attempted: the same refusal, no request", again is not None and len(t.log) == asked)
    lines.append(f"401 mid-collect -> 1 refusal line naming QA_JIRA_API_TOKEN, 0 unavailable rows, auth_stop at '{inventory['auth_stop']['stopped_at']}'")
    # the renewed token: the next successful read clears the mark
    t_ok = Transport([("/issue/APP-1?fields=*all", app_issue(attachment=[attachment(55)])), ("/file/55", b"PNG")])
    update_inventory(out, collect_jira_source(client_for(t_ok, custom_fields=[]), "APP-1", out))
    check("K8b: a read after renewal removes the stop mark", "auth_stop" not in json.loads(out.read_text(encoding="utf-8")))
    # --- B: a 404 on a ticket of a PROVEN prefix, the login works: ONE not-found row, one check for many ---
    out = root / "b" / "work" / "source-inventory.json"
    t = Transport([("fields=updated", {"key": "APP-1"}), ("/issue/APP-1?fields=*all", app_issue()),
                   ("/issue/APP-7", 404), ("/issue/APP-8", 404), ("/issue/ZZZ-1", 404)])
    c = client_for(t, custom_fields=[])
    update_inventory(out, collect_jira_source(c, "APP-1", out))
    ghost = peek_jira_source(c, "APP-7", out)
    check_eq("K8b: a 404 with a working login is ONE not-found row", (ghost["status"], ghost.get("not_found")), ("excluded", True))
    check_eq("K8b: ... after ONE login check (a re-read of the ticket already read)", t.count("fields=updated"), 1)
    peek_jira_source(c, "APP-8", out)
    peek_jira_source(c, "ZZZ-1", out)
    check_eq("K8b: two more 404s (one of an unproven prefix) cost no further check: the positive answer is cached for the run",
             t.count("fields=updated"), 1)
    lines.append("404 + login check 200 -> 1 not-found row, 1 check for 3 not-found keys")
    out = root / "b2" / "work" / "source-inventory.json"
    t = Transport([("/myself", {"accountId": "x"}), ("/issue/APP-7", 404)])
    ghost = peek_jira_source(client_for(t, custom_fields=[], project_keys=["APP"]), "APP-7", out)
    check_eq("K8b: before any read succeeded the check is /myself, and its 200 makes the 404 a not-found row",
             (t.count("/myself"), ghost["status"], ghost.get("not_found")), (1, "excluded", True))
    # --- C: a CAPTCHA 403 and a login page are the same as a 401 ---
    out = root / "c" / "work" / "source-inventory.json"
    captcha = lambda request: urllib.error.HTTPError(request.full_url, 403, "forbidden",
                                                     {"X-Seraph-LoginReason": "CAPTCHA_CHALLENGE"}, None)
    exc = refused(lambda: collect_jira_source(client_for(Transport([("/issue/APP-1", captcha), ("/myself", captcha)]),
                                                        custom_fields=[]), "APP-1", out))
    check("K8b: a CAPTCHA 403 (the login check is refused too) is the same stop as a 401",
          exc is not None and exc.status == 403 and "QA_JIRA_API_TOKEN" in str(exc), str(exc))
    login = lambda request: Response(b"<html>login</html>", "text/html", {"X-Seraph-LoginReason": "AUTHENTICATION_DENIED"}, request.full_url)
    exc = refused(lambda: collect_jira_source(client_for(Transport([("/issue/APP-1", login), ("/myself", login)]),
                                                        custom_fields=[]), "APP-1", out))
    check("K8b: a login page is the same stop; its message says so", exc is not None and exc.status is None
          and "a login page" in str(exc), str(exc))
    lines.append("CAPTCHA 403 and login page -> the same stop as 401")
    # --- D: the renewed-token world: a prefix refused by a dead token yesterday is asked again today ---
    out = root / "d" / "work" / "source-inventory.json"
    issue = app_issue(description="See TC-001 in the attached spec.")
    t = Transport([("fields=updated", 401), ("/issue/APP-1?fields=*all", issue), ("/project/TC", 401)])
    exc = refused(lambda: collect_jira_source(client_for(t, custom_fields=[]), "APP-1", out))
    check("K8b: a 401 on the project probe is a lost login, not 'unproven'", exc is not None and exc.stopped_at == "the project TC")
    saved = json.loads(out.read_text(encoding="utf-8"))
    check("K8b: nothing is cached for the refused prefix (no `unproven` entry)", "TC" not in (saved.get("prefix_probes") or {}))
    t = Transport([("/issue/APP-1?fields=*all", issue), ("/project/TC", 404)])
    c = client_for(t, custom_fields=[])
    update_inventory(out, collect_jira_source(c, "APP-1", out))
    check_eq("K8b: with the renewed token the prefix is probed AGAIN, once", t.count("/project/TC"), 1)
    t2 = Transport([("/issue/APP-1?fields=*all", issue)])
    collect_jira_source(client_for(t2, custom_fields=[]), "APP-1", out)
    check_eq("K8b: and the answer, a real one, is then cached", t2.count("/project/"), 0)
    lines.append("project probe 401 -> AuthLost, no cache; after renewal 1 probe, then cached")
    # --- E: the check itself could not be answered (503): nothing is known, so nothing is not-found ---
    out = root / "e" / "work" / "source-inventory.json"
    sleeps = []
    t = Transport([("/issue/APP-1", 401), ("/myself", 503)])
    record = collect_jira_source(client_for(t, sleeps, custom_fields=[]), "APP-1", out)
    check_eq("K8b: 401 + a check that gets 503 is an unavailable source, retryable, never a stop",
             (record["status"], record["retryable"], "could not be confirmed" in record["exclusion_or_error"]),
             ("unavailable", True, True))
    check_eq("K8b: the check was retried by the ordinary policy first (5 s, 15 s)", sleeps, [5, 15])
    lines.append("401 + check 503x3 -> unavailable, retryable (not a stop, not a not-found)")
    # --- F: `unproven` is not a fact about a prefix: a transient failure of the probe is asked again, never cached ---
    out = root / "f" / "work" / "source-inventory.json"
    t = Transport([("/issue/APP-1?fields=*all", app_issue(description="See NEW-1.")), ("/project/NEW", 503)])
    c = client_for(t, [], custom_fields=[])
    update_inventory(out, collect_jira_source(c, "APP-1", out))
    saved = json.loads(out.read_text(encoding="utf-8"))
    mention = next(s for s in saved["sources"] if s["canonical_ref"].endswith("/NEW-1"))
    check_eq("K8b: a 503 on the project probe leaves the mention unavailable, and NOTHING is cached for the prefix",
             (mention["status"], "NEW" in (saved.get("prefix_probes") or {})), ("unavailable", False))
    asked = t.count("/project/NEW")
    collect_jira_source(c, "APP-1", out)
    check_eq("K8b: the next collect asks the prefix again (no `unproven` cache to outlive the outage)",
             t.count("/project/NEW"), 2 * asked)
    lines.append("project probe 503 -> unavailable mention, not cached, asked again")
    # --- G: the story's own ticket at S0: nothing has been read yet, so the check is /myself ---
    work = root / "g" / "work"
    t = Transport([("/issue/TP1-15045", 401), ("/myself", 401)])
    exc = refused(lambda: jira_ticket(client_for(t), KEY, work / "ticket-raw"))
    check("K8b: a lost login at S0 is the same stop (no read had worked, so the check was /myself)",
          exc is not None and exc.stopped_at == f"the ticket {KEY}" and t.count("/myself") == 1, str(exc))
    marked = json.loads((work / "source-inventory.json").read_text(encoding="utf-8"))
    check_eq("K8b: ... marked in the inventory, and nothing else was written", (marked["auth_stop"]["stopped_at"], marked["sources"],
             sorted(p.name for p in work.iterdir())), (f"the ticket {KEY}", [], ["source-inventory.json"]))
    jira_ticket(client_for(story_routes()), KEY, work / "ticket-raw")
    seeded = json.loads((work / "source-inventory.json").read_text(encoding="utf-8"))
    check("K8b: the S0 read after renewal clears the mark and seeds the inventory", "auth_stop" not in seeded and seeded["proof_key"] == KEY)
    lines.append("S0: the story's own 401 + /myself 401 -> the same stop, then cleared by the renewed read")
    kline("K8b", "; ".join(lines))


CF_PAGE = (b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>"
           b"<body>Sorry, you have been blocked</body></html>")
CF_HEADERS = {"Server": "cloudflare", "CF-RAY": "8a1b2c3d4e5f-AMS", "Content-Type": "text/html; charset=UTF-8"}


def cf(status=403):
    """An answer the tracker did not write: a protection layer's HTML page (B-408)."""
    return lambda request: urllib.error.HTTPError(request.full_url, status, "blocked", dict(CF_HEADERS), io.BytesIO(CF_PAGE))


def intercepted(root: Path) -> None:
    """B-408 (AK4, E20-E22, E31): an answer the tracker is not shown to have written is never "renew the token"; a
    real lost login behind it is still reported; a block that starts mid-run stops once; the K8b controls stay."""
    import source_inventory as SI
    lines = []
    # --- A: the Cloudflare 403 on the first call AND on the probe -> Intercepted, the token not judged ---
    out = root / "ia" / "work" / "source-inventory.json"
    t = Transport([("fields=updated", cf()), ("/issue/APP-1?fields=*all", app_issue(attachment=[attachment(55), attachment(56, "b.png")])),
                   ("/file/55", cf())])
    c = client_for(t, custom_fields=[])
    exc = refused(lambda: collect_jira_source(c, "APP-1", out))
    text = str(exc)
    check("AK4: a Cloudflare 403 on the first call and on the probe stops the run with Intercepted",
          isinstance(exc, SI.Intercepted) and exc.cause == "intermediary", repr(exc))
    check("AK4: its message names the title, says the token was not judged, and never says renew / stopped accepting",
          "Attention Required! | Cloudflare" in text and "token was not judged" in text and "renew" not in text
          and "stopped accepting" not in text, text)
    check_eq("AK4: ... as one line, and nothing after the stop was attempted (the second attachment was never asked for)",
             (len(text.splitlines()), t.count("/file/56"), t.count("fields=updated")), (1, 0, 1))
    check("AK4 / amendment 9: client.auth_lost IS the Intercepted, so the next read raises it with no request",
          c.auth_lost is exc and refused(lambda: c.get_bytes(BASE + "/rest/api/2/issue/APP-2")) is exc and t.count("/issue/APP-2") == 0)
    stop = json.loads(out.read_text(encoding="utf-8"))["auth_stop"]
    check_eq("AK4 / E22: the inventory marks the stop with cause `intermediary`", (stop["cause"], stop["status"]), ("intermediary", 403))
    check_eq("AK4: and zero unavailable rows were booked", [s for s in json.loads(out.read_text(encoding="utf-8"))["sources"]
                                                          if s["status"] == "unavailable"], [])
    lines.append("Cloudflare 403 (call and probe) -> Intercepted, 1 probe, cause intermediary")
    # --- B: the block starts AFTER the login was proven (auth_ok): it still stops once, with one probe (amendment 2) ---
    out = root / "ib" / "work" / "source-inventory.json"
    t = Transport([("fields=updated", cf()), ("/issue/APP-1?fields=*all", app_issue(attachment=[attachment(55), attachment(56, "b.png")])),
                   ("/file/55", cf())])
    c = client_for(t, custom_fields=[])
    c.auth_ok = True
    exc = refused(lambda: collect_jira_source(c, "APP-1", out))
    check_eq("E20: a block that starts mid-run, after auth_ok, stops once (Intercepted) with ONE probe - the auth_ok shortcut does not take it",
             (type(exc).__name__, t.count("fields=updated"), t.count("/file/56")), ("Intercepted", 1, 0))
    # --- C: a per-path block whose probe says the login works -> unavailable rows, retryable, ONE probe in all ---
    out = root / "ic" / "work" / "source-inventory.json"
    t = Transport([("fields=updated", {"key": "APP-1"}), ("/issue/APP-1?fields=*all", app_issue(attachment=[attachment(55), attachment(56, "b.png")])),
                   ("/file/55", cf()), ("/file/56", cf())])
    c = client_for(t, custom_fields=[])
    record = collect_jira_source(c, "APP-1", out)
    items = record["materials"]["attachments"]["items"]
    check_eq("AK4: per-path blocks with a working login -> both attachments unavailable and retryable, never a stop",
             [(i["status"], i["retryable"]) for i in items], [("unavailable", True), ("unavailable", True)])
    check("AK4: ... the reason names what answered, in the factory's words (the title, no raw page)",
          all("Attention Required! | Cloudflare" in i["error"] and "<html" not in i["error"].lower() for i in items), str(items))
    check_eq("AK4: the second foreign answer cost NO probe (one per process)", t.count("fields=updated"), 1)
    check_eq("E20: the client remembers the word", (c.foreign_probed, c.foreign_word), (True, "ok"))
    # --- D: a foreign 404 on a project prefix is `unproven`, never cached, never `not_tracker` (E31) ---
    out = root / "id" / "work" / "source-inventory.json"
    issue = app_issue(description="See TC-001 in the attached spec.")
    t = Transport([("/issue/APP-1?fields=*all", issue), ("/project/TC", cf(404))])
    c = client_for(t, custom_fields=[])
    update_inventory(out, collect_jira_source(c, "APP-1", out))
    saved = json.loads(out.read_text(encoding="utf-8"))
    check_eq("E31: a foreign 404 on the project probe is NOT cached for the prefix", "TC" in (saved.get("prefix_probes") or {}), False)
    tc = [s for s in saved["sources"] if s["canonical_ref"].endswith("/TC-001")]
    check("E31: ... and the mention is not booked as 'not a tracker project'", all(s.get("status") != "excluded" for s in tc), str(tc))
    t2 = Transport([("/issue/APP-1?fields=*all", issue), ("/project/TC", 404)])
    c2 = client_for(t2, custom_fields=[])
    update_inventory(out, collect_jira_source(c2, "APP-1", out))
    check_eq("E31 control: the same 404 WITHOUT a protection page is the cached fact it always was",
             json.loads(out.read_text(encoding="utf-8"))["prefix_probes"]["TC"]["result"], "not_tracker")
    # --- E: a foreign 404 on a peek is never `not_found`, even with the login proven ---
    out = root / "ie" / "work" / "source-inventory.json"
    t = Transport([("fields=updated", {"key": "APP-1"}), ("/issue/APP-1?fields=*all", app_issue()), ("/issue/APP-7", cf(404))])
    c = client_for(t, custom_fields=[])
    update_inventory(out, collect_jira_source(c, "APP-1", out))
    ghost = peek_jira_source(c, "APP-7", out)
    check_eq("E20: a foreign 404 on a key of a proven prefix is NOT a not-found row: unavailable and retryable",
             (ghost["status"], ghost.get("not_found"), ghost["retryable"]), ("unavailable", None, True))
    # --- F: a foreign first answer, then the service's own 401 on the probe: a real lost login behind a WAF (E21) ---
    out = root / "if" / "work" / "source-inventory.json"
    t = Transport([("/issue/APP-1", cf()), ("/myself", 401)])
    exc = refused(lambda: collect_jira_source(client_for(t, custom_fields=[]), "APP-1", out))
    check("E21: still an AuthLost (not Intercepted), citing the probe's own answer, and it says to renew the token",
          exc is not None and not isinstance(exc, SI.Intercepted) and "HTTP 401 on the login check that followed HTTP 403" in str(exc)
          and "QA_JIRA_API_TOKEN" in str(exc) and exc.status == 401, str(exc))
    # --- G: the probe's 200 is a challenge page, not the tracker's JSON (E13) ---
    out = root / "ig" / "work" / "source-inventory.json"
    t = Transport([("/issue/APP-1", 403), ("/myself", lambda request: Response(CF_PAGE, "text/html", url=request.full_url))])
    exc = refused(lambda: collect_jira_source(client_for(t, custom_fields=[]), "APP-1", out))
    check("E13: a 200 challenge page on the probe -> Intercepted (the login counts as ok only on the service's JSON)",
          isinstance(exc, SI.Intercepted) and "not the tracker's JSON" in str(exc), str(exc))
    # --- H: controls - the tracker's OWN refusals keep reading as before ---
    out = root / "ih" / "work" / "source-inventory.json"
    own = lambda request: urllib.error.HTTPError(request.full_url, 403, "forbidden", {"Content-Type": "application/json"},
                                                 io.BytesIO(b'{"errorMessages":["You do not have permission."],"errors":{}}'))
    t = Transport([("fields=updated", {"key": "APP-1"}), ("/issue/APP-1?fields=*all", app_issue()), ("/issue/APP-9", own)])
    c = client_for(t, custom_fields=[])
    update_inventory(out, collect_jira_source(c, "APP-1", out))
    blocked = peek_jira_source(c, "APP-9", out)
    check_eq("control: the tracker's own JSON 403 is a plain unavailable, NOT retryable (K8b unchanged), the login never in doubt",
             (blocked["status"], blocked["retryable"]), ("unavailable", False))
    check_eq("control: the tracker's own answer needed no foreign probe", c.foreign_probed, False)
    # --- the reason of a failed read: described, never the raw page; the User-Agent on every request ---
    seen = []

    def spy(request, timeout=0):
        seen.append(request.headers.get("User-agent"))
        raise cf()(request)

    try:
        client_for(spy, custom_fields=[]).get_bytes(BASE + "/rest/api/2/serverInfo", "application/json")
    except FetchError as exc2:
        check("E30 / AK4: the final error of a failed read carries the classification: the title, no raw HTML",
              exc2.status == 403 and "Attention Required! | Cloudflare" in exc2.reason and "<html" not in exc2.reason.lower(), exc2.reason)
    # --- B-408 F2: the Jira client builds its answer through the helper's ONE path: the bound is exactly 65536 ---
    for size in (65535, 65536, 65537):
        text = b"x" * size
        edge = lambda request, text=text: urllib.error.HTTPError(request.full_url, 401, "u", {"Content-Type": "text/plain"}, io.BytesIO(text))
        try:
            client_for(Transport([("/serverInfo", edge)]), custom_fields=[]).get_bytes(BASE + "/rest/api/2/serverInfo", "application/json")
            got = None
        except FetchError as exc3:
            got = (exc3.answer.truncated, len(exc3.answer.body), exc3.answer.verdict["kind"])
        check_eq(f"F2: a {size}-byte 401 text through the Jira client: cut only beyond 65536, as through http_client.fetch",
                 got, (size > 65536, 65536 if size > 65536 else size, "unclear" if size > 65536 else "service"))
    check_eq("AK1: the User-Agent on the Jira request names the factory", [u.startswith("qa-factory/") and "python" not in u.lower() for u in seen], [True])
    lines.append("block mid-run -> 1 stop, 1 probe; per-path block + working login -> unavailable rows, 1 probe in all; foreign 404 -> unproven")
    kline("B-408", "; ".join(lines))


def reads_skipped(root: Path) -> None:
    """t-282 F8 (K-F8): an optional read S0 could not make is RECORDED in the inventory, not swallowed. A lost
    login is not one of them: it stops the run through the auth gate, as built."""
    import source_inventory as SI
    ctx = {"repos": REPOS, "known_hosts": HOSTS}
    lines = []

    def inventory_of(work):
        return json.loads((work / "source-inventory.json").read_text(encoding="utf-8"))

    def s0(name, transport, sleeps=None):
        work = root / name / "work"
        return work, jira_ticket(client_for(transport, sleeps), KEY, work / "ticket-raw", context=ctx)

    work, snapshot = s0("rs-none", story_routes())
    check_eq("K-F8: nothing skipped -> reads_skipped is `[]` in the inventory (the null outcome is a recorded state)",
             inventory_of(work).get("reads_skipped"), [])
    sleeps = []
    t = story_routes(extra=[("/remotelink", 503)])
    work, snapshot = s0("rs-503", t, sleeps)
    inventory = inventory_of(work)
    check_eq("K-F8: /remotelink 503 after the retries -> one entry with the call, the status and the reason",
             inventory["reads_skipped"],
             [{"call": "/remotelink", "status": 503, "why": "the tracker answered HTTP 503 on every attempt"}])
    check_eq("K-F8: ... after the ordinary retry policy (3 requests, sleeps 5 s and 15 s) and the ticket was still read",
             (t.count("/remotelink"), sleeps, snapshot["key"], snapshot["links"]["remote_links"]), (3, [5, 15], KEY, []))
    check("K-F8: ... and no remotelink.json is in the raw folder (nothing was read, nothing is claimed)",
          not (work / "ticket-raw" / "remotelink.json").exists())
    check("K-F8: ... while the field catalogue, which WAS read, is stored and not booked",
          inventory["field_ids"]["epic_link"] == ["customfield_10014", "customfield_10015"])
    lines.append(f"/remotelink 503x3 -> {inventory['reads_skipped'][0]}")
    # the skip survives the writes of collect and peek (update_inventory keeps every other top-level key)
    output = work / "source-inventory.json"
    update_inventory(output, collect_jira_source(client_for(story_routes()), KEY, output))
    check_eq("K-F8: a collect after it keeps the entry (S1 writes the same file)",
             [e["call"] for e in inventory_of(work)["reads_skipped"]], ["/remotelink"])
    work, _ = s0("rs-timeout", story_routes(extra=[("/remotelink", TimeoutError())]))
    check_eq("K-F8: a timeout is booked too, status null",
             [(e["call"], e["status"], e["why"]) for e in inventory_of(work)["reads_skipped"]],
             [("/remotelink", None, "network timeout on every attempt")])
    work, _ = s0("rs-404", story_routes(extra=[("/remotelink", 404)]))
    check_eq("K-F8: a 404 on the endpoint is booked, and not retried",
             [(e["call"], e["status"], e["why"]) for e in inventory_of(work)["reads_skipped"]],
             [("/remotelink", 404, "the tracker answered HTTP 404")])
    work, snapshot = s0("rs-field", story_routes(extra=[("/rest/api/2/field", 404)]))
    inventory = inventory_of(work)
    check_eq("K-F8: /field 404 -> one entry; the ticket is read without the catalogue",
             (inventory["reads_skipped"], snapshot["key"]),
             ([{"call": "/field", "status": 404, "why": "the tracker answered HTTP 404"}], KEY))
    check("K-F8: ... and no `field_ids` is written (an empty list would read as 'the instance has no epic field')",
          "field_ids" not in inventory)
    # a lost login on /remotelink is NOT a skipped read: the auth gate stops the run
    t = Transport([("fields=updated", 401), ("/issue/TP1-15045/remotelink", 401),
                   ("/issue/TP1-15045?fields=*all", RAW), ("/rest/api/2/field", FIELDS)])
    c = client_for(t)
    work = root / "rs-401" / "work"
    exc = refused(lambda: jira_ticket(c, KEY, work / "ticket-raw", context=ctx))
    inventory = inventory_of(work)
    check("K-F8: /remotelink 401 with the login check refused too -> the auth stop, as built (C4/C5)",
          exc is not None and exc.stopped_at == f"the remote links of {KEY}" and inventory["auth_stop"]["status"] == 401, str(exc))
    check_eq("K-F8: ... and NO entry is booked for it", ([e for e in inventory.get("reads_skipped") or [] if e["call"] == "/remotelink"],
                                                          c.reads_skipped), ([], []))
    # the same 401 where the login check says the login works is no lost login: a read that was not made, booked
    t = Transport([("fields=updated", {"key": KEY}), ("/issue/TP1-15045/remotelink", 401),
                   ("/issue/TP1-15045?fields=*all", RAW), ("/rest/api/2/field", FIELDS)])
    work, _ = s0("rs-401-ok", t)
    check_eq("K-F8: ... but a 401 whose login check passes (login works) is booked, never swallowed",
             [(e["call"], e["status"]) for e in inventory_of(work)["reads_skipped"]], [("/remotelink", 401)])
    # K11 temporal: an earlier S0 stored the catalogue; this S0 cannot read /field -> the stored ids, nothing booked
    work, first = s0("rs-store", story_routes())
    stored = inventory_of(work)["field_ids"]
    t = story_routes(extra=[("/rest/api/2/field", 503)])
    work, second = s0("rs-store", t)
    inventory = inventory_of(work)
    check_eq("K-F8 (K11): /field unavailable but an earlier S0's ids are stored -> the stored ids stay, nothing is booked",
             (inventory["reads_skipped"], inventory["field_ids"], second["parent"] == first["parent"]), ([], stored, True))
    check("K-F8 (K11): ... and /field was asked (this S0 tried), it is the store that answered", t.count("/rest/api/2/field") == 3)
    # the helper: one entry per call, a delayed retry says so, no secret in the sentence
    c = client_for(story_routes())
    SI.book_read_skipped(c, None, "/remotelink", FetchError(503, "HTTP 503", retryable=True))
    SI.book_read_skipped(c, None, "/field", FetchError(429, "server requested delayed retry", retryable=True, retry_at="2026-10-01T12:00:00Z"))
    SI.book_read_skipped(c, None, "/remotelink", FetchError(None, "Jira JSON response was not valid JSON"))
    check_eq("K-F8: one entry per call (a second failure of the same call replaces the first), in order",
             [(e["call"], e["status"]) for e in c.reads_skipped], [("/field", 429), ("/remotelink", None)])
    check_in("K-F8: a delayed retry is said as such", "asked to retry later", c.reads_skipped[0]["why"])
    kline("K-F8", "; ".join(lines) + "; /field 404 -> entry, no field_ids; /remotelink 401 + lost login -> auth stop, 0 entries; "
                  "stored field_ids + /field 503 -> []")


def sso_redirect(root: Path) -> None:
    """t-282 F9 (K-F9): a redirect to ANOTHER host is a login page for the auth gate (an SSO redirect is how a
    lost login looks behind single sign-on), never the network fault that became exit 3; a redirect that stays on
    the tracker's host - a context path moved, a relative `Location` - is an ordinary answer."""
    import source_inventory as SI
    sso = "https://sso.example.invalid/login?back=%2Fjira"

    def redirect(location, code=302):
        return lambda request: urllib.error.HTTPError(request.full_url, code, "Found", {"Location": location}, None)

    c = client_for(Transport([("/issue/APP-1", redirect(sso))]))
    try:
        c.get_bytes(BASE + "/rest/api/2/issue/APP-1")
        err = None
    except FetchError as exc:
        err = exc
    check("K-F9: a 302 whose Location host is another host is a login page (login_page, no status)",
          err is not None and err.login_page is True and err.status is None and "single sign-on" in err.reason, str(err))
    check_not_in("K-F9: ... and the reason does not carry the redirect target (it may hold a token)", "sso.example.invalid", err.reason)
    for code in (301, 303, 307, 308):
        try:
            client_for(Transport([("/issue/APP-1", redirect(sso, code))])).get_bytes(BASE + "/rest/api/2/issue/APP-1")
            got = None
        except FetchError as exc:
            got = exc
        check(f"K-F9: ... the same for a {code}", got is not None and got.login_page is True, str(got))
    # through the gate: the probe, then AuthLost naming the door - the S0 route and S1's
    t = Transport([("/issue/TP1-15045", redirect(sso)), ("/myself", redirect(sso))])
    exc = refused(lambda: jira_ticket(client_for(t), KEY, root / "sso-a" / "work" / "ticket-raw"))
    check("K-F9: S0 meeting the SSO redirect -> the auth stop (a login page), naming the token's variable, after one probe",
          exc is not None and exc.status is None and "a login page" in str(exc) and "QA_JIRA_API_TOKEN" in str(exc)
          and t.count("/myself") == 1, str(exc))
    out = root / "sso-b" / "work" / "source-inventory.json"
    t = Transport([("/issue/APP-1", redirect(sso)), ("/myself", redirect(sso))])
    exc = refused(lambda: collect_jira_source(client_for(t, custom_fields=[]), "APP-1", out))
    check("K-F9: S1 collect meeting it -> the same stop, not an `unavailable` source", exc is not None and "a login page" in str(exc), str(exc))
    # same host: ordinary
    for label, location in (("a context-path redirect on the same host", BASE + "/jira/rest/api/2/issue/APP-1"),
                            ("a relative Location", "/jira/rest/api/2/issue/APP-1"),
                            ("the same host in another letter case", "https://JIRA.example.test/jira/x")):
        try:
            client_for(Transport([("/issue/APP-1", redirect(location))])).get_bytes(BASE + "/rest/api/2/issue/APP-1")
            got = None
        except FetchError as exc:
            got = exc
        check_eq(f"K-F9: {label} is NOT a login page (status 302, not retryable)",
                 (got.login_page, got.status, got.retryable) if got else None, (False, 302, False))
    record = collect_jira_source(client_for(Transport([("/issue/APP-1", redirect(BASE + "/jira/x"))]), custom_fields=[]),
                                 "APP-1", root / "sso-c" / "work" / "source-inventory.json")
    check_eq("K-F9: ... so a same-host redirect leaves an ordinary unavailable source, no stop", record["status"], "unavailable")
    try:
        client_for(Transport([("/issue/APP-1", 302)])).get_bytes(BASE + "/rest/api/2/issue/APP-1")
        got = None
    except FetchError as exc:
        got = exc
    check_eq("K-F9: ... (no Location, no host to compare: status 302, not a login page)", (got.login_page, got.status), (False, 302))
    # a 200 whose final URL (after redirects) is on another host
    t = Transport([("/issue/APP-1", lambda request: Response({"key": "APP-1"}, url=sso))])
    try:
        client_for(t).get_bytes(BASE + "/rest/api/2/issue/APP-1")
        got = None
    except FetchError as exc:
        got = exc
    check("K-F9: a 200 whose final URL is on another host is a login page", got is not None and got.login_page is True, str(got))
    same = client_for(Transport([("/issue/APP-1", lambda request: Response({"key": "APP-1"}, url=BASE + "/jira/rest/api/2/issue/APP-1"))]))
    check_eq("K-F9: a 200 whose final URL is the same host on another path is the ordinary answer",
             json.loads(same.get_bytes(BASE + "/rest/api/2/issue/APP-1")), {"key": "APP-1"})
    # the real opener's handler: urllib asks it before it follows a redirect
    handler = SI._SameOriginRedirect(("https", "jira.example.test", None))
    req = urllib.request.Request(BASE + "/browse/APP-1")
    try:
        handler.redirect_request(req, None, 302, "Found", {}, sso)
        got = None
    except FetchError as exc:
        got = exc
    check("K-F9: the handler of the real opener reads a cross-host redirect as a login page too", got is not None and got.login_page is True, str(got))
    followed = handler.redirect_request(req, None, 302, "Found", {}, BASE + "/jira/browse/APP-1")
    check_eq("K-F9: ... and follows a same-host redirect (a moved context path)", followed.full_url, BASE + "/jira/browse/APP-1")
    relative = handler.redirect_request(req, None, 302, "Found", {}, "/jira/browse/APP-1")
    check_eq("K-F9: ... and a relative Location (no host) is the same host", relative.full_url, BASE + "/jira/browse/APP-1")
    try:
        handler.redirect_request(req, None, 302, "Found", {}, "http://jira.example.test/browse/APP-1")
        got = None
    except FetchError as exc:
        got = exc
    check_eq("K-F9: the same host on another scheme keeps the old refusal (cross-origin, not a login page)",
             (got.login_page, "cross-origin" in got.reason) if got else None, (False, True))


def telemetry(root: Path) -> None:
    path = root / "telemetry" / "command-1.jsonl"
    t = story_routes()
    c = client_for(t, telemetry_path=path, telemetry_task=KEY)
    issue, raw = c.issue_with_raw(KEY)
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    end = next(e for e in events if e["phase"] == "end")
    check_eq("K10: one REST read leaves one `command` span (a start and an end)",
             sorted((e["span_kind"], e["phase"]) for e in events), [("command", "end"), ("command", "start")])
    check("K10: the end carries duration_ms and bytes == the response length, from plugin:ticket_adapter.py for the ticket",
          isinstance(end.get("duration_ms"), (int, float)) and end.get("bytes") == len(RAW)
          and end["source"] == "plugin:ticket_adapter.py" and end["task"] == KEY and end["outcome"] == "ok", str(end))
    c.get_json_with_raw("/rest/api/2/field")
    ends = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if '"phase":"end"' in line]
    check_eq("K10: every further REST call is a span of its own, with its own bytes", [e.get("bytes") for e in ends], [len(RAW), len(FIELDS)])
    # negative control: a telemetry place that cannot be written never fails the read
    blocker = root / "blocker"
    blocker.write_text("a file where the telemetry directory should be", encoding="utf-8")
    c2 = client_for(story_routes(), telemetry_path=blocker / "command-1.jsonl")
    _, raw2 = c2.issue_with_raw(KEY)
    check("K10 negative: an unwritable telemetry directory -> the read still succeeds, same bytes", raw2 == RAW)
    c3 = client_for(story_routes(), telemetry_path=None)
    check("K10: no telemetry path, no span file, same read", c3.issue_with_raw(KEY)[1] == RAW)
    kline("K10", f"one read -> span_kind command, duration_ms {end['duration_ms']}, bytes {end['bytes']} (== len(response) "
                 f"{len(RAW)}); unwritable telemetry dir -> read still ok")


def fields_missing(root: Path) -> None:
    said = []
    t = story_routes()
    snapshot = jira_ticket(client_for(t, custom_fields=["customfield_20001", "customfield_99999"]), KEY,
                           root / "k12" / "work" / "ticket-raw", say=said.append)
    check_eq("K12: a configured field the instance does not have is named in provenance.fields_missing",
             snapshot["provenance"]["fields_missing"], ["customfield_99999"])
    check_eq("K12: ... with ONE line, and the field the instance has is in the light form",
             (len(said), "customfield_99999" in said[0], snapshot["custom_fields"].get("customfield_20001")),
             (1, True, "Synthetic named note kept because config names it."))
    said2 = []
    clean = jira_ticket(client_for(story_routes()), KEY, None, say=said2.append)
    check("K12 control: nothing missing -> no fields_missing and no line", "fields_missing" not in clean["provenance"] and not said2)
    # an empty whitelist table REFUSES, naming the file, before any request is made
    table = TL.load_fields_table()
    bad = root / "k12" / "jira-fields.json"
    bad.write_text(json.dumps(dict(table, standard=[])), encoding="utf-8")
    saved, t = TL.FIELDS_TABLE_PATH, story_routes()
    TL.FIELDS_TABLE_PATH = bad
    try:
        try:
            jira_ticket(client_for(t), KEY, None)
            msg = "no refusal"
        except TL.TableError as exc:
            msg = str(exc)
    finally:
        TL.FIELDS_TABLE_PATH = saved
    check("K12 negative: an empty whitelist is a refusal that names the file and the key",
          "jira-fields.json" in msg and "`standard`" in msg, msg)
    check_eq("K12: ... and it came BEFORE the first request", t.log, [])
    kline("K12", f"configured customfield_99999 not on the instance -> provenance.fields_missing={snapshot['provenance']['fields_missing']}, "
                 f"{len(said)} line; empty whitelist -> refusal naming jira-fields.json, 0 requests")


def description_limit() -> None:
    """K14, wired into the route: one printed line over the table's limit, none at it, never a cut."""
    limit = TL.load_fields_table()["description_limit_bytes"]
    for size, lines in ((limit, 0), (limit + 1, 1)):
        issue = json.loads(RAW)
        issue["fields"]["description"] = "x" * size
        said = []
        snapshot = jira_ticket(client_for(story_routes(json.dumps(issue).encode("utf-8"))), KEY, None, say=said.append)
        check_eq(f"K14 (route): a description of {size:,} bytes -> {lines} printed line(s), and it is kept whole",
                 (len(said), len(snapshot["description"])), (lines, size))


def retries() -> None:
    def flaky(status, retry_after, fail_times):
        state = {"n": 0}

        def opener(request, timeout=0):
            state["n"] += 1
            if state["n"] <= fail_times:
                raise urllib.error.HTTPError(request.full_url, status, "slow",
                                             {"Retry-After": retry_after} if retry_after else {}, None)
            return Response({"key": "APP-1"}, url=request.full_url)
        return opener, state

    sleeps = []
    opener, state = flaky(429, "10", 1)
    got = client_for(opener, sleeps).get_json("/rest/api/2/issue/APP-1")
    check_eq("K15: 429 with Retry-After 10 -> waits 10 s, then success", (got["key"], sleeps, state["n"]), ("APP-1", [10], 2))
    sleeps = []
    opener, state = flaky(429, "20", 1)
    try:
        client_for(opener, sleeps).get_json("/rest/api/2/issue/APP-1")
        err = None
    except FetchError as exc:
        err = exc
    check("K15: Retry-After 20 -> FetchError naming the time (the driver's question), no sleep, one request",
          err is not None and err.retry_at and err.retryable and sleeps == [] and state["n"] == 1, str(getattr(err, "retry_at", None)))
    sleeps = []
    opener, state = flaky(503, None, 3)
    try:
        client_for(opener, sleeps).get_json("/rest/api/2/issue/APP-1")
        err3 = None
    except FetchError as exc:
        err3 = exc
    check_eq("K15: 503 x3 -> FetchError after the existing policy (5 s, 15 s), three requests",
             (err3.status if err3 else None, sleeps, state["n"]), (503, [5, 15], 3))
    kline("K15", f"429+Retry-After 10 -> slept {10}s then ok (2 requests); Retry-After 20 -> FetchError(retry_at={err.retry_at}), "
                 f"no sleep; 503x3 -> FetchError({err3.status}), slept [5, 15], 3 requests")


def missing_credentials() -> None:
    """t-287 item 3: a token (or user) environment variable the shell lacks is a lost LOGIN for a read - `AuthLost`
    naming the variables, raised BEFORE any request - and still the old FetchError for a write."""
    saved = {name: os.environ.get(name) for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN")}
    try:
        t = story_routes()
        c = client_for(t)
        del os.environ["QA_JIRA_API_TOKEN"]
        exc = refused(lambda: c.get_bytes(BASE + "/rest/api/2/issue/APP-1"))
        check_eq("item 3: the token variable unset -> AuthLost (not a FetchError), the variable named once, the value never, no request",
                 (type(exc).__name__, exc is not None and str(exc).count("QA_JIRA_API_TOKEN"), exc is not None and "QA_JIRA_EMAIL" in str(exc), t.log),
                 ("AuthLost", 1, False, []))
        check("item 3: the sentence has no network or VPN advice and says no request was made",
              exc is not None and "network" not in str(exc).lower() and "vpn" not in str(exc).lower() and "no request was made" in str(exc), str(exc))
        check_eq("item 3: the door is the variable's name, the stop point says where", (exc.door, exc.status, exc.stopped_at), ("QA_JIRA_API_TOKEN", None, "the first request"))
        os.environ["QA_JIRA_API_TOKEN"] = "test-only-token"
        check_eq("item 3: the login is NOT cached as lost: the next read after the variable comes back is made",
                 (c.get_bytes(BASE + "/rest/api/2/field") == FIELDS, t.count("/rest/api/2/field")), (True, 1))
        del os.environ["QA_JIRA_EMAIL"]
        exc = refused(lambda: c.get_bytes(BASE + "/rest/api/2/field"))
        check_eq("item 3: the USER variable unset (the token set) -> the same, naming that variable only",
                 (type(exc).__name__, "QA_JIRA_EMAIL" in str(exc), "QA_JIRA_API_TOKEN" in str(exc)), ("AuthLost", True, False))
        del os.environ["QA_JIRA_API_TOKEN"]
        exc = refused(lambda: c.get_bytes(BASE + "/rest/api/2/field"))
        check_eq("item 3: both unset -> both named", ("QA_JIRA_EMAIL" in str(exc), "QA_JIRA_API_TOKEN" in str(exc)), (True, True))
        # a bearer token needs no user: only the token variable counts
        bearer = JiraClient(BASE, "", "QA_JIRA_API_TOKEN", auth_type="bearer", opener=story_routes(), sleeper=lambda s: None,
                            config={})
        exc = refused(lambda: bearer.get_bytes(BASE + "/rest/api/2/field"))
        check_eq("item 3: bearer, token unset -> the token variable only", (type(exc).__name__, str(exc).count("QA_JIRA"), "QA_JIRA_API_TOKEN" in str(exc)), ("AuthLost", 1, True))
        # the write keeps its old class: a FetchError whose reason names the variables (post_json is not a read)
        wrote = story_routes()
        writer = client_for(wrote)
        try:
            writer.post_json("/rest/api/2/issue", {"fields": {}})
            got = None
        except FetchError as err:
            got = (type(err).__name__, "missing credential" in err.reason, err.status)
        check_eq("item 3 (the write side is untouched): post_json still raises a FetchError `missing credential...`, status None, no request",
                 (got, wrote.log), (("MissingCredential", True, None), []))
        # positive control: everything set -> the read goes out
        os.environ["QA_JIRA_EMAIL"], os.environ["QA_JIRA_API_TOKEN"] = "reader@example.invalid", "test-only-token"
        ok = story_routes()
        check_eq("item 3 (positive control): both variables set -> the read is made", (client_for(ok).get_bytes(BASE + "/rest/api/2/field") == FIELDS, len(ok.log)), (True, 1))
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_the_ticket_by_rest() -> None:
    root = temp_dir("qa-ticket-by-rest-")
    for name in ("QA_JIRA_EMAIL", "QA_JIRA_API_TOKEN"):
        BEFORE_ENV[name] = os.environ.get(name)
    os.environ["QA_JIRA_EMAIL"] = "reader@example.invalid"
    os.environ["QA_JIRA_API_TOKEN"] = "test-only-token"
    try:
        k8_requests(root)
        auth_loss(root)
        intercepted(root)
        missing_credentials()
        reads_skipped(root)
        sso_redirect(root)
        telemetry(root)
        fields_missing(root)
        description_limit()
        retries()
        key_shape()
    finally:
        for name, value in BEFORE_ENV.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        cleanup(root)


def key_shape() -> None:
    """C11 / item (4): one key shape for the factory, the not-tracker list is DATA, the custom-field scan is gone."""
    import source_inventory as SI
    check("C11: source_inventory.TICKET_KEY_RE IS ticket_light.KEY_RE", SI.TICKET_KEY_RE is TL.KEY_RE)
    check_eq("C11: MY_PROJ-12 is one candidate, never PROJ-12", SI.extract_ticket_keys("see MY_PROJ-12 and PROJ-13"), ["MY_PROJ-12", "PROJ-13"])
    check_eq("FR-13: the not-tracker list is the table's (UTF-8 and ISO-8601 are not keys)",
             (SI.extract_ticket_keys("UTF-8 ISO-8601 REAL-5"), set(SI.NOT_TRACKER_PREFIXES) == set(TL.load_fields_table()["not_tracker_prefixes"])),
             (["REAL-5"], True))
    saved = TL.FIELDS_TABLE_PATH
    TL.FIELDS_TABLE_PATH = Path(saved).with_name("no-such-table.json")
    try:
        try:
            SI.extract_ticket_keys("UTF-8 REAL-5")
            msg = "no refusal"
        except TL.TableError as exc:
            msg = str(exc)
    finally:
        TL.FIELDS_TABLE_PATH = saved
    check("FR-13: a missing table REFUSES naming the file, it never lets UTF-8 become a source", "no-such-table.json" in msg, msg)
    # --- t-282: the extractor twin (one extractor with S0's references, FR-17) ---
    host = "https://host.example.test"
    check_eq("K-TWIN: a key in a browse link comes from the link row's own key, the bare key beside it too",
             SI.extract_ticket_keys(f"see {host}/browse/ABC-7 and ABC-8"), ["ABC-7", "ABC-8"])
    check_eq("K-TWIN: a key inside a NON-browse link path is not a bare key", SI.extract_ticket_keys(f"{host}/x/ABC-9/doc"), [])
    check_eq("K-TWIN control: the same key written bare IS a key", SI.extract_ticket_keys("see ABC-9 here"), ["ABC-9"])
    check_eq("K-TWIN (F7): a tracker behind a context path gives its key", SI.extract_ticket_keys(f"{host}/jira/browse/ABC-7"), ["ABC-7"])
    check_eq("K-TWIN: a link and a bare mention of one key, across values, is one key (no double)",
             SI.extract_ticket_keys(f"{host}/browse/ABC-7 ABC-7", "ABC-7"), ["ABC-7"])
    check_eq("K-TWIN: a not-tracker prefix is skipped from a link's key too", SI.extract_ticket_keys(f"{host}/browse/LICENSE-2 UTF-8"), [])
    check_eq("K-TWIN (F11): a letter glued to a key, either side, is no key", SI.extract_ticket_keys("fooTP1-9 TP1-9a"), [])
    check_eq("K-TWIN: a local path is consumed, not a source of keys; None and empty values are fine",
             SI.extract_ticket_keys("C:" + TL.BS + "work" + TL.BS + "TC-009.txt ~/x/TC-010/y", None, ""), [])
    saved_kinds, saved_finder, saved_path = SI._REFERENCE_KINDS, SI._BROWSE_KEY_RE, TL.KINDS_TABLE_PATH
    SI._REFERENCE_KINDS = SI._BROWSE_KEY_RE = None
    TL.KINDS_TABLE_PATH = Path(saved_path).with_name("no-such-kinds.json")
    try:
        msgs = []
        for call in (lambda: SI.extract_ticket_keys("ABC-1"),
                     lambda: SI._known_prefixes(client_for(Transport([])), Path("none") / "source-inventory.json", "APP-1",
                                                {"description": "x", "links": {}})):
            try:
                call()
                msgs.append("no refusal")
            except TL.TableError as exc:
                msgs.append(str(exc))
    finally:
        SI._REFERENCE_KINDS, SI._BROWSE_KEY_RE, TL.KINDS_TABLE_PATH = saved_kinds, saved_finder, saved_path
    check("K-TWIN: a reference-kinds table that cannot be read REFUSES naming the file, in the extractor and in the prefix finder",
          all("no-such-kinds.json" in m for m in msgs), str(msgs))
    # --- F7: the /browse/KEY finder is built from the table, one source ---
    check("F7: _BROWSE_KEY_RE is the table's ticket rules + KEY_RE (not a second literal of the marker or the key)",
          SI._BROWSE_KEY_RE.pattern == TL.ticket_url_regex(TL.load_reference_kinds()).pattern
          and "(?:^|/)browse/" in SI._BROWSE_KEY_RE.pattern and TL.KEY_RE.pattern in SI._BROWSE_KEY_RE.pattern,
          SI._BROWSE_KEY_RE.pattern)
    snapshot = {"title": "", "description": "see https://jira.example.test/jira/browse/ZED-1 and https://jira.example.test/browsers/YEE-2",
                "acceptance_criteria": [], "comments": [], "links": {}}
    known = SI._known_prefixes(client_for(Transport([])), Path("none") / "source-inventory.json", "APP-1", snapshot)
    check_eq("F7: a /jira/browse/ZED-1 link makes ZED a known prefix; /browsers/YEE-2 does not (the finder and the kind rule agree)",
             ("ZED" in known, "YEE" in known), (True, False))
    source = Path(SI.__file__).read_text(encoding="utf-8")
    check("F7: no second literal of the marker: the source no longer builds the finder from '\"/browse/\" +'",
          '"/browse/" + TICKET_KEY_RE' not in source)
    check("F17 (b): the custom-field scans are gone: no scan reads a snapshot's `custom_fields` for keys",
          'snapshot.get("custom_fields")' not in source
          and "custom_fields" not in source.split("def _known_prefixes")[1].split("def _proven_prefixes")[0])


# --- C2-9 (D-0043): a gap the factory itself established is not asked; a kind the person answered is not asked again -----

import source_inventory as SI  # noqa: E402

MR = "https://git.example.com/team/sdk/-/merge_requests/510"
SHARE = "https://share.example.com/sites/x/video.mp4"
LIMIT = 30000


def gsrc(sid="SRC-m", media=(), attachments=(), **over):
    """A read, reviewed, required source whose only open points are the given gap rows."""
    item = {"source_id": sid, "canonical_ref": f"https://jira/browse/{sid}", "relation": "referenced",
            "relevance": "relevant", "required": True, "status": "read", "inspection_status": "read",
            "human_review": {"words": "ok", "shown": {"relevance": "relevant"}},
            "materials": {"comments": {"status": "read"},
                          "attachments": {"status": "read", "items": list(attachments)},
                          "external_media": {"status": "unavailable" if media else "read", "items": list(media)}}}
    item.update(over)
    return item


def mrow(url=MR, cause="host_unreachable", **extra):
    return dict({"url": url, "status": "unavailable", "cause": cause}, **extra)


def PROBE(**over):
    return dict({"probe_ref": "sources/SRC-m/mr-510.json", "probe_code": "host_unreachable"}, **over)


def arow(size=None, cause="too_large", status="unavailable", **extra):
    row = {"attachment_id": "9", "filename": "shot.png", "analysis_status": status, "analysis_cause": cause}
    if size is not None or "size" in extra:
        row["size"] = size
    row.update(extra)
    return row


def cinv(*items):
    return {"schema_version": 1, "sources": list(items)}


def comp(*items, **kw):
    kw.setdefault("size_limit", LIMIT)
    return completeness(cinv(*items), **kw)


def asked(summary) -> bool:
    return "SRC-m" in summary["unavailable_materials"]


def test_gap_defaults():
    """T1 / T1b / T2 / T3 / T4 / T5 / T15 / T16."""
    mid = SI._media_id(mrow(), 0)
    summary = comp(gsrc(media=[mrow(**PROBE())]))
    check_eq("T1 a host_unreachable verdict with its collector receipt is a gap by default, not a question",
             (summary["defaulted_gaps"], summary["unavailable_materials"], summary["open_points"], summary["complete"],
              summary["gate_blocked"], [p["id"] for p in summary["defaulted_points"].get("SRC-m", [])]),
             (["SRC-m"], [], {}, True, False, [mid]))
    point = (summary["defaulted_points"].get("SRC-m") or [{}])[0]
    check_eq("T1 the entry names the cause and the carrier", (point.get("cause"), "host_unreachable" in point.get("basis", ""), point.get("name")),
             ("host_unreachable", True, MR))
    for label, url in (("an address", SHARE), ("a merge request", MR), ("a pull request", "https://github.com/o/r/pull/7")):
        row = mrow(url, "forbidden_by_policy")
        check_eq(f"T1b forbidden_by_policy on {label} is the role's word alone: asked, never a default (FR-59)",
                 (comp(gsrc(media=[row]))["defaulted_gaps"], asked(comp(gsrc(media=[row])))), ([], True))
    check_eq("T1 no_tool on an address that is not a merge request is a gap by default",
             comp(gsrc(media=[mrow(SHARE, "no_tool")]))["defaulted_gaps"], ["SRC-m"])
    check_eq("T1 too_large with a measured size AT the limit is a gap by default; one byte under is asked",
             (comp(gsrc(attachments=[arow(LIMIT)]))["defaulted_gaps"], asked(comp(gsrc(attachments=[arow(LIMIT - 1)])))),
             (["SRC-m"], True))
    # T1i (SC2-41): with an `image_size_limit` a picture (and a file of unknown form) is judged by the larger limit, text by its own.
    # Mutations: m67 (a picture uses the text limit) and m68 (an unknown form uses the text limit) -> here.
    IMG = 5242880

    def basis_of(row, **kw):
        got = comp(gsrc(attachments=[row]), image_size_limit=IMG, **kw)
        return got["defaulted_gaps"], [p["basis"] for pts in got["defaulted_points"].values() for p in pts]
    check_eq("T1i a picture of 93,414 B with the image limit is ASKED, not defaulted (it is readable)",
             (basis_of(arow(93414))[0], asked(comp(gsrc(attachments=[arow(93414)]), image_size_limit=IMG))), ([], True))
    check_eq("T1i a picture AT the image limit is defaulted and the basis names that limit",
             basis_of(arow(IMG)), (["SRC-m"], [f"measured size {IMG} bytes, over the {IMG} bytes a role can open"]))
    check_eq("T1i a picture one byte under the image limit is asked (AT / BEYOND)", basis_of(arow(IMG - 1))[0], [])
    check_eq("T1i a text file of 93,414 B keeps the text limit: defaulted, basis 30000",
             basis_of(arow(93414, filename="notes.txt", media_type="text/plain")),
             (["SRC-m"], ["measured size 93414 bytes, over the 30000 bytes a role can open"]))
    check_eq("T1i a PDF keeps the text limit too (pages, not a picture)",
             basis_of(arow(93414, filename="a.pdf", media_type="application/pdf"))[0], ["SRC-m"])
    check_eq("T1i a file of unknown form (null type, no suffix) is judged by the larger limit: asked",
             basis_of(arow(93414, filename="blob", media_type=None))[0], [])
    check_eq("T1i image_size_limit 0 (cannot be told): a picture keeps the text limit, the old meaning",
             (comp(gsrc(attachments=[arow(30000)]), image_size_limit=0)["defaulted_gaps"]), ["SRC-m"])
    check_eq("T1i no image_size_limit at all (an old caller): the text limit for a picture, as before",
             comp(gsrc(attachments=[arow(93414)]))["defaulted_gaps"], ["SRC-m"])
    for label, bad in (("True", True), ("-1", -1), ("a string", "93414")):
        check_eq(f"T1i size {label} is asked under the image limit too", basis_of(arow(bad))[0], [])

    cases = {
        "host_unreachable with no probe_ref": mrow(),
        "an unknown probe_code": mrow(**PROBE(probe_code="brand_new")),
        "a probe_code the table maps to another cause": mrow(**PROBE(probe_code="unauthenticated")),
        "an absolute probe_ref": mrow(**PROBE(probe_ref="/etc/receipt.json")),
        "a probe_ref with ..": mrow(**PROBE(probe_ref="../x.json")),
        "an empty probe_ref": mrow(**PROBE(probe_ref="")),
        "no_tool on a merge request": mrow(MR, "no_tool"),
        "no_tool on an escaped merge request": mrow("https://git.example.com/team/sdk/-/merge\\_requests/510", "no_tool"),
        "too_large of a media item": mrow(SHARE, "too_large", size=10 ** 9),
        "the cause in another case": mrow(cause="HOST_UNREACHABLE", **PROBE()),
        "an auth_required": mrow(cause="auth_required"),
        "a transient": mrow(cause="transient"),
        "a partial_route": mrow(cause="partial_route"),
    }
    for label, row in cases.items():
        check(f"T1b {label} stays a question", asked(comp(gsrc(media=[row]))) and not comp(gsrc(media=[row]))["defaulted_gaps"], label)
    for label, row in {"no size": arow(), "a size that is not a number": arow("12k"), "a boolean size": arow(True),
                       "a negative size": arow(-1), "a float size": arow(40000.0),
                       "no_tool on an attachment": arow(10 ** 9, "no_tool"),
                       "an attachment whose cause is a login": arow(10 ** 9, "auth_required")}.items():
        check(f"T1b {label} stays a question", asked(comp(gsrc(attachments=[row]))), label)
    check("T1b without a read limit (guard off) a size decides nothing", asked(comp(gsrc(attachments=[arow(10 ** 9)]), size_limit=0)))
    # F-8: ONE lexical path check (`_safe_rel`, both OS spellings) for every work-relative ref the recorders take
    for spelling in ("..\\x.json", "\\x.json", "C:/x.json", "C:x.json", "../x.json", "/x.json", "a/../../x.json", "", "  "):
        for label, call in (("evidence_ref", lambda r: record_attachment_inspection(Path("nowhere") / "work" / "i.json", "SRC-m", "9", "read", r)),
                            ("assessment_ref", lambda r: record_relevance_assessment(Path("nowhere") / "work" / "i.json", "SRC-m", "relevant", "why", r))):
            try:
                call(spelling)
                refused = False
            except Exception as exc:        # any other way out (a missing inventory) is NOT this check refusing
                refused = isinstance(exc, ValueError) and "safe" in str(exc)
            check(f"F-8 {label} {spelling!r} is refused by the one path check", refused)
    # F-7: the limit is the TASK's project's, not the cwd's or the environment's
    proj = temp_dir("qa-gap-limit-")
    other_proj = temp_dir("qa-gap-limit-other-")
    held_env = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        for base, max_bytes, max_img in ((proj, 1000, 1500), (other_proj, 5, 7)):
            (base / "qa-factory").mkdir()
            (base / "qa-factory" / "config.json").write_text(json.dumps({"read": {"max_bytes": max_bytes, "max_image_bytes": max_img}}), encoding="utf-8")
        task = proj / "qa-factory" / "artifacts" / "T-1"
        task.mkdir(parents=True)
        os.environ["CLAUDE_PROJECT_DIR"] = str(other_proj)
        check_eq("F-7 the read limit comes from the config of the project the task lives in",
                 SI.class_kwargs(task)["size_limit"], 1000)
        check_eq("T4 class_kwargs carries the image limit: the default for a project with a config and no key, 0 for a bare folder",
                 (SI.class_kwargs(tmp_none := temp_dir("qa-gap-noimg-"))["image_size_limit"],), (0,))
        # f-1 (t-671): the PROJECT's `read.max_image_bytes` reaches class_kwargs and the defaulted basis.
        # Mutation m76 (`image_size_limit_of` ignores the key) -> killed by the two assertions below.
        check_eq("F-7 the image limit comes from the config of the project the task lives in (1500, not the default 5242880, not the cwd's 7)",
                 SI.class_kwargs(task)["image_size_limit"], 1500)
        shot = gsrc(attachments=[arow(1500)])
        got = completeness(cinv(shot), **SI.class_kwargs(task))
        check_eq("F-7 a 1500 B picture is defaulted with the project's image limit in the basis",
                 (got["defaulted_gaps"], [p["basis"] for pts in got["defaulted_points"].values() for p in pts]),
                 (["SRC-m"], ["measured size 1500 bytes, over the 1500 bytes a role can open"]))
        cleanup(tmp_none)
        bare = temp_dir("qa-gap-nolimit-")
        check_eq("F-7 a task with no project config: the limit cannot be told (0), so a size is asked",
                 SI.class_kwargs(bare)["size_limit"], 0)
        big = gsrc(attachments=[arow(2000, filename="notes.txt", media_type="text/plain")])   # a text file: a picture has its own limit (SC2-41)
        check_eq("F-7 a size over the TASK's limit is a default; the same size with no config is asked",
                 (completeness(cinv(big), **SI.class_kwargs(task))["defaulted_gaps"],
                  asked(completeness(cinv(big), **SI.class_kwargs(bare)))), (["SRC-m"], True))
        cleanup(bare)
    finally:
        if held_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = held_env
        cleanup(proj)
        cleanup(other_proj)
    check("T1b a source that is `unavailable` is never a default", "SRC-m" in comp(gsrc(status="unavailable", materials={}))["unavailable"])

    # T2 a point of the factory's own work is closed by neither
    work = gsrc(attachments=[arow(10 ** 9, status="pending")])
    for label, kw in (("a default", {}), ("a live kind", {"classes": [{"id": "GC-1", "cause": "too_large", "words": "w"}]})):
        s = comp(work, **kw)
        check_eq(f"T2 work with a too_large cause is not closed by {label}",
                 (s["incomplete_materials"], s["defaulted_gaps"], s["closed_by_class"]), (["SRC-m"], [], {}))

    # T3 the order on one point: the person's word, a kind, the default
    row = mrow(**PROBE())
    pid = SI._media_id(row, 0)
    kinds = [{"id": "GC-1", "cause": "host_unreachable", "words": "skip the unreachable"}]
    worded = gsrc(media=[row], gap_acceptance={"words": "w", "accepted_points": [{"id": pid, "class": "gap", "words": "w"}]})
    s = comp(worded, classes=kinds)
    check_eq("T3 the person's word on the point comes first: not the kind, not the default",
             (s["closed_by_person"], s["closed_by_class"], s["defaulted_gaps"]), ({"SRC-m": [pid]}, {}, []))
    s = comp(gsrc(media=[row]), classes=kinds)
    check_eq("T3 a kind comes before the default: closed by the kind, with its id; the source is an accepted gap",
             (s["closed_by_class"], s["defaulted_gaps"], s["accepted_gaps"], s["complete"]),
             ({"SRC-m": {pid: "GC-1"}}, [], ["SRC-m"], False))
    other = gsrc(media=[mrow(cause="auth_required")])
    check_eq("T3 a kind covers only its own cause", asked(comp(other, classes=kinds)), True)
    revoked = [dict(kinds[0], revoked_at="2026-10-01T00:00:00+00:00")]
    check_eq("T3 a taken-back kind covers nothing", asked(comp(other, classes=[dict(revoked[0], cause="auth_required")])), True)
    check_eq("T3 a kind with empty words covers nothing", asked(comp(other, classes=[dict(kinds[0], cause="auth_required", words=" ")])), True)
    check_eq("T3 a kind with a cause outside the list covers nothing",
             asked(comp(gsrc(media=[mrow(cause="bogus")]), classes=[dict(kinds[0], cause="bogus")])), True)
    legacy = gsrc(media=[mrow(cause="auth_required")], gap_acceptance={"words": "x", "accepted": []})
    s = comp(legacy, s1_closed=True, classes=[])
    check_eq("T3 s1_closed with a legacy acceptance: as before, first",
             (s["accepted_gaps"], s["closed_by_class"], s["gate_blocked"]), (["SRC-m"], {}, False))

    # T4 no record / an unreadable record
    check_eq("T4 classes=None is no kind at all", comp(other, classes=None)["unavailable_materials"], ["SRC-m"])
    s = comp(gsrc(media=[row]), classes=kinds, class_problem="work/gap-classes.json cannot be read (x)")
    check_eq("T4 an unreadable record covers nothing and says so (the default still stands: it needs no record)",
             (s["closed_by_class"], s["gap_class_problem"]), ({}, "work/gap-classes.json cannot be read (x)"))
    s = comp(other, classes=kinds, class_problem="work/gap-classes.json cannot be read (x)")
    check_eq("T4 and a point only a kind could close is asked", s["unavailable_materials"], ["SRC-m"])
    s = comp(other, s1_closed=True, class_problem="work/gap-classes.json cannot be read (x)")
    check_eq("T4 after S1 the unreadable record does not block it again (G3, the safe default named)",
             (s["gate_blocked"], s["closed_by_class"]), (False, {"SRC-m": {SI._media_id(other["materials"]["external_media"]["items"][0], 0): "unreadable"}}))
    tmp = temp_dir("qa-gap-classes-")
    try:
        check_eq("T4 no file: no kind and no problem", SI.live_gap_classes(tmp), ([], ""))
        (tmp / "work").mkdir()
        (tmp / "work" / "gap-classes.json").write_text("{broken", encoding="utf-8")
        rows, problem = SI.live_gap_classes(tmp)
        check_eq("T4 a broken file: nothing is covered and the problem names it", (rows, "gap-classes.json" in problem), ([], True))
        check_eq("T4 class_kwargs is the callers' one line", sorted(SI.class_kwargs(tmp)), ["class_problem", "classes", "image_size_limit", "size_limit"])
    finally:
        cleanup(tmp)

    # T5 the pseudo cause
    unknown = gsrc(relevance="unknown", status="read")
    gone = gsrc(status="unavailable", relevance="unknown")
    src_kind = [{"id": "GC-2", "cause": "source_unavailable", "words": "w"}]
    check_eq("T5 a source merely `relevance: unknown` is not called unreachable: the kind does not close it",
             comp(unknown, classes=src_kind)["unavailable"], ["SRC-m"])
    s = comp(gone, classes=src_kind)
    check_eq("T5 a source whose status IS unavailable is closed by the kind",
             (s["unavailable"], s["closed_by_class"]), ([], {"SRC-m": {"source:unavailable": "GC-2"}}))
    check_eq("T5 and never by default", comp(gone)["unavailable"], ["SRC-m"])

    # T15 the table covers every code vcs_evidence.py can answer
    src = (PLUGIN_ROOT / "scripts" / "vcs_evidence.py").read_text(encoding="utf-8")
    import re
    codes = set(re.findall(r'AccessError\("(\w+)"\)', src)) | {"unauthenticated", "forbidden", "not_found_or_hidden", "rate_limited"}
    codes |= set(re.findall(r'return "(host_unreachable|network_transient|cli_config_error)"', src))
    codes.discard("host_unresolved")      # git_readiness only: it is never in a collector receipt
    table = SI.cause_table()
    check_eq("T15 vcs_codes names exactly the codes vcs_evidence.py answers with", set(table["vcs_codes"]), codes)
    check_eq("T15 every cause is a word of media_causes", set(table["vcs_codes"].values()) <= set(table["media_causes"]), True)
    carried = {code for code, cause in table["vcs_codes"].items() if table["default_causes"].get(cause) in {"probe", "structural"}}
    check_eq("T15 no code but host_unreachable gives a cause that has a probe or structural carrier", carried, {"host_unreachable"})

    # T16 a damaged table
    saved = SI.CAUSES_PATH
    bad_dir = temp_dir("qa-causes-")
    try:
        bad = bad_dir / "source-causes.json"
        bad.write_text("{broken", encoding="utf-8")
        SI.CAUSES_PATH = bad
        SI._CAUSE_CACHE.clear()
        s = comp(gsrc(media=[mrow(**PROBE())]))
        check_eq("T16 an unreadable table gives no default at all, and a problem line naming the file",
                 (s["defaulted_gaps"], s["unavailable_materials"], "source-causes.json" in s["gap_class_problem"]), ([], ["SRC-m"], True))
        out = bad_dir / "inv.json"
        out.write_text(json.dumps(cinv(gsrc(media=[{"url": SHARE, "status": "pending"}]))), encoding="utf-8")
        try:
            record_external_media(out, "SRC-m", SHARE, "unavailable", "no_tool: no browser")
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        check_in("T16 the writer refuses, naming the file", "source-causes.json", refused)
    finally:
        SI.CAUSES_PATH = saved
        SI._CAUSE_CACHE.clear()
        cleanup(bad_dir)
    check_eq("T16 and the real table is read again", "no_tool" in SI.cause_table()["media_causes"], True)


def test_gap_words_and_basis():
    """T11a: the one helper of the words of a gap (N4) and the provenance sentence (D-0047)."""
    row = mrow(**PROBE(probe_ref="x"))
    item = gsrc(media=[mrow(cause="auth_required")], gap_acceptance={"words": "person word", "accepted_points": []})
    kinds = [{"id": "GC-1", "cause": "auth_required", "words": "skip all logins", "at": "2026-10-16T10:00:00+00:00"}]
    s = comp(item, classes=kinds)
    check_eq("T11a gap_words joins the person's word and the kind's", SI.gap_words(item, s["closed_by_class"], kinds),
             "person word | skip all logins")
    check_in("T11a class_basis says whose word and when", "GC-1 of 2026-10-16", SI.class_basis(s["closed_by_class"], kinds, "SRC-m"))
    check_eq("T11a a kind record without a date names the file, and no author is invented",
             "work/gap-classes.json" in SI.class_basis({"SRC-m": {"p": "GC-1"}}, [{"id": "GC-1", "words": "w"}], "SRC-m"), True)
    check_eq("T11a nothing closed by a kind: empty", SI.class_basis({}, kinds, "SRC-m"), "")
    del row


def test_media_refusal():
    """HF8-5 AK1-AK7, A-1..A-7: a refusal of `inspect --media-url` says what is wrong and names a door."""
    base = temp_dir("qa-media-refusal-")
    try:
        out = base / "work" / "source-inventory.json"
        out.parent.mkdir(parents=True)
        mr1 = "https://git.example.com/team/sdk/-/merge_requests/1924"

        def g(**kw):
            return gsrc(sid="SRC-1", **kw)

        def put(*sources):
            out.write_text(json.dumps(cinv(*sources)), encoding="utf-8")
            return out.read_bytes()

        def refuse(url, source="SRC-1", **kw):
            try:
                record_external_media(out, source, url, kw.pop("status", "unavailable"), "no_tool: x")
            except ValueError as exc:
                return str(exc)
            return ""

        def media(n, **row):
            return [dict({"url": f"https://share.example.com/v{i}.mp4", "status": "pending"}, **row) for i in range(n)]

        def receipt(src, iid, status="read", project="team/sdk", host="git.example.com", raw=None):
            path = base / "work" / "sources" / src / f"mr-{iid}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw if raw is not None else json.dumps(
                {"url": f"https://{host}/{project}/-/merge_requests/{iid}", "host": host, "project": project,
                 "iid": str(iid), "status": status}), encoding="utf-8")

        # AK1 / A-3: a receipt that was READ for this very request -> named, nothing to do; AK6 bytes untouched
        receipt("SRC-1", 1924)
        before = put(g(media=[]))
        text = refuse(mr1)
        check_in("AK1 names the receipt file", "work/sources/SRC-1/mr-1924.json", text)
        check_in("AK1 says it is not a material and nothing is to be done", "nothing is to be done", text)
        check_in("AK1 says development link", "development link", text)
        check_eq("AK6 the inventory is not changed", out.read_bytes(), before)
        # F1 (FR-41): a receipt that is not `read` is never "already collected": named by its status, door given
        receipt("SRC-1", 1930, status="unavailable")
        text = refuse("https://git.example.com/team/sdk/-/merge_requests/1930")
        check_not_in("F1 a failed receipt is not claimed as collected", "already collected", text)
        check_in("F1 it is named with its status", "has status 'unavailable'", text)
        check_in("F1 and the door to read it is given", "vcs_evidence.py --url", text)
        receipt("SRC-1", 1932, raw="{}")
        text = refuse("https://git.example.com/team/sdk/-/merge_requests/1932")
        check_not_in("F1 a receipt with no identity or status is not claimed either", "already collected", text)
        receipt("SRC-1", 1933, raw="not json")
        text = refuse("https://git.example.com/team/sdk/-/merge_requests/1933")
        check_in("F1 an unreadable receipt is named as such", "is unreadable", text)
        check_not_in("F1 and not claimed", "already collected", text)
        # F2: the same number of another project, or a GitLab receipt for a GitHub pull request, is not this URL's
        receipt("SRC-1", 1931, project="ui")
        text = refuse("https://git.example.com/team/sdk/-/merge_requests/1931")
        check_not_in("F2 another project's receipt is not claimed", "already collected", text)
        check_in("F2 it is named as another request", "another request: git.example.com/ui", text)
        receipt("SRC-1", 8)
        text = refuse("https://github.com/o/r/pull/8")
        check_not_in("F2/F4 a pull request gets no GitLab claim", "already collected", text)
        check_in("F4 a pull request is told what exists: GitLab only, name it for the person", "GitLab", text)
        check_not_in("F4 and is not sent to vcs_evidence as a door", "--output", text)
        # F7: the kind comes from the reference table, path only: not a request, so AK3 with the door `collect`
        put(g(media=media(1)))
        for tag, bad in (("a wiki path", "https://confluence.example.com/display/merge_requests/12"),
                         ("a query string", "https://git.example.com/x?next=/-/merge_requests/9"),
                         ("an issue of the same host", "https://git.example.com/team/sdk/-/issues/7"),
                         ("a number with a tail", "https://git.example.com/team/sdk/-/merge_requests/5a")):
            text = refuse(bad)
            check_in(f"F7 {tag} is not a request: the door collect", "`collect`", text)
            check_not_in(f"F7 {tag} is not called a development link", "development link", text)
        put(g(media=[]))
        # A-6: markdown-escaped URL is still recognised
        check_in("A-6 an escaped URL is still a development link",
                 "work/sources/SRC-1/mr-1924.json", refuse("https://git.example.com/team/sdk/-/merge\\_requests/1924"))
        # A-3: a layout without `mr-` in the name is NOT claimed as read (FR-41) -> AK2
        other = base / "work" / "sources" / "mr" / "1925.json"
        other.parent.mkdir(parents=True)
        other.write_text("{}", encoding="utf-8")
        text = refuse("https://git.example.com/team/sdk/-/merge_requests/1925")
        check_in("AK2 no receipt found: reads it through vcs_evidence", "vcs_evidence.py --url", text)
        check_in("AK2 says no receipt was found, not that it was read", "No collected receipt", text)
        check_not_in("A-3 and never claims a read it did not see", "already collected", text)
        check_not_in("A-3 and never names the file it did not see", "mr/1925.json", text)
        check_in("F5 the door hands the path the finder reads", "/work/sources/SRC-1/mr-1925.json", text)
        # A-3 (amended): several receipts of one number in different sources, same request: all listed
        receipt("SRC-2", 1924)
        text = refuse(mr1)
        check_in("A-3 both receipts are listed", "SRC-1/mr-1924.json, work/sources/SRC-2/mr-1924.json", text)
        # A-4: a failing search keeps the class of the refusal
        import base_slice
        saved = base_slice.receipt_files
        def boom(*_a, **_k):
            raise OSError("denied")
        def no_module(*_a, **_k):
            raise ImportError("gone")
        for exc_name, fake in (("OSError", boom), ("ImportError", no_module)):
            base_slice.receipt_files = fake
            try:
                text = refuse(mr1)
            finally:
                base_slice.receipt_files = saved
            check_in(f"A-4 an {exc_name} in the search gives AK2", "No collected receipt", text)
        # A-7: a commit URL is not a development link of this rule -> AK3 with the door
        text = refuse("https://git.example.com/team/sdk/-/commit/abcdef1")
        check_in("A-7 a commit URL goes to AK3: the door collect", "`collect`", text)
        check_not_in("A-7 and is not told it is a merge request", "development link", text)
        # AK3 / A-2: lists of 0, 5, 6 URLs
        put(g(media=media(0)))
        check_in("A-2 no media: said so, no empty list", "has no external media", refuse("https://x.example.com/a.mp4"))
        put(g(media=media(5)))
        text = refuse("https://x.example.com/a.mp4")
        check_in("A-2 five are all shown", "v4.mp4", text)
        check_not_in("A-2 and carry no tail", "more)", text)
        check_in("A-2 and the door is named", "`collect`", text)
        put(g(media=media(6)))
        text = refuse("https://x.example.com/a.mp4")
        check_in("A-2 six: five shown and a tail", "(+1 more)", text)
        check_not_in("A-2 the sixth is not printed", "v5.mp4", text)
        # AK4: unknown source
        put(g(media=media(1)), gsrc(sid="SRC-9"))
        text = refuse("https://share.example.com/v0.mp4", source="NOPE")
        check_in("AK4 names the known source_id values", "SRC-1, SRC-9", text)
        # AK5: two items with the URL
        dup = media(1) * 2
        put(g(media=dup))
        text = refuse("https://share.example.com/v0.mp4")
        check_in("AK5 two items carry this URL, with statuses", "2 items carry this URL", text)
        check_in("AK5 statuses", "pending, pending", text)
        put(g(media=media(1) * 6))
        check_in("AK5 six statuses: five shown and a tail", "(+1 more)", refuse("https://share.example.com/v0.mp4"))
        # A-1: a VCS URL that IS an item (one match) goes the old path: no_tool refused, pending stays pending
        put(g(media=[{"url": mr1, "status": "pending"}]))
        try:
            record_external_media(out, "SRC-1", mr1, "unavailable", "no_tool: x")
            old = ""
        except ValueError as exc:
            old = str(exc)
        check_in("A-1 an MR among the items takes the old no_tool path", "authenticates read-only", old)
        row = json.loads(out.read_text(encoding="utf-8"))["sources"][0]["materials"]["external_media"]["items"][0]
        check_eq("A-1 and stays pending", row["status"], "pending")
        # A-1 positive: the same MR item is recorded as before with a read receipt
        record_external_media(out, "SRC-1", mr1, "read", local_ref="sources/SRC-1/mr-1924.json")
        row = json.loads(out.read_text(encoding="utf-8"))["sources"][0]["materials"]["external_media"]["items"][0]
        check_eq("A-1 positive: the MR item is recorded read", (row["status"], row["local_ref"]),
                 ("read", "sources/SRC-1/mr-1924.json"))
        # F6: an empty list never says "pass one of them"
        put()
        text = refuse("https://share.example.com/v0.mp4")
        check_in("F6 an empty inventory names the door collect", "`collect`", text)
        check_not_in("F6 and offers nothing to pass", "Pass one of them", text)
        # AK7: the neighbour for attachments
        def attach_refusal(*sources, attachment_id="77"):
            put(*sources)
            try:
                record_attachment_inspection(out, "SRC-1", attachment_id, "read", "work/evidence/x.json")
            except ValueError as exc:
                return str(exc)
            return ""

        text = attach_refusal(g(attachments=[arow(cause="x", status="read", attachment_id="9"), arow(attachment_id="10")]))
        check_in("AK7 lists the attachment ids", "9, 10", text)
        check_in("AK7 names the id given", "'77'", text)
        text = attach_refusal(g(attachments=[]))
        check_in("F6 a source with no attachments says so and names collect", "no attachments", text)
        check_in("F6 the door is collect", "`collect`", text)
        check_not_in("F6 and offers nothing to pass", "Pass one of them", text)
        text = attach_refusal(g(attachments=[arow(attachment_id="9"), arow(attachment_id="9")]), attachment_id="9")
        check_in("AK7 two attachments with one id: counted, door collect", "2 attachments carry id 9", text)
        text = attach_refusal()
        check_in("F6 an empty inventory for an attachment names collect", "`collect`", text)
        check_not_in("F6 and offers nothing to pass", "Pass one of them", text)
    finally:
        cleanup(base)


if __name__ == "__main__":
    main()
