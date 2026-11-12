Fixture run-12586-red-then (t-1508 section 5.0; created by node R5, t-1521).

Source (read only, 28.10.2026): the stand run TP1-12586, artifacts/TP1-12586/work/ of the testproject1-dev-010 checkout,
and testproject1_test_harness/tests/integrations/project/test_ms_teams_integration.py of the same checkout.

What is here (all ids, hashes, ranges and structure as in the run):
  work/automation-manifest.json   tests[] of the two instances test_put_project_change_moves_ms_teams_integration (TC-002) and
                                  test_put_project_change_into_project_with_ms_teams_is_rejected (TC-003), then_bindings and
                                  unresolved[] of TC-002/TC-003. Dropped: the per-test `novelty` block (a table of 24 file hashes,
                                  read by no check here). TC-002 is red at Then 1, TC-003 at Then 2; every Then carries the
                                  test's one assertion range (160-189 and 345-364): the live "order not established" shape.
  work/triage.json                whole file (2 rows, attempt a96f5e653377735139aa).
  work/run-report.json            rows of the two instances: current_results (attempt a96f5e...) and the history rows of attempts
                                  a96f5e... and a5ba38dc967d56c26201 (purpose: diagnostic). Dropped: other instances, manual checks,
                                  evidence, witness, reducer; totals recomputed for the kept rows (failed only).
  work/test-cases/integrations/   TC-002.md, TC-003.md, whole.
  work/bug-drafts/                both drafts, whole.
  test-code/                      the function of TC-003 (lines 314-364 of the original file), verbatim; the Then asserts sit at
                                  original lines 345-349, 350-354, 355-359, 360-364.

  test-code/product_stub.py       (t-1561, key K-R4-S) the stand-in for the harness and the product that the function above needs to
                                  run: every product call is replaced by a canned answer, a move of an MS Teams integration
                                  answers `400 Project mismatch` and changes nothing. A test composes ONE module, the stub then
                                  the verbatim function, so the function's own lines are untouched; Then 1, 3 and 4 hold and Then 2
                                  fails: the red shape of the stand run.
  controller/TP1-12586/state/execution-jobs/   (t-1561, key K-R4-6) five jobs of the run (profile `api`: two initial, one
                                  repair_verify, two red_probe), all created before the controller cutoff, machine paths replaced
                                  (controller/README.txt); build_fixture.py `--jobs <run>` adds them to a copy.

Cyrillic: none of the source files held any; no replacement was made.
controller/ (the state of the run at the refusal of S5-qa-automator-5, key K-R2-S) is made by t-1541; see its README.txt.
