Fixture of test_gate_b_orders.py (GB-1a, HF5-17): the task root of run TP1-12586 (package 0.10.4), cut at the gate B decision
(INCLUDED; found by `type == decision` and `payload.gate == B`, never by a number): 148 events, the last one the decision with
two selected drafts and no orders (the decision was recorded by 0.10.4, which knew no orders).

Source (read only, outside the repository):
  D:/ws1/testproject1-dev-010\testproject1-sdk\test-harness\qa-factory\artifacts\TP1-12586\
  state\events.jsonl seq 1..148 (149 is the scribe dispatch that "reopened" the story, 151 the bug reporter, 152/153 the releases)
  work\ledger.json, work\test-plan.json, work\source-inventory.json, work\automation-manifest.json, the two source snapshots
  the inventory names

Changed, and only this (rebuild.py in this folder does it; it is not run by any test; with no argument it says the source is
absent and exits 2):
  - every Cyrillic letter became Latin letters of the same shape (FR-30: the package and its fixtures are English)
  - the person's gate B words became their English twin: "1) 1 and 2 are one bug 2) I will check by hand 3) no MR needed"
    (state\words\gate-b-decision.txt holds the same text)
  - the stand's absolute paths became `<stand>` and the user's home `<home>` (FR-37, AR-4: the fixture is bound to no machine)
  - hashes recomputed after the word replacement by rebuild.py; the folder is rebuilt, never hand-edited:
      * the event chain (`previous_hash`, `event_hash`) through `event_store.content_hash`; sequence, expected_revision,
        idempotency_key, event_id, task_id and the payload structure are as recorded
      * the bindings of the CURRENT gate A decision (plan, semantic plan, oracle, coverage revisions, source inventory hashes) are
        the values `Controller.gate_inputs()` computes over these English files, because the plan and the inventory changed
        with the words; without it every dispatch of the fixture is refused for "Gate A sources changed"
Not in the fixture (a test projects it): pipeline.json - `Controller._project_pipeline(projection(events))` writes it.
What `story_step.py start --stage S8 --role qa-bug-reporter` needs besides the journal: the plan, the source inventory with its two
snapshots, the automation manifest and the projected pipeline.json (measured in GB-1a step 0 (c)).
