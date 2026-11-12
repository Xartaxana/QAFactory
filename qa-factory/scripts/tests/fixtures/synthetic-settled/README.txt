synthetic-settled - fixtures of test_cost_capture_settled.py (DP-3 = HF7-3, release 0.10.7)

This is NOT a snapshot of a stand: the stand of the specification (testproject1-dev-010) is not on the machine that built
the node, so every file here is synthetic, of the same shape the specification describes. The control numbers of the
measurement it cites are not reproduced. Nothing here holds money (no cost, *_usd or reconciliation value, no
dollar sign followed by a digit), no personal path and no text of a real message.

tails.json
  The REAL shapes of the end of a Claude Code transcript, from the measurement of t-243: after the row that matters
  the host appends non-message lines (`last-prompt`, `attachment`, `system`, `cost-state`); the file of a role ends
  with the host's `tool_result` for the handback call. Keys of the object are the case names K5a reads.
  Row text is a placeholder; types, flags (`isMeta`, `isSidechain`), tool names and ids are as the host writes them.

cost-0.10.4-provisional.json, cost-0.10.4-complete.json
  A cost file of the logic before 0.10.7: no `capture_logic`, no `usage_final`; one says `provisional`, the other
  `complete` (the old `--recapture` wrote it for any session). The `transcript` field holds the placeholder
  `{transcripts}/main.jsonl`; the test copies the file into a temporary folder and puts that folder's path there.
