---
task: TP1-12586
created: 2026-10-27
ids: [R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14, R-15, R-16]
by_source: {story: 1, feature: 0, assumption: 0, discussion: 9, ac: 0, derived: 6}
confidence: low
---

## Register

The ticket has no acceptance_criteria field; the nine "Required acceptance validation" items sit in the AI-assistant comment of 2026-09-30 (comment 15958292) and are registered as `discussion` rows, inferred. Ticket revision 2026-10-24T16:37:20.406+0000; testproject1 diff eecc7e4c, testproject1-ui diff 6c7026b9.

| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact | delta |
|---|---|---|---|---|---|---|---|---|
| R-1 | A user can change the Project of an existing integration (description: "same way it already works for Data sources / Assistants / Workflows") | story | — | yes | — | diff:src/pages/integrations/components/SettingsForm/SettingsForm.tsx:604 | blocked-flow | changed |
| R-2 | An existing integration has a visible "Change project" action | discussion | — | yes | — | diff:src/pages/integrations/components/SettingsForm/SettingsForm.tsx:604 | blocked-flow | changed |
| R-3 | The project change moves the integration and its supported settings to the target project (PUT with server-side transfer accepted, Q1 b; checked by outcome) | discussion | — | yes | — | diff:src/testproject1/rest_api/routers/project_settings.py:185 | data-loss | changed |
| R-4 | The user can select a permitted target project; Move is the only mode in scope (Q3: copy dropped, open item for the analyst) | discussion | — | yes | — | expected-contract | blocked-flow | new |
| R-5 | Move transfers an MS Teams integration to another permitted project (Q2 a: the 400 Project mismatch is a defect) | discussion | — | yes | — | current-code:src/testproject1/service/settings/settings_request_validator.py:327 | blocked-flow | changed |
| R-6 | After a successful move the original MS Teams integration is no longer associated with the source project | discussion | — | yes | — | diff:src/testproject1/service/settings/settings_transfer_service.py:396 | data-loss | new |
| R-7 | The target project shows the moved integration and it remains usable | discussion | — | yes | — | expected-contract | blocked-flow | new |
| R-8 | The UI shows clear validation or errors when a requested copy or move is not allowed | discussion | — | yes | — | diff:src/testproject1/rest_api/routers/project_settings.py:169 | degraded | changed |
| R-9 | Integration lists and project-related state of both projects refresh after transfer, checked over everything configurable at project creation (Q6) | discussion | — | yes | — | expected-contract | degraded | new |
| R-10 | The MS Teams singleton constraint remains enforced: no duplicate concurrent MS Teams integrations | discussion | — | yes | — | current-code:src/external/alembic/versions/a8032409ff23_scope_ms_teams_project_singleton_to_project_type.py:43 | blocked-flow | unchanged |
| R-11 | Field update and project move on one integration are atomic: both land or neither does (shared transactional session) | derived | invariant:atomic-update-and-move | yes | — | diff:src/testproject1/clients/postgres.py:316 | data-loss | new |
| R-12 | On a move, datasources left in the source project have their setting_id cleared, so they fail visibly | derived | aspect:persistent and shared data | yes | — | diff:src/testproject1/service/settings/settings_transfer_service.py:356 | access | new |
| R-13 | Changing the project of an existing project-scope integration requires admin permission on the target project | derived | aspect:roles and permissions | yes | — | diff:src/testproject1/rest_api/routers/project_settings.py:169 | access | new |
| R-14 | A confirmation modal ("Change integration project?") warns about dependents in the old project before the project change is submitted | derived | aspect:failure and error paths | yes | — | diff:src/pages/integrations/components/EditSettingPageBase.tsx:222 | degraded | new |
| R-15 | The user-scope integration PUT also moves the project (via the transfer service, in one transaction) when project_name changes | derived | aspect:cross-team integration | yes | — | diff:src/testproject1/rest_api/routers/user_settings.py:247 | blocked-flow | new |
| R-16 | While editing, the credential-type auto-reset is skipped so loaded credential values are not discarded when the project changes | derived | aspect:inputs and validation | yes | — | diff:src/pages/integrations/components/SettingsForm/SettingsForm.tsx:467 | data-loss | new |

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | silent | contradicts:"it's not a defect - it's expected behaviour. It was designed like this" (Test User 3 2026-06-17) vs "Recommend keeping open as a focused contributor candidate" (Test User 1 2026-06-30) | silent | n/a:no open bug found in the bundle |
| R-2 | silent | contradicts:"Change project action" (comment 2026-09-30) vs diff: no separate button, the Project dropdown is enabled on edit (SettingsForm.tsx:604) | silent | n/a:no open bug found in the bundle |
| R-3 | silent | contradicts:"The UI must invoke the transfer endpoint instead" and "Do not implement this through a standard integration PUT" (comment 2026-09-30) vs diff: update_project_setting calls SettingsTransferService.transfer_setting inside the PUT; the UI has no /v1/settings/transfer call | silent | n/a:no open bug found in the bundle |
| R-4 | silent | contradicts:"explicitly choose the applicable transfer mode" (comment 2026-09-30) vs diff: no mode selector, only a confirm modal | silent | n/a:no open bug found in the bundle |
| R-5 | silent | contradicts:"Move mode is valid for MS Teams and should be available through the UI" (comment 2026-09-30) vs current-code: ms_teams PUT with a different project_name raises 400 "Project mismatch" (settings_request_validator.py:327), and the diff runs that validation before the move | ok:T3 (singleton duplicate case only; no ms_teams project-change case) | n/a:no open bug found in the bundle |
| R-6 | silent | silent | ok:T1 (move relocates project integrations; not ms_teams) | n/a:no open bug found in the bundle |
| R-7 | silent | silent | ok:T1 | n/a:no open bug found in the bundle |
| R-8 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-9 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-10 | silent | ok:comment 2026-09-30 "singleton behavior is intentional and must remain unchanged" | ok:T3 | n/a:no open bug found in the bundle |
| R-11 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-12 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-13 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-14 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-15 | silent | silent | silent | n/a:no open bug found in the bundle |
| R-16 | silent | silent | silent | n/a:no open bug found in the bundle |

## Behaviour claims

| R | before | before_ref | now | now_ref | differs | question | origin |
|---|---|---|---|---|---|---|---|
| R-11 | unknown (each write committed in its own session) | diff:-src/testproject1/clients/postgres.py:311 | one transaction, rollback on exception | diff:src/testproject1/clients/postgres.py:316 | unknown | Q5 | |
| R-12 | unknown (no datasource unlink in transfer) | absent | datasource setting_id cleared on move | diff:src/testproject1/service/settings/settings_transfer_service.py:356 | unknown | Q5 | |
| R-13 | unknown (project could not be edited in UI) | diff:-src/pages/integrations/components/SettingsForm/SettingsForm.tsx:604 | admin on target project checked | diff:src/testproject1/rest_api/routers/project_settings.py:169 | unknown | Q5 | |
| R-14 | absent | absent | confirm modal before submit | diff:src/pages/integrations/components/EditSettingPageBase.tsx:222 | unknown | Q5 | |
| R-15 | unknown | diff:-src/testproject1/rest_api/routers/user_settings.py:245 | user-scope PUT moves project | diff:src/testproject1/rest_api/routers/user_settings.py:247 | unknown | Q5 | |
| R-16 | credential type auto-reset ran during edit | diff:-src/pages/integrations/components/SettingsForm/SettingsForm.tsx:477 | skipped while editing | diff:src/pages/integrations/components/SettingsForm/SettingsForm.tsx:467 | yes | Q5 | |

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-1 | Project dropdown enabled on edit is the delivered feature | Test User 3: the disabled dropdown is designed behaviour | Whether editing the project is a feature or a defect | Q4 a adopted: feature wanted |
| R-3 | Dedicated UI call to POST /v1/settings/transfer | PUT with changed project_name, moved server-side by the transfer service | Which endpoint is the oracle; response shape, error codes | Q1 b adopted: outcome check |
| R-4 | UI exposes move and copy choice | Move only, no mode choice | Copy cases exist or not | Q3 b adopted: Move only |
| R-5 | MS Teams project change must succeed (move) | Validator rejection 400 is intended | MS Teams budget-switch scenario works or not | Q2 a adopted: Move must succeed, 400 is APP_BUG |

## Source completeness

| source | relation | relevance | assessment receipt | full-read receipt | revision/hash | status | gap or exclusion reason |
|---|---|---|---|---|---|---|---|
| TP1-12586 | task | relevant | work/source-inventory.json | work/sources/SRC-a4a01f76e6db46898144/9e64d42a381be43c/ticket.json | 2026-10-24T16:37:20.406+0000 | read | 4 comments read, no attachments |
| CR-004 | referenced | unknown | work/source-inventory.json | none | unknown | unavailable | person: likely a code-review comment, go on without it |
| TP1-13289 | referenced | not_relevant | work/source-inventory.json | none | unknown | excluded | not relevant per inventory |
