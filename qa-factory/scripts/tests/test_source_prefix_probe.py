"""TP1-15045 spent 51 Jira requests confirming 7 local-numbering
prefixes (BR, FTR, TC, US, BE, FE) were not tracker projects, recorded the factory's own
narration as a person's answer, and let the scout collect a second `--relation task` source.
"""
import json
import os
import sys
import urllib.error

from harness import PLUGIN_ROOT, check, check_eq, cleanup, finish, temp_dir, temp_project, run_script

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from source_inventory import (JiraClient, collect_jira_source, completeness,
                              conflicting_task_source, record_late_review, record_source_review,
                              render_review, review_rows, update_inventory, validate_inventory,
                              VALID_RELATIONS)  # noqa: E402

os.environ["QA_PREFIX_PROBE_USER"] = "reader@example.invalid"
os.environ["QA_PREFIX_PROBE_TOKEN"] = "test-only-token"


def make_client(opener, **kw):
    return JiraClient("https://jira.example.invalid", "QA_PREFIX_PROBE_USER", "QA_PREFIX_PROBE_TOKEN",
                      api_version="3", opener=opener, **kw)


class Response:
    def __init__(self, data, content_type="application/json"):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.data

    def geturl(self):
        return "https://jira.example.invalid/fixture"


def main():
    # --- an unknown prefix costs one probe for the whole prefix, not one per key ------
    root = temp_dir("qa-prefix-probe-")
    try:
        output = root / "work" / "source-inventory.json"
        # A spec.md-shaped description: 5 local-numbering tokens, 2 unknown prefixes (BR, TC).
        # TASK-1's own prefix is known for free; BR and TC are not.
        description = "See BR-1, BR-2, TC-001, TC-002 and TC-003 in the attached spec."
        issue = {"key": "TASK-1", "fields": {"updated": "rev-1", "summary": "story",
                 "description": description, "comment": {"total": 0, "comments": []}}}
        project_calls = []

        def opener(request, timeout=0):
            if "/issue/TASK-1?" in request.full_url:
                return Response(issue)
            if request.full_url.endswith("/project/BR") or request.full_url.endswith("/project/TC"):
                project_calls.append(request.full_url)
                raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)
            raise AssertionError(request.full_url)

        client = make_client(opener)
        record = collect_jira_source(client, "TASK-1", output)
        inventory = update_inventory(output, record)
        check_eq("one probe per unknown prefix, not per key", sorted(project_calls),
                 ["https://jira.example.invalid/rest/api/3/project/BR",
                  "https://jira.example.invalid/rest/api/3/project/TC"])
        excluded = [s for s in inventory["sources"] if s["canonical_ref"] != record["canonical_ref"]]
        check_eq("every local-numbering token still becomes its own source", len(excluded), 5)
        check("all five are excluded, not_found, in one step per prefix",
              all(s["status"] == "excluded" and s.get("not_found") for s in excluded))
        # t-721 3.5 (C2-3): the writer of the snapshot stamps the S1 receipt (`inspection_by: code:snapshot`), so the
        # collected source no longer owes `source:not_inspected`. This line used to read `complete == False` - that
        # False was the primary source's own missing receipt, never the excluded ones (they owe nothing); with the
        # receipt a fact of the disk, nothing is left to block (the review gate is `gate_blocked`, not `complete`).
        primary = [s for s in inventory["sources"] if s["canonical_ref"] == record["canonical_ref"]][0]
        check_eq("the collected source's receipt is stamped by the code, from its snapshot on disk (3.5)",
                 (primary["inspection_status"], primary.get("inspection_by")), ("read", "code:snapshot"))
        check_eq("excluded sources owe no materials (and the stamped primary owes no receipt)",
                 completeness(inventory)["complete"], True)
        check_eq("but they are not what blocks it",
                 completeness(inventory)["unavailable"] + completeness(inventory)["pending"], [])
        check_eq("the fresh inventory still validates", validate_inventory(inventory), [])

        # A second, later collect of the same task must not re-probe BR or TC.
        calls_before = len(project_calls)
        again = collect_jira_source(client, "TASK-1", output, existing_record=record)
        update_inventory(output, again)
        check_eq("the prefix cache survives update_inventory's rewrite", len(project_calls), calls_before)

        # review_rows still lists every one of them individually...
        rows = review_rows(inventory)
        not_found_rows = [r for r in rows if r["decision"] == "not found (404)"]
        check_eq("review_rows keeps the full, uncollapsed list (review --json's contract)",
                 len(not_found_rows), 5)
        # ...render_review collapses them into one row the person can still read.
        rendered = render_review(rows)
        check("render_review collapses into one row", rendered.count("not found (404)") == 1)
        check("the collapsed row names the count and the prefixes",
              "5 key-shaped tokens of 2 unknown prefixes" in rendered and "BR" in rendered
              and "TC" in rendered)
        check("collapsed is not hidden — --expand-not-found prints every row",
              render_review(rows, expand_not_found=True).count("not found (404)") == 5)
    finally:
        cleanup(root)

    # --- a known prefix (task's own, parent, issuelinks, /browse/ url, project_keys) --
    root = temp_dir("qa-prefix-known-")
    try:
        output = root / "work" / "source-inventory.json"
        issue = {"key": "TASK-2", "fields": {
            "updated": "rev-1", "summary": "story",
            "description": "See TASK-9, PARENT-3, LINK-4, BROWSED-1 (https://jira.example.invalid/browse/BROWSED-1) and ALLOWED-2.",
            "parent": {"key": "PARENT-3"}, "issuelinks": [{"inwardIssue": {"key": "LINK-4"}}],
            "comment": {"total": 0, "comments": []}}}

        def opener(request, timeout=0):
            if "/issue/TASK-2?" in request.full_url:
                return Response(issue)
            raise AssertionError("no project probe expected: " + request.full_url)

        client = make_client(opener, project_keys=["ALLOWED"])
        record = collect_jira_source(client, "TASK-2", output)
        # TASK, PARENT, LINK, BROWSED, ALLOWED are all known already — zero project probes.
        check_eq("known prefixes cost nothing, from any field they are mentioned in",
                 sorted(record["mentioned_ticket_keys"]),
                 ["ALLOWED-2", "BROWSED-1", "LINK-4", "PARENT-3", "TASK-9"])
    finally:
        cleanup(root)

    # --- without proven access a 404 stays unavailable (blocking), never excluded -----
    root = temp_dir("qa-prefix-unproven-")
    try:
        output = root / "work" / "source-inventory.json"
        issue = {"key": "TASK-3", "fields": {"updated": "rev-1", "summary": "story",
                 "description": "See NEW-1.", "comment": {"total": 0, "comments": []}}}

        def opener(request, timeout=0):
            if "/issue/TASK-3?" in request.full_url:
                return Response(issue)
            if request.full_url.endswith("/project/NEW"):
                raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, None)
            raise AssertionError(request.full_url)

        client = make_client(opener)
        record = collect_jira_source(client, "TASK-3", output)
        inventory = update_inventory(output, record)
        mentioned = next(s for s in inventory["sources"] if s["canonical_ref"] != record["canonical_ref"])
        check_eq("a non-404 (or unproven) prefix answer stays unavailable, not excluded",
                 (mentioned["status"], mentioned.get("not_found")), ("unavailable", None))
        check_eq("and it blocks the gate until a person accepts it",
                 completeness(inventory)["unavailable"], [mentioned["source_id"]])
    finally:
        cleanup(root)

    # --- --late marks a source shown without recording it as answered -----------------
    root = temp_dir("qa-late-review-")
    try:
        output = root / "work" / "source-inventory.json"
        reviewed = {"source_id": "s1", "canonical_ref": "https://jira/browse/APP-1", "relation": "task",
                    "relevance": "relevant", "relevance_reason": "explicit", "assessment_ref": None,
                    "discovered_from": None, "relation_evidence": None, "required": True,
                    "status": "read", "revision": "r1", "content_hash": "h", "snapshot_ref": "s",
                    "fetched_at": "t", "exclusion_or_error": None, "inspection_status": "read",
                    "materials": {k: {"status": "read", "count": 0} for k in
                                  ("comments", "attachments", "external_media")},
                    "human_review": {"words": "agreed", "by": "human", "at": "t",
                                     "shown": {"relevance": "relevant", "status": "read"}}}
        late = {**reviewed, "source_id": "s2", "canonical_ref": "https://jira/browse/APP-2"}
        del late["human_review"]
        output.parent.mkdir(parents=True)
        output.write_text(json.dumps({"schema_version": 1, "sources": [reviewed, late]}), encoding="utf-8")

        check("before --late, the new source still awaits review",
              any(r["source_id"] == "s2" for r in review_rows(json.loads(output.read_text()),
                                                               only_unreviewed=True)))
        inventory, marked = record_late_review(output)
        check_eq("record_late_review marks exactly the unreviewed one", marked, ["s2"])
        after = json.loads(output.read_text())
        s2 = next(s for s in after["sources"] if s["source_id"] == "s2")
        check("marked with a timestamp and no words", "shown_at_gate" in s2 and "words" not in s2["shown_at_gate"])
        check("review_rows(only_unreviewed=True) stops listing it once marked --late",
              not any(r["source_id"] == "s2" for r in review_rows(after, only_unreviewed=True)))
        check("but it is still reported by completeness(), non-blocking",
              "s2" in completeness(after)["unreviewed"] and not completeness(after)["gate_blocked"])

        # review --record still refuses the factory's own narration about a silence.
        try:
            record_source_review(output, "person replied only 'go on' and did not object")
            narrated_refused = False
        except ValueError as exc:
            narrated_refused = "--late" in str(exc)
        check("review --record refuses narration about a silence, and points at --late",
              narrated_refused)
    finally:
        cleanup(root)

    # --- --relation is mandatory for collect, and a second task source is refused -----
    root = temp_project("qa-relation-mandatory-")
    try:
        env = {"CLAUDE_PROJECT_DIR": str(root)}
        import os
        full_env = dict(os.environ, **env)
        p = run_script("ticket_adapter.py", "collect", "APP-1", "--output",
                       str(root / "qa-factory" / "work" / "source-inventory.json"), env=full_env)
        check_eq("collect without --relation is a usage error, not a silent default", p.returncode, 2)
        check("the error names the allowed values", all(v in p.stderr for v in VALID_RELATIONS))
    finally:
        cleanup(root)

    existing_sources = [{"relation": "task", "canonical_ref": "https://jira/browse/PARENT-1"}]
    check_eq("a second --relation task for a different ticket is refused",
             conflicting_task_source(existing_sources, "task", "https://jira/browse/OTHER-2") is not None,
             True)
    check_eq("re-collecting the SAME task source is not a conflict",
             conflicting_task_source(existing_sources, "task", "https://jira/browse/PARENT-1"), None)
    check_eq("any other relation never conflicts", conflicting_task_source(existing_sources, "subject",
                                                                           "https://jira/browse/OTHER-2"), None)

    finish("test_source_prefix_probe")


if __name__ == "__main__":
    main()
