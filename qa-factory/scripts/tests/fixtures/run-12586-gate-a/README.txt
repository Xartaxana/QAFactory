Fixture of the live run TP1-12586 at gate A (hotfix-12586/4, HF4-8 and HF4-9; tests test_gate_a_settled_forks.py and
test_raise_reaches_plan_row.py).

Source on the stand: D:/ws1/testproject1-dev-010\testproject1-sdk\test-harness\qa-factory\artifacts\TP1-12586\
  work/requirements-register.md      <- work\requirements-register.md, copied as it is (no Cyrillic in it)
  work/requirements-readiness.json   <- work\requirements-readiness.json, copied as it is (Q1..Q7; Q7 raised for TC-014 Then 1)
  work/question-answers.jsonl        <- work\question-answers.jsonl; the Cyrillic `words` of Q3, Q4, Q5, Q6, Q7 are replaced
                                        by English of the same shape (the person's words stay the person's words); ids, statuses,
                                        letters, `where`, `at` and `row_hash` are kept byte for byte, so every answer still
                                        sits on the exact row it was given on
  work/test-plan.json                <- work\test-plan.json, ONLY the rows TS-1, TS-2, TS-8 and TS-14, copied as they are (no
                                        Cyrillic in the file); `{"rows": [...]}` as the stand's plan
  case-TC-014-raise.md               <- work\test-cases\cases\TC-014\cv_ecf1a870aadb0cb02a0b.md, the TC-014 version that still
                                        says `raise` (the S4 exit has not raised its question yet), copied as it is
  pipeline.json                      NOT the stand's file: the stand's pipeline.json is the state AFTER the person's gate A
                                        words ("R-3: a / R-5: a / R-1: a ..."), which name the cards and would close them by the
                                        old mention rule - the very thing this fixture must not hide. This one is the shape of
                                        the story BEFORE the gate A answer: no gate record, no waiver, no stage override.

What the stand showed before the fix (work\gate-a-brief.txt, lines 24-65): Open questions (5) = Q7, R-3 (TS-1), R-5 (TS-2),
R-1 (TS-8), TS-14, although the person had answered Q1 b, Q2 a and Q4 a at the S2 stop (R-3, R-5, R-1 name those questions
in the `Decision` cell of `## Reading forks`: `Q1 b adopted: ...`), and "Already decided by you" listed none of Q1..Q7.

Nothing here is a secret, a thinking signature or an api-request line.
