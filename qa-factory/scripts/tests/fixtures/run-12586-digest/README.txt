Fixture of live run 12586 (hotfix-12586/4 HF4-6): the SubagentStop of a qa-case-critic whose own last word is
a SubagentHandback call, while the parent session's last assistant row is the conductor's prose.

Sources on the stand (read only):
  subagents/agent-a19dac213a6228a50.jsonl <- C:\Users\dev1\.claude\projects\D--ws-testproject1-dev-010-testproject1-sdk-test-harness\22686563-d408-46cd-b461-7c3b276d6746\subagents\agent-a19dac213a6228a50.jsonl, rows 75-76
  parent.jsonl <- the parent session 22686563-d408-46cd-b461-7c3b276d6746.jsonl (same folder, one level up), its last assistant row with text before row 75 (line 816, 2026-10-28T01:03:30Z)
Journal evidence: D:/ws1/testproject1-dev-010\testproject1-sdk\test-harness\qa-factory\records\journal.jsonl lines 17, 31, 56
  (gate_block "not the handoff form" naming the parent's prose as the role's first line).

Changed: the parent's prose is translated from Russian to English (same shape: a lead sentence, a bold-led bullet, a
closing line); usage, request ids, classifier context, wire inputs are dropped from the child rows and cwd becomes
/project. Kept: message ids, the tool_use id, uuids, timestamps, the handback input verbatim (it holds no Cyrillic).
event.json paths are relative to this folder; the test resolves them. No secrets, no thinking signatures, no
api-request rows.
