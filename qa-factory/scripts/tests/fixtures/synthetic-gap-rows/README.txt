SYNTHETIC fixture - not a snapshot of any stand or of any real session.

It was written by hand (release 0.10.7, node HF7-2) because no stand exists on the machine that built it.
The numbers measured on a real stand (11 false names on one session) are NOT reproduced here and nothing in
the test pins them.

Three cost files, cut down to what the By-task grouping reads (`by_activity`, `agents[]`, `requests[]`, the
gap fields). No money anywhere: rows carry token counts and `pricing_coverage: none`; the test checks the
directory for money fields and for a dollar sign followed by a digit, with a negative control.

- doc-before.json: a file as the previous release wrote it. Three roles are named as gaps by their bare
  journal name (`qa-scout`, ...), though their files carry usage and their rows are all of the story
  activity; two more rows belong to no activity. The old grouping put every name on every label of the
  session (so on "Unclassified" too); the new one puts each name on the label its own rows have.
- doc-doctor.json: the same shape for a doctor run: one role, rows of the doctor activity and of no activity.
  The name belongs to "Doctor" only.
- doc-journal-gap.json: a file as the current release writes it: a role the journal saw dispatched and that
  left no file (`qa-ghost`), with its place in `incomplete_where` (the story activity, which has rows).
