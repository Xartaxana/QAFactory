"""A mentioned ticket is looked at before it is collected: comments, attachments and the
tickets it names enter a story only once it is judged relevant.

TP1-15045 collected two unrelated tickets in full — ten attachments, 8 MB of video — and
then could not leave S1 because nobody had inspected the attachments of tickets that had
already been excluded."""
import json
import sys

from harness import PLUGIN_ROOT, check, check_eq, cleanup, finish, temp_dir

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from source_inventory import (collect_jira_source, completeness, peek_jira_source,  # noqa: E402
                              record_relevance_assessment, record_source_review,
                              update_inventory, validate_inventory, FetchError)


class Client:
    base_url = "https://jira.invalid"
    acceptance_criteria_fields = []
    api_version = "2"
    project_keys = []

    def __init__(self):
        self.comment_calls, self.byte_calls, self.project_calls = [], [], []

    def get_json(self, path):
        # every mentioned prefix here is a real tracker project — the probe just
        # confirms it, one request per prefix, so every mention still becomes a source.
        self.project_calls.append(path)
        return {"key": path.rsplit("/", 1)[-1]}

    def issue(self, key):
        if key == "GONE-1":
            raise FetchError(403, "HTTP 403", retryable=False)
        if key == "FE-1":
            raise FetchError(404, "HTTP 404", retryable=False)
        mentions = {"TASK-1": "see BUG-7 and GONE-1; step FE-1, encoded UTF-8 per ISO-8601",
                    "BUG-7": "caused by DEEP-9"}.get(key, "")
        return {"key": key, "id": "1", "fields": {
            "updated": "rev-" + key, "summary": "title " + key, "description": mentions,
            "comment": {"total": 3},
            "attachment": [{"id": "1", "filename": "video.mp4", "content": "bytes-" + key, "size": 3}]}}

    def all_comments(self, key, first=None):
        self.comment_calls.append(key)
        return []

    def get_bytes(self, url):
        self.byte_calls.append(url)
        return b"abc"


def main():
    root = temp_dir("qa-source-peek-")
    try:
        output = root / "work" / "source-inventory.json"
        client = Client()
        update_inventory(output, collect_jira_source(client, "TASK-1", output))
        inventory = json.loads(output.read_text(encoding="utf-8"))
        check_eq("the task names three key-shaped tokens; UTF-8 and ISO-8601 are not among them",
                 sorted(s["canonical_ref"].rsplit("/", 1)[-1] for s in inventory["sources"]),
                 ["BUG-7", "FE-1", "GONE-1", "TASK-1"])
        ghost = peek_jira_source(client, "FE-1", output)
        update_inventory(output, ghost)
        check_eq("a 404 while the tracker is provably readable leaves the key out",
                 (ghost["status"], ghost["relevance"], ghost.get("not_found")),
                 ("excluded", "not_relevant", True))
        from source_inventory import review_rows, load_inventory
        check_eq("and the person sees it as its own line, not among ordinary exclusions",
                 [r["decision"] for r in review_rows(load_inventory(output)) if r["key"] == "FE-1"],
                 ["not found (404)"])
        # Jira says 404 for "no permission" too, and a dead session says it for everything.
        blind = root / "blind" / "work" / "source-inventory.json"
        blind.parent.mkdir(parents=True)
        lost = peek_jira_source(client, "FE-1", blind)
        check_eq("with no readable source to prove access, a 404 is an unavailable source",
                 (lost["status"], lost["relevance"]), ("unavailable", "unknown"))

        downloads = list(client.byte_calls)
        record = peek_jira_source(client, "BUG-7", output)
        inventory = update_inventory(output, record)
        check_eq("a peek downloads no attachment", client.byte_calls, downloads)
        check("and reads no comment page", "BUG-7" not in client.comment_calls)
        check_eq("it still says what is there to be fetched",
                 (record["materials"]["attachments"]["count"], record["materials"]["comments"]["count"]), (1, 3))
        check("the assessment snapshot is on disk", (output.parent / record["assessment_ref"]).is_file())
        check_eq("a peeked ticket waits for a decision", (record["status"], record["relevance"]),
                 ("pending", "pending"))
        check("its own mentions do not enter the story yet",
              not any(s["canonical_ref"].endswith("/DEEP-9") for s in inventory["sources"]))
        check_eq("the inventory stays valid", validate_inventory(inventory), [])

        inventory = record_relevance_assessment(output, record["source_id"], "not_relevant",
                                                "an unrelated accessibility defect", record["assessment_ref"])
        gone = peek_jira_source(client, "GONE-1", output)
        inventory = update_inventory(output, gone)
        check_eq("an unreachable ticket is unavailable, not silently dropped",
                 (gone["status"], gone["relevance"]), ("unavailable", "unknown"))
        summary = completeness(inventory)
        check_eq("the excluded ticket owes nothing", summary["pending"] + summary["incomplete_materials"],
                 [s["source_id"] for s in inventory["sources"] if s["canonical_ref"].endswith("/TASK-1")])
        check_eq("the unreachable one is the open point", summary["unavailable"], [gone["source_id"]])
        check_eq("nothing was downloaded for either", client.byte_calls, downloads)

        # a relevant mention is then collected in full, and only now grows the graph
        relevant = peek_jira_source(client, "BUG-7", output)
        update_inventory(output, relevant)
        record_relevance_assessment(output, relevant["source_id"], "relevant", "the defect under test",
                                    relevant["assessment_ref"])
        full = collect_jira_source(client, "BUG-7", output, relation="referenced")
        inventory = update_inventory(output, full)
        check("full collection fetches comments and bytes", "BUG-7" in client.comment_calls
              and "bytes-BUG-7" in client.byte_calls)
        check("and its mentions become visible", any(s["canonical_ref"].endswith("/DEEP-9")
                                                     for s in inventory["sources"]))

        # the person's review survives a re-collect of the same source
        for source in inventory["sources"]:
            if source["relevance"] == "pending":
                record_relevance_assessment(output, source["source_id"], "not_relevant", "unrelated",
                                            "sources/x/assessment/ticket.json")
        record_source_review(output, "agreed")
        again = collect_jira_source(client, "BUG-7", output, relation="referenced")
        inventory = update_inventory(output, again)
        kept = next(s for s in inventory["sources"] if s["canonical_ref"].endswith("/BUG-7"))
        check_eq("human_review is carried over a re-collect", kept["human_review"]["words"], "agreed")
    finally:
        cleanup(root)
    finish("test_source_peek")


if __name__ == "__main__":
    main()
