"""CX1-16 (t-1042, built as t-1087): the FB-14 state of TP2-2406, run through `main`'s own road.

The live run TP2-2406 (FB-14) stopped at S1 with a READ parent and a READ story whose inspection receipts were never
written, and the person answered the block three times. On `main` the receipt of a READ source whose snapshot lies on disk
is written by the CODE (C2-3, t-721 section 3.5: `ticket_adapter.py receipts`, `inspection_by: code:snapshot`), and a
person's word about a gap goes through `ticket_adapter.py accept-gap` (a point, or a whole kind). This file holds the
preserved state UNCHANGED and shows both halves with the four readers of the road: the controller (`source_inputs`,
`accept`), `stage_done`, the exit gate of the scout - they agree, or the file says which one differs and why.

* Her three `stage_overrides` words are kept as saved and pass NOTHING (D-0043: a word recorded outside `main`'s own
  commands is not a person's word to its readers; at `stage_done` and the gate that is also luck of wording - see R1).
* Writers are the CLIs (`receipts`, `accept-gap`, `waiver.py` for the F-3 pin), except the R10b and red-table words, which
  `set_words` writes in-process through `waiver.apply_stage_override`; readers run in-process. No package code is changed.
* The table of EXPECTED-RED lines (N-3 of the plan review) is asserted as red on purpose: each is a finding for a node of
  the Lead, and a red that turns green FAILS here so the table is rewritten by whoever fixes it.
Expectations come from the requirements named at each assertion (P13, P20, FR-4, FR-7, FR-58), never from `main`'s output.
"""
import ast
import contextlib
import hashlib
import io
import json
import sys
from types import SimpleNamespace

from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import source_inventory as SI  # noqa: E402
from test_gap_points import media  # noqa: E402

TASK = "TP2-2406"
FEATURE, PARENT, STORY = ("SRC-af66b35b3c01888af389", "SRC-7f78f2bbf6dd32486059", "SRC-e01f78dde5d45d41cd52")
DECISION = ("Go on without the missing S1 source receipts.\nThis waiver applies only to the missing "
            "receipts for TP2-2406 and TP2-1847. Keep and use all available Jira/MR "
            "evidence.\nPreserve FB-13 as a Factory defect.")
WORD_HUMAN = "missing S1 source receipts for TP2-2406 and TP2-1847"
WORD_SUMMARY = ("sources pending/invalid: {'complete': False, 'gate_blocked': True, 'pending': [], "
                "'unavailable': [], 'incomplete_materials': ['SRC-7f78f2bbf6dd32486059', "
                "'SRC-e01f78dde5d45d41cd52'], 'unavailable_materials': [], 'accepted_gaps': "
                "['SRC-af66b35b3c01888af389'], 'review_missing': False, 'unreviewed': "
                "['SRC-af66b35b3c01888af389'], 'awaiting_review': False, 'open_points': "
                "{'SRC-7f78f2bbf6dd32486059': ['source:not_inspected'], 'SRC-e01f78dde5d45d41cd52': "
                "['source:not_inspected']}, 'closed_by_person': {'SRC-af66b35b3c01888af389': "
                "['source:unavailable']}, 'left_out_by_word': {}, 'earlier_rule_line': '', "
                "'earlier_rule_sources': []}")
WORD_QUOTED = ("sources pending/invalid: source-receipt:SRC-7f78f2bbf6dd32486059; "
               "source-receipt:SRC-e01f78dde5d45d41cd52")
GITLAB = "https://git.example/tp2-group/ai-runway/runs/September-2026/nightwing"
LACK = "source materials lack retrieval or inspection receipts"
GATE_PREFIX = "source-inventory.json: "
PAIR_REFUSAL = "S1 unavailable sources require explicit unresolved gap handoff"
BARRIER = "is a controller-managed stage and the controller has not accepted it"


def fb14_inventory(work) -> dict:
    """Her preserved `work/source-inventory.json` (package.diff, `fb14_inventory`), verbatim: the snapshot bytes are written
    under `work/` so `verify_inventory_files` sees what the run saw (hashes recomputed)."""
    review = {"at": "2026-10-10T22:09:49.145319Z", "by": "human", "words": "Keep TP2-2406 and TP2-1847."}

    def snapshot(source_id, revision, text):
        ref = f"sources/{source_id}/{revision}/ticket.json"
        target = work / ref
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text)
        return ref, hashlib.sha256(text).hexdigest()

    diff_bytes = b"diff --git a/x b/x\n"
    (work / "impl-diff.txt").write_bytes(diff_bytes)
    parent_ref, parent_hash = snapshot(PARENT, "1e670f9c41380564", b'{"key": "TP2-1847"}')
    story_ref, story_hash = snapshot(STORY, "f5de45aca24de48a", b'{"key": "TP2-2406"}')
    feature = {
        "assessment_ref": "work/source-inventory.json", "canonical_ref": "https://example.org/browse/TP5-212",
        "content_hash": None, "discovered_from": None,
        "exclusion_or_error": "Feature-title text was retried and tracker still returned 404; source unavailable.",
        "fetched_at": "2026-10-10T20:46:12.189243Z",
        "gap_acceptance": {
            "accepted": ["unavailable: Feature-title text was retried and tracker still returned 404; source unavailable."],
            "accepted_points": [{"at": "2026-10-10T22:16:23.269386Z", "by": "human", "class": "gap",
                                 "id": "source:unavailable", "kind": "source", "revision": None, "shown": False,
                                 "text": "unavailable: Feature-title text was retried and tracker still returned 404; source unavailable.",
                                 "words": "Mark it unavailable if the 404 persists."}],
            "at": "2026-10-10T22:16:23.269386Z", "by": "human", "words": "Mark it unavailable if the 404 persists."},
        "human_review": dict(review, shown={"relevance": "not_relevant", "status": "excluded"}),
        "inspection_ref": None, "inspection_status": "pending",
        "materials": {"attachments": {"count": None, "items": [], "status": "unknown"},
                      "comments": {"count": None, "status": "unknown"}},
        "mentioned_ticket_keys": [], "not_found": True, "relation": "referenced", "relation_evidence": None,
        "relevance": "unknown", "relevance_reason": "Feature-title text was retried and tracker still returned 404; source unavailable.",
        "required": True, "revision": None, "snapshot_ref": None, "source_id": FEATURE, "status": "unavailable"}
    parent = {
        "assessment_ref": parent_ref, "canonical_ref": "https://example.org/browse/TP2-1847",
        "content_hash": parent_hash, "discovered_from": STORY, "exclusion_or_error": None,
        "fetched_at": "2026-10-10T20:47:00.976089Z",
        "human_review": dict(review, shown={"relevance": "relevant", "status": "read"}),
        "inspection_ref": None, "inspection_status": "pending",
        "materials": {"attachments": {"count": 0, "items": [], "status": "read"},
                      "comments": {"count": 0, "status": "read"},
                      "external_media": {"count": 1, "status": "read", "items": [
                          {"access_problem": False, "cause": "no_tool",
                           "content_hash": hashlib.sha256(diff_bytes).hexdigest(), "error": None,
                           "local_ref": "impl-diff.txt", "provenance": "fetched", "status": "read",
                           "url": GITLAB}]}},
        "mentioned_ticket_keys": [], "relation": "parent", "relation_evidence": "task parent TP2-1847",
        "relevance": "relevant", "relevance_reason": "explicit required source", "required": True,
        "revision": "2026-09-22T13:16:16.171+0000", "snapshot_ref": parent_ref, "source_id": PARENT,
        "status": "read"}
    story = {
        "assessment_ref": story_ref, "canonical_ref": "https://example.org/browse/TP2-2406",
        "content_hash": story_hash, "discovered_from": "dispatch", "exclusion_or_error": None,
        "fetched_at": "2026-10-10T20:45:50.005274Z",
        "human_review": dict(review, shown={"relevance": "relevant", "status": "read"}),
        "inspection_ref": None, "inspection_status": "pending",
        "materials": {"attachments": {"count": 0, "items": [], "status": "read"},
                      "comments": {"count": 0, "status": "read"},
                      "external_media": {"count": 0, "items": [], "status": "read"}},
        "mentioned_ticket_keys": ["TP2-1847"], "relation": "task", "relation_evidence": "S0 ticket snapshot",
        "relevance": "relevant", "relevance_reason": "explicit required source", "required": True,
        "revision": "2026-09-21T21:45:31.378+0000", "snapshot_ref": story_ref, "source_id": STORY,
        "status": "read"}
    return {"field_ids": {"epic_link": ["customfield_32201", "customfield_14500"],
                          "fetched_at": "2026-10-10T20:31:58.516968Z"},
            "prefix_probes": {"TP2": {"checked_at": "2026-10-10T20:31:58.516968Z",
                                             "reason": "known at S0 without a request", "result": "tracker"}},
            "proof_key": TASK, "reads_skipped": [], "schema_version": 1,
            "sources": [feature, parent, story]}


@contextlib.contextmanager
def story(prefix, mutate=None):
    """R0, the one setup: `temp_project`, the root pinned, the controller at S1 dispatched, her inventory (after `mutate`, a
    callable on the dict) and her `pipeline.json` with the three `stage_overrides` she saved, dispatched as she had them."""
    import hooklib
    from controller import Controller
    root = temp_project(prefix)
    art = root / "qa-factory" / "artifacts" / TASK
    work = art / "work"
    work.mkdir(parents=True)
    try:
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            c = Controller(art)
            c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(art)},
                                   "idempotency_key": "init"})
            (art / "S0.txt").write_text("S0", encoding="utf-8")
            c.apply("dispatch", {"id": "S0", "stage": "S0", "role": "worker", "scope": ["TC-1"], "input_hash": "S0",
                                 "budget": {}, "known_paths": {}, "idempotency_key": "dS0"})
            c.apply("accept", {"id": "S0", "status": "accepted", "stage_complete": True,
                               "evidence_refs": [{"path": "S0.txt", "sha256": hashlib.sha256(b"S0").hexdigest()}],
                               "idempotency_key": "aS0"})
            c.apply("dispatch", {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout", "scope": ["TC-1"],
                                 "input_hash": "S1", "budget": {}, "known_paths": {}, "idempotency_key": "dS1"})
            inventory = fb14_inventory(work)
            if mutate:
                mutate(inventory)
            inv = work / "source-inventory.json"
            inv.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
            pipe = art / "pipeline.json"
            pipeline = json.loads(pipe.read_text(encoding="utf-8"))
            pipeline.update({"ticket": TASK, "source_inventory_required": True,
                             "stages": {"S0": {"status": "completed"}, "S1": {"status": "running"}},
                             "stage_overrides": [{"stage": "S1", "match": word, "decision": DECISION,
                                                  "at": "2026-10-11T19:15:56+00:00", "by": "human"}
                                                 for word in (WORD_HUMAN, WORD_SUMMARY, WORD_QUOTED)]})
            pipe.write_text(json.dumps(pipeline), encoding="utf-8")
            yield SimpleNamespace(root=root, art=art, work=work, inv=inv, pipe=pipe, c=c)
    finally:
        cleanup(root)


def ctl_open(refusal):
    """The sources with an open point in the controller's refusal: its text is the raw summary dict (`str(summary)`, the
    finding F-4 - a refusal with no door), so the parse is the pinned form; `None` means the text is no longer that."""
    try:
        return set(ast.literal_eval((refusal or "").split("sources pending/invalid: ", 1)[-1])["open_points"])
    except Exception:
        return None


def readers(s):
    """The four readers of S1 at one look. `sd_block` is stage_done's own S1 verdict (N-1): the exit code alone says nothing
    before the controller accepts S1, since it is the same `EXIT_BAD_ARGS` for 'inventory incomplete' and 'controller-managed'."""
    import exit_gate
    import stage_done
    import waiver
    from event_store import StateConflict
    from source_preflight import check_source_inventory
    pipeline = json.loads(s.pipe.read_text(encoding="utf-8"))
    ctl = None
    try:
        s.c.source_inputs()
    except StateConflict as exc:
        ctl = str(exc)
    pre = check_source_inventory(s.art, pipeline)
    blocking, passed = waiver.split_overridden(pre["errors"], pipeline, "S1")
    gate_blocking, gate_passed = exit_gate.all_errors("qa-scout", TASK, "handoff")
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        code = stage_done.run(TASK, "S1", "done", "qa-scout", "done", True)
    text = err.getvalue()
    block = text.split("S1 source inventory incomplete: ", 1)[1].split("\n", 1)[0] if "S1 source inventory incomplete" in text else ""
    return SimpleNamespace(ctl=ctl, pre=blocking, passed=passed, gaps=pre["gaps"], code=code, err=text, sd_block=block,
                           gate=[str(e) for e in gate_blocking if str(e).startswith(GATE_PREFIX)],
                           gate_passed=[p for p in gate_passed if GATE_PREFIX in str(p["error"])])


def blocked(r):
    """Does each reader refuse the inventory: (controller, stage_done's check, exit gate, stage_done's S1 verdict)."""
    return (r.ctl is not None, bool(r.pre), bool(r.gate), bool(r.sd_block))


def named(r, sid):
    """Does each reader still hold a refusal that names `sid` (controller: an open point of it)."""
    return (sid in (ctl_open(r.ctl) or ()), any(sid in line for line in r.pre), any(sid in line for line in r.gate),
            sid in r.sd_block)


def cli(s, command, *rest):
    return run_script("ticket_adapter.py", command, "--output", str(s.inv), *rest)


def word(s, name, text):
    import person_words
    return str(person_words.write_words(s.art, "", name, text))


def accept(s, **extra):
    """The S1 accept the road makes (`story_step finish` hands the pair over): None when taken, else the refusal."""
    from event_store import StateConflict
    (s.art / "S1.txt").write_text("S1", encoding="utf-8")
    payload = {"id": "S1-qa-scout-1", "status": "accepted", "stage_complete": True, "idempotency_key": "aS1",
               "evidence_refs": [{"path": "S1.txt", "sha256": hashlib.sha256(b"S1").hexdigest()}], **extra}
    try:
        s.c.apply("accept", payload)
    except StateConflict as exc:
        return str(exc)
    return None


def sha(s):
    return hashlib.sha256(s.inv.read_bytes()).hexdigest()


def sources(s):
    return {item["source_id"]: item for item in json.loads(s.inv.read_text(encoding="utf-8"))["sources"]}


def all_close(r, what):
    """After the S1 accept: stage_done exits 0 and none of the four readers refuses - one verdict (I-2, FR-4)."""
    check_eq(f"{what}: no reader refuses, stage_done exits 0", (blocked(r), r.code), ((False,) * 4, 0))


# --------------------------------------------------------------------------------------------
# R1-R7: the main road, one story - her state, the code's stamp, the feature gap carried, the stage closed.
# --------------------------------------------------------------------------------------------
def r1_before_any_word(s):
    import stage_done
    r = readers(s)
    # I-2, FR-4: nothing was recorded by main's commands - the four readers refuse, with no silent pass.
    check_eq("R1: all four readers refuse her state", blocked(r), (True,) * 4)
    check("R1: the check is ONE line naming the parent and the story, and not the accepted feature (P13: a recorded "
          "gap does not block)", len(r.pre) == 1 and PARENT in r.pre[0] and STORY in r.pre[0] and FEATURE not in r.pre[0])
    check_in("R1: ...and it says what is missing", LACK, r.pre)
    check_eq("R1: the exit gate carries that same line under its own prefix", r.gate, [GATE_PREFIX + r.pre[0]])
    check_eq("R1: stage_done refuses S1 on its own words, with the exit code of a refusal",
             (r.code, bool(r.sd_block)), (stage_done.EXIT_BAD_ARGS, True))
    check_eq("R1: the controller's refusal names the parent and the story as open (its text is the raw summary: F-4)",
             ctl_open(r.ctl), {PARENT, STORY})
    # D-0043: a word recorded outside main's commands is not a person's word to main's readers; at stage_done and the gate
    # this also holds only because her wording is not a substring of main's line (text-dependent, see the F-3 finding).
    check_eq("R1: her three saved words pass nothing at stage_done or the gate", (r.passed, r.gate_passed), ([], []))


def r2_stamp_by_the_code(s):
    # C2-3 (t-721 3.5, D-0043): the factory's own work - the receipt of a source that was read - is written by the code.
    done = cli(s, "receipts")
    check_eq("R2: `receipts` exits 0", done.returncode, 0)
    check("R2: it stamps the parent and the story and leaves the feature",
          "receipts: 2 source(s) stamped" in done.stdout and "1 left as they are" in done.stdout, done.stdout)
    items = sources(s)
    check_eq("R2: parent and story carry the code stamp (inspection_status, inspection_by); the feature is untouched",
             [(items[x]["inspection_status"], items[x].get("inspection_by")) for x in (PARENT, STORY, FEATURE)],
             [("read", SI.STAMP_BY), ("read", SI.STAMP_BY), ("pending", None)])
    kept = sha(s)
    check_in("R2: a second run stamps nothing (FR-7: nothing is asked or written twice)",
             "receipts: 0 source(s) stamped", cli(s, "receipts").stdout)
    check_eq("R2: ...and the bytes are the same", sha(s), kept)


def r3_after_the_stamp(s):
    import story_step
    r = readers(s)
    # I-2: the stamp is the one change - none of the four readers refuses on the inventory any more.
    check_eq("R3: no reader refuses the inventory after the stamp", blocked(r), (False,) * 4)
    check_eq("R3: the gate has no source line, her words passed nothing", (r.gate, r.passed, r.gate_passed), ([], [], []))
    check_eq("R3: the feature's recorded gap is carried as a line, with the person's words (D-0047: said out loud)",
             r.gaps, [f"accepted gap: {FEATURE} — Mark it unavailable if the 404 persists."])
    pair = story_step._s1_accepted_gaps(s.art)
    check_eq("R3: the handoff pair names the feature (`unresolved` is a list)", pair.get("unresolved"), [FEATURE])
    check("R3: ...and its reason carries the id and the person's words", FEATURE in pair.get("reason", "")
          and "Mark it unavailable if the 404 persists." in pair.get("reason", ""), str(pair))
    return pair


def r4_accept(s, pair):
    from controller import Controller
    # FR-4: an incomplete inventory is not closed silently - without the named gap the accept is refused.
    check_in("R4: without the pair the S1 accept is refused", PAIR_REFUSAL, accept(s) or "")
    check_eq("R4: with the pair the S1 accept is taken", accept(s, **pair), None)
    check_eq("R4: ...and S1 is completed", (Controller(s.art).state().get("stages") or {}).get("S1", {}).get("status"),
             "completed")


def r5_to_r7_after_the_accept(s):
    r = readers(s)
    all_close(r, "R5")
    # D-0047 (said out loud) against FR-7 (not asked again): the gap is printed with the person's words, exit 0.
    check_in("R5: stage_done prints the carried gap with the words", f"continues with explicit source gap(s): accepted gap: "
             f"{FEATURE} — Mark it unavailable if the 404 persists.", r.err)
    check_not_in("R5: ...and no 'block passed by a person' line (her words passed nothing: there was nothing to pass)",
                 "continues past block(s) the person passed", r.err)
    check_eq("R6: the exit gate holds no source-inventory line", (r.gate, r.gate_passed), ([], []))
    s.c.apply("dispatch", {"id": "S2", "stage": "S2", "role": "worker", "scope": ["TC-1"], "input_hash": "S2",
                           "budget": {}, "known_paths": {}, "idempotency_key": "dS2"})
    again = readers(s)
    all_close(again, "R7: after the S2 dispatch")
    check_eq("R7: no reader asks again (FR-7)", (again.ctl, again.pre, again.gate), (None, [], []))


def part_main_road():
    with story("qa-fb14-road-") as s:
        r1_before_any_word(s)
        r2_stamp_by_the_code(s)
        pair = r3_after_the_stamp(s)
        r4_accept(s, pair)
        r5_to_r7_after_the_accept(s)


# --------------------------------------------------------------------------------------------
# R8: the person's word about ONE source goes through `accept-gap` and reaches all four readers (I-2, I-3).
# --------------------------------------------------------------------------------------------
def two_media_gaps(inventory):
    """N-2: an `external_media` block that is `partial` with an unavailable item of a cause outside the defaults
    (`auth_required`) - with her block `read` the item is ignored and every reader passes before any word."""
    for item in inventory["sources"]:
        n = {PARENT: 12, STORY: 13}.get(item["source_id"])
        if n:
            item["materials"]["external_media"] = {"count": 1, "status": "partial", "items": [
                media(f"{GITLAB}/-/merge_requests/{n}", "unavailable", cause="auth_required", error="HTTP 401")]}


def part_word_per_source():
    import story_step
    with story("qa-fb14-word-", two_media_gaps) as s:
        check_in("R8: the stamp is made first", "receipts: 2 source(s) stamped", cli(s, "receipts").stdout)
        r = readers(s)
        check_eq("R8: before any word all four readers hold both media gaps",
                 (named(r, PARENT), named(r, STORY)), ((True,) * 4, (True,) * 4))
        parent_words = "The parent MR needs a login I do not have; go on without it."
        done = cli(s, "accept-gap", "--source-id", PARENT, "--words-file", word(s, "parent", parent_words))
        check_eq("R8a: the word for the parent is taken", (done.returncode, "accepted: TP2-1847" in done.stdout),
                 (0, True))
        r = readers(s)
        # I-3: a word covers exactly the sources it names - the parent's line is gone everywhere, the story's stands everywhere.
        check_eq("R8a: the parent's line is gone at all four readers, the story's stands at all four",
                 (named(r, PARENT), named(r, STORY)), ((False,) * 4, (True,) * 4))
        kept = sha(s)
        again = cli(s, "accept-gap", "--source-id", PARENT, "--words-file", word(s, "parent-again", parent_words))
        check_eq("R10e: the same word again is 'already accepted' and writes nothing (FR-7)",
                 (again.returncode, "already accepted: TP2-1847" in again.stdout, sha(s)), (0, True, kept))
        story_words = "The story MR is private; skip it."
        cli(s, "accept-gap", "--source-id", STORY, "--words-file", word(s, "story", story_words))
        r = readers(s)
        check_eq("R8b: the word for the story clears the last line - no reader refuses, stage_done's S1 verdict is gone",
                 blocked(r), (False,) * 4)
        # N-1: before the controller accepts S1, stage_done exits 2 on the controller barrier (F-3), so no exit code is read here.
        check_in("R8b: stage_done stops only at the controller barrier (pinned: F-3)", BARRIER, r.err)
        check_eq("R8b: the S1 accept is taken with the pair", accept(s, **story_step._s1_accepted_gaps(s.art)), None)
        r = readers(s)
        all_close(r, "R8c")
        check("R8c: stage_done prints both records with the person's words, and the feature's",
              all(text in r.err for text in (PARENT, parent_words, STORY, story_words, FEATURE)), r.err)


# --------------------------------------------------------------------------------------------
# R9: the person's word about a whole KIND of gap (`--cause`), recorded once, applied without a question (D-0043).
# --------------------------------------------------------------------------------------------
def part_word_per_class():
    def feature_unaccepted(inventory):
        inventory["sources"][0].pop("gap_acceptance")        # no point word for the feature: only the class word closes it

    with story("qa-fb14-class-", feature_unaccepted) as s:
        cli(s, "receipts")
        r = readers(s)
        check_eq("R9: before the class word all four readers refuse the unaccepted feature", blocked(r), (True,) * 4)
        check_eq("R9 (temporal): no class record exists before the word", (s.work / SI.GAP_CLASSES_FILE).exists(), False)
        words = "Every source that stays unavailable: go on without it."
        done = cli(s, "accept-gap", "--cause", "source_unavailable", "--words-file", word(s, "class", words))
        check_eq("R9: the class word is recorded as GC-1 and closes the feature now",
                 (done.returncode, "class recorded: GC-1 source_unavailable - closes 1 open point(s) now" in done.stdout),
                 (0, True))
        r = readers(s)
        check_eq("R9: no reader refuses after the class word (stage_done's S1 verdict is gone)", blocked(r), (False,) * 4)
        check("R9: the gap line carries whose word, which answer and when (D-0047)",
              len(r.gaps) == 1 and "on the basis of your answer GC-1 of " in r.gaps[0] and words in r.gaps[0], str(r.gaps))
        import story_step
        check_eq("R9: the S1 accept is taken with the pair", accept(s, **story_step._s1_accepted_gaps(s.art)), None)
        r = readers(s)
        all_close(r, "R9")
        check("R9: stage_done prints the basis of the class answer", "on the basis of your answer GC-1 of " in r.err
              and words in r.err, r.err)
        kept = (s.work / SI.GAP_CLASSES_FILE).read_bytes()
        again = cli(s, "accept-gap", "--cause", "source_unavailable", "--words-file", word(s, "class-again", words))
        check_eq("R9: the class word again changes nothing and nothing is asked (D-0043, FR-7)",
                 ("already recorded: GC-1" in again.stdout, (s.work / SI.GAP_CLASSES_FILE).read_bytes()), (True, kept))
        all_close(readers(s), "R9, second pass")


# --------------------------------------------------------------------------------------------
# R10: the negative twins. One UNSTAMPED story (her R1 state) serves (a), (b), the empty words, the red table and the F-3 pin.
# --------------------------------------------------------------------------------------------
SHOWN = "The factory has not yet written the receipt that it looked at this source."


def set_words(s, *pairs):
    """Replace `stage_overrides` of `pipeline.json` by `(stage, match)` words, each written in-process through
    `waiver.apply_stage_override` - the one writer of that record (no second hand-built copy of its shape)."""
    import waiver
    pipeline = json.loads(s.pipe.read_text(encoding="utf-8"))
    pipeline["stage_overrides"] = []
    for stage, match in pairs:
        waiver.apply_stage_override(pipeline, stage, match, "Go on, I decided.", "2026-10-20T01:00:00+00:00")
    s.pipe.write_text(json.dumps(pipeline), encoding="utf-8")


def twin_unknown_ids(s):
    # I-3: a word covers exactly the sources it names. A ticket key, a partial id and a foreign id name no source of the story.
    kept = sha(s)
    for label, sid in (("a ticket key", TASK), ("a partial id", "SRC-e01f"), ("a foreign id", "SRC-x9")):
        done = cli(s, "accept-gap", "--source-id", sid, "--words-file", word(s, "unknown", "Go on without it."))
        check_eq(f"R10a: {label} is refused, names the id given, and the inventory bytes are the same",
                 (done.returncode != 0, sid in done.stderr, sha(s)), (True, True, kept))


def twin_empty_words(s):
    # An empty word is no word (P13 needs a word): nothing is recorded, nothing is created. One file per form.
    kept = sha(s)
    folder = s.art / "state" / "words"
    folder.mkdir(parents=True, exist_ok=True)
    for n, (label, raw, scope) in enumerate((("zero bytes", b"", ("--source-id", PARENT)),
                                             ("a BOM only", b"\xef\xbb\xbf", ("--cause", "source_unavailable")),
                                             ("spaces only", b"  \r\n  ", ("--cause", "source_unavailable")))):
        (folder / f"empty-{n}.txt").write_bytes(raw)
        done = cli(s, "accept-gap", *scope, "--words-file", str(folder / f"empty-{n}.txt"))
        check_eq(f"edge: a words file of {label} - exit 2, 'is empty', nothing recorded",
                 (done.returncode, "is empty" in done.stderr, sha(s), (s.work / SI.GAP_CLASSES_FILE).exists()),
                 (2, True, kept, False))


def twin_other_words(s):
    line = readers(s).pre[0]
    # P13 is a word for THIS block: the S1 line quoted in a word of another stage passes nothing at S1, and an unrelated S1 word neither.
    for label, pairs in (("the full S1 line recorded for S5", (("S5", line),)),
                         ("an unrelated S1 word", (("S1", "stand gap: RP-frontend-jest"),))):
        set_words(s, *pairs)
        r = readers(s)
        check_eq(f"R10b: {label} - all four readers still refuse, nothing passed",
                 (blocked(r), r.passed, r.gate_passed), ((True,) * 4, [], []))


# N-3: a word names the sources it lifts by their WHOLE id, case-exact (I-3). It does not on `main`: `split_overridden` is a
# case-less substring and the shared line is ONE line for several sources. (case, the S1 word, ids whose lines must still block)
RED_CASES = (("a lower-case full id", STORY.lower(), (PARENT, STORY)),
             ("the story's own id, lifting the shared line", STORY, (PARENT,)))
# Dropped as vacuous (N-3): her key-shaped cases (a partial key, a key in a URL, an id inside a path, a foreign key) - the line
# carries ids, never keys, so they block on `main` for a reason that has nothing to do with whole-token matching.


# Fixed in release 0.10.8 (the red line said "if fixed, move this case"): a PARTIAL id lifts nothing - the word names a source by its whole id.
FIXED_CASES = (("a partial id", "SRC-e01f", (PARENT, STORY)),)


def fixed_table(s):
    for case, text, stands in FIXED_CASES:
        set_words(s, ("S1", text))
        r = readers(s)
        held = [all(any(i in line for line in lines) for i in stands) for lines in (r.pre, r.gate)]
        check_eq(f"I-3 {case}, word {text!r}: the lines of {len(stands)} source(s) keep blocking at stage_done and the gate",
                 (held, len(r.passed), len(r.gate_passed)), ([True, True], 0, 0))


def red_table(s):
    for case, text, stands in RED_CASES:
        set_words(s, ("S1", text))
        r = readers(s)
        held = [all(any(i in line for line in lines) for i in stands) for lines in (r.pre, r.gate)]
        seen = (f"stage_done blocking {len(r.pre)} passed {len(r.passed)}, gate blocking {len(r.gate)} "
                f"passed {len(r.gate_passed)}")
        check(f"EXPECTED-RED (I-3) {case}, word {text!r}: lines of {len(stands)} source(s) must keep blocking at stage_done "
              f"and the gate; observed {seen}", (held, len(r.passed), len(r.gate_passed)) == ([False, False], 1, 1),
              f"turned GREEN or lost the precondition ({held}, passed {len(r.passed)}, gate passed {len(r.gate_passed)}): "
              f"red means the WORD lifted the line at both readers; if fixed, move this case to the requirement assertions")


def pin_s1_waiver(s):
    # PINNED AS DESIGNED (batch 1 section L F-3, c31ba256): `waiver.py --stage S1` passes stage_done's check and the exit gate
    # but never the controller; the S1 accept is the barrier and stage_done stops there. A finding (the Lead files it at the
    # merge) asks for one meaning of that word; this pin records what `main` does today, it is not a requirement (I-6).
    set_words(s)
    done = run_script("waiver.py", "--task", TASK, "--stage", "S1", "--block", LACK,
                      "--words-file", word(s, "waiver", "Go on without the receipts."))
    r = readers(s)
    check_eq("F-3: the S1 waiver word is recorded and passes stage_done's check and the exit gate",
             (done.returncode, r.pre, len(r.passed), r.gate, len(r.gate_passed) > 0), (0, [], 1, [], True))
    check_eq("F-3: ...but the controller still refuses it and names the open sources", ctl_open(r.ctl), {PARENT, STORY})
    check_in("F-3: ...the S1 accept with a pair is refused at the inventory",
             "sources pending/invalid", accept(s, unresolved=["source receipts"], reason="Go on without the receipts.") or "")
    check_eq("F-3 barrier: stage_done then stops at the controller-managed barrier, not at its own S1 check",
             (BARRIER in r.err, "S1 source inventory incomplete" in r.err), (True, False))


def part_negative_twins():
    with story("qa-fb14-twins-") as s:
        twin_unknown_ids(s)
        twin_empty_words(s)
        twin_other_words(s)
        fixed_table(s)
        red_table(s)
        pin_s1_waiver(s)


def part_revision():
    # N-6: on an UNSTAMPED copy - after the stamp `source:not_inspected` is not a point any more. `_entry_in_force`: a work
    # word is for the revision it was given on; the source changed after the word, so the point is open again.
    with story("qa-fb14-rev-") as s:
        done = cli(s, "accept-gap", "--source-id", STORY, "--point", "source:not_inspected", "--shown-text", SHOWN,
                   "--words-file", word(s, "work", "The factory will look at it; go on."))
        check_eq("R10g: the word on the factory's own work point is taken as such (factory-owned)",
                 (done.returncode, "factory-owned: TP2-2406" in done.stdout), (0, True))
        opened = lambda: set(SI.completeness(SI.load_inventory(s.inv), **SI.class_kwargs(s.art))["open_points"])
        check_eq("R10g: after the word only the parent's work point is open", opened(), {PARENT})
        inventory = json.loads(s.inv.read_text(encoding="utf-8"))
        inventory["sources"][2]["revision"] = "2026-10-20T00:00:00.000+0000"
        s.inv.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
        check_eq("R10g: the story's revision changed after the word - its point is open again", opened(), {PARENT, STORY})


def part_other_bytes():
    # I-4: a receipt taken from other bytes does not count - not as a stamp, and not as a word (FR-59: integrity is not a guess).
    with story("qa-fb14-bytes-") as s:
        (s.work / sources(s)[STORY]["snapshot_ref"]).write_bytes(b'{"key": "SOMEONE-ELSE"}')
        done = cli(s, "receipts")
        items = sources(s)
        # N-7 (M-1 killer): the stamp fields of the story stay as they were, the parent's are written.
        check_eq("R10c: `receipts` stamps 1 (the parent); the story with other bytes keeps inspection_status pending, no stamp",
                 ("receipts: 1 source(s) stamped" in done.stdout, items[STORY]["inspection_status"],
                  "inspection_by" in items[STORY], items[PARENT].get("inspection_by")), (True, "pending", False, SI.STAMP_BY))
        r = readers(s)
        check("R10c: controller, stage_done's check and the gate all name the changed hash of the story",
              "content hash changed" in (r.ctl or "") and any("content hash changed" in x for x in r.pre) and bool(r.gate)
              and bool(r.sd_block), str(r.ctl))
        done = cli(s, "accept-gap", "--source-id", STORY, "--point", "source:not_inspected", "--shown-text", SHOWN,
                   "--words-file", word(s, "work", "Go on, the factory will look."))
        r = readers(s)
        check_eq("R10c: a word on the work point is taken, and the readers still refuse on the changed hash",
                 (done.returncode, "content hash changed" in (r.ctl or ""), blocked(r)), (0, True, (True,) * 4))


def main():
    part_main_road()
    part_word_per_source()
    part_word_per_class()
    part_negative_twins()
    part_revision()
    part_other_bytes()
    finish("test_fb14_real_state")


if __name__ == "__main__":
    main()
