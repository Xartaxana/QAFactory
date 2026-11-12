"""E34 source resolution preserves dirty work and rejects a matching branch on wrong content."""
import subprocess
import sys

from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_dir

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from source_preflight import assess_freshness, resolve_source  # noqa: E402

ROOT = temp_dir("qa-source-preflight-")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def main() -> None:
    try:
        git("init", "-q")
        git("config", "user.email", "qa@example.invalid")
        git("config", "user.name", "QA Test")
        (ROOT / ".gitattributes").write_text("* text=auto\napp.txt text eol=crlf\n", encoding="utf-8")
        (ROOT / "app.txt").write_text("base\n", encoding="utf-8")
        for index in range(50):
            (ROOT / f"product-{index}.txt").write_text(f"product {index}\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-q", "-m", "base")
        base = git("rev-parse", "HEAD")
        git("switch", "-q", "-c", "QA-42-work")
        (ROOT / "app.txt").write_text("implementation\n", encoding="utf-8")
        git("commit", "-q", "-am", "implementation")
        implementation = git("rev-parse", "HEAD")
        (ROOT / "local.txt").write_text("human uncommitted bytes\n", encoding="utf-8")
        result = resolve_source(ROOT, implementation, "QA-42", default_branch="main",
                                implementation_paths=["app.txt"])
        check_eq("dirty matching task branch with exact implementation is reused", result["action"], "reuse")
        check("dirty work is reported and preserved", any("local.txt" in x for x in result["working_tree_status"]))
        check_eq("source preflight is read-only", result["mutated"], False)
        check_eq("ancestor fact is retained separately", result["source_is_ancestor"], True)
        check_eq("write permission is based on verified bytes", result["content_verified"], True)
        many = resolve_source(ROOT, implementation, "QA-42", default_branch="main",
                              implementation_paths=[f"product-{index}.txt" for index in range(50)])
        check_eq("many selected files are compared in bounded batched output",
                 many["implementation_path_count"], 50)
        check_eq("large path details are truncated from stdout records",
                 many["implementation_paths_truncated"], True)
        check_eq("attribute-normalized checkout bytes verify through git diff", result["content_verified"], True)
        (ROOT / "app.txt").write_text("locally overwritten\n", encoding="utf-8")
        overwritten = resolve_source(ROOT, implementation, "QA-42", default_branch="main",
                                     implementation_paths=["app.txt"])
        check_eq("locally overwritten product bytes deny writes", overwritten["write_allowed"], False)
        (ROOT / "app.txt").write_text("implementation\n", encoding="utf-8")
        (ROOT / "qa-notes.txt").write_text("unrelated QA draft\n", encoding="utf-8")
        scoped = resolve_source(ROOT, implementation, "QA-42", default_branch="main",
                                implementation_paths=["app.txt"])
        check_eq("unchanged product plus unrelated QA bytes remains reusable", scoped["write_allowed"], True)
        isolated = resolve_source(ROOT, implementation, "OTHER-9", default_branch="main")
        check_eq("dirty unrelated tree requires isolated source worktree",
                 isolated["action"], "isolate_from_source")
        check_eq("read-only preflight does not grant write ownership", isolated["write_allowed"], False)

        git("switch", "-q", "-c", "QA-43-reverted")
        (ROOT / "app.txt").write_text("base\n", encoding="utf-8")
        git("add", "app.txt")
        git("commit", "-q", "-m", "revert implementation content")
        reverted = resolve_source(ROOT, implementation, "QA-43", default_branch="main",
                                  implementation_paths=["app.txt"])
        check_eq("ancestor commit whose product content was reverted is not present",
                 reverted["source_is_ancestor"], True)
        check_eq("reverted product content denies writes", reverted["write_allowed"], False)
        git("switch", "-q", "QA-42-work")

        git("switch", "-q", "--detach", base)
        (ROOT / "other.txt").write_text("sibling\n", encoding="utf-8")
        git("add", "other.txt")
        git("commit", "-q", "-m", "sibling")
        wrong = git("rev-parse", "HEAD")
        git("switch", "-q", "QA-42-work")
        conflict = resolve_source(ROOT, wrong, "QA-42", requested_branch="QA-42-work",
                                  default_branch="main")
        check_eq("matching branch name with wrong source content is conflict",
                 conflict["action"], "resolve_conflict")
        check_eq("wrong-base conflict never invents a base SHA", conflict["qa_branch_base_sha"], None)
        check("wrong-base reason is explicit", bool(conflict["reason"]))
    finally:
        cleanup(ROOT)
    t279_the_two_gates_that_already_take_any_not_applicable_refuse_the_image_identity()
    t721_the_snapshot_receipt_is_a_fact_of_the_disk()
    t721_a_role_receipt_outranks_the_stamp()
    t721_the_writer_stamps_the_receipt_it_stores()
    c29_a_gap_by_default_is_not_a_question()
    finish("test_source_preflight")


def _s1_story(prefix: str, content: bytes = b'{"key": "APP-1"}', hashed: bytes = b'{"key": "APP-1"}', **over):
    """A task folder with one READ source whose snapshot lies under work/ and whose inspection receipt the role never
    wrote (the shape of a story that ran before the writer stamped): (task root, inventory path)."""
    import hashlib
    import json
    from test_gap_points import source
    task = temp_dir(prefix)
    snapshot = task / "work" / "sources" / "SRC-a1" / "r1" / "ticket.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(content)
    item = source("SRC-a1", "APP-1", relation="task", relevance_reason="the task", assessment_ref=None,
                  discovered_from=None, relation_evidence=None, fetched_at="t", revision="r1",
                  snapshot_ref="sources/SRC-a1/r1/ticket.json", content_hash=hashlib.sha256(hashed).hexdigest(),
                  inspection_status="pending", **over)
    path = task / "work" / "source-inventory.json"
    path.write_text(json.dumps({"schema_version": 1, "sources": [item]}), encoding="utf-8")
    return task, path


def _item(path):
    import json
    return json.loads(path.read_text(encoding="utf-8"))["sources"][0]


def t721_the_snapshot_receipt_is_a_fact_of_the_disk() -> None:
    """t-721 C2-3 (T10, section 3.5): a READ source with its snapshot and hash on disk gets its inspection receipt from the
    code (`ticket_adapter.py receipts`), so the S1 boundary no longer says its materials lack receipts and the point
    `source:not_inspected` is gone; without the fact (no snapshot_ref, a snapshot of another hash) nothing is stamped."""
    from source_inventory import completeness, load_inventory, snapshot_receipt
    from source_preflight import check_source_inventory
    from harness import run_script
    task, path = _s1_story("qa-receipt-")
    try:
        before = check_source_inventory(task, {})
        check_in("T10 control: before the stamp the boundary says the materials lack receipts",
                 "lack retrieval or inspection receipts", " ".join(before["errors"]))
        check_in("T10 control: and the point is `source:not_inspected`", "source:not_inspected",
                 str(completeness(load_inventory(path))["open_points"]))
        done = run_script("ticket_adapter.py", "receipts", "--output", str(path))
        check_eq("T10: the door stamps the one source, exit 0", (done.returncode, done.stdout.strip()),
                 (0, "receipts: 1 source(s) stamped from their snapshot on disk; 0 left as they are"))
        item = _item(path)
        check_eq("T10: the receipt is the snapshot, by the code", (item["inspection_status"], item["inspection_ref"],
                                                               item["inspection_by"]),
                 ("read", "sources/SRC-a1/r1/ticket.json", "code:snapshot"))
        after = check_source_inventory(task, {})
        check("T10: the boundary no longer lists the missing receipt", "lack retrieval" not in " ".join(after["errors"]),
              str(after["errors"]))
        check_eq("T10: and `source:not_inspected` is not a point any more",
                 completeness(load_inventory(path))["open_points"], {})
        again = run_script("ticket_adapter.py", "receipts", "--output", str(path))
        check_in("T10: a second run stamps nothing (idempotent)", "receipts: 0 source(s) stamped", again.stdout)
    finally:
        cleanup(task)
    # the predicate itself: the fact needs `read`, a snapshot_ref, a content_hash, and a source whose files verified
    fact = {"source_id": "S", "status": "read", "snapshot_ref": "r", "content_hash": "h"}
    check_eq("T10: the predicate holds on the whole fact", snapshot_receipt(fact, set()), True)
    for label, item, invalid in (("no snapshot_ref", dict(fact, snapshot_ref=None), set()),
                                 ("no content_hash", dict(fact, content_hash=""), set()),
                                 ("not read", dict(fact, status="unavailable"), set()),
                                 ("files that do not verify", fact, {"S"})):
        check_eq(f"T10: {label} - no receipt", snapshot_receipt(item, invalid), False)
    # a snapshot of ANOTHER hash on disk: the integrity check names the source, the stamp is not written
    task, path = _s1_story("qa-receipt-hash-", content=b"changed bytes")
    try:
        done = run_script("ticket_adapter.py", "receipts", "--output", str(path))
        check_eq("T10: a snapshot whose hash differs is not stamped", (done.returncode, _item(path)["inspection_status"],
                                                                      "0 source(s) stamped" in done.stdout),
                 (0, "pending", True))
    finally:
        cleanup(task)
    # a media gap the stamp does not touch: still a recorded gap with the person's door
    from test_gap_points import MR510, media, materials
    task, path = _s1_story("qa-receipt-media-", materials=materials(external_media={
        "status": "unavailable", "items": [media(MR510, "unavailable")]}))
    try:
        run_script("ticket_adapter.py", "receipts", "--output", str(path))
        errors = " ".join(check_source_inventory(task, {})["errors"])
        check_in("T10: a media gap stays a gap line, with `accept-gap` as its door", "accept-gap", errors)
    finally:
        cleanup(task)


def t721_a_role_receipt_outranks_the_stamp() -> None:
    """t-721 C2-3 (T10b, section 3.5): `assess` after the stamp rewrites `inspection_ref` to the assessment and drops
    `inspection_by`; the stamp after `assess` is a no-op (it never writes over `inspection_status: read`)."""
    from source_inventory import record_relevance_assessment
    from harness import run_script
    task, path = _s1_story("qa-receipt-assess-")
    try:
        run_script("ticket_adapter.py", "receipts", "--output", str(path))
        record_relevance_assessment(path, "SRC-a1", "relevant", "the whole ticket was read", "work/evidence/a.json")
        item = _item(path)
        check_eq("T10b: assess after the stamp - the ref is the assessment, no `by` is left",
                 (item["inspection_status"], item["inspection_ref"], "inspection_by" in item),
                 ("read", "work/evidence/a.json", False))
        kept = path.read_bytes()
        done = run_script("ticket_adapter.py", "receipts", "--output", str(path))
        check_eq("T10b: the stamp after assess is a no-op - nothing stamped, the file is the same bytes",
                 ("0 source(s) stamped" in done.stdout, path.read_bytes() == kept), (True, True))
    finally:
        cleanup(task)


def t721_the_writer_stamps_the_receipt_it_stores() -> None:
    """t-827 FX-1 (F1, section 3.5 / L-7): `update_inventory` - the live writer of the inventory - stamps the receipt of the
    snapshot it just stored. Three roads, each on a record written through the writer (not through the `receipts` door):
    a read record whose snapshot verifies is stamped; a receipt a role wrote (`assess`) is untouched; a code stamp over
    a NEW revision is renewed onto the new snapshot. The mutation `_stamp(record)` -> `pass` dies here."""
    import hashlib
    from source_inventory import STAMP_BY, update_inventory
    task, path = _s1_story("qa-writer-stamp-")
    try:
        record = _item(path)
        check_eq("FX-1 control: the record handed to the writer carries no receipt", record["inspection_status"], "pending")
        update_inventory(path, dict(record))
        item = _item(path)
        check_eq("FX-1 stamped: the writer put the code's receipt on the snapshot it stored",
                 (item.get("inspection_status"), item.get("inspection_ref"), item.get("inspection_by")),
                 ("read", "sources/SRC-a1/r1/ticket.json", STAMP_BY))
        # a role's receipt (assess) is not overwritten by the writer
        role = dict(record, inspection_status="read", inspection_ref="work/evidence/a.json")
        role.pop("inspection_by", None)
        update_inventory(path, role)
        item = _item(path)
        check_eq("FX-1 assess untouched: the role's receipt stays, no `by` is invented",
                 (item["inspection_status"], item["inspection_ref"], "inspection_by" in item),
                 ("read", "work/evidence/a.json", False))
        # a code stamp over a NEW revision is renewed onto the new snapshot, which lies on disk
        new_bytes = b'{"key": "APP-1", "rev": 2}'
        second = task / "work" / "sources" / "SRC-a1" / "r2" / "ticket.json"
        second.parent.mkdir(parents=True)
        second.write_bytes(new_bytes)
        renewed = dict(record, revision="r2", snapshot_ref="sources/SRC-a1/r2/ticket.json",
                       content_hash=hashlib.sha256(new_bytes).hexdigest(), inspection_status="read",
                       inspection_ref="sources/SRC-a1/r1/ticket.json", inspection_by=STAMP_BY)
        update_inventory(path, renewed)
        item = _item(path)
        check_eq("FX-1 renewed: the code stamp follows the new revision's snapshot",
                 (item["revision"], item.get("inspection_ref"), item.get("inspection_by")),
                 ("r2", "sources/SRC-a1/r2/ticket.json", STAMP_BY))
    finally:
        cleanup(task)


def t279_the_two_gates_that_already_take_any_not_applicable_refuse_the_image_identity() -> None:
    """t-279 K-NA / K-IMG on `source_preflight.assess_freshness` and `execution_fingerprint.build`. Neither ever
    carried the local_source-only rule (they accept `not_applicable` of any stand), so K-NA changes nothing here -
    pinned so a later edit cannot make it stricter by accident. K-IMG: an `unknown` that names the image is NOT a
    `matched`, and both gates need `matched` (error direction toward unknown): they refuse it."""
    from execution_fingerprint import build
    state = {"requirements_revision": "r1"}
    for word, action in (("matched", "reuse"), ("not_applicable", "reuse")):
        check_eq(f"{word}: freshness goes on", assess_freshness(state, state, word, ["i"])["action"], action)
    for word in ("unknown", "mismatched", "image"):
        check_eq(f"{word}: freshness is blocked", assess_freshness(state, state, word, ["i"])["action"], "blocked")
    image = {"profile_id": "api", "timestamp": "2026-10-01T10:00:00Z", "environment_id": "localhost",
             "expected_source_revision": "a" * 40, "evidence_refs": [], "provenance": {},
             "observed_runtime_identity": "image:sha256:" + "b" * 64, "result": "unknown"}
    spec = {"source_revision": "s", "test_files": [], "config_files": [], "dependency_files": []}
    try:
        build({**spec, "runtime_provenance": image})
        said = ""
    except ValueError as exc:
        said = str(exc)
    check_in("fingerprint: `unknown` + the image is refused by the runtime gate", "runtime provenance is unverified", said)
    try:
        build({**spec, "runtime_provenance": dict(image, result="not_applicable", observed_runtime_identity="")})
        said = ""
    except ValueError as exc:
        said = str(exc)
    check_in("fingerprint: `not_applicable` of any stand passes the runtime gate (it fails later, on the empty inputs)",
             "test and configuration inputs must be explicit", said)


def c29_a_gap_by_default_is_not_a_question():
    """T13 (C2-9): the S1 boundary lists a gap the factory itself established (a collector receipt answered host_unreachable) as
    `gap by default`, not as an error - no `S1_GAP` is born; a kind the person answered closes its points as `accepted gap` with the
    person's words; the same material without the carrier is an error as before."""
    import hashlib
    import json
    from source_preflight import check_source_inventory
    url = "https://git.example.com/team/sdk/-/merge_requests/510"
    ref = "sources/SRC-a1/mr-510.json"

    def story(cause, **row):
        media = {"status": "unavailable", "items": [dict({"url": url, "status": "unavailable", "cause": cause}, **row)]}
        task, path = _s1_story("qa-default-", materials={"comments": {"status": "read"}, "attachments": {"status": "read", "items": []},
                                                         "external_media": media})
        receipt = task / "work" / ref
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({"url": url, "error": "host_unreachable"}), encoding="utf-8")
        sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["sources"][0].update(inspection_status="read", inspection_ref="x", inspection_by="role")
        if row.get("probe_ref"):
            data["sources"][0]["materials"]["external_media"]["items"][0]["probe_sha256"] = sha
        path.write_text(json.dumps(data), encoding="utf-8")
        return task, path, sha

    task, path, sha = story("host_unreachable", probe_ref=ref, probe_code="host_unreachable")
    try:
        # the sha of the receipt rides in the row: write it so the integrity check passes
        data = json.loads(path.read_text(encoding="utf-8"))
        data["sources"][0]["materials"]["external_media"]["items"][0]["probe_sha256"] = sha
        path.write_text(json.dumps(data), encoding="utf-8")
        got = check_source_inventory(task, {})
        check_eq("T13 a gap by default raises no error and no question", (got["allowed"], got["errors"]), (True, []))
        check_in("T13 it is a line of `gaps`, with the cause and the carrier", "gap by default: SRC-a1", " | ".join(got["gaps"]))
        check_in("T13 control: the carrier is named", "host_unreachable", " | ".join(got["gaps"]))
    finally:
        cleanup(task)
    task, path, _ = story("host_unreachable")
    try:
        got = check_source_inventory(task, {})
        check_eq("T13 the same material without the carrier is the error it was", got["allowed"], False)
        check_in("T13 and names the door", "accept-gap", " ".join(got["errors"]))
        (task / "work" / "gap-classes.json").write_text(json.dumps({"schema_version": 1, "classes": [
            {"id": "GC-1", "cause": "host_unreachable", "words": "go on without what we cannot reach", "at": "2026-10-16T09:00:00+00:00"}]}),
            encoding="utf-8")
        got = check_source_inventory(task, {})
        check_eq("T13 a kind the person answered closes it: allowed", got["allowed"], True)
        line = " | ".join(got["gaps"])
        check_in("T13 as an `accepted gap` with the person's words", "accepted gap: SRC-a1", line)
        check_in("T13 and whose answer, when", "GC-1 of 2026-10-16", line)
    finally:
        cleanup(task)


if __name__ == "__main__":
    main()
