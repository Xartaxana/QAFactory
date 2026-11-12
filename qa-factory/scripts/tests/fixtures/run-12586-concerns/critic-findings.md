# Case critic findings - TP1-12586 - confirming review (dispatch S4-qa-case-critic-3)

Verdict: reject

Scope: 11 of 11 reviewed (TC-001, 002, 004, 005, 006, 007, 008, 009, 011, 012, 014). No case fails; the verdict follows the deterministic rule (3 dimension concerns: 3, 6, 8). Round cap: concerns F-1..F-5 and TC-014 F-1/F-2 were already raised and are carried unchanged to Gate A, none is blocking. Confidence: normal. Input hash: ea4f0ddd15c5502bfcb6b3b29465458f78399e818e520c60c3b8936e4249c1c9. Reviewer dispatch: S4-qa-case-critic-3. Pins as in rounds 1-2 (TC-014 cv_fdb829d700e61f126a9a). Sources read: the 11 case files at current content, test-plan.json (TS-14 grep), decisions file, rounds 1-2 findings. Code citations not re-opened.

## Re-check against the stand (second account, MS Teams flag on, UI :5173, ENV=development)

- TC-002 PC-1 still says `none` "not readable by anonymous GET; a person confirms". The flag is now on, so the case can run, but the precondition is still prose-grade (F-2 stays; use an `env`/`http` check or record the confirmation).
- TC-004 PC-1 and TC-012 PC-1 are still `none` checks about a second account. The stand now holds one (admin of proj-a, member of proj-b); the checks should become `stand_account` / `env: QA_SECOND_USER_EMAIL`. TC-004 F-4 stands: U2 is not stated as admin of the source.
- TC-014 PC-3 (ENV not local) is now met by the stated ENV=development; cite it at the run.

## Dimension scores

| # | dimension | score | basis |
|---|---|---|---|
| 1 | Coverage | pass | R-1..R-16 reach a row; R-4 copy part deferred by Q3 b |
| 2 | Atomicity | pass | partitions as the plan rows |
| 3 | Clarity | concern | TC-011 F-1 (setting list), TC-002 F-2, TC-007 F-3, TC-004/TC-012 PC-1 now checkable, TC-014 F-1 (origin project) |
| 4 | Edge cases | pass | declared techniques present |
| 5 | Negative scenarios | pass | collisions and no-role reachable |
| 6 | Traceability | concern | TS-14 in test-plan.json still oracle_unknown true / OB-17 unresolved while TC-014 asserts per Q7 (owner qa-test-strategist, Gate A) |
| 7 | Completeness | pass | 11 rows, 11 cases |
| 7b | Not contradicted | pass | Q1 b, Q2 a, Q3 b, Q4 a, Q5 a, Q7 followed |
| 8 | Seed the defect | concern | TC-004 F-4 (U2 source role), TC-005 F-5 (collision by alias rename in same PUT) |

## Open findings, unchanged and non-blocking

- TC-011 F-1: name the creation settings and non-default values in the Given.
- TC-002 F-2: replace the `none` flag check or record the confirmation.
- TC-007 F-3: datasource credentials need an `env`/`stand_account` entry.
- TC-004 F-4: state U2 is admin of the source and has no role in the target.
- TC-005 F-5: keep the colliding alias unchanged and change another field, as TC-006 does.
- TC-014 F-1: name the origin project and a fresh integration per partition. TC-014 F-2: update plan row TS-14 to Q7 resolved with member / admin / no-role partitions.

## Sensitivity records (proof_kind: design_analysis; no probe executed, observed_failure_ref none)

As in rounds 1 and 2 for OB-1..OB-17; no defect site changed since.

## Roll-call

| plan row | case | reviewed | verdict | note |
|---|---|---|---|---|
| TS-1 | TC-001 | yes | approve | all dimensions pass |
| TS-2 | TC-002 | yes | approve_with_concerns | F-2 flag precondition |
| TS-4 | TC-004 | yes | approve_with_concerns | F-4 U2 role; PC-1 checkable now |
| TS-5 | TC-005 | yes | approve_with_concerns | F-5 collision premise |
| TS-6 | TC-006 | yes | approve | collision reachable per code |
| TS-7 | TC-007 | yes | approve_with_concerns | F-3 datasource credentials |
| TS-8 | TC-008 | yes | approve | decision table accepted |
| TS-9 | TC-009 | yes | approve | secret part named gap |
| TS-11 | TC-011 | yes | approve_with_concerns | F-1 setting list |
| TS-12 | TC-012 | yes | approve | manual evidence policy present; PC-1 checkable now |
| TS-14 | TC-014 | yes | approve_with_concerns | F-1 origin project; F-2 stale plan row |

11 of 11 reviewed.

# Case critic findings - TP1-12586 - round 2 (dispatch S4-qa-case-critic-2)

Verdict: approve_with_concerns

Scope: 1 of 1 reviewed (TC-014, rewritten after Q7). Confidence: normal. Pin reviewed: TC-014 cv_fdb829d700e61f126a9a (earlier pin cv_1eefd8ddf907f7d307df is stale). Input hash: ea4f0ddd15c5502bfcb6b3b29465458f78399e818e520c60c3b8936e4249c1c9. Author dispatch: S4-qa-case-designer-2. Reviewer dispatch: S4-qa-case-critic-2. Obligation: OB-17.
Sources read: TC-014.md, test-plan.json row TS-14 (lines 431-461), requirements-register.md grep R-15, decisions file (Q7), story-case-links.json. Code citations in the case (user.py:143-144, _common.py:177-198, authentication.py:360-371) were not re-opened by me; they are the designer's reading and the person named the rule as oracle. Excluded: understanding.md, context-manifest.json.

## Roll-call

| plan row | case | reviewed | verdict | note |
|---|---|---|---|---|
| TS-14 | TC-014 | yes | approve_with_concerns | partitions match Q7 rule; F-1 origin project unnamed, F-2 plan row stale |

## Dimension scores

| # | dimension | score | basis |
|---|---|---|---|
| 1 | Coverage | pass | R-15 permission part covered by member, admin-of-target, no-role partitions |
| 2 | Atomicity | pass | one scenario (target-role gate), three partitions as the plan row |
| 3 | Clarity | concern | F-1 |
| 4 | Edge cases | pass | role partitions differ only in U's role on the target |
| 5 | Negative scenarios | pass | P-norole reachable on ENV=development (stated by the person); PC-3 records the dependency |
| 6 | Traceability | concern | F-2 |
| 7 | Completeness against plan | pass | TS-14 has its case |
| 7b | Not contradicted by sources | pass | Then 1-3 follow Q7 (person); Then 4 follows R-15; no source found contradicting |
| 8 | Seed the defect | pass | admin-only check turns Then 1 red; absent check turns Then 3 red; half-state turns Then 4 red (design_analysis only) |

## Findings

- F-1 (TC-014, Given and When, dimension 3, non-blocking): the origin project is never named, and the three partitions read as one integration moved three times. After P-member the integration sits in qa12586-proj-b, so "still in its origin project" in Then 3 and "not already in it" in When 2 depend on order and on an unnamed origin. Expected: name the origin (a project U may legitimately hold an integration in, other than proj-a, proj-b and NR) and create a fresh integration per partition, so each Then compares against that partition's own before-read. Not a replacement-grade fix because the origin project is a design choice.
- F-2 (plan row TS-14 vs TC-014, dimension 6, non-blocking, owner qa-test-strategist / Gate A): work/test-plan.json still carries OB-17 oracle_status unresolved, oracle_unknown true, an outcome "recorded" rather than asserted, and required_scenarios with no plain-member partition. The case now asserts per Q7. The case is right; the plan row is stale and the inherited fields do not match. Expected: plan row updated to Q7 resolved, with the three partitions.
- N-1 (PC-3, not scored): `none` check on ENV is accepted because the stand's ENV=development is stated by the person; the run record should cite that statement. If ENV=local, Then 3 is inconclusive, as the case says.
- N-2 (not scored): a global admin/maintainer partition and a nonexistent-target partition (404 for datasources) are not covered; the second account cannot form the first, and the plan names no 404 expectation for user-scope. Gate A may ask for them.

## Sensitivity records (proof_kind: design_analysis; no probe executed, observed_failure_ref none)

- OB-17, defect site update_user_setting project_name change: planted "admin of target only" fails Then 1; planted "no target check" fails Then 3; planted partial transfer fails Then 4.

# Case critic findings - TP1-12586 - round 1 (dispatch S4-qa-case-critic-1)

Verdict: approve_with_concerns

Scope: 11 of 11 reviewed (TC-001, 002, 004, 005, 006, 007, 008, 009, 011, 012, 014). TS-13 is a skip, no case. TC-003 and TC-010 are outside this dispatch (design_review_required false) and were not reviewed. Confidence: normal. Oracle: person's decisions Q1 b, Q2 a, Q3 b, Q4 a, Q5 a, Q6; the register is the oracle, code is observation only.
Input hash: ea4f0ddd15c5502bfcb6b3b29465458f78399e818e520c60c3b8936e4249c1c9. Author dispatch: the S4 designer window (case files at the pinned versions below). Reviewer dispatch: S4-qa-case-critic-1.
Sources read: test-plan.md, requirements-register.md (incl. Contradiction matrix), decisions file, 11 case files, state/story-case-links.json; code observation: settings_transfer_service.py lines 226-247 (alias conflict 409). Excluded: understanding.md and context-manifest.json not re-read (plan and register carry the oracle); CR-004 unavailable per the person.

## Pinned versions reviewed

TC-001 cv_060164c2f864d235eef8 · TC-002 cv_948bf9ee76564b469863 · TC-004 cv_bf0b424eeff643f7d464 · TC-005 cv_efcdf2bfbbe3c6b8048d · TC-006 cv_694388e7d4244ecc8327 · TC-007 cv_920af2601b8b0edc486d · TC-008 cv_3d9f776fbc026a39ebd4 · TC-009 cv_7f7ee6997a3f5c3bbd78 · TC-011 cv_916ebc3a0c8b97fbf570 · TC-012 cv_a22fb13f599b58dc39dc · TC-014 cv_ecf1a870aadb0cb02a0b

## Dimension scores

| # | dimension | score | basis |
|---|---|---|---|
| 1 | Coverage | pass | R-1..R-16 each reach a row; R-4 copy part is deferred_by_decision (Q3 b) |
| 2 | Atomicity | pass | TC-008 and TC-012 combine partitions/two lists as the plan rows do |
| 3 | Clarity | concern | F-1, F-2, F-3 |
| 4 | Edge cases | pass | unchanged/changed, confirm/cancel, singleton-free collision, control datasource present |
| 5 | Negative scenarios | pass | TC-004, 005, 006 reachable per code (409 alias conflict) |
| 6 | Traceability | pass | frontmatter complete, plan_row and covers match; see note N-1 |
| 7 | Completeness against plan | pass | every dispatched row has a case |
| 7b | Not contradicted by sources | pass | TC-002 follows Q2 a, TC-008 Q4 a, TC-001 Q1 b; TC-014 refuses to assert (oracle_unknown) |
| 8 | Seed the defect | concern | F-4, F-5 |

Two concerns, no fail: approve_with_concerns.

## Findings

- F-1 (TC-011, Given/Then 1, dimension 3): the setting list is deferred to the automator ("read from the create contract"). The Then compares "every creation setting", so the case cannot be judged complete or discriminating at Gate A. Expected: name the creation settings (or the exact create-contract fields) in the Given, with the non-default value of each. Per Q6 the completeness question stays in the report. Non-blocking.
- F-2 (TC-002, preconditions PC-1, dimension 3): the feature flag TEAMS_BOT_INTEGRATION_FEATURE is a `none` check "not readable by an anonymous GET". That was asserted, not shown. Expected: either an `http` check on the config path that exposes the flag, or an `env` check naming the variable, or a recorded search showing neither exists. Non-blocking.
- F-3 (TC-007, preconditions PC-1, dimension 3): the datasource creation may need external credentials; the check is `case_seeds`, which is never asked, so the gap would first appear in S5. Expected: a `stand_account` or `env` entry for the credential a datasource of the chosen type needs. Non-blocking.
- F-4 (TC-004, Given/Then 2, dimension 8): "U2 has no role in the target" does not say U2 is admin of the source. If U2 has no role in the source either, the 4xx of P-norole-target comes from the source-side check, and a missing target check is not detected by Then 2 (Then 1 with U1 does detect it). Expected: U2 is admin of the source project and has no role in the target.
- F-5 (TC-005, When 2, dimension 8): the collision is built by renaming the alias to the target's alias in the same PUT. If the transfer reads the stored row, the collision does not fire and the rejection premise fails. TC-006 builds the collision from the unchanged alias, which the code observation (settings_transfer_service.py:226-247, 409 Alias conflict) supports. Expected: in TC-005 change a non-alias field and keep the colliding alias, as TC-006 does.
- N-1 (TC-014, question_thens): `question: "raise"` is not a register question id. The contract matches register ids exactly; the gate rehearsal may refuse it. The raised question sits in `raise_questions`, which is the intended carrier; the designer should confirm the rehearsal accepts it. Not scored.
- N-2 (TC-002 expected red by Q2 a; TC-014 consistency Thens only): both are correct as designed. TC-014 can fail only on half-state or a broken control; it is a record, not a permission check.
- N-3 (TC-012): "visited in turn without reload" may be a client-side route cache; the completion condition is stated, accept. Expected dropdown options come from "the API" without naming which; name the endpoint at S5.

## Sensitivity records (proof_kind: design_analysis; no probe was executed, observed_failure_ref none)

| case | obligation | declared defect site | expected failure |
|---|---|---|---|
| TC-001 | OB-1 | update_project_setting ignores project_name | Then 2 and 3 fail (integration stays in source) |
| TC-002 | OB-2, OB-3 | ms_teams validator before move | Then 1 fails today (400 Project mismatch) |
| TC-004 | OB-5 | missing _check_permission on target | Then 1 fails (U1 gets 2xx); Then 2 fails only if U2 is source admin (F-4) |
| TC-005 | OB-6, OB-7 | update_user_setting non-atomic | Then 4 fails; only if the collision fires (F-5) |
| TC-006 | OB-8 | transactional_session absent | Then 3 fails (F stays f1) |
| TC-007 | OB-9 | _unlink_orphaned_datasources removed or clear-all | Then 1 or 2 fails |
| TC-008 | OB-10, OB-11 | modal cosmetic or dropdown disabled | Then 3 or 1 fails |
| TC-009 | OB-12 | credential auto-reset runs in edit | Then 1 fails |
| TC-011 | OB-14 | project settings reset by a move | Then 1 fails for the listed settings only (F-1) |
| TC-012 | OB-15 | dropdown lists all projects; lists not refreshed | Then 1 / 2 / 3 fail on screenshots |
| TC-014 | OB-17 | oracle unresolved | no permission defect can fail it by design; half-state fails Then 2 |

## Roll-call

| plan row | case | reviewed | verdict | note |
|---|---|---|---|---|
| TS-1 | TC-001 | yes | approve | all dimensions pass |
| TS-2 | TC-002 | yes | approve_with_concerns | F-2 flag precondition |
| TS-4 | TC-004 | yes | approve_with_concerns | F-4 U2 role on the source |
| TS-5 | TC-005 | yes | approve_with_concerns | F-5 collision premise |
| TS-6 | TC-006 | yes | approve | collision reachable per code |
| TS-7 | TC-007 | yes | approve_with_concerns | F-3 datasource credentials |
| TS-8 | TC-008 | yes | approve | decision table accepted |
| TS-9 | TC-009 | yes | approve | secret part named gap |
| TS-11 | TC-011 | yes | approve_with_concerns | F-1 setting list |
| TS-12 | TC-012 | yes | approve | manual evidence policy present |
| TS-14 | TC-014 | yes | approve | oracle_unknown, records only; N-1 |

11 of 11 reviewed.
