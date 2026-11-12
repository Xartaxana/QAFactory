Walker fixture of scenario_walk.py (TD-15.4). Hand-assembled, SYNTHETIC (ticket SYN-1, no Jira corpus), and NOT a story of the
scenario layer: `walker_fixture: true`, so `tools/test_quarantine.py enter` does not count it.

How it was made: a real controller run of stage S1 in a temp project (stage_done S0, initialize, `story_step start`, then
`finish --ignore-handoff`), the S1 manifest filled by hand, the file the S1 form names (impl-diff.txt) added by hand, the form's
source-inventory line set to `required: false` (a valid inventory is not hand-buildable here), every machine path in the events rewritten to `<stand>` / `<path>` and the event chain recomputed with
`event_store.content_hash`. pipeline.json and the controller projections are left out: `build_world` projects them from the events.
The gate A words (`state/words/gate-a.txt`) are one word; the world has no test plan, so the recorded decision outcome is `refused`.
