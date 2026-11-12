#!/usr/bin/env python3
"""FR-40: every state the factory records has a sanctioned way out, and the walk names it.

`design/state-exits.md` is that walk. This holds it to the source in both directions:

  * every state the code can record has a row — the states are ENUMERATED from
    `controller.projection([])`, from `manifest_put`'s own merge keys and from `waiver.py`, so a
    new field cannot be added without deciding how a story leaves it;
  * every door the walk names exists — a controller operation in its own operation lists, a CLI
    flag in its script's parser, a subcommand in its subparsers, a test file on disk. Keyed on
    names, never on line numbers, the way the controller-blocks walk is held.

The one door this walk had to build is exercised here too: `waiver.py --revoke`. A person's word
passes any block, and before this there was no way to take that word back except editing
`pipeline.json` by hand.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import controller as CTRL  # noqa: E402
import manifest_put as MP  # noqa: E402
import waiver as W  # noqa: E402

WALK = harness.PLUGIN_ROOT / "design" / "state-exits.md"
ROW_RE = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|")
BACKTICK_RE = re.compile(r"`([^`]+)`")
# A state this walk deliberately does not own: bookkeeping of the record itself, not something a
# story can sit in and wait.
NOT_A_STATE = {"schema_version", "revision"}


def walk_text() -> str:
    check("design/state-exits.md is where the walk lives", WALK.is_file(), str(WALK))
    return WALK.read_text(encoding="utf-8") if WALK.is_file() else ""


def named_states(text: str) -> set:
    """The states the walk has a row for: the first backticked token of a table row."""
    out = set()
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if not match or match.group(1).startswith("-") or match.group(1) == "state":
            continue
        # Every backticked name in the first column, not only the first: one row may own two
        # states that leave the same way (`self_fixes[]`, `runs[]` are both append-only logs).
        for found in BACKTICK_RE.findall(match.group(1)):
            out.add(found.split("[")[0].split(".")[0].split("{")[0].strip())
    return out


def every_recorded_state_has_a_row(text: str) -> None:
    """The enumeration is the point: a new key in the projection breaks this until the walk
    says how a story leaves it. `projection([])` is the controller's own answer to "what does a
    story record", not a list copied into this test."""
    rows = named_states(text)
    state = CTRL.projection([])
    keys = sorted(set(state) - NOT_A_STATE)
    check("the controller's own projection is what is walked", len(keys) >= 10, str(keys))
    missing = [key for key in keys if key not in rows]
    check_eq(f"every state of controller.json has a way out in the walk ({len(keys)})", missing, [])
    # `known_paths` and `environment_jobs` join the state only later (initialize / the projection
    # merge), so they are named explicitly rather than read off an empty story.
    for late in ("known_paths", "environment_jobs"):
        check(f"{late} is walked too", late in rows, str(sorted(rows))[:200])
    # `BY_RECORD` holds the list of a test that changed after its red run (B-194). It is named
    # here as well as walked: a key dropped from the tuple would simply stop being enumerated.
    check("expectation_changes is a merge key of manifest_put",
          "expectation_changes" in MP.BY_RECORD, str(MP.BY_RECORD))
    check("introduced_helpers is a merge key of manifest_put (BY_HELPER)",
          "introduced_helpers" in MP.BY_HELPER, str(MP.BY_HELPER))
    check("provisional is a merge key of manifest_put (BY_ID, t-2181 PC-3)",
          "provisional" in MP.BY_ID, str(MP.BY_ID))
    for key in sorted(set(MP.BY_CASE) | set(MP.BY_INSTANCE) | set(MP.APPEND_ONLY) | set(MP.BY_RECORD)
                      | set(MP.BY_HELPER) | set(MP.BY_ID)):
        check(f"the manifest's {key}[] has a way out in the walk", key in rows,
              str(sorted(rows))[:200])
    for record in ("stage_overrides", "gate_waivers", "remarks"):
        check(f"what a person recorded in {record}[] has a way out", record in rows,
              str(sorted(rows))[:200])


def every_door_the_walk_names_exists(text: str) -> None:
    operations = set(CTRL.OPERATIONS)
    named_ops = set(re.findall(r"`(?:--operation )?([a-z_]+)`", text)) & {
        "accept", "checkpoint", "dispatch", "release", "request_cancel", "reconcile_dispatch",
        "invalidate", "semantic_reopen", "rework", "revise_plan", "policy", "mutation",
        "gate-decision", "handoff", "initialize", "resume"}
    check("the walk names at least a dozen controller doors", len(named_ops) >= 12,
          str(sorted(named_ops)))
    unknown = sorted(op for op in named_ops if op not in operations)
    check_eq("and every one of them is an operation the controller has", unknown, [])

    # The retraction keys, read out of manifest_put rather than out of this test.
    source = (harness.SCRIPTS / "manifest_put.py").read_text(encoding="utf-8")
    for key in ("retracted_instances", "retracted_obligations", "retracted_provisional"):
        check(f"{key} is a key manifest_put handles", f'"{key}"' in source, key)
        check("and the walk names it as the door", key in text, key)

    # The CLI doors: a flag in its own parser, a subcommand in its own subparsers.
    # `finish --unresolved` is the S5 window's own exit (B-207 P6-B): the critic's window that cannot
    # close is accepted as unresolved with its reason, and the walk names that command as the door.
    for script, flag in (("waiver.py", "--revoke"), ("stand_lease.py", "--release"),
                         ("manifest_put.py", "--fragment"), ("stage_done.py", "--status"),
                         ("story_step.py", "--unresolved")):
        body = (harness.SCRIPTS / script).read_text(encoding="utf-8")
        check(f"{script} {flag} exists", f'"{flag}"' in body, script)
        check(f"and the walk names {script} {flag}", flag in text and script in text, script)
    # The walk names the whole command, the pair together (`--reason` alone also sits in `pause`'s
    # parser, so the flag check above cannot stand for it); `test_story_step.py` runs it end to end.
    check("the S5 window's unresolved exit is named as the pair --unresolved <why> --reason",
          'finish --task <T> --dispatch-id <critic id> --digest "<digest>" --unresolved <why> --reason "<words>"'
          in text, "story_step.py finish --unresolved --reason")
    env = (harness.SCRIPTS / "environment_preparation.py").read_text(encoding="utf-8")
    check("environment_preparation.py has the reconcile subcommand",
          'add_parser("reconcile")' in env, "reconcile")
    check("and the walk names it", "reconcile --key" in text, "reconcile")

    # Every test named as the proof has to be a file, or the proof is a claim.
    named_tests = sorted(set(re.findall(r"`(test_[a-z0-9_]+\.py)`", text)))
    check("the walk names its proofs by file", len(named_tests) >= 15, str(len(named_tests)))
    absent = [name for name in named_tests if not (harness.SCRIPTS / "tests" / name).is_file()]
    check_eq("and every one of them exists", absent, [])


def the_door_this_walk_had_to_build() -> None:
    """`stage_overrides[]` had no way out: a person's word passed a block and nothing could take
    it back. The record stays — the story still shows the block was passed and when it stopped."""
    pipeline = {"task": "QA-40"}
    at = W.now_iso()
    W.apply_stage_override(pipeline, "S1", "video", "go on without the video", at)
    errors = ["source material unavailable: the video and two external links"]
    blocking, passed = W.split_overridden(errors, pipeline, "S1")
    check_eq("a person's word passes the block", blocking, [])
    check_eq("and the pass carries their words", [p["decision"] for p in passed],
             ["go on without the video"])

    W.revoke_stage_override(pipeline, "S1", "video", "the video is attached now, read it", at)
    blocking, passed = W.split_overridden(errors, pipeline, "S1")
    check_eq("revoked, it passes nothing", blocking, errors)
    check_eq("and nothing is reported as passed", passed, [])
    entry = pipeline["stage_overrides"][0]
    check_eq("the record of the pass survives the revocation", entry["decision"],
             "go on without the video")
    check_eq("with the words that took it back", entry["revoked_decision"],
             "the video is attached now, read it")
    check("and when", bool(entry.get("revoked_at")), str(entry))

    # A second override of the same stage, revoked by `*`: both are taken back, neither is lost.
    W.apply_stage_override(pipeline, "S1", "links", "the links are optional", at)
    W.revoke_stage_override(pipeline, "S1", "*", "all of it is available now", at)
    check_eq("`*` revokes every override of that stage",
             [bool(o.get("revoked_at")) for o in pipeline["stage_overrides"]], [True, True])
    check_eq("and every original decision is still on the record",
             [o["decision"] for o in pipeline["stage_overrides"]],
             ["go on without the video", "the links are optional"])


def a_manifest_row_leaves_by_its_own_door() -> None:
    """The door FR-40 was written from, exercised on manifest_put's own merge."""
    manifest = {"tests": [{"case": "TC-1", "instance_id": "test_a[x]", "status": "green"},
                          {"case": "TC-1", "instance_id": "test_a[y]", "status": "green"}],
                "obligation_bindings": [{"obligation_id": "R-1-OB1", "instance_id": "test_a[x]"}]}
    merged, _summary = MP.merge(dict(manifest), {"retracted_instances": ["test_a[y]"]})
    check_eq("a retracted instance leaves tests[] and its neighbours stay",
             [row["instance_id"] for row in merged["tests"]], ["test_a[x]"])
    merged, _summary = MP.merge(dict(manifest), {"retracted_obligations": ["R-1-OB1"]})
    check_eq("a retracted obligation leaves obligation_bindings[]",
             merged.get("obligation_bindings"), [])
    held = {"provisional": [{"id": "P-1", "status": "open"}, {"id": "P-2", "status": "open"}]}
    merged, _summary = MP.merge(held, {"retracted_provisional": ["P-1"]})
    check_eq("a retracted assumption stays as history with its status, its neighbour is untouched",
             [(row["id"], row["status"]) for row in merged["provisional"]], [("P-1", "retracted"), ("P-2", "open")])


def a_blocked_row_leaves_when_its_instance_goes_green(text: str) -> None:
    """t-219 (B8, FR-40): an instance the stand blocked sits in tests[] (not green) beside an `unresolved[]` row of
    reason `blocked_by_env`. The way out is the stand coming back: a GREEN tests[] entry of that instance through
    `manifest_put.py --fragment` drops its row - the row that names it in `instance_ids` loses the id (and goes when
    the list is empty), the row of the cmp2 shape (a partition, no instance) goes whole. Never on a verdict-only
    patch, never on a case with two instances (code does not guess which test was meant), and never by editing the
    caller's manifest in place."""
    fix = {"kind": "service", "where": "frontend", "change": "the page must load", "restart": "re-run"}
    red = {"case": "TC-1", "instance_id": "test_a[x]", "covers": ["TC-1"], "test": "test_a[x]", "status": "red"}
    green = {"tests": [{"case": "TC-1", "instance_id": "test_a[x]", "covers": ["TC-1"], "status": "green"}]}
    cmp2_shape = {"tests": [red], "unresolved": [{"case": "TC-1", "reason": "blocked_by_env", "partitions": ["p"],
                                                  "remedy": fix}]}
    merged, summary = MP.merge(cmp2_shape, green)
    check_eq("a green entry drops the partition-scoped blocked row of its only instance", merged["unresolved"], [])
    check_eq("the drop is counted as a move, the instance is in tests[]", (summary["moved"], len(merged["tests"])), (1, 1))
    check_eq("the manifest the caller passed in is not edited in place", len(cmp2_shape["unresolved"]), 1)
    merged, _ = MP.merge(cmp2_shape, {"tests": [{"case": "TC-1", "instance_id": "test_a[x]", "critic_verdict": "unverified"}]})
    check_eq("a verdict-only patch (no status) is not a run: the blocked row stays", len(merged["unresolved"]), 1)
    named = {"tests": [red, dict(red, instance_id="test_b[y]", test="test_b[y]")],
             "unresolved": [{"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_a[x]", "test_b[y]"],
                             "remedy": fix}]}
    merged, _ = MP.merge(named, green)
    check_eq("a row naming two instances loses the one that went green", merged["unresolved"][0]["instance_ids"],
             ["test_b[y]"])
    merged, _ = MP.merge(merged, {"tests": [{"case": "TC-1", "instance_id": "test_b[y]", "covers": ["TC-1"],
                                             "status": "green"}]})
    check_eq("and goes when the list is empty", merged["unresolved"], [])
    two = {"tests": [red, dict(red, instance_id="test_b[y]", test="test_b[y]")],
           "unresolved": cmp2_shape["unresolved"]}
    merged, _ = MP.merge(two, green)
    check_eq("a partition row on a case with TWO instances is never guessed at: it stays", len(merged["unresolved"]), 1)
    only_row = {"unresolved": [{"case": "TC-1", "reason": "blocked_by_env", "instance_ids": ["test_a[x]"],
                                "remedy": fix}]}
    merged, _ = MP.merge({"tests": [red]}, only_row)
    check_eq("a row that names instances is instance-scoped: it never takes the case's tests[] rows with it",
             [t["instance_id"] for t in merged["tests"]], ["test_a[x]"])
    # the walk names the way out, in the S5 row of the story's state
    line = next((ln for ln in text.splitlines() if ln.startswith("| an S5 window whose instances the stand blocked")), "")
    check("the walk has an S5 row for the blocked window", bool(line))
    for needle in ("window_record.py", "acceptable as unresolved", "story_step.py finish", "--unresolved blocked_by_env",
                   "manifest_put.py --fragment", "stand_gaps.py --gate B", "test_blocked_by_env_window.py"):
        check(f"and that row names `{needle}`", needle in line, line[:120])


def blocked_rows_name_all_their_instances() -> None:
    """t-219 fix wave (O1, O2, O4): what `manifest_put` keeps of a `blocked_by_env` row.

    O1: two blocked rows of ONE case in one fragment are the automator saying two tests of it are blocked - the
    row keeps both (`instance_ids`, in order, no repeats, `instance_id` normalised away); the last row alone used
    to win and left the first test a plain failure with no row. Across fragments the incoming naming REPLACES
    both keys (replace is the allowed error: a union would keep a later real red marked blocked); a patch that
    names nothing (a remedy fix) keeps the naming.
    O2: a patch with no `status` (the critic's `unverified` verdict) reads as green in the whole-case drop; a
    blocked row is exempt - only an explicit green drops it - while any other reason keeps today's reading.
    O4: one instance named by several blocked rows loses ALL of them when it goes green."""
    fix = {"kind": "service", "where": "frontend", "change": "the page must load", "restart": "re-run"}

    def row(case: str, **more) -> dict:
        return {"case": case, "reason": "blocked_by_env", "remedy": fix, **more}

    def naming(merged: dict) -> list:
        return [(r["case"], r.get("instance_ids"), "instance_id" in r) for r in merged["unresolved"]]

    # --- O1: inside one fragment
    merged, _ = MP.merge({}, {"unresolved": [row("TC-4", instance_id="t[a]"), row("TC-4", instance_id="t[b]")]})
    check_eq("O1: two blocked rows of one case in one fragment keep BOTH instances, as instance_ids",
             naming(merged), [("TC-4", ["t[a]", "t[b]"], False)])
    merged, _ = MP.merge({}, {"unresolved": [row("TC-4", instance_ids=["t[a]", "t[b]"]), row("TC-4", instance_id="t[c]"),
                                             row("TC-4", instance_ids=["t[b]", "t[d]"])]})
    check_eq("O1: a row with instance_id and rows with instance_ids: one list, order kept, no repeats",
             naming(merged), [("TC-4", ["t[a]", "t[b]", "t[c]", "t[d]"], False)])
    merged, _ = MP.merge({}, {"unresolved": [row("TC-4", instance_id="t[a]"), row("TC-5", instance_id="t[z]"),
                                             row("TC-4", instance_id="t[b]")]})
    check_eq("O1: rows of another case are not folded into it",
             sorted(naming(merged)), [("TC-4", ["t[a]", "t[b]"], False), ("TC-5", None, True)])
    merged, _ = MP.merge({}, {"unresolved": [row("TC-4"), row("TC-4", instance_id="t[a]")]})
    check_eq("O1: a row that names nothing adds nothing to the other's naming", naming(merged),
             [("TC-4", ["t[a]"], False)])
    merged, _ = MP.merge({}, {"unresolved": [row("TC-4", detail="first"), row("TC-4", detail="second")]})
    check_eq("O1: two blocked rows that name no instance: the later row stands as it was (no naming invented)",
             (naming(merged), merged["unresolved"][0]["detail"]), ([("TC-4", None, False)], "second"))
    other = {"case": "TC-4", "reason": "impossible", "detail": "d"}
    merged, _ = MP.merge({}, {"unresolved": [row("TC-4", instance_id="t[a]"), other]})
    check_eq("O1: a blocked row and a row of another reason are not unioned: the later wins as it always did",
             merged["unresolved"], [other])
    # --- O1: across fragments
    old = {"unresolved": [row("TC-4", instance_ids=["t[a]", "t[b]"])]}
    merged, _ = MP.merge(old, {"unresolved": [row("TC-4", instance_ids=["t[b]"])]})
    check_eq("O1: a later fragment naming [b] only REPLACES the naming: [b]", naming(merged), [("TC-4", ["t[b]"], False)])
    merged, _ = MP.merge({"unresolved": [row("TC-4", instance_id="t[a]")]}, {"unresolved": [row("TC-4", instance_ids=["t[b]"])]})
    check_eq("O1: an old instance_id does not survive beside the new instance_ids (no union by accident)",
             naming(merged), [("TC-4", ["t[b]"], False)])
    merged, _ = MP.merge({"unresolved": [row("TC-4", instance_ids=["t[a]", "t[b]"])]},
                         {"unresolved": [row("TC-4", instance_id="t[c]")]})
    check_eq("O1: a later single instance_id replaces the list too, normalised to instance_ids",
             naming(merged), [("TC-4", ["t[c]"], False)])
    better = dict(fix, where="frontend:5173")
    merged, _ = MP.merge(old, {"unresolved": [{"case": "TC-4", "reason": "blocked_by_env", "remedy": better}]})
    check_eq("O1: a patch that names nothing (a remedy fix) keeps the naming and changes the remedy",
             (naming(merged), merged["unresolved"][0]["remedy"]), ([("TC-4", ["t[a]", "t[b]"], False)], better))
    merged, _ = MP.merge({"unresolved": [row("TC-4")]}, {"unresolved": [row("TC-4", detail="more")]})
    check_eq("O1: a row on a single-instance case that names nothing stays naming nothing",
             naming(merged), [("TC-4", None, False)])
    # --- O2
    red = {"case": "TC-9", "instance_id": "t9[x]", "covers": ["TC-9"], "test": "t9[x]", "status": "red"}
    verdict = {"tests": [{"instance_id": "t9[x]", "case": "TC-9", "critic_verdict": "unverified"}]}
    merged, _ = MP.merge({"tests": [red], "unresolved": [row("TC-9")]}, verdict)
    check_eq("O2: a patch with no status (the critic's verdict) leaves the whole-case blocked row of its case",
             [r["case"] for r in merged["unresolved"]], ["TC-9"])
    check_eq("O2: and the verdict landed on the test row", merged["tests"][0]["critic_verdict"], "unverified")
    green9 = {"tests": [{"instance_id": "t9[x]", "case": "TC-9", "covers": ["TC-9"], "status": "green"}]}
    merged, _ = MP.merge({"tests": [red], "unresolved": [row("TC-9")]}, green9)
    check_eq("O2: an EXPLICIT green of that instance still drops the row (B8)", merged["unresolved"], [])
    merged, _ = MP.merge({"tests": [red], "unresolved": [{"case": "TC-9", "reason": "impossible", "detail": "d"}]}, verdict)
    check_eq("O2: any other reason keeps today's reading - a status-less patch drops the whole-case row (not widened)",
             merged["unresolved"], [])
    # --- O4
    wide = {"case": "TC-3", "instance_id": "t[a]", "covers": ["TC-3", "TC-4", "TC-5"], "test": "t[a]", "status": "red"}
    green = {"tests": [{"case": "TC-3", "instance_id": "t[a]", "covers": ["TC-3", "TC-4", "TC-5"], "status": "green"}]}
    three = {"tests": [wide], "unresolved": [row(c, instance_ids=["t[a]"]) for c in ("TC-3", "TC-4", "TC-5")]}
    merged, summary = MP.merge(three, green)
    check_eq("O4: one instance named by three blocked rows: a green drops ALL three", merged["unresolved"], [])
    check_eq("O4: each drop is counted as a move", summary["moved"], 3)
    check_eq("O4: the caller's manifest is not edited in place", len(three["unresolved"]), 3)
    sibling = dict(wide, case="TC-4", instance_id="t[b]", test="t[b]", covers=["TC-4"])
    mixed = {"tests": [wide, sibling], "unresolved": [row("TC-3", instance_ids=["t[a]"]),
                                                     row("TC-4", instance_ids=["t[a]", "t[b]"])]}
    merged, _ = MP.merge(mixed, green)
    check_eq("O4: a row naming two instances, one of which goes green, keeps the other (trim, not drop); the single goes",
             naming(merged), [("TC-4", ["t[b]"], False)])


def a_whole_case_blocked_row_goes_with_an_explicit_green() -> None:
    """t-219 F1 (critic t-243): the O2 exemption keeps a whole-case `blocked_by_env` row only from a patch with NO
    explicit status. An explicit `status: green` covering the case drops it as it did before O2 - the exemption had
    also kept it on a case of two instances whose tests BOTH went green, a stale row beside a green case.
    Invariant: a row never hides a real result; the allowed error is "not blocked" (a sibling still red then reads
    as a plain failure and says so), never a stale blocked row."""
    fix = {"kind": "service", "where": "frontend", "change": "the page must load", "restart": "re-run"}
    row = {"case": "TC-009", "reason": "blocked_by_env", "remedy": fix, "detail": "the edit page stayed on Loading"}

    def test(iid: str, **more) -> dict:
        return {"case": "TC-009", "instance_id": iid, "covers": ["TC-009"], "test": iid, **more}
    before = {"tests": [test("x[a]", status="red"), test("x[b]", status="red")], "unresolved": [row]}
    merged, summary = MP.merge(before, {"tests": [test("x[a]", status="green"), test("x[b]", status="green")]})
    check_eq("F1: both instances of a 2-instance case explicitly green: the whole-case blocked row is dropped",
             merged["unresolved"], [])
    check_eq("F1: the drop is counted as one move", summary["moved"], 1)
    check_eq("F1: the manifest the caller passed in is not edited in place", len(before["unresolved"]), 1)
    merged, summary = MP.merge(before, {"tests": [test("x[a]", status="green")]})
    check_eq("F1 control: ONE explicit green on a 2-instance case drops it too (the pre-O2 rule; the sibling reads as a "
             "plain failure)", (merged["unresolved"], summary["moved"]), ([], 1))
    check_eq("F1 control: a single instance explicitly green: dropped (B8)",
             MP.merge({"tests": [test("x[a]", status="red")], "unresolved": [row]},
                      {"tests": [test("x[a]", status="green")]})[0]["unresolved"], [])
    for label, patch in (("no status at all", {"tests": [test("x[a]", critic_verdict="unverified"),
                                                          test("x[b]", critic_verdict="unverified")]}),
                         ("an empty status", {"tests": [test("x[a]", status="", critic_verdict="unverified"),
                                                         test("x[b]", status=" ", critic_verdict="unverified")]})):
        merged, summary = MP.merge(before, patch)
        check_eq(f"F1 control: {label}: the whole-case blocked row survives (O2)",
                 ([r["case"] for r in merged["unresolved"]], summary["moved"]), (["TC-009"], 0))
    merged, _ = MP.merge(before, {"tests": [test("x[a]", critic_verdict="unverified"), test("x[b]", status="green")]})
    check_eq("F1: one explicit green among status-less entries is enough: the row goes",
             merged["unresolved"], [])
    other = dict(row, case="TC-010")
    merged, _ = MP.merge(dict(before, unresolved=[row, other]), {"tests": [test("x[a]", status="green")]})
    check_eq("F1: only the rows of the cases an explicit green covers go - another case's blocked row stays",
             [r["case"] for r in merged["unresolved"]], ["TC-010"])


def the_s6_manual_rows(text: str) -> None:
    """t-250 B2 (FR-40): the three states a manual-agent check can leave a story in - a case with no record, a
    refused `prepare`, an inconclusive record - each has a row, and each row names its door. The doors are held
    to the source, the way the other rows' are: the command exists, its flag is in its own parser, and the
    controller operation the refused-prepare row names is one the controller has."""
    rows = {
        "an S6 manual case with no record": ["manual_evidence.py build", "--result inconclusive", "--limitation",
                                             "manual_capture.py", "--attempt", "env_blocked", "the person's word"],
        "a refused `prepare`": ["request.json", "{refused: {reason, door}}", "semantic_reopen", "the person's answer",
                                "not checked by hand"],
        "an inconclusive record": ["--result inconclusive", "manual_capture.py", "--attempt", "the person's word",
                                   "never coverage"]}
    lines = text.splitlines()
    for label, needles in rows.items():
        row = next((ln for ln in lines if ln.startswith("| " + label)), "")
        check(f"the walk has an S6 row for `{label}`", bool(row), label)
        for needle in needles:
            check(f"and the row `{label}` names `{needle}`", needle in row, row[:120])
    capture = (harness.SCRIPTS / "manual_capture.py").read_text(encoding="utf-8")
    evidence = (harness.SCRIPTS / "manual_evidence.py").read_text(encoding="utf-8")
    for subcommand in ("http", "ui"):
        check(f"manual_capture.py has the `{subcommand}` subcommand", f'"{subcommand}"' in capture, subcommand)
    check("manual_capture.py takes --attempt (a new attempt is the way out of a written one)", '"--attempt"' in capture)
    check("manual_evidence.py has the `build` subcommand", '"build"' in evidence)
    for flag in ("--result", "--limitation", "--attempt", "--masked"):
        check(f"and `build` takes {flag}", f'"{flag}"' in evidence, flag)
    check("semantic_reopen is a controller operation", "semantic_reopen" in set(CTRL.OPERATIONS))
    # the states are real: the closed vocabularies of the record the rows speak of
    import manual_evidence as ME
    check("the new phase words are valid evidence phases, and the old ones still read",
          {"pre_action", "post_action", "before", "after"} <= ME.PHASES, str(ME.PHASES))


def the_findings_register_rows(text: str) -> None:
    """K-25 (N8, AR-25): the two states gate B adds - a finding the person confirmed (`person_confirmed`) and a question the person
    left open (`deferred_to_report` entered at gate B) - each has a row naming its entry, its way out and its test; the oracle word
    is one the writer holds, and the way out the row names exists."""
    import exploratory_findings as EF
    import question_register as QR
    lines = text.splitlines()
    rows = {"`oracle_status = person_confirmed`": ["Driver.take_exploratory_answers", "--by person", "question_register.py --reopen",
                                                   "exploratory_findings.py correct", "test_exploratory_answers.py"],
            "`deferred_to_report` entered at gate B": ["Driver.take_exploratory_answers", "question_register.record", "--reopen",
                                                       "exploratory_open", "test_exploratory_answers.py"]}
    for label, needles in rows.items():
        row = next((ln for ln in lines if ln.startswith("| " + label)), "")
        check(f"K-25 the findings register has a row for {label}", bool(row), label)
        for needle in needles:
            check(f"K-25 and the row {label} names `{needle}`", needle in row, row[:120])
    check("K-25 the state is one the writer holds (and a role is not offered it)",
          EF.PERSON_CONFIRMED in EF.ORACLES and EF.PERSON_CONFIRMED not in EF.ROLE_ORACLES, str(EF.ORACLES))
    check("K-25 the deferred state is one the question register records", QR.DEFERRED == "deferred_to_report")
    check("K-25 `--reopen` is a flag of the question register", '"--reopen"' in (harness.SCRIPTS / "question_register.py").read_text(encoding="utf-8"))


def main() -> None:
    text = walk_text()
    the_findings_register_rows(text)
    every_recorded_state_has_a_row(text)
    every_door_the_walk_names_exists(text)
    the_door_this_walk_had_to_build()
    a_manifest_row_leaves_by_its_own_door()
    a_blocked_row_leaves_when_its_instance_goes_green(text)
    blocked_rows_name_all_their_instances()
    a_whole_case_blocked_row_goes_with_an_explicit_green()
    the_s6_manual_rows(text)
    finish("test_state_exits")


if __name__ == "__main__":
    main()
