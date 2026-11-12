---
task: TP1-15045
created: 2026-09-20
ids: [R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14, R-15]
by_source: {story: 2, feature: 2, assumption: 0, discussion: 0, ac: 9, derived: 2}
confidence: low
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable |
|---|---|---|---|---|---|---|
| R-1 | Toolbar Version History button opens a popup with one visual node-graph diff; YAML diff is a separate popup from the YAML panel (two entry points, no toggle) | ac | — | yes | AC-1 | diff:src/pages/workflows/editor/EditorActions.tsx:130 |
| R-2 | Visual diff modal renders one node graph for the target revision with one set of zoom in/out, fit-view and drag-to-pan controls | ac | — | yes | AC-2 | diff:src/pages/workflows/editor/DiffCanvasControls.tsx:103 |
| R-3 | Node in target revision but not in the compared version is shown with green border/marker (added) | ac | — | yes | AC-3 | diff:src/pages/workflows/editor/nodes/diffChromeContext.ts:22 |
| R-4 | Node removed vs compared version is shown at its former position with red border, REMOVED badge above, strikethrough label | ac | — | yes | AC-4 | diff:src/utils/workflowEditor/buildVisualDiffGraph.ts:130 |
| R-5 | Node in both with differing config is shown with amber/distinct border as modified, without exposing changed values inline | ac | — | yes | AC-5 | diff:src/pages/workflows/editor/nodes/diffChromeContext.ts:24 |
| R-6 | Visual diff is read-only (no drag of nodes, no selection/edit) | ac | — | yes | AC-6 | diff:src/pages/workflows/components/WorkflowVisualDiffView.tsx:94 |
| R-7 | Visual diff always compares exactly two revisions at a time; the editor buffer is only a convenience holder for one of the two (owner answer Q1). Code compares the selected revision with the current editor YAML (WorkflowVisualVersionHistoryPopup.tsx:62), consistent only if the buffer holds a revision | ac | — | yes | AC-6 | diff:src/pages/workflows/components/WorkflowVisualVersionHistoryPopup.tsx:62 |
| R-8 | Visual diff is an alternative alongside, not replacing, the textual diff (textual diff still works) | ac | — | yes | AC-6 | diff:src/pages/workflows/components/WorkflowVersionHistoryPopup.tsx:55 |
| R-9 | Restoring a version from the YAML or Visual popup runs Save-equivalent validation in background on restored content; issues shown inline; restore not reverted; nothing persisted | ac | — | yes | AC-7 | diff:src/pages/workflows/useWorkflowHistoryRestore.ts:82 |
| R-10 | POST /v1/workflows/{id}/validate runs the full pre-persist pipeline (MCP access control, autonomous-mode guard, executor validation, guardrail existence/project/permission); 200 with advisory warnings or the same structured errors as update | feature | — | yes | TR-1 | diff:src/testproject1/rest_api/routers/workflow.py:575 |
| R-11 | Validate endpoint performs no database write (full dry-run) | feature | — | yes | TR-2 | diff:src/testproject1/rest_api/routers/workflow.py:581 |
| R-12 | Validate handles access, not-found and malformed config like update (403/404/400) | story | — | yes | TR-3 | diff:src/testproject1/rest_api/routers/workflow.py:595 |
| R-13 | Existing workflow versioning / text diff behaviour (TP1-8827) is not regressed | story | — | yes | REG-1 | current-code:src/pages/workflows/components/WorkflowVersionHistoryPopup.tsx:55 |
| R-14 | A read-only user must NOT be able to Restore in either history popup (owner answer Q2); gate dropped in MR 1881 (canRestore = yaml_config != null) is a suspected defect. Manual-human check on preview (factory has no preview access) | derived | aspect:roles-and-permissions | yes | — | diff:src/pages/workflows/components/WorkflowVisualVersionHistoryPopup.tsx:107 |
| R-15 | A removed node in YAML lacking layout metadata has a defined position (code falls back to {0,0}) | derived | aspect:inputs-and-validation | no | — | none — flag for gate A |

<!-- manifest_gap: none — S1 handover was enough; no source opened in this stage. -->

## Contradiction matrix

| R | parent story/feature | area cases (TC-*) | area open bugs |
|---|---|---|---|
| R-1 | ok:TP1-14482 AC1 | n/a:no case store (test-cases/ absent) | n/a:no bug store (qa-factory/bugs absent) |
| R-2 | ok:TP1-14482 AC2 | n/a:no case store | n/a:no bug store |
| R-3 | ok:TP1-14482 AC3 | n/a:no case store | n/a:no bug store |
| R-4 | silent | n/a:no case store | n/a:no bug store |
| R-5 | ok:TP1-14482 AC5 | n/a:no case store | n/a:no bug store |
| R-6 | ok:TP1-14482 AC6 | n/a:no case store | n/a:no bug store |
| R-7 | contradicts:"AC6: 'always compares exactly two revisions at a time'" vs code "prepareVisualDiffCanvas(selectedEntry.yaml_config ?? '', currentEditorYaml)" (WorkflowVisualVersionHistoryPopup.tsx:62); resolved by owner Q1: two revisions, buffer may hold one | n/a:no case store | n/a:no bug store |
| R-8 | ok:TP1-14482 AC6 | n/a:no case store | n/a:no bug store |
| R-9 | ok:TP1-14482 AC7 | n/a:no case store | n/a:no bug store |
| R-10 | ok:TP1-14482 Technical Requirements | n/a:no case store | n/a:no bug store |
| R-11 | ok:TP1-14482 Technical Requirements | n/a:no case store | n/a:no bug store |
| R-12 | ok:TP1-15045 scope items 13/14 | n/a:no case store | n/a:no bug store |
| R-13 | ok:TP1-8827 | n/a:no case store | n/a:no bug store |
| R-14 | silent | n/a:no case store | n/a:no bug store |
| R-15 | silent | n/a:no case store | n/a:no bug store |

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-7 | Popup compares two persisted revisions (baseline vs selected) | Popup compares the selected revision with the current editor buffer (incl. unsaved edits), as coded | Added/removed/modified markers differ whenever the editor holds unsaved changes or the selected revision is the latest | owner Q1: Reading A stands; buffer is a holder for one of the two revisions. A check with unsaved edits in the buffer is out of the oracle |
| R-4 | Former position taken from the baseline revision's layout meta | Any removed node without layout meta sits at {0,0} | Removed node may overlap the origin on YAML without meta | question at gate A (R-15) |
| R-14 | Restore is write-gated (as before MR 1881) | Restore open to any viewer; only the Save afterwards is gated | A read-only user can overwrite editor content | owner Q2: Reading A (read-only must not Restore); suspected defect, manual-human check |

## Source completeness

| source | relation | relevance | assessment receipt | full-read receipt | revision/hash | status | gap or exclusion reason |
|---|---|---|---|---|---|---|---|
| TP1-15045 | task | relevant | work/source-inventory.json | work/source-inventory.json | 2026-09-18T08:23:41.338+0000 | read | — |
| TP1-14482 | parent | relevant | work/source-inventory.json | work/source-inventory.json | 2026-09-18T08:17:35.665+0000 | read | — |
| TP1-8827 | normative | relevant | work/source-inventory.json | work/source-inventory.json | jira-2026-09-20 | read | — |
| testproject1!4214 | technical | relevant | work/mr-testproject1_-_merge_requests_4214.json | same | 0cc6c4f1 | read | — |
| testproject1-ui!1881 | technical | relevant | work/mr-testproject1-ui_-_merge_requests_1881.json | same | e6532059 | read | some UI file diffs collapsed by GitLab; read through git at pinned head |
| testproject1-ui!1924 | referenced | relevant | work/mr-testproject1-ui_-_merge_requests_1924.json | same | 135699ae | read | evaluation-only test MR, not product coverage |
| testproject1-ai/docs PR 387 | referenced | relevant | work/gh-docs-pr387.json | same | 87875ba0 | read | — |
| SharePoint demo video (TP1-14482 comment) | referenced | unknown | work/source-inventory.json | — | unknown | unavailable | behind EXAMPLE SSO; gap accepted by the person; oracle gap limited to visual look of the demo |
| TP1-14473 | referenced | not_relevant | — | — | — | excluded | out of scope by the person's decision |
