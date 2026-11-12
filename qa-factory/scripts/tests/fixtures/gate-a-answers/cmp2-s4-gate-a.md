Approved: the plan and the cases are approved as they stand, as one story (XXL by your arithmetic; the decomposition recommendation is noted, and my word is to test it as one story).

Q1: a
Q2: b
Q3: a
Q4: a
Q5: a
Q6: a

Q2 is the owner's own word (2026-10-01 05:4x): the former position means the node's place in the graph, not its coordinates - the diff layout reuses Beautify, so only presence, red styling, badge and strikethrough are asserted. The others are read as built in testproject1-ui!1881 and testproject1!4214; a divergence from the acceptance criteria goes into the findings as a wording gap, not as a bug - this run writes no bugs to the tracker.

After your approval, by name:
- vcs (24 uncommitted changes): go on on this branch - the files are the factory's own artifacts under test-harness/qa-factory/, nothing of the product; no commit, no stash.
- TS-12.sfg1 (guardrail assignments have no confirmed read endpoint): accept the gap; the row stays, S5 reports what it cannot observe.
- s5_toolchain (collection failed with ModuleNotFoundError testproject1_sdk in conftest): repaired by me before this answer - `poetry install` in the copy's test-harness installed testproject1-sdk-python 0.2.14 (develop, ../sdk/testproject1-python); `pytest --collect-only` on testproject1_test_harness/tests/activity/test_activity_events_access.py now collects 1 test. Rehearse again; nothing more to install.
- stand gap RP-api (reporter): apply - change it on my word.
- s5_environment (AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_PROFILE; accounts auditor, default_scoped_user, project_scoped_user): accept the gap; the stage reports those cases as not executed. Nobody puts keys anywhere in this run.
- case preconditions TP1-15045_TC_001, TC_002, TC_003, TC_004, TC_006, TC_007, TC_008, TC_009, TC_011, TC_016, TC_018 (seeded by the case itself): not a stand gap - the case creates its own workflow and revisions; S5 runs them. Factory finding, ours: a precondition the packet itself calls "seeded by the case itself" or "the localhost superadmin holds it" with "no machine check exists" is not a question for a person - 16 of these 21 cards are that.
- case preconditions TC_010, TC_012, TC_015 (an account with WRITE on an own project): the localhost superadmin holds it; S5 runs them.
- case preconditions TC_014 (P-nowrite, P-noproject) and TC_017 (P-readonly) (a second non-admin user): accept as blocked on localhost; S5 reports exactly those partitions as not executed.
