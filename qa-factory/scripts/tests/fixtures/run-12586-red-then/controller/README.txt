Fixture controller/ (t-1541, key K-R2-S of spec t-1508 5.2; used by test_s5_plan_controller.k17).

Source (read only, 28.10.2026): artifacts/TP1-12586 of the stand run in the testproject1-dev-010 checkout
(testproject1-sdk/test-harness/qa-factory/artifacts/TP1-12586). Rebuild: `python -B build_fixture.py <that path>`.

What it is: the state of the run at 12:10:29 UTC, when `finish S5-qa-automator-5` (the author's plan rework) was refused for the
row bound. The events are cut at sequence 138 (the dispatch of S5-qa-automator-5, 12:08:44 UTC; sequence 139 is the checkpoint of
12:12:59), so the dispatch is open, as it was at the refusal. Besides the events: pipeline.json, state/plan-baseline.json,
work/s5-plan.json and work/s5-plan-reviews.json (the plan the author handed in and the critic's receipt), work/test-plan.json,
work/test-cases/ and state/case-versions/ (the case files the plan check reads), work/handoffs/S5-qa-code-critic-*.yaml
(the critic's forms the row bound reads). The directory is named for the ticket because the event store checks it.

Three changes to the bytes, all forced:
  - machine paths (t-1561, AR-4): the home folder of the machine the run was made on becomes `<home>` (user name included), a
    checkout under the working root becomes `<project>`, the host's transcript folder name becomes `<project-slug>`; the rest of
    each path stays. build_fixture.py does it (`machine_free`, `--rescrub` on the copy already here); nothing in the copy names a
    user or a drive layout of the machine;
  - Cyrillic is transliterated to Latin (the package is English, FR-30); the replaced text is a person's words and reasons in the
    events, pipeline.json and the case files, none of which a check reads by its wording;
  - the event chain is re-hashed over the changed payloads (event_store.content_hash), sequence and idempotency keys unchanged
    (the path replacement changes payload bytes too, so the chain is re-hashed after it as well).
Verified: on the unchanged copy of the same files the refusal is the same sentence the run printed ("the rework changed the rows of
TC-003, which no blocker of S5-qa-code-critic-1 names ..."); on this copy `_s5_plan_accept_problems` gives it, and gives none after
the word `plan rows by person: S5-qa-automator-5`.
