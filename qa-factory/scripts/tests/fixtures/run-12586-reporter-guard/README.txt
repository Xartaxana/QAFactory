Fixture of test_gate_ordered_reporter.py (GB-2, HF5-18, t-1547): the stage guard's input on run TP1-12586 (package 0.10.4) at the
moment it refused the bug reporter: gate B recorded approved with two bug drafts chosen, the delivery verdict `no`.

Source (read only, outside the repository):
  D:/ws1/testproject1-dev-010\testproject1-sdk\test-harness\qa-factory\artifacts\TP1-12586\
  pipeline.json, work\ledger.json, work\automation-manifest.json, state\dispatch-denials.jsonl (line 1 only)

TP1-12586\pipeline.json                 the live file, `gates.B` as recorded (id, status approved, selected_drafts x2, decision approved)
TP1-12586\work\ledger.json              the live ledger: delivery_verdict `no`, delivery_ready false
TP1-12586\work\automation-manifest.json the live manifest, the bulky lists emptied (tests, then_bindings, obligation_bindings,
                                            runs, plan_remarks, deviations); `unresolved` and `revision` as recorded
dispatch-denial-line1.jsonl                 line 1 of the run's dispatch-denials.jsonl: the refusal of rule 4 at 12:38:33 (the red control)
rebuild.py                                  how the copy is made; not run by any test (with no argument it says the source is absent, exit 2)

Changed, and only this: every Cyrillic letter became its Latin transliteration (FR-30: the package and its fixtures are English); the
person's gate B words (also copied into `reopened_by_words`) became their English twin "1) 1 and 2 are one bug 2) I will check by hand
3) no MR needed"; the stand's absolute paths became `<stand>` and the user's home `<home>` (FR-37, AR-4).

Step 0 (a), measured: on the live pipeline.json alone `dispatch_errors` (rules 1-3) REFUSED the reporter, for rule 3, not rule 1/2: the
manifest was absent in the copy ("work/automation-manifest.json is absent: S5 is not recorded as skipped"). With the manifest in the
copy rules 1-3 pass (S0..S8 `done`; S9 `done` and `reopened_at` do not matter to them), so the pipeline's stages stay as recorded.
