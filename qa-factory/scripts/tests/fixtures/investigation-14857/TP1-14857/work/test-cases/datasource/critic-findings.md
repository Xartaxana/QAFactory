# Round 1 - qa-case-critic S4-qa-case-critic-1, TP1-14857, area datasource

Verdict: approve_with_concerns

Dispatch: author S4-qa-case-designer-1, reviewer S4-qa-case-critic-1, input hash aef5db488877970ea02067a87a0e467cf95a6598bc153cba18790dc228d15856. Confidence: medium (testproject1 checkout lacks commit ed7d0291f911; the code under test was not opened, only the register, plan, understanding and the pinned cases).
Scope: plan rows with design_review_required = true: TS-2, TS-6, TS-7, TS-8, TS-9, TS-10, TS-11, TS-12 (TS-13/TS-14 are skip rows, no case). TC-001/003/004/005 (TS-1, 3, 4, 5, not design-review rows) were not reviewed. 8 of 8 dispatched rows reviewed.
Oracle: person's S1 decision, trigger-time stamping (register R-3). Sources read: test-plan.md, requirements-register.md (incl. contradiction matrix, reading forks), understanding.md, the eight pinned cases. Excluded: test-plan.json (long lines, plan.md view used), context-manifest.json, implementation diff.

## Dimension scores

| # | dimension | score | evidence |
|---|---|---|---|
| 1 | Coverage | pass | R-2/R-3/R-7 -> TC-002; R-16 -> TC-006; R-15 -> TC-007; R-13 -> TC-008; R-18/R-11 -> TC-009; R-19 -> TC-010; R-10/R-20 -> TC-011; R-9 -> TC-012. R-14 skip (TS-14), R-8/R-12 skip (TS-13) with reasons in the plan. |
| 2 | Atomicity | pass | one scenario per case; TC-012 and TC-011 hold several partitions, kept named (P-incremental, P-file-kb, P-svn; P-initial-code, P-initial-faq). |
| 3 | Clarity | concern | F-1, F-2 below. |
| 4 | Edge cases | pass | TC-002 mid-run read, TC-010 two zones plus minute rounding, TC-012 per entry point. |
| 5 | Negative scenarios | concern | F-3 below (TC-006 failure mechanism unspecified). |
| 6 | Traceability | pass | defect_class, priority, plan_row, covers match the plan rows (TS-2 order, TS-6 error-path, TS-7 state, TS-8 concurrency, TS-9 contract, TS-10 contract, TS-11 state, TS-12 state). |
| 7 | Completeness against plan | pass | every dispatched row has a case; if_answered branches are in each case's coverage table. |
| 7b | Not contradicted by sources | pass | R-2/R-3/R-7 contradiction is decided by the person (trigger time); TC-002 states AC-2 wording is not asserted. R-16 conflict (AC-1 vs MR non-goal) is raised, not resolved, in TC-006. No imported oracle values. |
| 8 | Seed the defect | pass | see below. |

## Seeded-defect analysis (proof_kind: design_analysis; nothing was executed, no observed_failure_ref)

| case | obligation | declared defect site | seeded defect | expected failure |
|---|---|---|---|---|
| TC-002 | OB-2-1 | order @ IndexInfo stamp vs process() completion (index.py:1135) | stamp written at completion (or not at all, the unfixed code) | Then 1 fails: early read E shows B0 while status in-progress. Stamp rewritten at completion: Then 2 fails (L != E). A run too fast to catch in-progress is inconclusive, not green. |
| TC-006..TC-012 | OB-6-1..OB-12-1 | n/a | probes by design: oracle open (then_oracles source unknown, question_thens a/b) | no verdict can fail; this is the plan's disposition (manual-agent). Each keeps the expected value open and invents none. Checked: no literal is asserted in any Then of TC-006..TC-012. |

## Findings

F-1 (TC-012, Then 1 / When 2, dimension 3, blocking: false). The probe's stated observation is "count of changes" / "moved a second time", and the self-probe note says double flattens is detected "by comparing reads before and after completion". The steps read the stamp only after COMPLETED plus one read after a pause. A trigger-time stamp followed by a second write at completion gives the same final value in both reads as a single stamp, so a double move is not observable as written. Expected: an early read during each run (as TC-002 step 2) is added to When, so the timeline B0 -> early -> late -> after pause is recorded per entry point. Check: When names a read taken while the status is in-progress for every partition (P-incremental, P-file-kb, P-svn), or the case drops "how often" from the title and Then.

F-2 (TC-002 and the other design-review cases, preconditions PC-2, dimension 3, blocking: false). `{"none": "build identity of the stand is known only to a person or the deploy pipeline"}` for "the backend build contains MR 4566". The plan itself says the stand may not contain the fix. If the stand exposes a version/build endpoint, a `{"http": ...}` check would do; the case does not record that a search for one was made. Expected: either an http check on the stand's version path, or a note in the precondition that a bounded search found none. Check: PC-2 carries a check other than `none`, or the reason line names where the search was made. Not raised on TC-007/008/009: their `none` preconditions (slot count, cron timing, provider stub) are recorded as "the agent searches first" and each case is inconclusive without them.

F-3 (TC-006, Given / When 1, precondition PC-1, dimension 5, blocking: false). The negative branch is "its source is made invalid by the case" (deleted branch or invalidated integration) with no stated mechanism. A harness client may not be able to delete a branch, and an invalidated integration may fail at the status check rather than during the reindex. The case does say a run that does not reach Failed is inconclusive, which stops a false pass, but reachability of the branch is not shown. Expected: the Given names the concrete way the failure is produced (for example, which API call edits the datasource or integration to a nonexistent branch or invalid credentials before the reindex), or states that none was found and the row is an environment gap. Check: step in Given/When that produces the failure through an API the harness has.

## Notes without a score

- TC-002 Then 2 uses `update_date` as the completion marker while a self-probe note says update_date is read as information only (R-8 not asserted). Not a defect: the stamp-before-completion ordering needs it; keep the note's wording consistent if edited.
- TC-007/008 depend on a known concurrency slot count; both cases mark the run inconclusive if installing is not reached. Residue of settlement datasources is the accepted risk named in the plan (`data_cleanup` not confirmed).
- All open-oracle cases carry question_thens with both readings; none invents an expected value.

## Roll-call

| plan row | case | reviewed | verdict | note |
|---|---|---|---|---|
| TS-2 | TC-002 | yes | approve_with_concerns | seeded defect fails Then 1/2; F-2 PC-2 build check |
| TS-6 | TC-006 | yes | approve_with_concerns | probe, oracle open; F-3 failure mechanism and reachability, F-2 not applicable |
| TS-7 | TC-007 | yes | approve | probe, oracle open (OQ-4); inconclusive without installing |
| TS-8 | TC-008 | yes | approve | probe, oracle open (OQ-6); inconclusive if the schedule does not fire |
| TS-9 | TC-009 | yes | approve | probe, oracle open (OQ-8); environment gap without a provider, not a pass |
| TS-10 | TC-010 | yes | approve | probe, oracle open (OQ-9); ui evidence policy stated |
| TS-11 | TC-011 | yes | approve | probe, oracle open (OQ-3); raw JSON read |
| TS-12 | TC-012 | yes | approve_with_concerns | probe, oracle open (OQ-5); F-1 double move not observable as written |
