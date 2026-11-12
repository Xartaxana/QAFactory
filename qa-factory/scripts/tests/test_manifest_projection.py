#!/usr/bin/env python3
"""A fragment the merge cannot take is refused before the commit; a committed event that cannot project is
named, never fatal; `manifest_put.py --recover` replays the journal (t-040).

TP2-2406, S5-4, 19.10.2026 (package 0.9.0+codex.20261019004233.75591514): the automator committed seven
`manifest_patch` events (journal seq 110-115, 117). Seq 115 renamed a test (sent the new spelling, retracted the
old one) and `_retract_instances` raised "names no row" AFTER the commit, inside the projection, because the new
row had already replaced the old one by alias. The event was durable and the projection was not, so every later
`manifest_put` replayed seq 115 and raised again: `work/automation-manifest.json` stayed at revision 5 while seq 117
sat in the journal, and the S5 exit gate refused for a `run_witness` the manifest could never receive. The
controller's `recover` rebuilt only the controller's projection and removed the one stale marker both shared.

The fixture is the REAL fragments of that journal, copied verbatim as data (compact JSON, nothing trimmed);
nothing under the live run is read at test time.

What is proved here, by invariant:
  * the real seven fragments go through `manifest_put.run` and every one commits and projects;
  * a merge refusal is raised BEFORE the commit: exit EXIT_BAD_FRAGMENT, the journal and the tree unchanged;
  * an event already in the journal whose merge raises is skipped and NAMED on the manifest (`unprojected_events`),
    `revision` counts merged events only, and the fold goes on; the fold never raises;
  * `--recover` replays the journal, writes only the projection and is idempotent;
  * the manifest's stale marker is its own, so the controller's recover cannot erase it.

HF3-2 (hotfix-12586/3, spec t-1248 part B): a retracted instance takes its Then rows with it, and the ghost of a retracted
instance is refused on a NEW write. The 2406 journal was written BEFORE that refusal, so seq 117 (the ghost) is committed
through the raw journal helper (`Stand.append_projected`) and A10-A19 are statements about the REPLAY of that journal; the
refusal itself is case Q (B-K3).
"""
import contextlib
import copy
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import event_store  # noqa: E402
import manifest_put as MP  # noqa: E402
from event_store import EventStore  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402

TASK = "TP2-2406"
CLASS_OLD = "BrownEvents.Tests.SessionFeedbackApiIntegrationTests."
CLASS_NEW = "BrownEvents.Tests.AttendeeDashboardIntegrationTests."
FUNCTION = "SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"
OLD, NEW = CLASS_OLD + FUNCTION, CLASS_NEW + FUNCTION
SERVICE = "BrownEvents.Tests.SessionFeedbackServiceTests."
TC1 = SERVICE + "SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee"
TC2 = SERVICE + "SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds"
NOBODY = "Nobody.Holds.ThisId[x]"

# journal seq -> the `payload.fragment` of that `manifest_patch` event, as the live run committed it
FRAGMENTS = {
    110: '{"tests":[{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","file":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs","marker":"TP2-2406_TC_001","covers":["TC-001"],"shape":"extend","consolidates":["TC-001"],"why":"Extends the existing service-test idiom with independent persistence read-back.","status":"green","obligation_ids":["OB-1"],"case_version_links":[{"case_id":"TC-001","version":"cv_4fb727314775ea39b564"}]},{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","file":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs","marker":"TP2-2406_TC_002","covers":["TC-002"],"shape":"extend","consolidates":["TC-002"],"why":"Extends the existing registration-denial test with before/after owned-pair reads.","status":"green","obligation_ids":["OB-2"],"case_version_links":[{"case_id":"TC-002","version":"cv_7edda3056fd4aff39ca6"}]},{"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","file":"backend/BrownEvents.Tests/SessionFeedbackApiIntegrationTests.cs","marker":"TP2-2406_TC_003","covers":["TC-003"],"shape":"new","consolidates":["TC-003"],"why":"A public HTTP boundary is required for the error-message and no-write contract.","status":"green","obligation_ids":["OB-3"],"case_version_links":[{"case_id":"TC-003","version":"cv_f128c110b97c91eb7962"}]}],"then_bindings":[{"case":"TC-001","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:79","status":"covered"},{"case":"TC-001","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:85","status":"covered"},{"case":"TC-002","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:105","status":"covered"},{"case":"TC-002","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:109","status":"covered"},{"case":"TC-003","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackApiIntegrationTests.cs:70","status":"covered"},{"case":"TC-003","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackApiIntegrationTests.cs:77","status":"covered"}],"unresolved":[{"case":"TC-004","reason":"blocked_by_env","detail":"No resettable PostgreSQL-backed integration harness is available; EF InMemory cannot prove the unique index.","instance_ids":[],"remedy":{"kind":"service","where":"docker-compose.yml","change":"provide a resettable PostgreSQL integration harness","restart":"start the harness before the scoped test run"}}]}',
    111: '{"tests":[{"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","file":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs","marker":"TP2-2406_TC_003","covers":["feedback-api/TC-003"],"shape":"new","consolidates":["feedback-api/TC-003"],"why":"A public HTTP boundary is required for the error-message and no-write contract.","status":"green","obligation_ids":["OB-3"],"case_version_links":[{"case_id":"TC-003","version":"cv_f128c110b97c91eb7962"}]}],"then_bindings":[{"case":"feedback-api/TC-003","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:181","status":"covered"},{"case":"feedback-api/TC-003","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:188","status":"covered"},{"case":"TC-004","then":1,"instance_id":null,"assertion_ref":null,"status":"unresolved","reason":"blocked_by_env","detail":"A resettable PostgreSQL harness is required to observe the duplicate result."},{"case":"TC-004","then":2,"instance_id":null,"assertion_ref":null,"status":"unresolved","reason":"blocked_by_env","detail":"A resettable PostgreSQL harness is required for the exact-pair query."}],"obligation_bindings":[{"obligation_id":"OB-1","instance_ids":["BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee"],"design_assessment":"sufficient","assertion_refs":["backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:81","backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:87"],"change_disposition":"new_or_changed","change_basis_ref":"manifest:TC-001","code_validity":"unverified","sensitivity":"missing"},{"obligation_id":"OB-2","instance_ids":["BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds"],"design_assessment":"sufficient","assertion_refs":["backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:109","backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:113"],"change_disposition":"new_or_changed","change_basis_ref":"manifest:TC-002","code_validity":"unverified","sensitivity":"missing"},{"obligation_id":"OB-3","instance_ids":["BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"],"design_assessment":"sufficient","assertion_refs":["backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:181","backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:188"],"change_disposition":"new_or_changed","change_basis_ref":"manifest:feedback-api/TC-003","code_validity":"unverified","sensitivity":"missing"},{"obligation_id":"OB-4","instance_ids":[],"design_assessment":"unknown","assertion_refs":[],"change_disposition":"unchanged","change_basis_ref":"manifest:TC-004","code_validity":"unverified","sensitivity":"not_required","quality_not_applicable_reason":"blocked_by_env"}]}',
    112: '{"tests":[{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","file":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs","selector":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","function":"SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","marker":"TP2-2406_TC_001","covers":["TC-001"],"shape":"extend","consolidates":["TC-001"],"why":"Extends the existing service-test idiom with independent persistence read-back.","status":"green","obligation_ids":["OB-1"],"case_version_links":[{"case_id":"TC-001","version":"cv_4fb727314775ea39b564"}]},{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","file":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs","selector":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","function":"SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","marker":"TP2-2406_TC_002","covers":["TC-002"],"shape":"extend","consolidates":["TC-002"],"why":"Extends the existing registration-denial test with before/after owned-pair reads.","status":"green","obligation_ids":["OB-2"],"case_version_links":[{"case_id":"TC-002","version":"cv_7edda3056fd4aff39ca6"}]},{"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","file":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs","selector":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","function":"SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","marker":"TP2-2406_TC_003","covers":["feedback-api/TC-003"],"shape":"new","consolidates":["feedback-api/TC-003"],"why":"A public HTTP boundary is required for the error-message and no-write contract.","status":"green","obligation_ids":["OB-3"],"case_version_links":[{"case_id":"TC-003","version":"cv_f128c110b97c91eb7962"}]}]}',
    113: '{"tests":[{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","selector_args":["--filter","FullyQualifiedName=BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee"],"report_test_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee"},{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","selector_args":["--filter","FullyQualifiedName=BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds"],"report_test_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds"},{"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","selector_args":["--filter","FullyQualifiedName=BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"],"report_test_id":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"}]}',
    114: '{"tests":[{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","status":"red"},{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","status":"red"},{"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","status":"red"}],"then_bindings":[{"case":"TC-001","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:81","status":"covered"},{"case":"TC-001","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:87","status":"covered"},{"case":"TC-002","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:109","status":"covered"},{"case":"TC-002","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","assertion_ref":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs:113","status":"covered"},{"case":"feedback-api/TC-003","then":1,"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:225","status":"covered"},{"case":"feedback-api/TC-003","then":2,"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:230","status":"covered"}]}',
    115: '{"retracted_instances":["BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"],"tests":[{"instance_id":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","file":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs","selector":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","function":"SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","marker":"TP2-2406_TC_003","covers":["feedback-api/TC-003"],"shape":"new","consolidates":["feedback-api/TC-003"],"why":"A public HTTP boundary is required for the error-message and no-write contract.","status":"red","obligation_ids":["OB-3"],"selector_args":["--filter","FullyQualifiedName=BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"],"report_test_id":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","case_version_links":[{"case_id":"TC-003","version":"cv_f128c110b97c91eb7962"}]}],"then_bindings":[{"case":"feedback-api/TC-003","then":1,"instance_id":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:225","status":"covered"},{"case":"feedback-api/TC-003","then":2,"instance_id":"BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","assertion_ref":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:230","status":"covered"}],"obligation_bindings":[{"obligation_id":"OB-3","instance_ids":["BrownEvents.Tests.AttendeeDashboardIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback"],"design_assessment":"sufficient","assertion_refs":["backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:225","backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs:230"],"change_disposition":"new_or_changed","change_basis_ref":"manifest:feedback-api/TC-003","code_validity":"unverified","sensitivity":"missing"}]}',
    117: '{"tests":[{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_PersistsNullCommentAndSubmissionTime_ForEndedRegisteredAttendee","case":"TC-001","file":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs","status":"red"},{"instance_id":"BrownEvents.Tests.SessionFeedbackServiceTests.SubmitAsync_DoesNotPersistFeedback_ForUnregisteredAttendeeAfterSessionEnds","case":"TC-002","file":"backend/BrownEvents.Tests/SessionFeedbackServiceTests.cs","status":"red"},{"instance_id":"BrownEvents.Tests.SessionFeedbackApiIntegrationTests.SubmitFeedback_ReturnsClearPreEndError_AndDoesNotPersistFeedback","case":"feedback-api/TC-003","file":"backend/BrownEvents.Tests/AttendeeDashboardIntegrationTests.cs","status":"red"}],"obligation_bindings":[{"obligation_id":"OB-4","instance_ids":[],"design_assessment":"unknown","assertion_refs":[],"change_disposition":"unchanged","change_basis_ref":"manifest:TC-004","code_validity":"unverified","sensitivity":"not_required","quality_not_applicable_reason":"blocked_by_env"}]}',
}


def fragment(seq: int) -> dict:
    return json.loads(FRAGMENTS[seq])


class Stand:
    """A temp project with one task root and a manifest store, the way `manifest_put.run` finds them."""

    def __enter__(self):
        self.root = harness.temp_project("qa-manifest-projection-")
        harness.use_project(self.root)
        self.task = self.root / "qa-factory" / "artifacts" / TASK
        (self.task / "work").mkdir(parents=True)
        (self.task / "pipeline.json").write_text(json.dumps({"ticket": TASK, "stages": {}, "gates": {}}),
                                                 encoding="utf-8")
        self.manifest_path = self.task / "work" / "automation-manifest.json"
        self.log = self.task / "state" / "events.jsonl"
        self.store = EventStore(self.task, stale_marker=MP.MANIFEST_STALE_MARKER)
        return self

    def __exit__(self, *_):
        harness.cleanup(self.root)

    def put(self, what) -> tuple:
        """(exit code, stdout, stderr) of `manifest_put.run` on a fragment (a dict, or JSON text)."""
        text = what if isinstance(what, str) else json.dumps(what)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = MP.run(TASK, text)
        return code, out.getvalue(), err.getvalue()

    def recover(self) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = MP.recover(TASK)
        return code, out.getvalue(), err.getvalue()

    def send(self, *seqs) -> list:
        return [self.put(fragment(seq))[0] for seq in seqs]

    def journal(self) -> int:
        return len(self.log.read_text(encoding="utf-8").splitlines()) if self.log.exists() else 0

    def manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def markers(self) -> list:
        return sorted(p.name for p in (self.task / "state").glob("*stale*"))

    def tree(self) -> dict:
        """Every file of the task root with its bytes' hash: what a refusal must leave as it found it."""
        import hashlib
        return {p.relative_to(self.task).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.task.rglob("*")) if p.is_file()}

    def append_unprojected(self, what: dict, key: str) -> dict:
        """Commit a `manifest_patch` straight through the store with NO projection: the state of a journal
        written before the pre-commit refusal existed (2406's), or by a raise nobody foresaw."""
        return self.store.commit("manifest_patch", what, key, project=None)

    def append_projected(self, what: dict, key: str) -> dict:
        """The same raw commit (no pre-commit refusal) WITH the projection `run` would have written: a journal line
        written before the refusal of a ghost existed, whose manifest file is current (HF3-2, B-K2)."""
        return self.store.commit("manifest_patch", what, key, project=MP.projector(self.manifest_path))


def rows_of(manifest: dict, case: str) -> list:
    return [t for t in manifest.get("tests") or [] if case in (t.get("covers") or [])]


def case_a_the_real_2406_journal():
    with Stand() as st:
        check_eq("A1: seq 110-114 commit and project, the revision the live run stopped at",
                 st.send(110, 111, 112, 113, 114), [0] * 5)
        check_eq("A1b: and the manifest is at revision 5", st.manifest()["revision"], 5)
        code, out, err = st.put(fragment(115))
        check_eq("A2: seq 115, the rename that raised AFTER its commit on 2406, commits and projects", code, 0)
        check_eq("A2b: and says nothing on stderr", err, "")
        m = st.manifest()
        check_eq("A3: the manifest moved to revision 6", m["revision"], 6)
        check_eq("A4: ONE row for feedback-api/TC-003 after the rename, three rows in all",
                 (len(rows_of(m, "feedback-api/TC-003")), len(m["tests"])), (1, 3))
        check_eq("A5: its instance id is the NEW spelling", rows_of(m, "feedback-api/TC-003")[0]["instance_id"], NEW)
        check_eq("A6: the old id stands once in retracted_instances", m.get("retracted_instances"), [OLD])
        bound = {b["obligation_id"]: b["instance_ids"] for b in m["obligation_bindings"]}
        check_eq("A7: OB-3 is bound to the NEW id", bound.get("OB-3"), [NEW])
        check("A8: a clean fold carries no unprojected_events key (a manifest without it reads as before)",
              "unprojected_events" not in m)
        check_eq("A9: no stale marker of either kind", st.markers(), [])
        # B-K1 (HF3-2): the rename of seq 115 takes the two Thens bound to the retired spelling, and `run` says so
        # (one computation with the projection, `removed_then_lines`).
        check_eq("B-K1: after seq 115 the manifest holds 8 then_bindings rows, none on OLD, two on NEW",
                 (len(m["then_bindings"]), sum(1 for b in m["then_bindings"] if b.get("instance_id") == OLD),
                  sum(1 for b in m["then_bindings"] if b.get("instance_id") == NEW)), (8, 0, 2))
        check_in("B-K1: the run on 115 names the first row it took out", f"feedback-api/TC-003 Then 1 on {OLD}", out)
        check_in("B-K1: ... and the second", f"feedback-api/TC-003 Then 2 on {OLD}", out)
        check_in("B-K1: ... under the block that says what was taken out", "then_bindings rows taken out by this send", out)
        check_eq("B-K1: the merge's own count is the summary key `then_rows_retired`",
                 MP.merge(MP.fold(st.store.read()[:-1]), fragment(115))[1].get("then_rows_retired"), 2)

        # HF3-2 (M4, B-K2): since the rule "a retracted instance takes its Then rows with it", `run` REFUSES this very
        # fragment (its third row is the ghost of OLD, see C-block B-K3). The journal of 2406 holds it all the same - it was
        # written before the refusal existed - so A10-A15, A18 and A19 are statements about the REPLAY of that journal, and
        # seq 117 is committed through the raw journal helper and projected by the fold, the way that journal was written.
        event = st.append_projected({"fragment": fragment(117)}, "manifest:real-2406-seq-117")
        check_eq("A10: seq 117 (OB-4, the case links), written before the refusal existed, projects: the manifest is no "
                 "longer stuck", (event["type"], st.markers()), ("manifest_patch", []))
        m = st.manifest()
        check_eq("A11: revision 7 - every committed event is a revision", (m["revision"], st.journal()), (7, 7))
        check_eq("A12: OB-1..OB-4 are all bound", sorted(b["obligation_id"] for b in m["obligation_bindings"]),
                 ["OB-1", "OB-2", "OB-3", "OB-4"])
        real = {t["instance_id"]: t for t in m["tests"] if t.get("covers")}
        check_eq("A13: the three real instances each keep their case link (the exit gate's 'no case links')",
                 sorted(real), sorted([TC1, TC2, NEW]))
        check("A13b: and every one carries case_version_links", all(t.get("case_version_links") for t in real.values()))
        check_eq("A14: the retraction history still holds the old id once", m.get("retracted_instances"), [OLD])
        check_eq("A15: unresolved holds TC-004 blocked_by_env",
                 [(u["case"], u["reason"]) for u in m["unresolved"]], [("TC-004", "blocked_by_env")])
        # 5a-K1 (t-085 spec A, FA-16 (b)) merged the array BY UNIT, so before HF3-2 the two OLD-id Thens of seq 114 outlived
        # seq 115's rename: 4 + 2 + 2 + 2 = 10 rows, and `s5_precheck` caught them as `unlinked-` until seq 117's ghost
        # hid the label. HF3-2 (B-K1; requirement: finding 20261026-otzyv-otmenyaet-then-i-prizrak-skryvaet-unlinked - a
        # retraction takes the Thens of the retired spelling, none is left bound to a test that is gone): seq 115 retires
        # the two OLD rows, because no remaining row wears the OLD spelling: 4 + 2 + 2 = 8, (10, 2, 2) -> (8, 0, 2).
        check_eq("A16: MEASURED - the retraction of seq 115 takes the old-spelling Then rows of seq 114 with it (HF3-2): "
                 "8 rows, none on OLD, two on NEW",
                 (len(m["then_bindings"]), sum(1 for b in m["then_bindings"] if b.get("instance_id") == OLD),
                  sum(1 for b in m["then_bindings"] if b.get("instance_id") == NEW)), (8, 0, 2))
        check("A17: the merge invents no run_witness: none of the seven fragments carried one", "run_witness" not in m)

        # MEASURED, not endorsed: 117 re-sends the OLD spelling (the role did not know it was retracted).
        ghost = [t for t in m["tests"] if t["instance_id"] == OLD]
        bound = (any(OLD in (b.get("instance_ids") or []) for b in m["obligation_bindings"])
                 or any(b.get("instance_id") == OLD for b in m["then_bindings"]))
        # HF3-2: the fifth element flipped True -> False (it was True under 5a-K1 only because the OLD Thens outlived the
        # rename): with no OLD Then row left the ghost is bound to nothing. The replayed journal still PROJECTS the ghost
        # (`merge` never raises on it); the refusal of such a row is for new writes (B-K3).
        check_eq("A18: MEASURED - seq 117 re-sending the retracted spelling, replayed from a journal written before the "
                 "refusal, lands as a FOURTH row: no covers, no version pin, bound to nothing (no obligation, no Then row) - "
                 "it is linked to feedback-api/TC-003 only through its own `case` - beside the NEW-spelling row that keeps "
                 "that case",
                 (len(m["tests"]), len(ghost), ghost[0].get("covers") if ghost else None,
                  ghost[0].get("case_version_links") if ghost else None, bound,
                  MP._links(ghost[0]) if ghost else None, rows_of(m, "feedback-api/TC-003")[0]["instance_id"]),
                 (4, 1, None, None, False, ["feedback-api/TC-003"], NEW))
        check("A18b: and it is the ONE predicate's ghost (`is_ghost_row`), which the precheck and the refusal both ask",
              MP.is_ghost_row(ghost[0], m) and not any(MP.is_ghost_row(t, m) for t in m["tests"] if t is not ghost[0]))
        code, out, err = st.put({"retracted_instances": [OLD]})
        m = st.manifest()
        check_eq("A19: FR-40 - the ghost has a door: retracting the id again drops that row (a row now exists)",
                 (code, [t["instance_id"] for t in m["tests"] if t["instance_id"] == OLD], len(m["tests"])), (0, [], 3))
        check_eq("A19b: and the history keeps the id once", m.get("retracted_instances"), [OLD])


def case_b_idempotent_replay():
    with Stand() as st:
        first = st.put(fragment(110))
        before, lines = st.manifest_path.read_bytes(), st.journal()
        again = st.put(fragment(110))
        check_eq("B1: the same fragment sent again is the store's reuse path: exit 0", again[0], 0)
        check_eq("B2: no new event", st.journal(), lines)
        check("B3: the manifest is byte-identical", st.manifest_path.read_bytes() == before)
        check_eq("B4: and the receipt printed is the committed event's own",
                 again[1].splitlines()[0], first[1].splitlines()[0])


def case_c_refusals_before_the_commit():
    with Stand() as st:
        st.send(110)
        lines, tree = st.journal(), st.tree()
        code, out, err = st.put({"retracted_instances": [NOBODY]})
        check_eq("C1: a retraction of an id nobody holds is refused with EXIT_BAD_FRAGMENT", code, MP.EXIT_BAD_FRAGMENT)
        check_in("C2: the refusal names the id", NOBODY, err)
        check_in("C3: and the merge's own words", "names no row this manifest holds", err)
        check_in("C4: and says nothing was committed", "nothing was committed", err)
        check_in("C5: and the role's repair marker (this is the role's to fix, not a person's)", REPAIR_MARKER, err)
        check_in("C6: and a door the role can run", f"manifest_put.py --task {TASK} --fragment", err)
        check_eq("C7: the journal line count is unchanged - NO event was appended", st.journal(), lines)
        check("C8: and nothing in the task root changed (validate writes nothing, FR-45)", st.tree() == tree)

        code, out, err = st.put({"unresolved": 5})
        check_eq("C9: a fragment whose merge raises something other than ValueError is refused the same way",
                 (code, st.journal()), (MP.EXIT_BAD_FRAGMENT, lines))
        check_in("C9b: and the refusal names the error type", "TypeError", err)

        code, out, err = st.put({"expected_revision": 99, "runs": [{"label": "w"}]})
        check_eq("C10: expected_revision is compared with the FOLDED revision: a wrong one is refused",
                 (code, st.journal()), (MP.EXIT_BAD_FRAGMENT, lines))
        check("C10b: and the refusal names both numbers and the door", "99" in err and "revision 1" in err
              and "manifest_view.py" in err, err)
        code, out, err = st.put({"expected_revision": 1, "runs": [{"label": "w"}]})
        check_eq("C11: POSITIVE CONTROL - the right expected_revision commits", (code, st.manifest()["revision"]), (0, 2))

        st.send(111, 112, 113, 114)
        st.put(fragment(115))
        lines = st.journal()
        code, out, err = st.put({"tests": [{"instance_id": NEW, "status": "green"}], "retracted_instances": [OLD]})
        check_eq("C12: an id an EARLIER revision already retired is still refused ('already gone')",
                 (code, st.journal()), (MP.EXIT_BAD_FRAGMENT, lines))
        check_in("C12b: with the merge's own words", "a row that is already gone is not retracted again", err)
        check_eq("C13: exit codes: a refused fragment and a committed-stale one are different answers",
                 MP.EXIT_BAD_FRAGMENT != MP.EXIT_COMMITTED_STALE and MP.EXIT_BAD_ARGS not in
                 (MP.EXIT_BAD_FRAGMENT, MP.EXIT_COMMITTED_STALE), True)


def case_d_and_e_committed_but_unprojected():
    with Stand() as st:
        st.send(110, 111, 112, 113, 114)
        bad = {"fragment": {"retracted_instances": [NOBODY]}}
        st.append_unprojected(bad, "manifest:test-names-no-row")
        st.append_unprojected({"note": "a payload with no fragment"}, "manifest:test-no-fragment")
        st.append_unprojected({"fragment": fragment(115)}, "manifest:test-later-good")
        check_eq("D0: three events are in the journal and the projection was never run for them",
                 (st.journal(), st.manifest()["revision"]), (8, 5))
        journal_bytes = st.log.read_bytes()
        code, out, err = st.recover()
        check_eq("D1: --recover exits 0", code, 0)
        check("D1b: and the journal is byte-identical afterwards: a historical event is never rewritten",
              st.log.read_bytes() == journal_bytes)
        m = st.manifest()
        check_eq("D2: revision counts the MERGED events only: five, plus the good one after the bad ones",
                 m["revision"], 6)
        gaps = m.get("unprojected_events") or []
        check_eq("D3: the two events that could not be merged are named by sequence and key",
                 [(g["sequence"], g["idempotency_key"]) for g in gaps],
                 [(6, "manifest:test-names-no-row"), (7, "manifest:test-no-fragment")])
        check_in("D4: with the merge's own error", "names no row this manifest holds", gaps[0]["error"])
        check_in("D4b: and, for a payload with no fragment, that error", "carries no `fragment` object", gaps[1]["error"])
        check_eq("D5: the later good event WAS merged (the fold goes on): the rename of 115 is in",
                 rows_of(m, "feedback-api/TC-003")[0]["instance_id"], NEW)
        check_eq("D6: the line says what was merged and what was not",
                 out.splitlines()[0].startswith("manifest: revision 6, 6 events merged, 2 unprojected: seq 6 ("), True)
        check_in("D6b: and names the second gap", "; seq 7 (", out)
        check_in("D6c: and tells the role what to do with them, with the whole command",
                 f"correct what the entry's error names and send it with `manifest_put.py --task {TASK} --fragment <file>`",
                 out)
        first = st.manifest_path.read_bytes()
        st.recover()
        check("D7: --recover twice gives a byte-identical file (idempotent)", st.manifest_path.read_bytes() == first)
        code, out, err = st.recover()
        check_eq("D8: the second run is a no-op that says so (FR-23), exit 0, and still prints the gaps (FR-41)",
                 (code, out.splitlines()[0].startswith("manifest: already current - revision 6, 6 events merged, 2 unprojected: seq 6 ("),
                  "stays listed as the journal's record" in out), (0, True, True))
        st.manifest_path.unlink()
        code, out, err = st.recover()
        check_eq("D9: the projection file absent altogether: --recover rebuilds it from the journal (not 'current')",
                 (code, st.manifest_path.read_bytes() == first, out.startswith("manifest: revision 6, 6 events merged")),
                 (0, True, True))
        st.manifest_path.write_bytes(b'{"revision": 1}')
        code, out, err = st.recover()
        check_eq("D10: a stale file is rewritten, byte-identical to the fold again",
                 (code, st.manifest_path.read_bytes() == first), (0, True))

        code, out, err = st.put({"expected_revision": 7, "runs": [{"label": "journal count"}]})
        check_eq("E0: expected_revision is the FILE's revision (merged events only), not the journal's length",
                 (code, st.journal()), (MP.EXIT_BAD_FRAGMENT, 8))
        code, out, err = st.put({"expected_revision": 6, "runs": [{"label": "after the gaps"}]})
        check_eq("E1: a later run commits and projects on that journal - it is not poisoned", code, 0)
        m = st.manifest()
        check_eq("E2: revision 7, the journal has 9 events", (m["revision"], st.journal()), (7, 9))
        check_eq("E3: the gaps are still on the manifest after a normal write (never silent)",
                 [g["sequence"] for g in m["unprojected_events"]], [6, 7])
        check_in("E4: and the run tells the role", "NOT in the manifest", out)


def case_f_the_manifests_own_marker():
    with Stand() as st:
        st.send(110)
        controller_marker = st.task / "state" / "projection-stale.json"
        controller_marker.write_text('{"revision": 0, "error": "the controller\'s own"}', encoding="utf-8")
        real = event_store.atomic_json

        def failing(path, value):
            if Path(path).name == "automation-manifest.json":
                raise OSError("simulated disk failure")
            return real(path, value)

        event_store.atomic_json = failing
        try:
            code, out, err = st.put(fragment(111))
        finally:
            event_store.atomic_json = real
        check_eq("F1: a commit whose projection fails exits EXIT_COMMITTED_STALE", code, MP.EXIT_COMMITTED_STALE)
        check_in("F2: the refusal names the door the role can run",
                 f"replay with manifest_put.py --task {TASK} --recover", err)
        check_in("F2b: and says the fragment is in the journal and is not to be sent again",
                 "the fragment is in the journal, do not send it again", err)
        check_eq("F3: the event is in the journal", st.journal(), 2)
        check_eq("F4: the manifest writes ITS marker; the controller's stays as it was",
                 st.markers(), ["manifest-projection-stale.json", "projection-stale.json"])
        check_in("F4b: and the controller's marker was not overwritten", "the controller's own",
                 controller_marker.read_text(encoding="utf-8"))

        EventStore(st.task).recover(lambda events: None)  # what `controller --operation recover` does to markers
        check_eq("F5: the controller's recover removes ITS marker and cannot erase the manifest's trace",
                 st.markers(), ["manifest-projection-stale.json"])
        code, out, err = st.recover()
        check_eq("F6: --recover rebuilds the manifest and clears its marker",
                 (code, st.markers(), st.manifest()["revision"]), (0, [], 2))
        check_in("F6b: and prints the line", "manifest: revision 2, 2 events merged", out)

        # the same marker is the one the reuse path clears: a repeat of the committed key re-projects
        event_store.atomic_json = failing
        try:
            st.put(fragment(112))
        finally:
            event_store.atomic_json = real
        check_eq("F7: setup - the second stale commit left the manifest's marker", st.markers(), ["manifest-projection-stale.json"])
        code, out, err = st.put(fragment(112))
        check_eq("F8: sending the committed fragment again re-projects through the reuse path and clears the marker",
                 (code, st.markers(), st.journal()), (0, [], 3))


def case_g_no_invented_witness():
    with Stand() as st:
        rows = {"tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001", "status": "green"}]}
        st.put(rows)
        check("G1: a fragment with rows and no run_witness merges and the projection carries none", "run_witness" not in st.manifest())
        st.put({"tests": [{"case": "TC-002", "file": "a.py", "marker": "TC-002", "status": "green"}],
                "runs": [{"label": "w2"}]})
        check("G2: and a second window does not invent one either", "run_witness" not in st.manifest())
        st.put({"run_witness": "evidence/w.json"})
        check_eq("G3: POSITIVE CONTROL - a fragment that carries one sets it", st.manifest().get("run_witness"), "evidence/w.json")
        # the fold is also asked directly: a journal of three fragments none of which carries one
        events = [{"sequence": i, "idempotency_key": f"k{i}", "type": "manifest_patch", "payload": {"fragment": rows}}
                  for i in (1, 2)]
        check("G4: the fold alone invents nothing", "run_witness" not in MP.fold(events))


def case_h_the_command_line():
    with Stand() as st:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(st.root))
        done = harness.run_script("manifest_put.py", "--task", TASK, "--recover", cwd=st.root, env=env)
        check_eq("H1: a journal with no manifest events: --recover prints 'nothing to project', exit 0",
                 (done.returncode, done.stdout.strip()), (0, "manifest: nothing to project"))
        check("H1b: and writes no manifest", not st.manifest_path.exists())
        st.send(110)
        lines, before = st.journal(), st.manifest_path.read_bytes()
        refused = harness.run_script("manifest_put.py", "--task", TASK, "--recover", "--fragment", "{}",
                                     cwd=st.root, env=env)
        check_eq("H2: --recover with --fragment is refused (one action per call): exit 2",
                 refused.returncode, MP.EXIT_BAD_ARGS)
        check_in("H2b: and the refusal names the way: recover first, then the fragment in a second call",
                 "takes no --fragment", refused.stderr)
        check("H2c: and nothing was written", st.journal() == lines and st.manifest_path.read_bytes() == before)
        refused = harness.run_script("manifest_put.py", "--recover", cwd=st.root, env=env)
        check_eq("H3: --recover without --task is refused: exit 2", refused.returncode, MP.EXIT_BAD_ARGS)
        done = harness.run_script("manifest_put.py", "--task", TASK, "--recover", cwd=st.root, env=env)
        check_eq("H4: --recover on a manifest the journal already adds up to: exit 0 and the null-outcome line",
                 (done.returncode, done.stdout.strip()), (0, "manifest: already current - revision 1, 1 events merged"))
        check("H4b: and the file is byte-identical to the one the commit wrote", st.manifest_path.read_bytes() == before)

        # the lock: --recover takes the same wait the CLI has for commits, and fails at once without one
        with st.store.lock():
            code, out, err = st.recover()
        check_eq("H5: a held writer lock with no wait: exit EXIT_COMMITTED_STALE, nothing written, the cause named",
                 (code, "active state writer" in err, st.manifest_path.read_bytes() == before),
                 (MP.EXIT_COMMITTED_STALE, True, True))
        seen = []
        real, argv = MP.recover, sys.argv
        MP.recover = lambda task, wait_seconds=0.0: seen.append(wait_seconds) or 0
        sys.argv = ["manifest_put.py", "--task", TASK, "--recover"]
        try:
            try:
                MP.main()
            except SystemExit as stop:
                check_eq("H6: main exits with recover's code", stop.code, 0)
        finally:
            MP.recover, sys.argv = real, argv
        check_eq("H6b: main hands --recover the lifecycle wait the commits use", seen, [event_store.LIFECYCLE_WAIT_SECONDS])


def case_i_the_fold():
    def event(seq, kind, payload):
        return {"sequence": seq, "idempotency_key": f"k{seq}", "type": kind, "payload": payload}

    good = {"tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001"}]}
    events = [event(1, "manifest_patch", {"fragment": good}),
              event(2, "controller_note", {"anything": 1}),
              event(3, "manifest_patch", {"fragment": {"retracted_instances": [NOBODY]}}),
              event(4, "manifest_patch", {"fragment": "not an object"}),
              event(5, "manifest_patch", None),
              event(6, "manifest_patch", {"fragment": {"unresolved": 5}}),
              event(7, "manifest_patch", {"fragment": {"runs": [{"label": "w"}]}})]
    snapshot = copy.deepcopy(events)
    folded = MP.fold(events)
    check_eq("I1: the fold never raises on a malformed or raising event; revision counts merged events only",
             folded.get("revision"), 2)
    check_eq("I2: every event it skipped is named, in order", [g["sequence"] for g in folded["unprojected_events"]],
             [3, 4, 5, 6])
    check_eq("I3: each gap carries the error type first",
             [g["error"].split(":")[0] for g in folded["unprojected_events"]],
             ["ValueError", "ValueError", "ValueError", "TypeError"])
    check("I4: the events are not touched (a fold writes nothing, not even into its input)", events == snapshot)
    check("I5: a non-manifest event is ignored, not unprojected", all(g["sequence"] != 2 for g in folded["unprojected_events"]))
    check_eq("I6: the same events fold to the same manifest", MP.fold(events), folded)
    check_eq("I7: an empty journal folds to an empty manifest", MP.fold([]), {})

    planted = MP.fold([event(1, "manifest_patch", {"fragment": {"unprojected_events": [{"sequence": 99}],
                                                                "runs": [{"label": "w"}]}})])
    check("I8: the list is REPLACED on every fold: a role cannot plant one, and an empty list is omitted",
          "unprojected_events" not in planted)
    seeded = MP.fold([event(1, "manifest_seed", {"manifest": {"revision": 4, "tests": []}}),
                      event(2, "manifest_patch", {"fragment": good})])
    check_eq("I9: a seed carries its revision into the fold, as before", seeded["revision"], 5)
    broken = MP.fold([event(1, "manifest_seed", {"manifest": "not an object"}), event(2, "manifest_patch", {"fragment": good})])
    check_eq("I10: a seed that is no object is named, and the patch after it still merges",
             (broken["revision"], [g["sequence"] for g in broken["unprojected_events"]]), (1, [1]))


def case_j_a_retraction_the_merge_already_satisfied():
    merged = {}
    for seq in (110, 111, 112, 113, 114):
        merged, _ = MP.merge(merged, fragment(seq))
    try:
        renamed, summary = MP.merge(merged, fragment(115))
        raised = ""
    except ValueError as exc:  # red, not a traceback, when the satisfied retraction is refused again
        renamed, summary, raised = merged, {}, str(exc)
    check_eq("J0: the merge of the real seq 115 does not raise", raised, "")
    check_eq("J1: the rename (new spelling sent, old retracted) no longer raises: one row for the case",
             [t["instance_id"] for t in renamed["tests"] if "feedback-api/TC-003" in (t.get("covers") or [])], [NEW])
    check_eq("J2: the old id is recorded once and the summary does not count a row nothing dropped",
             (renamed.get("retracted_instances"), summary.get("retracted_instances")), ([OLD], None))
    wrong = dict(fragment(115), retracted_instances=[NOBODY])
    try:
        MP.merge(merged, wrong)
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check_in("J3: an id the manifest never held still raises (a role's wrong id)", "names no row this manifest holds", refused)
    try:
        MP.merge(renamed, {"tests": [{"instance_id": NEW}], "retracted_instances": [OLD]})
        again = ""
    except ValueError as exc:
        again = str(exc)
    check_in("J4: an id an earlier revision already retired still raises", "already gone", again)
    try:
        MP._retract_instances({"tests": []}, {"retracted_instances": ["a[1]"]}, {})
        direct = ""
    except ValueError as exc:
        direct = str(exc)
    check_in("J5: a caller that passes no history of held rows (the 3-argument form) keeps the strict refusal",
             "names no row this manifest holds", direct)
    sibling = {"obligation_bindings": []}
    MP._retract_obligations(sibling, {"retracted_obligations": ["OB-9"]}, {})
    check_eq("J6: the sibling _retract_obligations has no such window: it records an absent id and never raises",
             sibling["retracted_obligations"], ["OB-9"])


def case_k_the_readers_of_the_marker():
    """The marker is read where the other two are: the audit (control plane + its stale check names the
    manifest's door) and the dashboard's stale flag."""
    import audit_factory as A
    import factory_dashboard as D
    from unittest.mock import patch
    check("K1: the audit's control plane holds the manifest's marker beside the controller's, and the environment jobs' "
          "(the three the dashboard flags: t-1253 F-8)",
          {"projection-stale.json", "environment-projection-stale.json", MP.MANIFEST_STALE_MARKER} <= A.CONTROL_PLANE)
    with Stand() as st:
        (st.task / "pipeline.json").write_text(json.dumps({"stages": {"S6": {"status": "done"}}}), encoding="utf-8")

        def findings() -> str:
            with patch.object(A, "artifact_root", return_value=st.task.parent), \
                    patch.object(A, "state_dir", return_value=st.root / "qa-factory"), \
                    patch.object(A, "FINDINGS", []), contextlib.redirect_stdout(io.StringIO()):
                A.a18_board_runs_row()
                return "\n".join(A.FINDINGS)

        door = f"manifest_put.py --task {TASK} --recover"
        check_not_in_text("K2: CONTROL - no marker, no manifest finding", door, findings())
        marker = st.task / "state" / MP.MANIFEST_STALE_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('{"revision": 1}', encoding="utf-8")
        check_in("K3: the audit names the manifest's own door when its marker stands", door, findings())
        flags = lambda: [t.get("projection_stale") for t in D.parse_taskruns(st.root)]  # noqa: E731
        check_eq("K4: the dashboard flags the task whose manifest projection is stale", flags(), [True])
        marker.unlink()
        check_eq("K5: CONTROL - and not when no marker stands", flags(), [False])
        # t-1253 F-8: the environment jobs' marker is read by the audit as the dashboard reads it
        environment = st.task / "state" / "environment-projection-stale.json"
        check_not_in_text("K6: CONTROL - no environment marker, no environment finding", "environment jobs projection",
                          findings())
        environment.write_text('{"error": "x"}', encoding="utf-8")
        check_in("K7: the audit names the environment jobs' projection when its marker stands",
                 f"{TASK}: the environment jobs projection is stale", findings())
        check_eq("K7b: and the dashboard flags the same task", flags(), [True])


def case_l_the_seed_commit_and_the_replay_tell_their_own_cause():
    """The critic's probe P3 (t-041, F1): a legacy manifest, a DIFFERENT archived copy and no manifest event.
    The seed commit's projection fails on the migration conflict BEFORE the fragment is committed; the text must
    not say the fragment is in the journal, and the replay must not name the busy-writer door for it."""
    legacy_manifest = {"revision": 1, "tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001"}]}

    def legacy_stand(st):
        (st.task / "automation-manifest.json").write_text(json.dumps(legacy_manifest), encoding="utf-8")
        archive = st.task / "state" / "migration" / "automation-manifest.json"
        archive.parent.mkdir(parents=True)
        archive.write_text(json.dumps({"revision": 9}), encoding="utf-8")

    with Stand() as st:
        legacy_stand(st)
        code, out, err = st.put({"runs": [{"label": "w"}]})
        kinds = [json.loads(line)["type"] for line in st.log.read_text(encoding="utf-8").splitlines()]
        check_eq("L1: the seed commit's stale projection is NOT exit 4 (no fragment is committed): "
                 "EXIT_BAD_FRAGMENT; the journal holds the seed and nothing else",
                 (code, kinds), (MP.EXIT_BAD_FRAGMENT, ["manifest_seed"]))
        check_in("L2: it says the fragment was NOT committed", "your fragment was NOT committed", err)
        check("L2b: and never says the fragment is in the journal, or not to be sent again",
              "in the journal, do not send it again" not in err and "do not send it again" not in err, err[:400])
        check("L3: it names BOTH files, and the replay and then the fragment as the way on",
              all(x in err for x in ("`automation-manifest.json`", "`state/migration/automation-manifest.json`",
                                     f"replay with manifest_put.py --task {TASK} --recover",
                                     f"manifest_put.py --task {TASK} --fragment <file>")), err[:600])
        check_eq("L3b: the manifest's own marker stands", st.markers(), ["manifest-projection-stale.json"])

        code, out, err = st.recover()
        check_eq("L4: --recover hits the same conflict: exit EXIT_COMMITTED_STALE, the journal unchanged",
                 (code, st.journal()), (MP.EXIT_COMMITTED_STALE, 1))
        check("L5: and names the two files and the orchestrator - NOT the busy-writer door",
              all(x in err for x in ("manifest migration conflict", "`state/migration/automation-manifest.json`",
                                     "tell the orchestrator")) and "busy" not in err and "in a moment" not in err,
              err[:600])

        code, out, err = st.put({"runs": [{"label": "w"}]})
        check_eq("L6: the same fragment again: now the seed is in, so the FRAGMENT commit is the stale one - exit 4 "
                 "and the 'is in the journal' text, with the files named (told apart by which commit raised)",
                 (code, st.journal(), "the fragment is in the journal, do not send it again" in err,
                  "`state/migration/automation-manifest.json`" in err), (MP.EXIT_COMMITTED_STALE, 2, True, True))

        (st.task / "state" / "migration" / "automation-manifest.json").write_bytes(
            (st.task / "automation-manifest.json").read_bytes())
        code, out, err = st.recover()
        check_eq("L7: once the person has settled the files, --recover works: exit 0, revision 2",
                 (code, st.markers(), st.manifest()["revision"]), (0, [], 2))

    with Stand() as st:
        legacy_stand(st)
        (st.task / "state" / "migration" / "automation-manifest.json").write_text(
            json.dumps(legacy_manifest), encoding="utf-8")
        code, out, err = st.put({"runs": [{"label": "w"}]})
        check_eq("L8: CONTROL - the same legacy manifest with an IDENTICAL archive seeds and commits: exit 0, 2 events",
                 (code, st.journal(), err), (0, 2, ""))

    with Stand() as st:
        st.send(110)
        with st.store.lock():
            code, out, err = st.recover()
        check("L9: a HELD lock: the busy-writer door, in words", code == MP.EXIT_COMMITTED_STALE
              and "The story writer is busy" in err and "in a moment" in err, err[:400])
        with st.log.open("ab") as f:
            f.write(b"not an event\n")
        code, out, err = st.recover()
        check("L10: a damaged journal is a StateConflict too, but NOT a busy writer: no 'in a moment', "
              "the orchestrator is named", code == MP.EXIT_COMMITTED_STALE and "corrupt event" in err
              and "not a busy writer" in err and "in a moment" not in err, err[:400])

    with Stand() as st:
        st.send(110)
        real = event_store.atomic_json

        def failing(path, value):
            if Path(path).name == "automation-manifest.json":
                raise OSError("simulated disk failure")
            return real(path, value)

        event_store.atomic_json = failing
        st.manifest_path.unlink()  # a manifest that is already current is not written again: the replay needs a file to rebuild
        try:
            code, out, err = st.recover()
        finally:
            event_store.atomic_json = real
        check("L11: a disk failure is neither: it prints its own words and a door that fits",
              code == MP.EXIT_COMMITTED_STALE and "simulated disk failure" in err and "disk" in err
              and "busy" not in err and "orchestrator" not in err, err[:400])


def case_m_the_story_root():
    """CX2-21: on main a journal is written only into a story folder that EXISTS (CX1-18): `--recover` resolves the
    story through the same driver `run` uses, and a phantom key is a refusal that creates nothing."""
    from hooklib import StoryRootError
    with Stand() as st:
        st.send(110)
        ghost, before = st.task.parent / "NOPE-1", st.tree()
        for name, call in (("recover", lambda: MP.recover("NOPE-1")), ("run", lambda: MP.run("NOPE-1", '{"runs": [{"label": "w"}]}'))):
            try:
                call()
                raised = None
            except StoryRootError as exc:
                raised = exc
            check(f"M1: {name} on a story key with no folder is a StoryRootError that creates nothing",
                  raised is not None and not ghost.exists() and st.tree() == before, repr(raised))


def case_n_a_refused_fragment_on_the_seed_path_writes_nothing():
    """t-1253 B-1 (the critic's probes of t-1250): a manifest exists (the legacy root-level one, or `work/`) and the
    journal holds no manifest event. The seed commit PROJECTS (it writes the manifest and moves a legacy file into
    `state/migration/`), so the fragment must be refused BEFORE it: a refusal that says "nothing was committed" with a
    journal line and moved files behind it is a false statement (FR-41)."""
    legacy_manifest = {"revision": 1, "tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001"}]}
    for label, where in (("a root-level legacy manifest", lambda st: st.task / "automation-manifest.json"),
                         ("a work/ manifest written before the journal existed", lambda st: st.manifest_path)):
        with Stand() as st:
            where(st).write_text(json.dumps(legacy_manifest), encoding="utf-8")
            lines, tree = st.journal(), st.tree()
            code, out, err = st.put({"retracted_instances": [NOBODY]})
            check_eq(f"N1 ({label}): an unmergeable fragment is refused, exit 3, and the journal gains no line",
                     (code, st.journal()), (MP.EXIT_BAD_FRAGMENT, lines))
            check(f"N2 ({label}): nothing in the task root changed - no seed event, no manifest rewritten, no legacy "
                  "file moved", st.tree() == tree, str(sorted(set(st.tree().items()) ^ set(tree.items()))))
            check_in(f"N3 ({label}): and the words 'nothing was committed' are TRUE", "nothing was committed", err)
            check_in(f"N3b ({label}): the merge's own words", "names no row this manifest holds", err)
            code, out, err = st.put({"expected_revision": 7, "runs": [{"label": "w"}]})
            check_eq(f"N4 ({label}): expected_revision is read against the SEED's revision and refused the same way",
                     (code, st.journal(), st.tree() == tree, "revision 1" in err),
                     (MP.EXIT_BAD_FRAGMENT, lines, True, True))
            code, out, err = st.put({"expected_revision": 1, "runs": [{"label": "w"}]})
            check_eq(f"N5 CONTROL ({label}): the right expected_revision on the same world commits the seed and the "
                     "fragment", (code, st.journal(), st.manifest()["revision"], st.markers()), (0, 2, 2, []))
            check("N5b CONTROL: and a legacy file is archived, not left beside the projection",
                  not (st.task / "automation-manifest.json").exists()
                  or (st.task / "state" / "migration" / "automation-manifest.json").exists())


def case_o_a_file_that_differs_in_type_or_order_is_not_current():
    """t-1253 F-1 (the critic's probe): `--recover` leaves a file alone only when it is what the projection would
    write. `1 == 1.0 == True` and a reordered file are EQUAL values; a type a hand edit or a foreign writer changed is a
    doubt (AR-28), and a doubt rebuilds."""
    with Stand() as st:
        st.send(110)
        first = st.manifest_path.read_bytes()
        standing = json.loads(first)
        check_eq("O0: setup - the revision is 1 (so that True and 1.0 equal it) and the file has several keys",
                 (standing["revision"], len(standing) > 2), (1, True))
        compact_reversed = json.dumps(dict(reversed(list(standing.items()))), separators=(",", ":"))
        for label, text in (("revision: true", json.dumps(dict(standing, revision=True))),
                            ("revision: 1.0", json.dumps(dict(standing, revision=1.0))),
                            ("compact, keys reversed", compact_reversed)):
            st.manifest_path.write_text(text, encoding="utf-8")
            code, out, err = st.recover()
            check_eq(f"O1 ({label}): --recover rebuilds it - not 'already current' - to the bytes the projection writes",
                     (code, out.startswith("manifest: already current"), st.manifest_path.read_bytes() == first),
                     (0, False, True))
        code, out, err = st.recover()
        check_eq("O2 CONTROL: the file the projection wrote is current and is left alone",
                 (code, out.startswith("manifest: already current - revision 1"), st.manifest_path.read_bytes() == first),
                 (0, True, True))


def case_p_the_exit_reader_and_the_one_door_text():
    """t-1253 F-3 (`outcome`, the ONE reader of the exit code for the five callers) and F-2 (one text for `run` and
    `--recover`, true before and after the corrected content is sent)."""
    check_eq("P1: exit 0 is committed", MP.outcome(0, TASK), ("committed", ""))
    check_eq("P2: exit 4 (committed, projection stale) is 'stale' and the move is the replay command",
             MP.outcome(MP.EXIT_COMMITTED_STALE, TASK), ("stale", f"manifest_put.py --task {TASK} --recover"))
    check_eq("P3: exit 3, 2 and any other code are 'refused' with no move",
             [MP.outcome(code, TASK) for code in (MP.EXIT_BAD_FRAGMENT, MP.EXIT_BAD_ARGS, 1, 5)], [("refused", "")] * 4)
    with Stand() as st:
        st.send(110)
        st.append_unprojected({"fragment": {"retracted_instances": [NOBODY]}}, "manifest:test-names-no-row")
        code, recovered, err = st.recover()
        corrected = {"tests": [{"instance_id": "new.t[y]", "case": "TC-009"}]}
        code, ran, err = st.put(corrected)
        check_eq("P4: the corrected content commits and the manifest holds its row",
                 (code, any(t.get("instance_id") == "new.t[y]" for t in st.manifest()["tests"])), (0, True))
        check_eq("P5: the earlier entry stays listed (a terminal trail today)",
                 [g["sequence"] for g in st.manifest()["unprojected_events"]], [2])
        door = MP._unprojected_door(TASK)
        for label, text in (("--recover (before the corrected send)", recovered), ("run (after it)", ran)):
            check_in(f"P6 ({label}): the one sentence of the door is printed", door, text)
            check("P6b: it names the whole command, and does not demand 'send it again'",
                  f"`manifest_put.py --task {TASK} --fragment <file>`" in text
                  and "send that content again" not in text and "send it again" not in text, text)
        code, again, err = st.recover()
        check_in("P7: a later --recover says the same sentence: the entry is a record, not a standing demand",
                 "stays listed as the journal's record", again)


def ghost_of_117() -> dict:
    """The third row of the real seq 117, the ghost of OLD, as a one-row fragment."""
    return {"tests": [t for t in fragment(117)["tests"] if t["instance_id"] == OLD]}


def case_q_a_ghost_is_refused_before_the_commit():
    """HF3-2 (F-3 (a), review t-1254 M2 / B-K3): after seq 115 retracted OLD, a send of OLD with no case links is the ghost
    that hid the `unlinked-` label on 2406. It is refused in `_refuse_unmergeable` (under the lock, `_MergeRefused`), with
    the doors; the same row WITH its links is the legitimate return of the name, a patch of a live row is not a ghost, and
    the journal of 2406, written before the refusal, still folds (A10-A19)."""
    with Stand() as st:
        st.send(110, 111, 112, 113, 114, 115)
        lines, tree = st.journal(), st.tree()
        code, out, err = st.put(fragment(117))
        check_eq("B-K3: the real seq 117 after seq 115 is refused: EXIT_BAD_FRAGMENT, no event, nothing changed",
                 (code, st.journal(), st.tree() == tree), (MP.EXIT_BAD_FRAGMENT, lines, True))
        for what, needle in (("the id", OLD), ("the view that lists the current spellings", f"manifest_view.py --task {TASK}"),
                             ("the links to send", "`covers` and `case_version_links`"), ("the repair marker", REPAIR_MARKER),
                             ("the word that nothing was committed", "nothing was committed"),
                             ("the rule's own words", "changes a test this manifest retracted")):
            check_in(f"B-K3: the refusal names {what}", needle, err)
        check("B-K3: ... and only the ghost, not the two live rows of the same fragment", TC1 not in err and TC2 not in err, err)

        # the same row, one field apart: each of LINK_FIELDS makes it a return of the name, not a ghost (M2 point 3)
        for field, value in (("covers", ["feedback-api/TC-003"]), ("case_links", ["feedback-api/TC-003"]),
                             ("case_version_links", [{"case_id": "TC-003", "version": "cv_f128c110b97c91eb7962"}]),
                             ("cases", ["feedback-api/TC-003"])):
            check_eq(f"B-K3 CONTROL ({field}): the ghost row carrying `{field}` is not a ghost",
                     MP.is_ghost_row(dict(ghost_of_117()["tests"][0], **{field: value}), st.manifest()), False)
        back = dict(ghost_of_117()["tests"][0], covers=["feedback-api/TC-003"],
                    case_version_links=[{"case_id": "TC-003", "version": "cv_f128c110b97c91eb7962"}])
        code, out, err = st.put({"tests": [back]})
        check_eq("B-K3 CONTROL: the same row with `covers` and `case_version_links` is the legitimate return of the name: it commits",
                 (code, err, st.journal()), (0, "", lines + 1))
        check_eq("B-K3 CONTROL: ... and the row stands beside the live one", sorted(t["instance_id"] for t in st.manifest()["tests"]),
                 sorted([TC1, TC2, NEW, OLD]))

    # the predicate on its own, by what the OTHER rows wear (M2 point 2): a retracted spelling that a live row still answers
    # to (the 0.7.7 case-prefixed one) is that row's, and a patch of it is a patch, not a ghost; with nobody else wearing it
    # the same link-less row IS one - whether it stands in the manifest (the precheck's ask) or in a fragment (the refusal's)
    live = {"instance_id": "test_x[eu]", "case": "TC-012", "file": "a.py", "covers": ["TC-012"], "status": "green"}
    manifest = {"tests": [live], "retracted_instances": ["TC-012::test_x[eu]"]}
    prefixed = {"instance_id": "TC-012::test_x[eu]", "status": "red"}
    check_eq("B-K3 CONTROL: a link-less patch under the retracted 0.7.7 spelling a LIVE row still wears is no ghost",
             MP.is_ghost_row(prefixed, manifest), False)
    check_eq("B-K3: ... the same patch is a ghost once nobody wears that spelling",
             MP.is_ghost_row(prefixed, dict(manifest, tests=[])), True)
    stands = {"tests": [dict(prefixed)], "retracted_instances": ["TC-012::test_x[eu]"]}
    check_eq("B-K3: ... and a link-less row that STANDS in the manifest is asked as it stands: a ghost (the precheck's ask); "
             "with a twin that wears its spelling, neither is", (MP.is_ghost_row(stands["tests"][0], stands),
                                                                   MP.is_ghost_row(stands["tests"][0],
                                                                                   dict(stands, tests=[*stands["tests"], live]))),
             (True, False))
    check_eq("B-K3 edge: rows that are no objects, no id, and a manifest that lists no retraction are never ghosts",
             [MP.is_ghost_row(None, {}), MP.is_ghost_row("x", {"retracted_instances": ["x"]}),
              MP.is_ghost_row({"status": "red"}, {"retracted_instances": [""]}),
              MP.is_ghost_row({"instance_id": "a[1]"}, {"retracted_instances": "a[1]"}),
              MP.is_ghost_row({"instance_id": "a[1]"}, {"tests": [None, 3]}),
              MP.is_ghost_row({"instance_id": "a[1]"}, None)], [False] * 6)


def check_not_in_text(name: str, needle: str, text: str) -> bool:
    return check(name, needle not in text, f"{needle!r} unexpectedly found in:\n{text[:400]}")


def main() -> None:
    case_k_the_readers_of_the_marker()
    case_a_the_real_2406_journal()
    case_b_idempotent_replay()
    case_c_refusals_before_the_commit()
    case_d_and_e_committed_but_unprojected()
    case_f_the_manifests_own_marker()
    case_g_no_invented_witness()
    case_h_the_command_line()
    case_i_the_fold()
    case_j_a_retraction_the_merge_already_satisfied()
    case_l_the_seed_commit_and_the_replay_tell_their_own_cause()
    case_m_the_story_root()
    case_n_a_refused_fragment_on_the_seed_path_writes_nothing()
    case_o_a_file_that_differs_in_type_or_order_is_not_current()
    case_p_the_exit_reader_and_the_one_door_text()
    case_q_a_ghost_is_refused_before_the_commit()
    finish("manifest projection (t-040, TP2-2406 S5-4)")


if __name__ == "__main__":
    main()
