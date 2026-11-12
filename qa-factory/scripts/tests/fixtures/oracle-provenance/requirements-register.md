---
task: TP1-15045
created: 2026-10-01
ids: [R-1, R-13, R-16, R-17, R-18, R-19, R-27]
by_source: {story: 0, feature: 0, assumption: 0, discussion: 0, ac: 2, derived: 5}
confidence: low
---

## Register

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact |
|---|---|---|---|---|---|---|---|
| R-1 | Visual revision diff opens from workflow version history. | ac | — | yes | AC-1 | diff:testproject1-ui:src/pages/workflows/editor/EditorActions.tsx:134 | blocked-flow |
| R-13 | POST /v1/workflows/{workflow_id}/validate runs the same required pre-persist validation pipeline as PUT update. | ac | — | yes | AC-13 | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:103 | blocked-flow |
| R-16 | The validate endpoint enforces access: unknown workflow gives 404, no project access is refused, a user without WRITE ability on the workflow gets access denied, and nothing is validated for them. | derived | aspect:roles-and-permissions | yes | — | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:581 | access |
| R-17 | The validate endpoint rejects bad input with the same codes as update: unparseable config 400 "Workflow Configuration error", autonomous mode 403, error_format=json returns structured details; a valid config returns 200 "Workflow configuration is valid" with warnings. | derived | aspect:inputs-and-validation | yes | — | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:613 | blocked-flow |
| R-18 | GuardrailService.sync_guardrail_assignments_for_entity with dry_run=True checks existence, project and permission but creates and deletes no assignment; the non-dry path behaves as before (assignments of another project are still marked for deletion). | derived | invariant:guardrail-dry-run | yes | — | diff:testproject1-backend:src/testproject1/service/guardrail/guardrail_service.py:181 | data-loss |
| R-19 | PUT /v1/workflows/{id} after the refactor (_run_pre_persist_update_validation; guardrail dry-run now runs before MCP, autonomous and executor checks; updated_config.id set) returns the same results and error codes for every invalid input as before and still persists on success. | derived | aspect:failure-and-error-paths | yes | — | diff:testproject1-backend:src/testproject1/rest_api/routers/workflow.py:532 | degraded |
| R-27 | The YAML panel Version History button keeps working after its aria-label changed from "Version History (visual editor)" to "Version History (YAML)" and the old label moved to the new toolbar button; the existing UI test looks for the old label. | derived | bug:none-recorded; invariant:aria-label-rename | yes | — | diff:testproject1-ui:src/pages/workflows/editor/configPanels/YamlPanel.tsx:166 | degraded |

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | contradicts:"Parent AC1: separate entry points rather than a toggle; AC2: when the user switches to Visual mode; mockup has a YAML/Visual toggle" (TP1-14482) | silent | silent | n/a:area_bugs is empty in the manifest |
| R-13 | ok:TP1-14482 AC13 | silent | silent | n/a:area_bugs is empty in the manifest |
| R-16 | silent | silent | silent | n/a:area_bugs is empty in the manifest |
| R-17 | silent | silent | silent | n/a:area_bugs is empty in the manifest |
| R-18 | silent | silent | silent | n/a:area_bugs is empty in the manifest |
| R-19 | silent | silent | silent | n/a:area_bugs is empty in the manifest |
| R-27 | contradicts:"AC15: not regressed" vs "YamlPanel.tsx:166 renames the aria-label" (testproject1-ui!1881) | silent | contradicts:"test_workflow_version_history.py:25 expects the old label" vs "the MR gives the old label to the new toolbar button" | n/a:area_bugs is empty in the manifest |
