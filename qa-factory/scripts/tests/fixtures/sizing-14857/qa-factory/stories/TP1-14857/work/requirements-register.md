---
task: TP1-14857
created: 2026-10-26
ids: [R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14, R-15, R-16, R-17, R-18, R-19, R-20]
by_source: {story: 1, feature: 0, assumption: 0, discussion: 1, ac: 5, derived: 13}
confidence: low
---

<!-- Register for TP1-14857 (Closed Bug, fix delivered by testproject1 MR !4566; test MR !798 is an earlier QA run).
     Oracle policy (person's S1 decision, state/words/s1-decision-20261026-195804.txt): trigger-time stamping is the
     oracle for "Last indexed"; AC-2 wording "latest completed reindex operation" is kept as an open PO documentation
     question (OQ-1), the existing trigger-time implementation is NOT filed as a product bug. AC-4 and AC-5 stay open.
     confidence is low: the parent TP1-13289 is an composer epic with no AC, TP1-10937 plan.md/spec.md
     attachments were skipped_by_policy (not read), and foo_analytics_repo stand data is unreachable on local-docker.
     R-8..R-12 are implementation-only (derived from the diff) and are claims about the code, see Behaviour claims.
     R-13..R-20 are derived RISKS (failure modes FM-1..FM-8 of the scout), each with an evidence basis; none is a
     confirmed requirement and none supplies an expected value - the expected behaviour is an owner question. -->

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact | delta |
|---|---|---|---|---|---|---|---|---|
| R-1 | A successfully completed full reindex updates the repository's Last indexed timestamp (the stored `last_reindex_triggered_at` changes from the old value to a new one). | ac | - | yes | AC-1 | diff:src/testproject1/datasource/code/code_datasource_processor.py:221 | degraded | changed |
| R-2 | The displayed timestamp necessarily to the latest completed reindex operation (AC-2 verbatim; per the person's decision it is read as the latest reindex TRIGGER time, wording kept as OQ-1). | ac | - | yes | AC-2 | diff:src/testproject1/rest_api/models/index.py:1135 | degraded | changed |
| R-3 | Oracle decision: Last indexed equals the time the reindex was triggered (stamped before processing, `datetime.now()` at trigger), not the time it completed; this is not a product bug. | discussion | - | yes | - | diff:src/testproject1/rest_api/models/index.py:1135 | degraded | changed |
| R-4 | Refreshing or reopening the repository details does not restore an outdated timestamp (stamp is persisted by a targeted UPDATE and mirrored on the in-memory IndexInfo so a later full `update()` keeps it). | ac | - | yes | AC-3 | diff:src/testproject1/rest_api/models/index.py:1136 | degraded | changed |
| R-5 | The behavior is verified for foo_analytics_repo (AC-4 verbatim; this stand datasource is not in any diff and not on local-docker). | ac | - | no | AC-4 | none | degraded | new |
| R-6 | Existing timestamp updates for other repository indexing flows are not regressed (AC-5 verbatim; the AC names no flow). | ac | - | no | AC-5 | current-code:src/testproject1/triggers/actors/datasource.py:84 | degraded | unchanged |
| R-7 | After a successful full reindex, the Last indexed field displays the timestamp of the completed reindex operation (story Expected Result verbatim; conflicts with the trigger-time oracle R-3). | story | - | yes | - | diff:src/testproject1/rest_api/models/index.py:1135 | degraded | changed |
| R-8 | The manual-path stamp is written by a targeted UPDATE of `last_reindex_triggered_at` only: it does not bump `update_date`, so STALE health (`last_reindex_triggered_at > update_date`) stays meaningful. | derived | invariant:IV-1-stamp-does-not-bump-update_date | yes | - | diff:src/testproject1/rest_api/models/index.py:1136 | degraded | new |
| R-9 | Every manual reindex entry point stamps exactly once at trigger time: KB `schedule(func=...)` (full, incremental, resume, file-KB update), the code closure, the SVN service closure, the SVN router closure and the provider service. | derived | invariant:IV-2-every-manual-entry-point-stamps-once | yes | - | diff:src/testproject1/datasource/base_datasource_processor.py:135 | degraded | changed |
| R-10 | Plain `schedule(background_tasks)` (initial index creation, no `func`) does not stamp Last indexed. | derived | invariant:IV-3-creation-is-not-stamped | yes | - | current-code:src/testproject1/datasource/base_datasource_processor.py:118 | cosmetic | unchanged |
| R-11 | Provider datasource reindex: stamp is written after the update step and before the external call; status Started or InProgress starts progress; a synchronous Completed with no errors calls `complete_progress()`; errors go through `_handle_error`. | derived | invariant:IV-4-provider-reindex-completion-handling | yes | - | diff:src/testproject1/service/provider/datasource/provider_datasource_reindex_service.py:85 | degraded | changed |
| R-12 | A successful `process()` no longer assigns `last_reindex_triggered_at` in memory; the entry point's stamp is the only writer on the manual path. | derived | invariant:IV-5-process-success-does-not-rollout | yes | - | diff:src/testproject1/datasource/base_datasource_processor.py:229 | none | changed |
| R-13 | RISK FM-1: a scheduled (cron) code/SVN/KB reindex stamps by targeted SQL only; when no concurrency slot is free `set_queued()`/`clear_queued()` run a full `update()` that may write the stale in-memory `last_reindex_triggered_at` back over the new stamp. Expected value undefined (OQ-6). | derived | aspect:persistent and shared data | yes | - | current-code:src/testproject1/datasource/datasource_concurrency_manager.py:127 | degraded | unchanged |
| R-14 | RISK FM-2: SharePoint OAuth `_on_process_end` runs a full `self.index.update()`; on the scheduled path the in-memory stamp is stale and may overwrite the DB stamp. Expected value undefined (OQ-6). | derived | aspect:cross-team integration | yes | - | current-code:src/testproject1/datasource/sharepoint/sharepoint_datasource_processor.py:330 | degraded | unchanged |
| R-15 | RISK FM-3: a manual reindex of a queued index is stamped at `schedule()` while the run waits for a slot; Last indexed precedes real processing and a queue timeout can leave `last_reindex_triggered_at > update_date` (STALE). Trigger-time is decided (R-3); the STALE-on-timeout expectation is OQ-4. | derived | aspect:failure and error paths | yes | - | current-code:src/testproject1/datasource/datasource_concurrency_manager.py:126 | degraded | changed |
| R-16 | RISK FM-4: a failed or guardrail-blocked manual reindex still shows a new Last indexed (stamp is written before processing; AC-1 says "successfully completed"). Expected value undefined (OQ-4). | derived | aspect:failure and error paths | yes | - | current-code:src/testproject1/datasource/base_datasource_processor.py:248 | degraded | changed |
| R-17 | RISK FM-5: two cache manual unrounded of the same datasource: the second stamp must be the later one and a long-lived in-memory IndexInfo (KB `schedule()` uses `processor.index`) may overwrite the later DB value via a full `update()`. Later-trigger-wins is implied by AC-3 only. | derived | aspect:persistent and shared data | yes | - | current-code:src/testproject1/datasource/code/code_datasource_processor.py:218 | degraded | changed |
| R-18 | RISK FM-6: provider reindex returning a status other than Started, InProgress or Completed with no errors (e.g. Failed with an empty errors list) leaves the datasource neither in progress, completed nor errored. Provider contract not read (OQ-8). | derived | aspect:integrations with external systems | yes | - | current-code:src/testproject1/service/provider/datasource/provider_datasource_reindex_service.py:72 | degraded | changed |
| R-19 | RISK FM-7: the stamp is a naive server-local `datetime.now()` in a DateTime column; the UI `formatScheduleDate` may shift the displayed time (time zone / precision). Expected value undefined (OQ-9). | derived | aspect:inputs and validation | yes | - | current-code:../testproject1-ui/src/pages/dataSources/components/DataSourceDetails.tsx:825 | cosmetic | changed |
| R-20 | RISK FM-8: initial indexing (create) is not stamped, so Last indexed is absent until the first reindex; `DataSourceDetails.tsx:821` renders it only when truthy. Whether that is intended is OQ-3. Evidence: the earlier QA run's recon (MR 798 recon-report.md, preview stand) saw no Last indexed row on a never-reindexed Git datasource. | derived | aspect:failure and error paths | yes | - | current-code:src/testproject1/rest_api/routers/index/kb_atlassian.py:109 | cosmetic | unchanged |

<!-- manifest_gap: none -->

## Functions

| Function | Requirements |
|---|---|
| a manual reindex stamps Last indexed at the trigger | R-1, R-2, R-3, R-7, R-8, R-9, R-10, R-11, R-12, R-16, R-18, R-19, R-20 |
| the stamp holds: refresh, reopen and later writes do not bring back an old value | R-4, R-13, R-14, R-15, R-17 |

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | ok:TP1-14857 Steps 1-5 and AC-1 | ok:MR4566 spec.md Goal 1 | ok:UI-1 | n/a:TP1-15791 is a Duplicate of this ticket, no separate contract |
| R-2 | contradicts:"AC-2: The displayed timestamp necessarily to the latest completed reindex operation." (TP1-14857) vs "ts = datetime.now() ... values(last_reindex_triggered_at=ts)" taken at trigger time (index.py:1135) | contradicts:"AC-2: ... latest completed reindex operation" vs MR4566 commit message "stamp it at trigger time" and spec.md Non-goals "Switching the value to completion time" | ok:UI-1 asserts trigger time | n/a:TP1-15791 duplicate |
| R-3 | contradicts:"Expected Result: ... displays the timestamp of the completed reindex operation." (TP1-14857) vs "Per the confirmed AC-2 resolution, 'Last indexed' is the reindex trigger time, not the completion time." (MR798 test docstring, person decision s1-decision-20261026-195804) | ok:MR4566 spec.md Non-goals | ok:UI-1 | silent |
| R-4 | ok:TP1-14857 AC-3 and Step 4 | ok:MR4566 spec.md Constraints "No navigation" | ok:UT-3 | silent |
| R-5 | silent | silent | n/a:no case can reference stand data foo_analytics_repo | silent |
| R-6 | silent | silent | ok:UI-2 | n/a:TP1-12034 and TP1-12780 scheduler defects carry no timestamp contract (scout reassessment) |
| R-7 | contradicts:"Expected Result: ... displays the timestamp of the completed reindex operation." (TP1-14857) vs "ts = datetime.now()" at trigger time (index.py:1135) | contradicts:same Expected Result vs MR4566 spec.md "Switching the value to completion time" listed as a non-goal | ok:UI-1 | silent |
| R-8 | silent | silent | ok:UT-3 | silent |
| R-9 | silent | silent | ok:UT-2 | silent |
| R-10 | silent | silent | ok:UT-2 | n/a:no open bug mentions initial indexing |
| R-11 | silent | silent | ok:UT-6 | silent |
| R-12 | silent | silent | ok:UT-2 | silent |
| R-13 | silent | silent | silent | n/a:TP1-12034, TP1-13171 scheduler trigger defects, not the queue/stamp interaction |
| R-14 | silent | silent | silent | silent |
| R-15 | silent | silent | silent | silent |
| R-16 | silent | contradicts:"Whether failed or guardrail-blocked runs should move 'Last indexed'" is a non-goal (MR4566 spec.md) vs AC-1 "A successfully completed full reindex updates ... timestamp" | silent | silent |
| R-17 | silent | silent | silent | silent |
| R-18 | silent | silent | ok:UT-6 covers Started/InProgress/Completed/errors only | silent |
| R-19 | silent | silent | silent | silent |
| R-20 | silent | silent | silent | silent |

<!-- R-2, R-3, R-7 contradictions are DECIDED by the person (trigger-time oracle); they stay visible as OQ-1 (minor,
     PO documentation question) and are not a blocker. R-16 is raised as OQ-4. -->

## Behaviour claims

| R | before | before_ref | now | now_ref | differs | question | origin |
|---|---|---|---|---|---|---|---|
| R-8 | absent: manual reindex wrote no stamp at all | absent | stamp via targeted UPDATE, update_date untouched | diff:src/testproject1/rest_api/models/index.py:1136 | yes | OQ-7 | |
| R-9 | absent: manual reindex entry points did not stamp (Last indexed stayed outdated) | absent | each manual entry point stamps once at trigger and mirrors it in memory | diff:src/testproject1/datasource/base_datasource_processor.py:135 | yes | OQ-7 | |
| R-11 | Started only started progress; no stamp; no complete_progress | diff:-src/testproject1/service/provider/datasource/provider_datasource_reindex_service.py:81 | stamp before external call; Started/InProgress start progress; Completed completes | diff:src/testproject1/service/provider/datasource/provider_datasource_reindex_service.py:85 | yes | OQ-7 | |
| R-12 | success path assigned last_reindex_triggered_at = datetime.now() in memory only | diff:-src/testproject1/datasource/base_datasource_processor.py:224 | assignment removed | diff:src/testproject1/datasource/base_datasource_processor.py:229 | yes | OQ-7 | |

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-2 | AC-2 means the latest completed reindex operation's completion time | AC-2 is stale; trigger time is meant | A reindex running longer than a minute shows a different value; under A the shipped code would be a defect | reading B adopted per person's S1 decision; wording question OQ-1 stays open for the PO |
| R-1 | "successfully completed" gates the update: a failed run must not move Last indexed | the stamp is written at trigger, success is not checked | A failed or blocked reindex shows a fresh Last indexed (R-16) | question at gate A (OQ-4); trigger-time stamp is not filed as a bug |
| R-9 | Only a full reindex moves Last indexed (ticket title and AC-1 say "full reindex") | any manual schedule(func) moves it: resume, incremental, file-KB update (MR spec Goal 1) | Resuming an interrupted index moves Last indexed without a new full index | question at gate A (OQ-5) |
| R-6 | "other repository indexing flows" = flows that stamped before (scheduled actors, watchdog resume) | all datasource types and triggers incl. initial indexing | Proceeding whether R-13, R-14, R-20 count as regressions | question at gate A (OQ-3) |
| R-5 | foo_analytics_repo on a stand where it exists | any equivalent code datasource on local-docker | AC-4 stays unverified on local-docker under reading A | question at gate A (OQ-2) |

## Source completeness

| source | relation | relevance | assessment receipt | full-read receipt | revision/hash | status | gap or exclusion reason |
|---|---|---|---|---|---|---|---|
| TP1-14857 | task | relevant | work/source-inventory.json SRC-060145c7e93542a69692 | work/ticket-view.md | 2026-10-22T14:17:45.340+0000 | read | the single comment is an automated complexity assessment, not a requirement |
| TP1-15791 | referenced | relevant | work/source-inventory.json SRC-5a93606917e1f7d2c56b | work/source-inventory.json | 2026-10-20T15:32:33.416+0000 | read | Duplicate of this ticket |
| TP1-10937 | referenced | relevant | work/source-inventory.json SRC-e3b288d3ebe1bb04b0c6 | work/source-inventory.json | 2026-10-23T10:38:43.013+0000 | read | plan.md and spec.md attachments skipped_by_policy:type, not read; scheduler defect, not this ticket's contract |
| TP1-13289 | parent | not_relevant | work/context-manifest.json parent_feature | work/context-manifest.json | n/a | read | composer epic, no AC |
| MR testproject1!4566 | referenced | relevant | work/mr-testproject1-4566.json | work/impl-diff-testproject1.txt (1348 lines, all read) | ed7d0291f911e4b5d01aa72dfe60cb421145c2f6 | read | production diff 6 files; docs, Makefile and .gitleaks.toml hunks are not behaviour |
| MR testproject1-sdk!798 | referenced | relevant | work/mr-tests-798.json | work/impl-diff-tests.txt | 1cdc715d942112521e728a40360a59a2334565b4 | read | earlier QA run; lines 1201-1927 embed a copy of the testproject1 diff and 2200-2560 are run-log text, spot-checked not line-read |
| testproject1-ui DataSourceDetails.tsx:821-825 | normative | relevant | work/context-manifest.json observables | work/context-manifest.json | main | read | read by the scout, not re-opened here |
