approve
Gate A: **approved.** Proceed to S5 with the plan and the case set as they stand — no edits; test it as one story, do not split, even at size XXL over the cap. The critic's `approve_with_concerns` verdict stands as it is.

The items, by name:

1. **Dirty working tree (25 uncommitted changes on this branch)** — go on, on this branch as-is. Nothing is committed or stashed on my behalf.
2. **Toolchain (`ModuleNotFoundError: No module named 'pydantic'`, tests cannot even be collected)** — install it: run `poetry install` in `test-harness` on my word, then re-run `pytest --collect-only` and go on. I will not have S5 write code that nothing can run, and I will not accept "not executed" for a missing dependency.
3. **Stand gap RP-api (no machine-readable report)** — **apply**, and read its own diagnosis first: the reporter is not misconfigured, the collection fails for the same missing dependency as item 2. After the install, re-probe the card; if a run still leaves no report the factory can read, then change `profiles[api].commands.one_test` as the card describes and record it.
4. **Credentials and accounts** — accept the gap. AWS_ACCESS_KEY / AWS_SECRET_KEY / AWS_PROFILE are not available on this stand, and the auditor, default_scoped_user and project_scoped_user accounts are not provisioned; report the cases that need them as not executed, by name, and never as passed.
5. **TS-19's declared gap** — accept the gap, with the reading in Q1 below: the row stays in the plan, carries its conflict flags, and produces no invented oracle.

The open questions:

- **Q1 (AC7, UI visibility of the filter configuration)** — reading **(a)**, in my words: this is **missed scope, not a deferral**. The ticket's AC7 stands; the MR's own spec declares testproject1-ui out of scope, and no testproject1-ui branch, MR or `settingsUIConfig.ts` key for `github_json_path_filter` exists. So the UI requirement stays unmet in this delivery and is reported as a discrepancy against the acceptance criteria: a **local bug proposal under `qa-factory/bugs`, nothing goes to Jira**. No UI test row this cycle — there is nothing to observe yet — and the plan notes AC7 as not-yet-satisfiable.
- **Q2 (the pre-existing event-type filter's 400 → 200)** — reading **(a)**: the 200 acknowledgement for a filtered-out or disallowed event is the intended, documented behaviour, aligned with the GitLab precedent, not a regression under AC9. Test the new 200/no-dispatch outcome as the norm. No backward-compat case asserts the old 400 still occurs, and no migration note is owed by this story. Question closed.
- **TS-10 (the same fork, R-11)** — it is the same question, answered the same way: automate the resolved half only (200, no dispatch), exactly as the row already does. Drop the disputed "assert the old 400 is gone" sub-assertion; it tests a behaviour we just declared gone by design.

Two more things from the packet:

- **The gate decision that will not record (TS-19's design review is not independent and its cases carry no pinned version)** — that is the factory's own repair, not a decision of mine: rework the S4 designer and critic so the row's cases are pinned and reviewed by a dispatch that did not write them, then rehearse the gate again. My approval above stands and is not to be re-asked afterwards.
- **TP1-13289, surfaced after the S1 review** — stays left out, as before: it is not a source for this story.

The warnings: run the read-only ticket-adapter probe, it is the factory's own receipt and it is cheap — the adapter demonstrably read the ticket, its comments and four merge requests this run. Leave the `config_schema` migration alone: this is an experiment copy and no migration decision is made tonight; carry it as a warning.

Standing for the rest of the run, unchanged: bugs stay local proposal files under `qa-factory/bugs` and are not submitted anywhere; a merge request, if the pipeline reaches one, is opened as Draft only, on a branch with the suffix `-c`; the remote branches TP1-13797_github-webhook-json-path-filter and -b are ignored entirely — they are not a source, not existing coverage and not a precedent.
