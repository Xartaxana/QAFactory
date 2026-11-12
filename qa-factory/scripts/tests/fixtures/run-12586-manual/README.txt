Fixture of test_gate_decision_manual_pass.py (HF4-14): the task root of run TP1-12586 (package 0.10.3), cut at the
event BEFORE the gate A decision.

Source (read only, outside the repository):
  <project>\testproject1-sdk\test-harness\qa-factory\artifacts\TP1-12586\  (the stand's checkout; the machine prefix is scrubbed, AR-4)
  state\events.jsonl seq 1..46 (seq 47 is the gate A decision recorded by the conductor, seq 118 the semantic_reopen)
  work\test-plan.json, work\test-cases\, state\case-versions\, state\story-case-links.json, state\plan-baseline.json,
  work\source-inventory.json, the two source snapshots it names, work\question-answers.jsonl, pipeline.json

Changed, and only this (rebuild.py in this folder does it; it is not run by any test):
  - every Cyrillic letter became Latin letters of the same shape (FR-30: the package and its fixtures are English); the
    event chain was re-hashed because it hashes every payload
  - pipeline.json keeps the one stage override that exists before the decision (the S4 design review)
  - work\test-plan.json: the stand's file is the plan AFTER the rework that followed the reopen, so OB-13 and OB-15 are
    put back to `decision: new` with no evidence_policy, and OB-17 to `decision: unresolved, oracle_status: unresolved`
    (the state the strategist authored, as the conductor's session printed it before the rework). Rows TS-10, TS-12,
    TS-14 keep `disposition: manual-agent` and their row-level evidence_policy (ui, ui, api).
  - state\words\gate-a-decision.txt is new: the person's words in English, with the closed word `approve as is`
    (the real words were Russian).
THIS FIXTURE IS A MOTION, not "the state at the cut". Do not take it for the recorded state in a later test:
  - the plan hash is 62c066cc..., NOT the hash the conductor's gate A approved (7bfe2482..., seq 47): the stand's plan is the
    reworked one with three obligations (OB-13, OB-15, OB-17) rewound; TS-14 lost its Q7 `question_refs` in that rework
  - state\story-case-links.json pins TC-001 at cv_9342b71470e02c52cfaa and TC-004 at cv_05e9226b163aa18ce90b, two case
    versions created AFTER the cut (no event 1..46 names them; they come from after the reopen)

Dropped as not read by gate-decision / prepare_request: evidence, test code, run reports, briefs, handoffs, merge-request
snapshots, execution jobs, state\controller.json (a projection, rebuilt from the events).
