"""B-172 piece P1: an accepted source gap closes only the points a person was shown.

The point model (`gap_points`), `completeness()` computed from it, `record_gap_acceptance` and the
`accept-gap` CLI. Written in the order the change was made: the equivalence with the old
`completeness()` was fixed FIRST (section I3, expected values written by hand before any code
changed), the rest after.
"""
import hashlib
import json
import random
import re
import sys
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project, run_script

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import source_inventory as SI  # noqa: E402

MATERIAL_KINDS = ("comments", "attachments", "external_media")
OLD_KEYS = ("complete", "gate_blocked", "pending", "unavailable", "incomplete_materials",
            "unavailable_materials", "accepted_gaps", "review_missing", "unreviewed",
            "awaiting_review")


def materials(**blocks):
    """Every block `read`; a keyword replaces one (a str is a status, a dict is the block, None
    removes the block from the record)."""
    out = {kind: {"status": "read", "count": 0} for kind in MATERIAL_KINDS}
    for kind, value in blocks.items():
        if value is None:
            out.pop(kind)
        elif isinstance(value, str):
            out[kind] = {"status": value}
        else:
            out[kind] = value
    return out


def source(sid="SRC-a1", key="APP-1", **over):
    item = {"source_id": sid, "canonical_ref": f"https://jira.example.invalid/browse/{key}",
            "required": True, "relation": "referenced", "status": "read", "relevance": "relevant",
            "inspection_status": "read", "revision": "rev-1", "exclusion_or_error": None,
            "materials": materials()}
    item.update(over)
    if "human_review" not in over:
        item["human_review"] = {"words": "seen", "shown": {"relevance": item["relevance"]}}
    elif over["human_review"] is None:
        item.pop("human_review")
    return item


def inv(*sources):
    return {"schema_version": 1, "sources": list(sources)}


def E(complete, blocked, pending=(), unavailable=(), incomplete=(), unavail_mat=(), accepted=(),
      review_missing=False, unreviewed=(), awaiting=False):
    return {"complete": complete, "gate_blocked": blocked, "pending": list(pending),
            "unavailable": list(unavailable), "incomplete_materials": list(incomplete),
            "unavailable_materials": list(unavail_mat), "accepted_gaps": list(accepted),
            "review_missing": review_missing, "unreviewed": list(unreviewed),
            "awaiting_review": awaiting}


def old_keys(summary):
    return {key: summary[key] for key in OLD_KEYS}


def open_of(summary, sid):
    return summary["open_points"].get(sid, [])


def closed_of(summary, sid):
    return summary["closed_by_person"].get(sid, [])


def attachment(aid="1", status="read", analysis="pending", name="a.png", size=3, **more):
    row = {"attachment_id": aid, "filename": name, "size": size, "status": status,
           "analysis_status": analysis}
    row.update(more)
    return row


def media(url, status="pending", **more):
    row = {"url": url, "status": status, "content_hash": None, "local_ref": None, "error": None}
    row.update(more)
    return row


# --------------------------------------------------------------------------------------------
# I3 - the equivalence, fixed first. The expected values below were written by hand from the
# OLD `completeness()` before source_inventory.py was touched; the run against the unchanged
# module is the first witness. Every inventory has NO usable `gap_acceptance`.
# --------------------------------------------------------------------------------------------
S = "SRC-a1"
I3_CASES = [
    ("a clean read source", inv(source()), E(True, False)),
    ("a source still pending", inv(source(status="pending")), E(False, True, pending=[S])),
    ("a source unavailable",
     inv(source(status="unavailable", relevance="unknown", exclusion_or_error="HTTP 403")),
     E(False, True, unavailable=[S])),
    ("read, inspection receipt pending", inv(source(inspection_status="pending")),
     E(False, True, incomplete=[S])),
    ("read, inspection receipt absent", inv(source(inspection_status=None)),
     E(False, True, incomplete=[S])),
    ("comments block pending", inv(source(materials=materials(comments="pending"))),
     E(False, True, incomplete=[S])),
    ("attachments block unknown", inv(source(materials=materials(attachments="unknown"))),
     E(False, True, incomplete=[S])),
    ("external_media block absent", inv(source(materials=materials(external_media=None))),
     E(False, True, incomplete=[S])),
    ("comments block unavailable", inv(source(materials=materials(comments="unavailable"))),
     E(False, True, unavail_mat=[S])),
    ("external_media block partial", inv(source(materials=materials(external_media="partial"))),
     E(False, True, unavail_mat=[S])),
    ("attachment analysis pending, block read",
     inv(source(materials=materials(attachments={"status": "read", "items": [attachment()]}))),
     E(False, True, incomplete=[S])),
    ("attachment analysis unavailable, block read",
     inv(source(materials=materials(attachments={"status": "read", "items": [
         attachment(analysis="unavailable")]}))),
     E(False, True, unavail_mat=[S])),
    ("attachment analysis skipped, block read",
     inv(source(materials=materials(attachments={"status": "read", "items": [
         attachment(analysis="skipped")]}))),
     E(False, True, unavail_mat=[S])),
    ("attachment with no analysis status",
     inv(source(materials=materials(attachments={"status": "read", "items": [
         {"attachment_id": "1", "filename": "a.png", "status": "read"}]}))),
     E(False, True, incomplete=[S])),
    ("media block pending holding one unavailable item (old: incomplete, NOT unavailable)",
     inv(source(materials=materials(external_media={"status": "pending", "items": [
         media("https://share.example.invalid/x.mp4", "unavailable")]}))),
     E(False, True, incomplete=[S])),
    ("media block unavailable holding one pending item (old: unavailable only)",
     inv(source(materials=materials(external_media={"status": "unavailable", "items": [
         media("https://share.example.invalid/x.mp4", "pending")]}))),
     E(False, True, unavail_mat=[S])),
    ("media block read holding one unavailable item (old never reads media items)",
     inv(source(materials=materials(external_media={"status": "read", "items": [
         media("https://share.example.invalid/x.mp4", "unavailable")]}))),
     E(True, False)),
    ("an excluded source owes nothing, a kept clean one passes",
     inv(source(),
         source("SRC-b2", "APP-2", status="excluded", relevance="not_relevant",
                inspection_status="pending",
                materials=materials(attachments={"status": "read", "items": [
                    attachment(analysis="unavailable"), attachment("2", analysis="pending")]}))),
     E(True, False)),
    ("relevance pending on a read source", inv(source(relevance="pending")),
     E(False, True, pending=[S])),
    ("relevance unknown on a read source", inv(source(relevance="unknown")),
     E(False, True, unavailable=[S])),
    ("no source at all", inv(), E(False, True)),
    ("a blank-words acceptance stops nothing",
     inv(source(status="unavailable", relevance="unknown", gap_acceptance={"words": "   "})),
     E(False, True, unavailable=[S])),
    ("one source per list",
     inv(source("SRC-a1", "APP-1", status="pending"),
         source("SRC-a2", "APP-2", status="unavailable", relevance="unknown"),
         source("SRC-a3", "APP-3", inspection_status="pending"),
         source("SRC-a4", "APP-4", materials=materials(comments="partial"))),
     E(False, True, pending=["SRC-a1"], unavailable=["SRC-a2"], incomplete=["SRC-a3"],
       unavail_mat=["SRC-a4"])),
    ("nobody has reviewed the decisions yet", inv(source(human_review=None)),
     E(True, True, review_missing=True, awaiting=True)),
    ("a source found after the review is not a silent pass",
     inv(source(), source("SRC-b2", "APP-2", human_review=None)),
     E(True, False, unreviewed=["SRC-b2"])),
    ("a source that is not required is ignored",
     inv(source(), source("SRC-b2", "APP-2", required=False, status="pending")),
     E(True, False)),
    ("status excluded but relevance relevant owes nothing either way",
     inv(source(status="excluded")), E(True, False)),
]


def old_completeness(inventory):
    """The pre-change `completeness()`, frozen verbatim (git HEAD of 30.09, source_inventory.py
    :904-977, minus the docstring). The random comparison below runs against it."""
    pending, unavailable, incomplete_materials, unavailable_materials = [], [], [], []
    accepted_gaps, unreviewed = [], []
    required_sources = [item for item in inventory.get("sources", []) if item.get("required")]
    for item in required_sources:
        source_id = item.get("source_id")
        if not SI._reviewed(item):
            unreviewed.append(source_id)
        if item.get("status") == "excluded" and item.get("relevance") == "not_relevant":
            continue
        found = {"pending": False, "source": False, "incomplete": False, "materials": False}
        if item.get("status") == "pending" or item.get("relevance") == "pending":
            found["pending"] = True
        elif item.get("status") == "unavailable" or item.get("relevance") == "unknown":
            found["source"] = True
        if item.get("status") == "read":
            if item.get("inspection_status") != "read":
                found["incomplete"] = True
            materials_ = item.get("materials") or {}
            for kind in ("comments", "attachments", "external_media"):
                material_status = (materials_.get(kind) or {}).get("status")
                if material_status in {"pending", "unknown", None}:
                    found["incomplete"] = True
                elif material_status in {"unavailable", "partial"}:
                    found["materials"] = True
            for receipt in (materials_.get("attachments") or {}).get("items") or []:
                if receipt.get("analysis_status") in {"pending", "unknown", None}:
                    found["incomplete"] = True
                elif receipt.get("analysis_status") in {"unavailable", "skipped"}:
                    found["materials"] = True
        if not any(found.values()):
            continue
        if SI._gap_accepted(item):
            accepted_gaps.append(source_id)
            continue
        if found["pending"]:
            pending.append(source_id)
        if found["source"]:
            unavailable.append(source_id)
        if found["incomplete"]:
            incomplete_materials.append(source_id)
        if found["materials"]:
            unavailable_materials.append(source_id)
    incomplete_materials = sorted(set(incomplete_materials))
    unavailable_materials = sorted(set(unavailable_materials))
    accepted_gaps = sorted(set(accepted_gaps))
    review_missing = bool(required_sources) and len(unreviewed) == len(required_sources)
    blocking = bool(pending or unavailable or incomplete_materials or unavailable_materials)
    return {"complete": bool(required_sources) and not blocking and not accepted_gaps,
            "gate_blocked": not required_sources or blocking or review_missing,
            "pending": pending, "unavailable": unavailable,
            "incomplete_materials": incomplete_materials,
            "unavailable_materials": unavailable_materials,
            "accepted_gaps": accepted_gaps,
            "review_missing": review_missing,
            "unreviewed": [] if review_missing else sorted(set(unreviewed)),
            "awaiting_review": review_missing and not any(
                item.get("relevance") == "pending" for item in required_sources)}


def random_source(rng, n):
    statuses = ["read", "read", "pending", "unavailable", "excluded"]
    relevances = ["relevant", "relevant", "pending", "unknown", "not_relevant"]
    blocks = ["read", "read", "pending", "unknown", "unavailable", "partial", None]
    item_status = ["read", "pending", "unavailable", "skipped", "unknown", "partial", None]
    item = {"source_id": f"SRC-{n:04x}", "canonical_ref": f"https://jira.example.invalid/browse/R-{n}",
            "required": rng.random() < 0.9, "status": rng.choice(statuses),
            "relevance": rng.choice(relevances), "inspection_status": rng.choice(
                ["read", "read", "pending", "unknown", None]),
            "exclusion_or_error": rng.choice([None, "HTTP 403"]), "revision": "r"}
    mats = {}
    for kind in MATERIAL_KINDS:
        choice = rng.choice(blocks)
        if choice is None:
            if rng.random() < 0.5:
                continue
            mats[kind] = {}
            continue
        mats[kind] = {"status": choice}
    for kind in ("attachments", "external_media"):
        if kind in mats and rng.random() < 0.7:
            rows = []
            for i in range(rng.randint(0, 3)):
                row = {"status": rng.choice(item_status)}
                if kind == "attachments":
                    row.update(attachment_id=str(rng.randint(1, 3)), filename=f"f{i}.png")
                    analysis = rng.choice(item_status)
                    if analysis is not None:
                        row["analysis_status"] = analysis
                else:
                    row["url"] = f"https://h.example.invalid/{rng.randint(1, 3)}"
                rows.append(row)
            mats[kind]["items"] = rows
    item["materials"] = mats
    if rng.random() < 0.8:
        item["human_review"] = {"words": "seen", "shown": {"relevance": item["relevance"]}}
    if rng.random() < 0.15:
        item["gap_acceptance"] = {"words": rng.choice(["", "  "])}
    return item


def part_i3():
    for label, inventory, expected in I3_CASES:
        check_eq("I3 old result kept: " + label, old_keys(SI.completeness(inventory)), expected)
    rng = random.Random(172)
    mismatches, mismatches_closed = [], []
    for n in range(1500):
        inventory = inv(*[random_source(rng, n * 4 + i) for i in range(rng.randint(1, 3))])
        want = old_completeness(inventory)
        got, got_closed = old_keys(SI.completeness(inventory)), old_keys(SI.completeness(inventory, s1_closed=True))
        if got != want:
            mismatches.append((n, got, want))
        if got_closed != want:
            mismatches_closed.append((n, got_closed, want))
    check_eq("I3 1500 random inventories with no usable acceptance equal the frozen old function",
             mismatches[:1], [])
    check_eq("I3 and the same 1500 with s1_closed=True (t-151 edge: the flag changes nothing without an acceptance)",
             mismatches_closed[:1], [])


# --------------------------------------------------------------------------------------------
# fixtures shaped like the cmp1 inventory (TP1-13797, 30.09), nothing copied from it
# --------------------------------------------------------------------------------------------
def local_norm(url):
    return url.replace("\\_", "_").replace("\\", "")


def mid(url):
    """The expected id of an external material, computed here and not by the module."""
    return "media:" + hashlib.sha256(local_norm(url).encode("utf-8")).hexdigest()[:16]


SP_URL = ("https://share.example.invalid/:v:/r/sites/Team/Shared%20Documents/Demo/"
          "Demo-20260731-Meeting%20Recording.mp4?d=w0&csf=1&web=1&e=abc&xsdata=" + "A" * 1300
          + "&ovuser=b41b%2CPerson%40example.invalid")
MR510 = "https://git.example.invalid/team/sdk/-/merge_requests/510"
MR1522 = "https://git.example.invalid/team/ui/-/merge_requests/1522"
MR3890_ESCAPED = "https://git.example.invalid/team/app/-/merge\\_requests/3890"
MR3890 = "https://git.example.invalid/team/app/-/merge_requests/3890"
MR3758 = "https://git.example.invalid/team/app/-/merge_requests/3758"
LEGACY_WORDS = ("Go on without the demo recording and without the attachment you cannot fetch. "
                "The four merge-request links are reachable precedents: read them.")
TASK, PREC, EPIC = "SRC-a9a3", "SRC-606b", "SRC-0eaf"


def cmp1_inventory(legacy=True):
    """Two kept sources, both with the inspection receipt still pending; the task has a recording it
    cannot open, its precedent has one unavailable and three partial merge-request items; a third
    source is left out. With `legacy`, both carry the whole-source acceptance the old recorder wrote."""
    task = source(TASK, "TASK-1", relation="task", inspection_status="pending", revision="rev-t",
                  materials=materials(external_media={"status": "unavailable", "count": 2, "items": [
                      media(SP_URL, "unavailable", cause="auth_required",
                            error="auth_required: SSO login page"),
                      media("https://jira.example.invalid/browse/PREC-1", "read",
                            error="collected as its own source", local_ref="sources/x")]}))
    prec = source(PREC, "PREC-1", inspection_status="pending", revision="rev-p",
                  materials=materials(
                      attachments={"status": "read", "count": 1, "items": [attachment("6348", "read", "read")]},
                      external_media={"status": "unavailable", "count": 4, "items": [
                          media(MR510, "unavailable", cause="auth_required"),
                          media(MR1522, "partial", cause="partial_route"),
                          media(MR3890_ESCAPED, "partial", cause="partial_route"),
                          media(MR3758, "partial", cause="partial_route")]}))
    left = source(EPIC, "EPIC-1", status="excluded", relevance="not_relevant", inspection_status="pending",
                  materials=materials(attachments={"status": "unknown", "items": []}))
    if legacy:
        task["gap_acceptance"] = {"words": LEGACY_WORDS, "by": "human", "at": "2026-09-30T03:58:02Z",
                                  "accepted": ["materials not inspected", "materials unavailable: " + SP_URL]}
        prec["gap_acceptance"] = {"words": LEGACY_WORDS, "by": "human", "at": "2026-09-30T03:58:02Z",
                                  "accepted": ["materials not inspected", "materials unavailable: " + MR510]}
    return inv(left, task, prec)


_COUNTER = [0]
_TMP = []


def stored(inventory):
    """Write an inventory to a fresh work/ folder; return the path of source-inventory.json."""
    if not _TMP:
        _TMP.append(temp_project("qa-gap-points-"))
    _COUNTER[0] += 1
    path = _TMP[0] / f"case{_COUNTER[0]}" / "work" / "source-inventory.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def by_source(inventory, sid):
    return next(s for s in inventory["sources"] if s["source_id"] == sid)


def refused(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    return None


def ids_of(item):
    return [p["id"] for p in SI.gap_points(item)]


# --------------------------------------------------------------------------------------------
# R1 / G1 / I4 - the points
# --------------------------------------------------------------------------------------------
def part_points():
    u1, u2, u3, u4, u5 = (f"https://share.example.invalid/{n}.mp4" for n in "abcde")
    item = source(inspection_status="pending", materials=materials(
        comments="pending",
        attachments={"status": "unavailable", "items": [
            attachment("11", "read", "unavailable", "a.png"), attachment("12", "read", "skipped", "b.png"),
            attachment("13", "read", "pending", "c.png")]},
        external_media={"status": "partial", "items": [
            media(u1, "unavailable"), media(u2, "partial"), media(u3, "skipped"), media(u4, "read"),
            media(u5, "pending"), {"url": "https://share.example.invalid/f.mp4"}]}))
    points = {p["id"]: p for p in SI.gap_points(item)}
    check_eq("R1 the ids of a source with every kind of point",
             sorted(points),
             sorted(["source:not_inspected", "comments:block", "attachment:11", "attachment:12",
                     "attachment:13", mid(u1), mid(u2), mid(u3)]))
    check_eq("R1 classes: what the factory has not done is work, what the world did not give is a gap",
             {pid: p["class"] for pid, p in points.items()},
             {"source:not_inspected": "work", "comments:block": "work", "attachment:11": "gap",
              "attachment:12": "gap", "attachment:13": "work", mid(u1): "gap", mid(u2): "gap", mid(u3): "gap"})
    check("G1 an item that is read, pending or has no status explains nothing",
          not any(mid(u) in points for u in (u4, u5)) and len(points) == 8)
    check("G1 a block explained by an item gets no block point of its own",
          "attachments:block" not in points and "external_media:block" not in points)
    check_eq("R1 every point has exactly the documented keys",
             sorted(points["attachment:11"]), ["class", "id", "kind", "name", "text"])
    check_eq("R1 the media point's name is the normalized URL", points[mid(u1)]["name"], u1)
    check_eq("R1 source-level points",
             [(p["id"], p["class"]) for p in SI.gap_points(source(status="pending"))],
             [("source:pending", "work")])
    check_eq("R1 an unavailable source is a gap and names its reason",
             [(p["id"], p["class"], p["text"]) for p in SI.gap_points(
                 source(status="unavailable", relevance="unknown", exclusion_or_error="HTTP 403"))],
             [("source:unavailable", "gap", "unavailable: HTTP 403")])
    check_eq("R1 an excluded source has no points", SI.gap_points(
        source(status="excluded", relevance="not_relevant", inspection_status="pending")), [])
    check_eq("G1 a media block still `pending` gives its block point and NO media point, "
             "however its items stand",
             [(p["id"], p["class"]) for p in SI.gap_points(source(materials=materials(
                 external_media={"status": "pending", "items": [media(u1, "unavailable")]})))],
             [("external_media:block", "work")])
    for label, block in (
            ("empty items", {"status": "unavailable", "items": []}),
            ("every item read", {"status": "unavailable", "items": [media(u1, "read"), media(u2, "read")]}),
            ("items still pending", {"status": "partial", "items": [media(u1, "pending")]}),
            ("an item with no status", {"status": "unavailable", "items": [{"url": u1}]})):
        got = [(p["id"], p["class"]) for p in SI.gap_points(source(materials=materials(external_media=block)))]
        check_eq(f"I4 a block unavailable/partial with {label} is one gap point, never a silent pass",
                 got, [("external_media:block", "gap")])
    check_eq("I4 the same for an attachments block with no item",
             [(p["id"], p["class"]) for p in SI.gap_points(source(materials=materials(
                 attachments={"status": "unavailable", "items": []})))],
             [("attachments:block", "gap")])
    check_eq("I4 an attachment with no status at all is work, not a pass",
             [(p["id"], p["class"]) for p in SI.gap_points(source(materials=materials(
                 attachments={"status": "read", "items": [{"attachment_id": "7", "filename": "x.png"}]})))],
             [("attachment:7", "work")])


def part_identity():
    def attachments_of(*rows):
        return source(materials=materials(attachments={"status": "read", "items": list(rows)}))
    a = {"filename": "a.png", "size": 1, "status": "read", "analysis_status": "unavailable"}
    b = {"filename": "b.png", "size": 1, "status": "read", "analysis_status": "unavailable"}
    ids = ids_of(attachments_of(a, b))
    check("I4 two attachments with a missing id get two different ids",
          len(ids) == 2 and len(set(ids)) == 2)
    check("I4 and the id says it is a made-up one: position and a hash of name and size",
          all(re.fullmatch(r"attachment:unknown:\d:[0-9a-f]{12}", i) for i in ids))
    check_eq("I4 two attachments with the very same name and size still stay two points",
             len(set(ids_of(attachments_of(dict(a), dict(a))))), 2)
    check_eq("I4 two attachments whose id is the string `unknown` stay two points",
             len(set(ids_of(attachments_of(dict(a, attachment_id="unknown"), dict(b, attachment_id="unknown"))))), 2)
    check_eq("I4 one id on two receipts is not one material",
             len(set(ids_of(attachments_of(dict(a, attachment_id="5"), dict(b, attachment_id="5"))))), 2)
    check_eq("R1 a real, unique id is the id", ids_of(attachments_of(dict(a, attachment_id="5"))), ["attachment:5"])
    check_eq("R1 the ids are stable between two reads",
             ids_of(attachments_of(a, b)), ids_of(attachments_of(a, b)))
    odd = dict(a, attachment_id="9", filename="caf\u00e9-\u4e2d\u6587.png")
    point = SI.gap_points(attachments_of(odd))[0]
    check("I4 a non-ASCII filename is a point with the file's name in it",
          point["id"] == "attachment:9" and point["name"] == odd["filename"] and odd["filename"] in point["text"])

    def media_block(*rows, status="unavailable"):
        return source(materials=materials(external_media={"status": status, "items": list(rows)}))
    both = ids_of(media_block(media(MR3890_ESCAPED, "unavailable"), media(MR3890, "unavailable")))
    check_eq("G1 the escaped and the plain spelling of one URL are ONE point", both, [mid(MR3890)])
    check_eq("G1 it is open when only one of its spellings is",
             ids_of(media_block(media(MR3890_ESCAPED, "read"), media(MR3890, "unavailable"))), [mid(MR3890)])
    check_eq("G1 and the point exists only for the open spelling, a block with both read is the block point",
             ids_of(media_block(media(MR3890_ESCAPED, "read"), media(MR3890, "read"))), ["external_media:block"])
    check_eq("I4 two items with no URL are two points",
             len(set(ids_of(media_block({"status": "unavailable"}, {"status": "unavailable"})))), 2)
    long_point = SI.gap_points(media_block(media(SP_URL, "unavailable")))[0]
    check("I4 a 1.4 KB URL gives a short id and a text of at most 120 characters",
          len(SP_URL) > 1300 and long_point["id"] == mid(SP_URL) and len(long_point["id"]) == 22
          and len(long_point["text"]) <= 120)
    check("R1 that text names the host and the file, not the query string with a login in it",
          "share.example.invalid" in long_point["text"] and "Meeting Recording.mp4" in long_point["text"]
          and "ovuser" not in long_point["text"] and "SRC-" not in long_point["text"])
    texts = {n: SI.gap_points(media_block(media("https://h.example.invalid/" + "x" * n, "unavailable")))[0]["text"]
             for n in (60, 71, 72, 400)}
    check_eq("R1 the text limit AT the limit: 120 characters, kept whole",
             (len(texts[71]), "..." in texts[71], len(texts[60])), (120, False, 109))
    check_eq("R1 the text limit BEYOND it: cut to 120, and it says it was cut",
             [(len(texts[n]), texts[n].endswith("...: unavailable") or "..." in texts[n]) for n in (72, 400)],
             [(120, True), (120, True)])
    media_url_text = SI.gap_points(media_block(media(MR510, "unavailable")))[0]["text"]
    check_eq("R1 a merge request reads as its host, its project path, `merge_requests` and its number",
             media_url_text, "external material git.example.invalid/team/sdk/-/merge_requests/510: unavailable")


# --------------------------------------------------------------------------------------------
# the cmp1-shaped story: the DoD key
# --------------------------------------------------------------------------------------------
def part_cmp1():
    summary = SI.completeness(cmp1_inventory())
    check("cmp1 the gate is blocked", summary["gate_blocked"])
    check_eq("cmp1 blocked on the inspection receipt of both kept sources",
             summary["incomplete_materials"], sorted([TASK, PREC]))
    check_eq("cmp1 the precedent's partial merge requests still block", summary["unavailable_materials"], [PREC])
    check_eq("cmp1 the task's recording point is closed by the person's word",
             closed_of(summary, TASK), [mid(SP_URL)])
    check_eq("cmp1 the task's only open point is the inspection", open_of(summary, TASK),
             ["source:not_inspected"])
    check_eq("cmp1 the precedent's accepted point is the unavailable merge request only",
             closed_of(summary, PREC), [mid(MR510)])
    check_eq("cmp1 its three partial merge requests are open, the escaped spelling included",
             sorted(open_of(summary, PREC)),
             sorted(["source:not_inspected", mid(MR1522), mid(MR3890), mid(MR3758)]))
    check_eq("cmp1 both kept sources are in accepted_gaps (a source in accepted_gaps and blocking)",
             summary["accepted_gaps"], sorted([TASK, PREC]))
    check("cmp1 an excluded source stays out of everything",
          EPIC not in summary["incomplete_materials"] + summary["accepted_gaps"]
          and EPIC not in summary["open_points"])
    check("cmp1 the old keys are all still there",
          all(key in summary for key in OLD_KEYS))
    check_eq("cmp1 without acceptance nothing is closed", SI.completeness(
        cmp1_inventory(legacy=False))["accepted_gaps"], [])


# --------------------------------------------------------------------------------------------
# R4 / G4 / G6 / R3 - recording
# --------------------------------------------------------------------------------------------
def part_record():
    path = stored(cmp1_inventory(legacy=False))
    inventory = SI.record_gap_acceptance(path, [TASK], "go on without the recording")
    task = by_source(inventory, TASK)
    entries = task["gap_acceptance"]["accepted_points"]
    check_eq("R4 without points: every open gap point of the source, and only those",
             [e["id"] for e in entries], [mid(SP_URL)])
    check("R4 never a work-class point: the inspection stays open",
          "source:not_inspected" in open_of(SI.completeness(inventory), TASK))
    check_eq("R3 a stored point carries its class, text, words, revision and whether it was shown",
             (entries[0]["class"], entries[0]["kind"], entries[0]["words"], entries[0]["revision"],
              entries[0]["shown"], "Meeting Recording.mp4" in entries[0]["text"]),
             ("gap", "media", "go on without the recording", "rev-t", False, True))
    check("R3 the display strings are the point texts, and never `materials not inspected`",
          task["gap_acceptance"]["accepted"] == [entries[0]["text"]]
          and "materials not inspected" not in task["gap_acceptance"]["accepted"])
    check_eq("R3 words/by/at stay for the old readers",
             (task["gap_acceptance"]["words"], task["gap_acceptance"]["by"]), ("go on without the recording", "human"))

    # a source whose only open points are the role's work
    only_work = stored(inv(source(TASK, "TASK-1", inspection_status="pending")))
    message = refused(SI.record_gap_acceptance, only_work, [TASK], "go on")
    check("R4 a source with only work points is refused", message is not None)
    check("R4 and the refusal names them as the role's work",
          message and "the role's work" in message and "materials not inspected" in message
          and "has no open gap to accept" in message)
    check_in("R4 a source with no open point at all keeps the old refusal",
             "has no open gap to accept", refused(SI.record_gap_acceptance, stored(inv(source())), ["SRC-a1"], "go on"))
    check("R4 blank words are refused", refused(SI.record_gap_acceptance, path, [TASK], "  ") is not None)
    check("R4 an unknown source is refused", refused(SI.record_gap_acceptance, path, ["SRC-nope"], "go on") is not None)
    check("R4 nothing was written by any refusal", load(only_work)["sources"][0].get("gap_acceptance") is None)

    # with points
    path = stored(cmp1_inventory(legacy=False))
    ids = [mid(MR1522), mid(MR3890)]
    inventory, report = SI.apply_gap_acceptance(path, [PREC], "the partial merge requests are enough",
                                                points=ids)
    check_eq("R4 with points: exactly those points", [e["id"] for e in by_source(
        inventory, PREC)["gap_acceptance"]["accepted_points"]], ids)
    check_eq("R4 stored as shown to the person", by_source(inventory, PREC)["gap_acceptance"]["accepted_points"][0]["shown"], True)
    after = SI.completeness(inventory)
    check("R4 the others stay open (510, 3758, the inspection)",
          sorted(open_of(after, PREC)) == sorted([mid(MR510), mid(MR3758), "source:not_inspected"]))
    # G6: an id that is no longer open is printed, the call is not refused
    fresh = cmp1_inventory(legacy=False)
    by_source(fresh, PREC)["materials"]["external_media"]["items"][0]["status"] = "read"  # 510 arrived meanwhile
    path2 = stored(fresh)
    inventory, report = SI.apply_gap_acceptance(path2, [PREC], "go on", points=[mid(MR510), mid(MR3758)])
    check_eq("G6 an id no longer open is reported, not refused", report["no_longer_open"], {PREC: [mid(MR510)]})
    check_eq("G6 and the open ones are recorded", [e["id"] for e in by_source(
        inventory, PREC)["gap_acceptance"]["accepted_points"]], [mid(MR3758)])
    inventory, report = SI.apply_gap_acceptance(path2, [PREC], "go on", points=[mid(MR510)])
    check("G6 when every named id is no longer open nothing is recorded and nothing is refused",
          report["accepted"] == {} and report["no_longer_open"] == {PREC: [mid(MR510)]})
    message = refused(SI.record_gap_acceptance, path, [PREC], "go on", points=["media:0000000000000000"])
    check("G6 an id that never existed on the source is refused",
          message is not None and "has no point media:0000000000000000" in message)
    check("G6 with the valid ids and their texts",
          message and mid(MR510) in message and "git.example.invalid/team/sdk/-/merge_requests/510" in message
          and "source:not_inspected" in message and "materials not inspected" in message)
    check("R4 the refusal names the command",
          message and "accept-gap --output" in message and "--point" in message)
    check("R7 an empty id is refused", refused(SI.record_gap_acceptance, path, [PREC], "go on", points=[""]) is not None)
    check("R7 a blank list is refused", refused(SI.record_gap_acceptance, path, [PREC], "go on", points=[]) is not None)
    check("R7 a duplicate id is refused", refused(SI.record_gap_acceptance, path, [PREC], "go on",
                                                  points=[mid(MR510), mid(MR510)]) is not None)
    check("R7 points of two sources at once are refused",
          refused(SI.record_gap_acceptance, path, [PREC, TASK], "go on", points=[mid(MR510)]) is not None)
    check_eq("R4 a refusal writes nothing: the file still holds only the first call's two points",
             [e["id"] for e in by_source(load(path), PREC)["gap_acceptance"]["accepted_points"]], ids)

    # G4: a work-class id needs the shown text
    path = stored(cmp1_inventory(legacy=False))
    message = refused(SI.record_gap_acceptance, path, [TASK], "go on without inspecting it",
                      points=["source:not_inspected"])
    check("G4 a work-class point without the shown text is refused", message is not None)
    check("G4 and the refusal says what is expected",
          message and "--shown-text" in message and "source:not_inspected" in message)
    check("G4 nothing was written", by_source(load(path), TASK).get("gap_acceptance") is None)
    check("G4 a blank shown text is no shown text",
          refused(SI.record_gap_acceptance, path, [TASK], "go on", points=["source:not_inspected"],
                  shown_text="   ") is not None)
    inventory, report = SI.apply_gap_acceptance(path, [TASK], "go on without inspecting it",
                                                points=["source:not_inspected"],
                                                shown_text="TASK-1 was not inspected by the factory")
    entry = by_source(inventory, TASK)["gap_acceptance"]["accepted_points"][0]
    check_eq("G4 stored with the sentence and marked the factory's own",
             (entry["class"], entry["factory_owned"], entry["shown_text"], entry["shown"]),
             ("work", True, "TASK-1 was not inspected by the factory", True))
    check_eq("G4 reported so that the caller files the finding", [f["id"] for f in report["factory_owned"]],
             ["source:not_inspected"])
    check("G4 it closes that point, and only with the stored sentence",
          "source:not_inspected" not in SI.completeness(inventory)["open_points"].get(TASK, []))
    forged = json.loads(json.dumps(inventory))
    del by_source(forged, TASK)["gap_acceptance"]["accepted_points"][0]["shown_text"]
    check("G4 a stored work-class point with no shown text closes nothing",
          "source:not_inspected" in open_of(SI.completeness(forged), TASK))

    # R3: a second acceptance merges
    path = stored(cmp1_inventory(legacy=False))
    SI.record_gap_acceptance(path, [PREC], "first words", points=[mid(MR1522)])
    inventory = SI.record_gap_acceptance(path, [PREC], "second words", points=[mid(MR3758)])
    entries = {e["id"]: e for e in by_source(inventory, PREC)["gap_acceptance"]["accepted_points"]}
    check_eq("R3 a second acceptance merges", sorted(entries), sorted([mid(MR1522), mid(MR3758)]))
    check_eq("R3 each point keeps its own words", (entries[mid(MR1522)]["words"], entries[mid(MR3758)]["words"]),
             ("first words", "second words"))
    check_eq("R3 the latest words go to the old readers", by_source(inventory, PREC)["gap_acceptance"]["words"],
             "second words")
    inventory = SI.record_gap_acceptance(path, [PREC], "third words", points=[mid(MR1522)])
    entries = {e["id"]: e for e in by_source(inventory, PREC)["gap_acceptance"]["accepted_points"]}
    check_eq("R3 an acceptance still in force is never overwritten", entries[mid(MR1522)]["words"], "first words")

    # a legacy acceptance survives the first point acceptance recorded on top of it
    path = stored(cmp1_inventory(legacy=True))
    inventory = SI.record_gap_acceptance(path, [PREC], "and the third one too", points=[mid(MR3758)])
    closed = closed_of(SI.completeness(inventory), PREC)
    check_eq("R5 the point the legacy record closed stays closed after a point acceptance is added",
             sorted(closed), sorted([mid(MR510), mid(MR3758)]))
    migrated = {e["id"]: e for e in by_source(inventory, PREC)["gap_acceptance"]["accepted_points"]}
    check("R5 and it is stored as a legacy, not-shown point with the old words",
          migrated[mid(MR510)]["legacy"] is True and migrated[mid(MR510)]["shown"] is False
          and migrated[mid(MR510)]["words"] == LEGACY_WORDS)
    check("R5 a legacy record never becomes a work-class point",
          all(e["class"] == "gap" for e in migrated.values() if e.get("legacy")))


# --------------------------------------------------------------------------------------------
# R5 - a legacy acceptance (no accepted_points)
# --------------------------------------------------------------------------------------------
def legacy_source(accepted, materials_=None, **over):
    fields = {"inspection_status": "pending", "materials": materials_ or materials(
        external_media={"status": "unavailable", "items": [
            media(MR510, "unavailable"), media(MR1522, "unavailable")]})}
    fields.update(over)
    item = source(**fields)
    gap = {"words": "go on without it", "by": "human", "at": "t"}
    if accepted is not None:
        gap["accepted"] = accepted
    item["gap_acceptance"] = gap
    return item


def part_legacy():
    def open_ids(item):
        return SI.completeness(inv(item))["open_points"].get("SRC-a1", [])

    item = legacy_source(["materials not inspected", "materials unavailable: " + MR510])
    check_eq("R5 `materials not inspected` closes nothing, the exact name closes its point only",
             sorted(open_ids(item)), sorted(["source:not_inspected", mid(MR1522)]))
    check_eq("R5 a legacy string that is only `materials not inspected` closes nothing at all",
             sorted(open_ids(legacy_source(["materials not inspected"]))),
             sorted(["source:not_inspected", mid(MR510), mid(MR1522)]))
    check_eq("R5 `not read yet` and a string this code does not know close nothing",
             sorted(open_ids(legacy_source(["not read yet", "go on without everything"]))),
             sorted(["source:not_inspected", mid(MR510), mid(MR1522)]))
    check_eq("R5 several names in one string close each of them",
             sorted(open_ids(legacy_source(["materials unavailable: " + MR510 + ", " + MR1522]))),
             ["source:not_inspected"])
    check_eq("R5 a partial extra name in the string does not matter, the wrong name closes nothing",
             sorted(open_ids(legacy_source(["materials unavailable: https://git.example.invalid/other"]))),
             sorted(["source:not_inspected", mid(MR510), mid(MR1522)]))
    check_eq("R5 the escaped spelling written by the old recorder closes the point of the URL",
             open_ids(legacy_source(["materials unavailable: " + MR3890_ESCAPED], materials(
                 external_media={"status": "unavailable", "items": [media(MR3890_ESCAPED, "unavailable")]}),
                 inspection_status="read")), [])

    # G9: a name that is not unique closes nothing
    twin = materials(attachments={"status": "read", "items": [
        attachment("1", "read", "unavailable", "same.png"), attachment("2", "read", "read", "same.png")]})
    check_eq("G9 a name shared by two attachments closes nothing",
             open_ids(legacy_source(["materials unavailable: same.png"], twin, inspection_status="read")),
             ["attachment:1"])
    solo = materials(attachments={"status": "read", "items": [
        attachment("1", "read", "unavailable", "same.png"), attachment("2", "read", "read", "other.png")]})
    check_eq("G9 the same name, unique in its source, closes its point",
             open_ids(legacy_source(["materials unavailable: same.png"], solo, inspection_status="read")), [])
    comma = materials(attachments={"status": "read", "items": [
        attachment("1", "read", "unavailable", "a, b.png")]})
    check_eq("I4 a name with `, ` inside that IS a material's exact name closes that material (t-151 item 3)",
             open_ids(legacy_source(["materials unavailable: a, b.png"], comma, inspection_status="read")),
             [])

    # the source-level string, exact equality only
    unavailable = source(status="unavailable", relevance="unknown", exclusion_or_error="HTTP 403",
                         gap_acceptance={"words": "go on", "accepted": ["unavailable: HTTP 403"]})
    check_eq("R5 the source's own legacy text closes it by exact equality",
             SI.completeness(inv(unavailable))["gate_blocked"], False)
    unavailable["gap_acceptance"]["accepted"] = ["unavailable: HTTP 500"]
    check_eq("R5 another text closes nothing", SI.completeness(inv(unavailable))["unavailable"], ["SRC-a1"])

    # words only: accepted absent or empty
    for label, accepted in (("absent", None), ("empty", [])):
        words_only = legacy_source(accepted)
        check_eq(f"R5 words with `accepted` {label}: every gap point closes, the inspection does not",
                 open_ids(words_only), ["source:not_inspected"])
    check("R5 words only never close a work-class point (a source not read yet stays pending)",
          SI.completeness(inv(legacy_source(None, status="pending")))["pending"] == ["SRC-a1"])
    check_eq("R5 words only close a source that is unavailable (a gap)",
             SI.completeness(inv(legacy_source(None, status="unavailable", relevance="unknown",
                                               exclusion_or_error="gone")))["unavailable"], [])
    blank = legacy_source(["unavailable: x"])
    blank["gap_acceptance"]["words"] = " "
    check("R5 blank words close nothing", SI.completeness(inv(blank))["gate_blocked"])
    neighbour = source(materials=materials(external_media={"status": "unavailable", "items": []}),
                       gap_acceptance={"words": "go on without the video"})
    summary = SI.completeness(inv(neighbour))
    check("R5 the neighbour's case: a block with no items closes on words only, passed is not complete",
          not summary["gate_blocked"] and summary["accepted_gaps"] == ["SRC-a1"] and not summary["complete"])


# --------------------------------------------------------------------------------------------
# R6, the position invariant, G3
# --------------------------------------------------------------------------------------------
def part_revision_and_position():
    path = stored(cmp1_inventory(legacy=False))
    SI.record_gap_acceptance(path, [PREC], "the 510 one is gone", points=[mid(MR510)])
    SI.record_gap_acceptance(path, [PREC], "and the inspection was not for us", points=["source:not_inspected"],
                             shown_text="EPIC precedent was not inspected")
    live = load(path)
    check("R6 both accepted points close on the revision they were given on",
          set(closed_of(SI.completeness(live), PREC)) == {mid(MR510), "source:not_inspected"})
    prec = by_source(live, PREC)
    prec["revision"] = "rev-p2"
    after = SI.completeness(live)
    check("R6 a gap-class accepted point persists by id across a new revision",
          mid(MR510) in closed_of(after, PREC))
    check("R6 a work-class accepted point of another revision stops closing",
          "source:not_inspected" in open_of(after, PREC)
          and "source:not_inspected" not in closed_of(after, PREC))
    # the same through update_inventory, the code that keeps the acceptance across a re-collect
    path = stored(cmp1_inventory(legacy=False))
    SI.record_gap_acceptance(path, [PREC], "the 510 one is gone", points=[mid(MR510)])
    SI.record_gap_acceptance(path, [PREC], "not for us", points=["source:not_inspected"], shown_text="not inspected")
    record = json.loads(json.dumps(by_source(load(path), PREC)))
    record["revision"] = "rev-p2"
    record.pop("gap_acceptance")
    result = SI.update_inventory(path, record)
    merged = SI.completeness(result)
    check("R6 update_inventory keeps the acceptance, and only the gap-class point still closes",
          closed_of(merged, PREC) == [mid(MR510)] and "source:not_inspected" in open_of(merged, PREC))
    reaccepted = SI.record_gap_acceptance(path, [PREC], "still not for us", points=["source:not_inspected"],
                                          shown_text="not inspected either")
    check("R6 a lapsed work-class point can be accepted again on the new revision",
          "source:not_inspected" in closed_of(SI.completeness(reaccepted), PREC))

    # position invariant: an excluded source owes nothing, whatever it carries
    left = source(EPIC, "EPIC-1", status="excluded", relevance="not_relevant", inspection_status="pending",
                  gap_acceptance={"words": "go on", "accepted_points": [
                      {"id": "source:not_inspected", "class": "work", "words": "go on", "shown_text": "x",
                       "revision": "rev-1"}]})
    for flag in (False, True):
        summary = SI.completeness(inv(source(), left), s1_closed=flag)
        check_eq(f"position: an excluded source with a stored acceptance owes and reports nothing (s1_closed={flag})",
                 (summary["accepted_gaps"], summary["open_points"], summary["closed_by_person"],
                  summary["gate_blocked"]), ([], {}, {}, False))
    flipped = source(inspection_status="pending", status="read", relevance="relevant",
                     gap_acceptance=left["gap_acceptance"])
    check("position: a source flipped back to kept re-derives its points and the stored acceptance closes again",
          SI.completeness(inv(flipped))["closed_by_person"] == {"SRC-a1": ["source:not_inspected"]}
          and SI.completeness(inv(flipped))["gate_blocked"] is False)
    check("position: with no acceptance the same source is computed by the old lists",
          old_keys(SI.completeness(inv(source(inspection_status="pending"))))
          == old_keys(old_completeness(inv(source(inspection_status="pending")))))
    # I3 with the new flag: no acceptance, no difference
    check("G3 the flag changes nothing for an inventory with no acceptance",
          all(old_keys(SI.completeness(case[1], s1_closed=True)) == case[2] for case in I3_CASES))

    # G3
    legacy = cmp1_inventory(legacy=True)
    new_rule = SI.completeness(legacy)
    old_rule = SI.completeness(legacy, s1_closed=True)
    check("G3 default: the new meaning of a recorded acceptance (blocked)",
          new_rule["gate_blocked"] and new_rule["earlier_rule_line"] == "")
    check_eq("G3 S1 already completed: the old meaning, nothing re-blocks",
             (old_rule["gate_blocked"], old_rule["incomplete_materials"], old_rule["unavailable_materials"],
              old_rule["accepted_gaps"]), (False, [], [], sorted([TASK, PREC])))
    check_eq("G3 and one plain line says so", old_rule["earlier_rule_line"],
             "S1 closed under the earlier acceptance rule: PREC-1, TASK-1 not inspected")
    check_eq("G3 with the sources by id", old_rule["earlier_rule_sources"], sorted([TASK, PREC]))
    with_points = cmp1_inventory(legacy=False)
    path = stored(with_points)
    accepted = SI.record_gap_acceptance(path, [PREC], "just this one", points=[mid(MR510)])
    kept = SI.completeness(accepted, s1_closed=True)
    check("G3 an acceptance recorded with points is a point acceptance under both meanings",
          kept["gate_blocked"] and PREC in kept["incomplete_materials"] and kept["earlier_rule_line"] == "")
    check("G3 a completed story with a word-only legacy acceptance and no unfinished work has no line",
          SI.completeness(inv(source(gap_acceptance={"words": "x", "accepted": []},
                                     materials=materials(comments="unavailable"))),
                          s1_closed=True)["earlier_rule_line"] == "")


# --------------------------------------------------------------------------------------------
# R7 - the CLI
# --------------------------------------------------------------------------------------------
def cli(path, *args):
    proc = run_script("ticket_adapter.py", "accept-gap", "--output", path, *args)
    return proc.returncode, proc.stdout, proc.stderr


def part_cli():
    path = stored(cmp1_inventory(legacy=False))
    code, out, err = cli(path, "--source-id", PREC, "--point", mid(MR1522) + "," + mid(MR3758), "--words", "read them later")
    check_eq("R7 --point with one source: accepted", code, 0)
    check_eq("R7 the output is `accepted: <KEY>: <point texts>`",
             [line for line in out.splitlines() if line.startswith("accepted:")],
             ["accepted: PREC-1: " + "; ".join(p["text"] for p in SI.gap_points(by_source(load(path), PREC))
                                                if p["id"] in (mid(MR1522), mid(MR3758)))])
    check("R7 the output names no SRC- id in the accepted line",
          "SRC-" not in [line for line in out.splitlines() if line.startswith("accepted:")][0])
    code, out, err = cli(path, "--source-id", PREC, "--point", mid(MR1522) + ",media:ffffffffffffffff", "--words", "x")
    check("R7 a foreign id is refused with the valid list", code == 3 and "has no point media:ffffffffffffffff" in err
          and "source:not_inspected" in err and mid(MR510) in err)
    code, out, err = cli(path, "--source-id", PREC, "--point", mid(MR510) + "," + mid(MR510), "--words", "x")
    check("R7 a duplicate id is refused with the valid list", code == 3 and "more than once" in err and mid(MR3890) in err)
    for label, value in (("an empty id", ""), ("a trailing comma", mid(MR510) + ","), ("an empty piece", "a,,b")):
        code, out, err = cli(path, "--source-id", PREC, "--point", value, "--words", "x")
        check(f"R7 {label} is refused, and the refusal lists the valid points",
              code == 3 and "none of them empty" in err and mid(MR510) in err)
    code, out, err = cli(path, "--source-id", PREC + "," + TASK, "--point", mid(MR510), "--words", "x")
    check("R7 --point with two sources is refused, naming the form", code == 3 and "exactly one --source-id" in err)
    code, out, err = cli(path, "--all-unavailable", "--point", mid(MR510), "--words", "x")
    check("R7 --point with --all-unavailable is refused", code == 3 and "exactly one --source-id" in err)
    check("R7 no refusal wrote anything but the first call",
          [e["id"] for e in by_source(load(path), PREC)["gap_acceptance"]["accepted_points"]]
          == [mid(MR1522), mid(MR3758)])

    code, out, err = cli(path, "--source-id", PREC, "--point", "source:not_inspected", "--words", "not for us")
    check("G4 the CLI refuses a work-class point without --shown-text and says what is expected",
          code == 3 and "--shown-text" in err and "sentence the person was shown" in err)
    code, out, err = cli(path, "--source-id", PREC, "--point", "source:not_inspected", "--words", "not for us",
                         "--shown-text", "PREC-1 was not inspected by the factory")
    check_eq("G4 with the shown text it is accepted", code, 0)
    check("G4 and the output says it is the factory's own work and names the finding door",
          "factory-owned: PREC-1:" in out and "project_decisions.py --root <project> add-finding" in out)
    stored_entry = [e for e in by_source(load(path), PREC)["gap_acceptance"]["accepted_points"]
                    if e["id"] == "source:not_inspected"][0]
    check_eq("G4 stored with the sentence, factory-owned", (stored_entry["shown_text"], stored_entry["factory_owned"]),
             ("PREC-1 was not inspected by the factory", True))
    code, out, err = cli(path, "--source-id", PREC, "--point", mid(MR1522), "--words", "x")
    code2, out2, err2 = cli(path, "--source-id", PREC, "--point", mid(MR1522), "--words", "x", "--shown-text", "unused")
    check("G4 a shown text with no work-class point is not stored, and the output says so",
          code2 == 0 and "--shown-text was not stored" in out2)

    # G6 on the CLI: printed, not refused
    live = load(path)
    by_source(live, PREC)["materials"]["external_media"]["items"][0]["status"] = "read"
    path_gone = stored(live)
    code, out, err = cli(path_gone, "--source-id", PREC, "--point", mid(MR510) + "," + mid(MR3758), "--words", "x")
    check("G6 an id no longer open is printed on the CLI and the call succeeds",
          code == 0 and f"not recorded, no longer open: PREC-1: {mid(MR510)}" in out and "accepted: PREC-1:" in out)

    # --all-unavailable: every gap point, never work
    path = stored(cmp1_inventory(legacy=False))
    code, out, err = cli(path, "--all-unavailable", "--words", "go on without all of it")
    check_eq("R7 --all-unavailable is accepted", code, 0)
    done = load(path)
    recorded = {sid: [e["id"] for e in by_source(done, sid)["gap_acceptance"]["accepted_points"]] for sid in (TASK, PREC)}
    check_eq("R7 --all-unavailable records every open gap point of every source that has one",
             recorded, {TASK: [mid(SP_URL)], PREC: [mid(MR510), mid(MR1522), mid(MR3890), mid(MR3758)]})
    check("R7 and never a work-class point: both inspections stay open",
          all("source:not_inspected" in open_of(SI.completeness(done), sid) for sid in (TASK, PREC)))
    check_eq("R7 nothing to accept is said, not an error",
             cli(stored(inv(source())), "--all-unavailable", "--words", "x")[:2], (0, "no open source gap to accept\n"))
    code, out, err = cli(stored(inv(source(TASK, "TASK-1", inspection_status="pending"))), "--source-id", TASK, "--words", "x")
    check("R4 the CLI refuses a source whose only points are the role's work",
          code == 3 and "the role's work" in err)


def part_cli_attachments():
    """R7b (SC2-41, point 2 verify-only): `accept-gap --all-unavailable` records EVERY gap point of EVERY source that has one, on the
    shape of the real ticket TP1-14857 (two screenshots refused for size, two files settled by the factory's policy), mixed
    with a source, an external material and a source that also owes work. A policy skip is settled-but-listed: no point, never
    recorded (FR-3). Mutation m70 (`apply_gap_acceptance` takes only the first point of each source) -> here."""
    ids = {"A": "SRC-r7ba", "B": "SRC-r7bb", "C": "SRC-r7bc", "D": "SRC-r7bd"}
    shots = [attachment("s1", "read", "unavailable", "screenshot-1.png", 93414, analysis_cause="too_large"),
             attachment("s3", "read", "unavailable", "screenshot-3.png", 83997, analysis_cause="too_large")]
    policy = [attachment(f"p{n}", "skipped_by_policy", "skipped_by_policy", name, size, skipped_by_policy="type",
                         reason="skipped_by_policy:type") for n, (name, size) in enumerate((("plan.md", 6023), ("spec.md", 5814)))]
    fine = attachment("ok", "read", "read", "2026-03-11_10h40_43.png", 8533)
    url = "https://share.example.invalid/video-r7b.mp4"
    a = source(ids["A"], "TP1-10937", materials=materials(
        attachments={"status": "read", "count": 5, "items": [shots[0], policy[0], fine, shots[1], policy[1]]}))
    b = source(ids["B"], "B-1", status="unavailable", exclusion_or_error="host unreachable")
    c = source(ids["C"], "C-1", materials=materials(external_media={"status": "unavailable", "count": 1, "items": [
        media(url, "unavailable", cause="auth_required")]}))
    d = source(ids["D"], "D-1", inspection_status="pending", materials=materials(
        attachments={"status": "read", "count": 1, "items": [attachment("d1", "read", "unavailable", "d.png", 5)]}))
    path = stored(inv(a, b, c, d))
    before = SI.completeness(load(path))
    check_eq("R7b the four sources are the ones with an open gap",
             sorted(sid for sid in ids.values() if open_of(before, sid)), sorted(ids.values()))
    code, out, err = cli(path, "--all-unavailable", "--words", "go on without them")
    check_eq("R7b --all-unavailable on the attachments shape is accepted", code, 0)
    done = load(path)
    recorded = {key: [e["id"] for e in by_source(done, sid).get("gap_acceptance", {}).get("accepted_points", [])]
                for key, sid in ids.items()}
    check_eq("R7b it records exactly the gap points: 5 over 4 sources, the two policy skips are not among them",
             recorded, {"A": ["attachment:s1", "attachment:s3"], "B": ["source:unavailable"], "C": [mid(url)], "D": ["attachment:d1"]})
    rows = {r["filename"]: r for r in by_source(done, ids["A"])["materials"]["attachments"]["items"]}
    check_eq("R7b the policy items stay settled-but-listed, untouched",
             [(rows[n]["analysis_status"], rows[n]["reason"]) for n in ("plan.md", "spec.md")], [("skipped_by_policy", "skipped_by_policy:type")] * 2)
    check_in("R7b D's own work (the inspection receipt) stays open", "source:not_inspected", " ".join(open_of(SI.completeness(done), ids["D"])))
    check("R7b no gap point of any source is left open",
          not [p for sid in ids.values() for p in open_of(SI.completeness(done), sid) if p != "source:not_inspected"],
          str({sid: open_of(SI.completeness(done), sid) for sid in ids.values()}))
    check_eq("R7b a second call finds nothing to accept (only D's work is left)", cli(path, "--all-unavailable", "--words", "x")[:2],
             (0, "no open source gap to accept\n"))


# --------------------------------------------------------------------------------------------
# I6 - the refusal the driver routes on
# --------------------------------------------------------------------------------------------
def part_refusal_prefix():
    import story_run
    from source_preflight import check_source_inventory
    root = _TMP[0] / "preflight"
    work = root / "work"
    work.mkdir(parents=True)
    task = source("SRC-aaaa1111", "APP-1", status="unavailable", relevance="unknown", exclusion_or_error="HTTP 403")
    mat = source("SRC-bbbb2222", "APP-2", materials=materials(external_media={
        "status": "unavailable", "items": [media(MR510, "unavailable")]}))
    ok = source("SRC-cccc3333", "APP-3")
    (work / "source-inventory.json").write_text(json.dumps(inv(task, mat, ok)), encoding="utf-8")
    errors = check_source_inventory(root, {})["errors"]
    gap_errors = [e for e in errors if "not accepted by a person" in e]
    check_eq("I6 the driver's regex is the one this test pins",
             story_run.S1_GAP_RE, r"source (?:material )?unavailable and not accepted by a person: (SRC-[0-9a-f]+)")
    found = sorted(i for e in gap_errors for i in re.findall(story_run.S1_GAP_RE, e, re.IGNORECASE))
    check_eq("I6 both refusals still match it and carry the source ids", found, ["SRC-aaaa1111", "SRC-bbbb2222"])
    check("I6 the two prefixes are byte-identical (`source ...` / `source material ...`, id, em dash)",
          any(e.startswith("source unavailable and not accepted by a person: SRC-aaaa1111 \u2014 ")
              for e in gap_errors)
          and any(e.startswith("source material unavailable and not accepted by a person: SRC-bbbb2222 \u2014 ")
                  for e in gap_errors))
    # an accepted point takes the refusal away, an unaccepted one keeps it (the id still travels in it)
    live = json.loads((work / "source-inventory.json").read_text(encoding="utf-8"))
    by_source(live, "SRC-bbbb2222")["gap_acceptance"] = {"words": "go on", "accepted_points": [
        {"id": mid(MR510), "class": "gap", "words": "go on"}]}
    (work / "source-inventory.json").write_text(json.dumps(live), encoding="utf-8")
    after = [e for e in check_source_inventory(root, {})["errors"] if "not accepted by a person" in e]
    check("I6 an accepted point takes its refusal away, the other stays",
          not any("SRC-bbbb2222" in e for e in after) and any("SRC-aaaa1111" in e for e in after))


# --------------------------------------------------------------------------------------------
# G2 - a re-collect of an unchanged revision keeps what the role recorded
# --------------------------------------------------------------------------------------------
class FakeClient:
    base_url = "https://jira.invalid"
    acceptance_criteria_fields = []
    api_version = "2"
    project_keys = []

    def __init__(self, revision="rev-1", description="see https://share.example.invalid/demo.mp4"):
        self.revision, self.description = revision, description

    def issue(self, key):
        return {"key": key, "fields": {"updated": self.revision, "summary": "subject",
                                       "description": self.description, "attachment": []}}

    def all_comments(self, *a):
        return []

    def get_bytes(self, url):
        raise OSError("no bytes in this test")

    def get_json(self, path):
        return {}


def part_reuse():
    work = _TMP[0] / "reuse" / "work"
    output = work / "source-inventory.json"
    client = FakeClient()
    record = SI.collect_jira_source(client, "APP-1", output, fetched_at="2026-09-30T01:00:00Z")
    SI.update_inventory(output, record)
    sid = record["source_id"]
    check("G2 a fresh collect starts pending", record["inspection_status"] == "pending"
          and record["materials"]["external_media"]["items"][0]["status"] == "pending")
    demo = "https://share.example.invalid/demo.mp4"
    SI.record_relevance_assessment(output, sid, "relevant", "read it", "work/evidence/note.json")
    SI.record_external_media(output, sid, demo, "unavailable", "auth_required: SSO login page")
    stored_record = by_source(load(output), sid)
    check("G2 the role has recorded an inspection receipt and an unavailable media item",
          stored_record["inspection_status"] == "read"
          and stored_record["materials"]["external_media"]["status"] == "unavailable")
    again = SI.collect_jira_source(client, "APP-1", output, existing_record=stored_record)
    check_eq("G2 unchanged revision: the inspection receipt is carried over",
             (again["inspection_status"], again["inspection_ref"]), ("read", "work/evidence/note.json"))
    item = again["materials"]["external_media"]["items"][0]
    check_eq("G2 and the media receipt, cause and all", (item["status"], item["cause"]), ("unavailable", "auth_required"))
    check_eq("G2 the media block status follows its items", again["materials"]["external_media"]["status"], "unavailable")
    check_eq("G2 an incomplete source is still re-collected (its media item is rebuilt) yet reports `unchanged`: "
             "same revision, files verify (t-151 item 6)", again["_refresh_result"], "unchanged")
    accepted = dict(stored_record, gap_acceptance={"words": "go on", "accepted": []})
    check("G2 the same with an accepted gap, whatever `completeness` says",
          SI.collect_jira_source(client, "APP-1", output, existing_record=accepted)["inspection_status"] == "read")
    # a read media receipt is carried only while its file is there
    evidence = work / "evidence" / "m.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes(b"what the media said")
    SI.record_external_media(output, sid, demo, "partial", "partial_route: no discussions", "evidence/m.md")
    partial_record = by_source(load(output), sid)
    kept = SI.collect_jira_source(client, "APP-1", output, existing_record=partial_record)
    check_eq("G2 a partial receipt whose file verifies is carried", kept["materials"]["external_media"]["items"][0]["status"], "partial")
    evidence.write_bytes(b"changed on disk")
    reset = SI.collect_jira_source(client, "APP-1", output, existing_record=partial_record)
    check_eq("G2 a receipt whose file no longer matches is reset to pending",
             reset["materials"]["external_media"]["items"][0]["status"], "pending")
    check("G2 while the inspection receipt of the same revision is still carried", reset["inspection_status"] == "read")
    check_eq("item 6: a media receipt lost on the way is work for the role again, so not `unchanged`",
             reset["_refresh_result"], "changed")
    evidence.write_bytes(b"what the media said")
    changed = SI.collect_jira_source(FakeClient(revision="rev-2"), "APP-1", output, existing_record=partial_record)
    check_eq("G2 a changed revision resets the inspection receipt as before",
             (changed["inspection_status"], changed["inspection_ref"]), ("pending", None))
    check_eq("G2 and every media item", changed["materials"]["external_media"]["items"][0]["status"], "pending")
    check_eq("G2 and the media block", changed["materials"]["external_media"]["status"], "pending")
    other_url = SI.collect_jira_source(FakeClient(description="see https://share.example.invalid/other.mp4"),
                                       "APP-1", output, existing_record=partial_record)
    check_eq("G2 a URL the record never held starts pending",
             [i["status"] for i in other_url["materials"]["external_media"]["items"]], ["pending"])


# --------------------------------------------------------------------------------------------
# t-151: the critic's two must-fix (G3 wired, the migration keeps the old record) and the rest
# --------------------------------------------------------------------------------------------
def sha12(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def base_dir():
    if not _TMP:
        _TMP.append(temp_project("qa-gap-points-"))
    return _TMP[0]


def controller_inventory(root):
    """A valid inventory under <root>/work whose one kept source is the cmp1 shape: a legacy
    whole-source acceptance, the inspection receipt never written, one merge request unavailable."""
    text = b'{"key": "APP-1"}'
    snapshot = root / "work" / "sources" / "SRC-c1" / "r1" / "ticket.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(text)
    item = source("SRC-c1", "APP-1", relation="task", relevance_reason="the task", assessment_ref=None,
                  discovered_from=None, relation_evidence=None, fetched_at="t", revision="r1",
                  snapshot_ref="sources/SRC-c1/r1/ticket.json", content_hash=hashlib.sha256(text).hexdigest(),
                  inspection_status="pending",
                  materials=materials(external_media={"status": "unavailable", "items": [
                      media(MR510, "unavailable")]}),
                  gap_acceptance={"words": "go on without it", "by": "human", "at": "t",
                                  "accepted": ["materials unavailable: " + MR510]})
    path = root / "work" / "source-inventory.json"
    path.write_text(json.dumps(inv(item)), encoding="utf-8")
    return path


def part_controller():
    """Item 1: `controller.source_inputs` and `project` pass `s1_closed` from the state. The real
    Controller, an S1 that is completed and one that is not, over the same inventory."""
    from controller import Controller
    from event_store import StateConflict

    def story(name, stages):
        root = base_dir() / name
        root.mkdir(parents=True)
        c = Controller(root)
        c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(root)},
                               "idempotency_key": "init"})
        for n in range(stages):
            stage = f"S{n}"
            (root / (stage + ".txt")).write_text(stage, encoding="utf-8")
            c.apply("dispatch", {"id": stage, "stage": stage, "role": "worker", "scope": ["TC-1"],
                                 "input_hash": stage, "budget": {}, "known_paths": {}, "idempotency_key": "d" + stage})
            c.apply("accept", {"id": stage, "status": "accepted", "stage_complete": True,
                               "evidence_refs": [{"path": stage + ".txt", "sha256": hashlib.sha256(
                                   (root / (stage + ".txt")).read_bytes()).hexdigest()}],
                               "idempotency_key": "a" + stage})
        controller_inventory(root)
        return c, root

    def refusal(c, state=None):
        try:
            c.source_inputs(state)
        except StateConflict as exc:
            return str(exc)
        return None

    def projected(root):
        return json.loads((root / "state" / "controller.json").read_text(encoding="utf-8"))["source_completeness"]

    open_c, open_root = story("ctl-open", 1)        # S0 accepted, S1 not started
    check("item 1: S1 not completed - source_inputs judges by the point rule and refuses (the S1 checkpoint)",
          "sources pending/invalid" in (refusal(open_c) or ""))
    open_c.apply("dispatch", {"id": "S1", "stage": "S1", "role": "worker", "scope": ["TC-1"], "input_hash": "S1",
                              "budget": {}, "known_paths": {}, "idempotency_key": "dS1"})
    check_eq("item 1: S1 dispatched but not completed - `project` displays the point rule (blocked, no earlier-rule line)",
             (projected(open_root)["gate_blocked"], projected(open_root)["earlier_rule_line"]), (True, ""))
    done_c, done_root = story("ctl-done", 2)        # S0 and S1 completed
    got = done_c.source_inputs()
    check_eq("item 1: S1 completed - source_inputs keeps the old meaning, nothing re-blocks",
             (got["source_completeness"]["gate_blocked"], got["source_completeness"]["accepted_gaps"]),
             (False, ["SRC-c1"]))
    check("item 1: and it says so in one line, in the receipt gate A binds",
          got["source_completeness"]["earlier_rule_line"].startswith("S1 closed under the earlier acceptance rule: APP-1"))
    done_c.apply("dispatch", {"id": "S2", "stage": "S2", "role": "worker", "scope": ["TC-1"], "input_hash": "S2",
                              "budget": {}, "known_paths": {}, "idempotency_key": "dS2"})
    check_eq("item 1: S1 completed - `project` displays the old meaning too",
             (projected(done_root)["gate_blocked"], projected(done_root)["earlier_rule_sources"]), (False, ["SRC-c1"]))
    # edges: anything that is not the word `completed` on S1 is not closed
    for label, state in (("no stages key", {}), ("stages None", {"stages": None}), ("stages empty", {"stages": {}}),
                         ("S1 absent", {"stages": {"S0": {"status": "completed"}}}),
                         ("S1 None", {"stages": {"S1": None}}), ("S1 empty", {"stages": {"S1": {}}}),
                         ("S1 pending", {"stages": {"S1": {"status": "pending"}}}),
                         ("S1 blocked", {"stages": {"S1": {"status": "blocked"}}}),
                         ("S1 done (the display word, not the state word)", {"stages": {"S1": {"status": "done"}}}),
                         ("S1 COMPLETED in capitals", {"stages": {"S1": {"status": "COMPLETED"}}}),
                         ("S1 rework", {"stages": {"S1": {"status": "pending", "rework": True}}})):
        check(f"item 1 edge: {label} -> s1_closed False, the point rule refuses",
              "sources pending/invalid" in (refusal(done_c, state) or ""))
    check("item 1 edge: only status `completed` on S1 opens the old meaning",
          refusal(done_c, {"stages": {"S1": {"status": "completed"}}}) is None)


def part_legacy_migration():
    """Item 2: the migration keeps the old record, and the `s1_closed` branch honours it."""
    legacy = cmp1_inventory(legacy=True)
    path = stored(legacy)
    accepted = SI.record_gap_acceptance(path, [PREC], "and the third one too", points=[mid(MR3758)])
    prec = by_source(accepted, PREC)["gap_acceptance"]
    check_eq("item 2: the migration keeps the old record whole beside the points (words, by, at, accepted)",
             prec.get("legacy"), {"words": LEGACY_WORDS, "by": "human", "at": "2026-09-30T03:58:02Z",
                                  "accepted": ["materials not inspected", "materials unavailable: " + MR510]})
    closed = SI.completeness(accepted, s1_closed=True)
    check_eq("item 2 (the critic's probe): S1 closed, legacy acceptance, one point recorded on top - "
             "gate_blocked stays False", closed["gate_blocked"], False)
    check_eq("item 2: and the whole precedent stays under the old meaning",
             (closed["accepted_gaps"], closed["incomplete_materials"], closed["unavailable_materials"]),
             (sorted([TASK, PREC]), [], []))
    check("item 2: the earlier-rule line still names the sources not inspected",
          closed["earlier_rule_line"] == "S1 closed under the earlier acceptance rule: PREC-1, TASK-1 not inspected")
    reopened = SI.completeness(accepted, s1_closed=False)
    check("edge: legacy + accepted_points + S1 reopened -> the point rule applies, the task stays blocked on inspection",
          reopened["gate_blocked"] and TASK in reopened["incomplete_materials"] and reopened["earlier_rule_line"] == "")
    check_eq("edge: and the legacy record closes only what its strings name - the migrated 510, plus the new 3758",
             sorted(closed_of(reopened, PREC)), sorted([mid(MR510), mid(MR3758)]))
    check_eq("edge: the work-class inspection point is never closed by the legacy record, reopened or not",
             "source:not_inspected" in open_of(reopened, PREC), True)
    again = SI.record_gap_acceptance(path, [PREC], "and one more", points=[mid(MR1522)])
    check_eq("item 2: a second point on top leaves the legacy record exactly as it was",
             by_source(again, PREC)["gap_acceptance"].get("legacy"), prec.get("legacy"))
    check_eq("item 2: still not blocked for a closed S1 after the second point",
             SI.completeness(again, s1_closed=True)["gate_blocked"], False)
    # the legacy source that was never touched by a point acceptance is the same record, not a copy
    check("item 2: a source with no point recorded yet has no `legacy` key (the acceptance itself is the old record)",
          "legacy" not in by_source(SI.load_inventory(stored(legacy)), TASK)["gap_acceptance"])
    # a new-format acceptance never acquires one, and is a point acceptance under both meanings
    fresh = stored(cmp1_inventory(legacy=False))
    SI.record_gap_acceptance(fresh, [PREC], "only this", points=[mid(MR510)])
    recorded = load(fresh)
    check("item 2: a point acceptance on a source with no old record has no `legacy` key",
          "legacy" not in by_source(recorded, PREC)["gap_acceptance"])
    check("item 2: and it is a point acceptance for a closed S1 too (still blocked on the inspection)",
          SI.completeness(recorded, s1_closed=True)["gate_blocked"])
    # blank or malformed legacy copies give no old meaning
    for label, bad in (("blank words", {"words": "  ", "accepted": []}), ("not a dict", "go on"), ("None", None)):
        doctored = json.loads(json.dumps(recorded))
        by_source(doctored, PREC)["gap_acceptance"]["legacy"] = bad
        check(f"item 2 edge: a `legacy` with {label} is no old record: a closed S1 stays point-judged",
              SI.completeness(doctored, s1_closed=True)["gate_blocked"])
    # accepted_points present but `legacy` only on the source that has an acceptance: per source
    mixed = json.loads(json.dumps(accepted))
    by_source(mixed, TASK).pop("gap_acceptance")
    check_eq("item 2: the old meaning is per source - the task without an acceptance is blocked again",
             SI.completeness(mixed, s1_closed=True)["incomplete_materials"], [TASK])


def part_legacy_names():
    """Item 3: a legacy `materials unavailable:` string closes only when EVERY piece of it names a material."""
    def open_ids(item):
        return sorted(SI.completeness(inv(item))["open_points"].get("SRC-a1", []))

    def rows(*names):
        return materials(attachments={"status": "read", "items": [
            attachment(str(i + 1), "read", "unavailable", name) for i, name in enumerate(names)]})

    def legacy_of(strings, *names):
        return legacy_source(strings, rows(*names), inspection_status="read")

    check_eq("item 3 (the critic's probe): attachments `a, b.png` and `b.png`, the string `a, b.png` - "
             "b.png is NOT closed by words that named another file",
             open_ids(legacy_of(["materials unavailable: a, b.png"], "a, b.png", "b.png")), ["attachment:2"])
    check_eq("item 3: a string with one piece that matches nothing closes nothing, its matching piece included",
             open_ids(legacy_of(["materials unavailable: b.png, nothing.png"], "b.png")), ["attachment:1"])
    check_eq("item 3: the same with the unmatched piece first",
             open_ids(legacy_of(["materials unavailable: nothing.png, b.png"], "b.png")), ["attachment:1"])
    check_eq("item 3: every piece a material: each closes",
             open_ids(legacy_of(["materials unavailable: a, b.png"], "a", "b.png")), [])
    check_eq("item 3: the exact whole string is tried first - `a, b.png` is one file, `a` and `b.png` stay open",
             open_ids(legacy_of(["materials unavailable: a, b.png"], "a, b.png", "a", "b.png")),
             ["attachment:2", "attachment:3"])
    check_eq("edge: a single name containing `, ` that matches a material exactly closes that material",
             open_ids(legacy_of(["materials unavailable: a, b.png"], "a, b.png")), [])
    check_eq("edge: an empty name closes nothing and does not crash",
             open_ids(legacy_of(["materials unavailable: "], "b.png")), ["attachment:1"])
    check_eq("edge: a whitespace-only name closes nothing",
             open_ids(legacy_of(["materials unavailable:    "], "b.png")), ["attachment:1"])
    check_eq("edge: an empty piece makes the whole string unreadable (`b.png, `)",
             open_ids(legacy_of(["materials unavailable: b.png, "], "b.png")), ["attachment:1"])
    check_eq("edge: a whitespace-only piece makes the whole string unreadable (`b.png,     `)",
             open_ids(legacy_of(["materials unavailable: b.png,     "], "b.png")), ["attachment:1"])
    check_eq("edge: a file with an empty name is not matched by an empty piece",
             open_ids(legacy_of(["materials unavailable: "], "")), ["attachment:1"])
    check_eq("edge: entries that are not strings are skipped, a readable one still closes",
             open_ids(legacy_of([None, 5, ["x"], "materials unavailable: b.png"], "b.png")), [])
    check_eq("edge: several readable strings each close their own",
             open_ids(legacy_of(["materials unavailable: a", "materials unavailable: b.png"], "a", "b.png", "c.png")),
             ["attachment:3"])
    check_eq("G9 still: a name two materials carry closes neither, and does not spoil a neighbour piece",
             open_ids(legacy_of(["materials unavailable: same.png, other.png"], "same.png", "same.png", "other.png")),
             ["attachment:1", "attachment:2"])
    media_item = legacy_source(["materials unavailable: " + MR510 + ", https://git.example.invalid/elsewhere"],
                               materials(external_media={"status": "unavailable", "items": [
                                   media(MR510, "unavailable")]}), inspection_status="read")
    check_eq("item 3: the same rule for external material - one piece that is no material of the source closes nothing",
             open_ids(media_item), [mid(MR510)])
    check_eq("item 3: empty `accepted` with words stays the decided words-only meaning (F8 a): gap points close",
             open_ids(legacy_of([], "b.png")), [])


def part_attachment_ids():
    """Item 4: `original_ref` is in the hash of a made-up attachment id."""
    def point_ids(*rows):
        return [p["id"] for p in SI.gap_points(source(materials=materials(attachments={"status": "read",
                                                                                      "items": list(rows)})))]

    def noid(ref, **more):
        row = {"filename": "a.png", "size": 3, "status": "read", "analysis_status": "unavailable"}
        if ref is not None:
            row["original_ref"] = ref
        row.update(more)
        return row

    rev1, rev2 = point_ids(noid("https://j.example.invalid/att/1")), point_ids(noid("https://j.example.invalid/att/2"))
    check("item 4: two different files of one name and size, one per revision, get two ids",
          len(rev1) == 1 and len(rev2) == 1 and rev1 != rev2)
    same = point_ids(noid("https://j.example.invalid/att/1"))
    check_eq("item 4: the same file, the same id", same, rev1)
    check_eq("item 4: two in one revision with different addresses are two points",
             len(set(point_ids(noid("https://j.example.invalid/att/1"), noid("https://j.example.invalid/att/2")))), 2)
    old_form = "attachment:unknown:0:" + sha12("a.png|3")
    check_eq("edge: original_ref absent -> the id every earlier acceptance was stored under, unchanged",
             point_ids(noid(None)), [old_form])
    check_eq("edge: original_ref empty -> the same old id", point_ids(noid("")), [old_form])
    check_eq("edge: original_ref None -> the same old id", point_ids(noid(None, original_ref=None)), [old_form])
    check("item 4: with an address the id is NOT the old form", rev1 != [old_form]
          and re.fullmatch(r"attachment:unknown:0:[0-9a-f]{12}", rev1[0]) is not None)
    check_eq("item 4: a real, unique id is untouched by the address",
             point_ids(noid("https://j.example.invalid/att/1", attachment_id="77")), ["attachment:77"])

    # an id stored under the old form: inert, printed as no longer open, never a refusal, blocks nothing
    item = source(inspection_status="read", materials=materials(attachments={"status": "read", "items": [
        noid("https://j.example.invalid/att/1")]}))
    item["gap_acceptance"] = {"words": "go on", "accepted_points": [
        {"id": old_form, "kind": "attachment", "class": "gap", "text": "attachment a.png: unavailable",
         "words": "go on", "at": "t", "revision": "rev-1", "shown": True}]}
    summary = SI.completeness(inv(item))
    check_eq("item 4: an old-form id in `accepted_points` closes nothing - the point is open again (one more question)",
             (open_of(summary, "SRC-a1"), closed_of(summary, "SRC-a1")), (rev1, []))
    path = stored(inv(item))
    before = path.read_bytes()
    inventory, report = SI.apply_gap_acceptance(path, ["SRC-a1"], "go on", points=[old_form])
    check_eq("item 4: naming the old id to the recorder prints it as no longer open, it does not refuse",
             report["no_longer_open"], {"SRC-a1": [old_form]})
    check("item 4: and writes nothing for it", path.read_bytes() == before and report["accepted"] == {})
    try:
        inventory, report = SI.apply_gap_acceptance(path, ["SRC-a1"], "go on", points=[old_form, rev1[0]])
    except ValueError as exc:  # only when the two spellings are one id (the hash ignores the address)
        report = {"accepted": {"SRC-a1": []}, "no_longer_open": {"refused": str(exc)}}
    check_eq("item 4: the old id and the new one together: the new one is recorded, the old printed",
             ([p["id"] for p in report["accepted"]["SRC-a1"]], report["no_longer_open"]),
             (rev1, {"SRC-a1": [old_form]}))
    check("item 4: an id that never existed is still refused",
          refused(SI.apply_gap_acceptance, path, ["SRC-a1"], "go on",
                  points=["attachment:unknown:0:" + sha12("other.png|9")]) is not None)


def part_point_text():
    """Item 5: the project segment stays in a merge request's text."""
    def text_of(url):
        return SI.gap_points(source(materials=materials(external_media={"status": "unavailable", "items": [
            media(url, "unavailable")]})))[0]["text"]

    sdk, ui = text_of("https://git.example.invalid/team/sdk/-/merge_requests/510"), \
        text_of("https://git.example.invalid/team/ui/-/merge_requests/510")
    check("item 5: `team/sdk/.../510` and `team/ui/.../510` no longer render identically", sdk != ui)
    check("item 5: each names its project", "team/sdk/-/merge_requests/510" in sdk and "team/ui/-/merge_requests/510" in ui)
    check_eq("item 5: a pull request keeps its owner and repository",
             text_of("https://github.example.invalid/acme/widgets/pull/42"),
             "external material github.example.invalid/acme/widgets/pull/42: unavailable")
    deep = "https://git.example.invalid/" + "/".join(["g" * 30] * 4) + "/proj/-/merge_requests/7"
    text = text_of(deep)
    check("item 5: a path too long for the line keeps the END of it, project included, and stays within 120 characters",
          len(text) <= 120 and "/.../" in text and text.endswith("proj/-/merge_requests/7: unavailable"))
    check_eq("item 5: a bare number with no path before it is not a crash", text_of("https://h.example.invalid/42"),
             "external material h.example.invalid/42: unavailable")
    check("item 5: a file still reads as host and file name only (no change for non-numeric tails)",
          text_of("https://share.example.invalid/a/b/c/clip.mp4") == "external material share.example.invalid/.../clip.mp4: unavailable")
    at_limit = text_of("https://h.example.invalid/" + "x" * 52 + "/-/merge_requests/1")
    beyond = text_of("https://h.example.invalid/" + "x" * 53 + "/-/merge_requests/1")
    check_eq("item 5 limit AT 120: the whole path, nothing elided", (len(at_limit), "/.../" in at_limit), (120, False))
    check("item 5 limit BEYOND it: the front is elided, the end and the number stay, never above 120",
          len(beyond) <= 120 and "/.../" in beyond and beyond.endswith("merge_requests/1: unavailable"))
    check("item 5: the ids of the two merge requests are two ids (display text is not identity)",
          SI.gap_points(source(materials=materials(external_media={"status": "unavailable", "items": [
              media("https://git.example.invalid/team/sdk/-/merge_requests/510", "unavailable"),
              media("https://git.example.invalid/team/ui/-/merge_requests/510", "unavailable")]})))[0]["id"]
          != SI.gap_points(source(materials=materials(external_media={"status": "unavailable", "items": [
              media("https://git.example.invalid/team/ui/-/merge_requests/510", "unavailable")]})))[0]["id"])


def part_refresh_word():
    """Item 6: `refresh` on an unchanged revision whose files verify does not say `changed`."""
    def fresh(name, description):
        output = base_dir() / name / "work" / "source-inventory.json"
        client = FakeClient(description=description)
        record = SI.collect_jira_source(client, "APP-1", output, fetched_at="2026-09-30T01:00:00Z")
        SI.update_inventory(output, record)
        SI.record_relevance_assessment(output, record["source_id"], "relevant", "read it", "work/evidence/note.json")
        return output, client, record["source_id"]

    output, client, sid = fresh("refresh-incomplete", "see https://share.example.invalid/demo.mp4")
    check("item 6: the source is incomplete (a media item is pending) - it is re-collected on refresh",
          sid in SI.completeness(SI.load_inventory(output))["incomplete_materials"])
    check_eq("item 6: refresh of an UNCHANGED revision reports `unchanged`, not `changed`",
             SI.refresh_relevant_sources(client, output)["results"], [{"source_id": sid, "result": "unchanged"}])
    check_eq("item 6: and the receipts the role wrote survive it",
             by_source(SI.load_inventory(output), sid)["inspection_status"], "read")
    check_eq("item 6: a CHANGED revision still reports `changed`",
             SI.refresh_relevant_sources(FakeClient(revision="rev-2", description="see https://share.example.invalid/demo.mp4"),
                                         output)["results"], [{"source_id": sid, "result": "changed"}])
    output, client, sid = fresh("refresh-complete", "no address here")
    check("item 6: a complete source", SI.completeness(SI.load_inventory(output))["complete"])
    check_eq("item 6: is reused and reports `unchanged` (the word the function already had)",
             SI.refresh_relevant_sources(client, output)["results"], [{"source_id": sid, "result": "unchanged"}])
    check_eq("item 6: a first collect is still `new`",
             SI.collect_jira_source(FakeClient(), "APP-9", base_dir() / "refresh-new" / "work" / "source-inventory.json")
             ["_refresh_result"], "new")
    # the stored files no longer verify: same revision, but the evidence is not what was recorded
    output, client, sid = fresh("refresh-tampered", "no address here")
    stored_item = by_source(SI.load_inventory(output), sid)
    (output.parent / stored_item["snapshot_ref"]).write_bytes(b"{}")
    check_eq("item 6 edge: a snapshot that no longer verifies is not `unchanged`",
             SI.collect_jira_source(client, "APP-1", output, existing_record=stored_item)["_refresh_result"], "changed")


def part_second_acceptance():
    """Item 7: a second acceptance of a point already accepted is reported as already accepted; the dead
    `open_points` is gone."""
    check("item 7: `open_points()` (no caller in the package) is gone", not hasattr(SI, "open_points"))
    path = stored(cmp1_inventory(legacy=False))
    inventory, report = SI.apply_gap_acceptance(path, [PREC], "first", points=[mid(MR510)])
    check_eq("item 7: a first acceptance has nothing already accepted", report["already_accepted"], {})
    before = path.read_bytes()
    inventory, report = SI.apply_gap_acceptance(path, [PREC], "again", points=[mid(MR510)])
    check_eq("item 7: the second acceptance of the same point is reported as already accepted",
             {sid: [p["id"] for p in points] for sid, points in report["already_accepted"].items()}, {PREC: [mid(MR510)]})
    check("item 7: nothing is rewritten, and the old words are kept", path.read_bytes() == before)
    inventory, report = SI.apply_gap_acceptance(path, [PREC], "both", points=[mid(MR510), mid(MR1522)])
    check_eq("item 7: a mix reports only the earlier one as already accepted",
             ([p["id"] for p in report["accepted"][PREC]], [p["id"] for p in report["already_accepted"][PREC]]),
             ([mid(MR510), mid(MR1522)], [mid(MR510)]))
    entries = {e["id"]: e["words"] for e in by_source(inventory, PREC)["gap_acceptance"]["accepted_points"]}
    check_eq("item 7: each point keeps its own words", entries, {mid(MR510): "first", mid(MR1522): "both"})
    path = stored(cmp1_inventory(legacy=False))
    SI.apply_gap_acceptance(path, [TASK], "go on")
    _, report = SI.apply_gap_acceptance(path, [TASK], "go on again")
    check_eq("item 7: the same without `points` (every open gap of the source)",
             list(report["already_accepted"]), [TASK])
    # the word printed by `accept-gap` is ticket_adapter.py's (not owned by this task): it reads
    # `report["already_accepted"]`, which is what this part pins.


def main():
    try:
        part_i3()
        part_points()
        part_identity()
        part_cmp1()
        part_record()
        part_legacy()
        part_revision_and_position()
        part_cli()
        part_cli_attachments()
        part_refusal_prefix()
        part_reuse()
        part_controller()
        part_legacy_migration()
        part_legacy_names()
        part_attachment_ids()
        part_point_text()
        part_refresh_word()
        part_second_acceptance()
    finally:
        for folder in _TMP:
            cleanup(folder)
    finish("test_gap_points")


if __name__ == "__main__":
    main()
