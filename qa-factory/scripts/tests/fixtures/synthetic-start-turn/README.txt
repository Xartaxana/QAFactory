SYNTHETIC fixture - not a snapshot of any stand or of any real session.

It was written by hand (release 0.10.7, node HF7-4) because no stand exists on the machine that built it.
The numbers measured on a real stand (35,223 s over 453 turns, 14,396 s over 18, ...) are NOT reproduced here
and nothing in the test pins them; the test pins the RULES, on the small numbers written below.

Files (transcripts are Claude Code `user` / `assistant` rows with the host's field names, message text replaced
by a stub; activities files have the shape `activity_capture.py` writes):
- chat-story.jsonl + chat-story.activities.json: two turns of the person, then a story that starts 5 s after the
  orchestrator's last request of the second turn (09:10:30). The first turn (09:00) starts no activity and stays
  where it was (Unclassified). The second turn (09:10:00..09:10:30) is the story's: its requests are the story's
  and the person's wait before it is not counted as a wait inside the story. Rows between: a tool result with
  a promptId and a host meta line, neither is a turn of the person.
- onboarding.jsonl + onboarding.activities.json: a turn that starts an onboarding (10:40, onboarding starts
  10:44:02, closed 12:30), a Write into `qa-factory/state/onboarding/` (the old reader read it as a task named
  "onboarding"), and a chat after the closure (13:05..13:18) which stays Unclassified.
- user-forms.jsonl: every kind of `user` row the classifier tells apart: the person's message, a tool result
  carrying a promptId, a meta line, a compaction summary, a background task's notification, a slash command's
  `<command-message>` row (the person's). Used by scan only.

No money (the usage rows carry token counts only) and no personal path: the test checks both, with a negative
control.
