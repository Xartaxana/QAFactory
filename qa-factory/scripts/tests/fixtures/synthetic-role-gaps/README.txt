SYNTHETIC fixture - not a snapshot of any stand or of any real session.

It was written by hand (release 0.10.7, node HF7-1) because no stand exists on the machine that built it.
The numbers measured on a real stand (26 agent files, 39 journal lines, 11 false names) are NOT reproduced
here and nothing in the test pins them.

What it holds, in the shape of a cost file's `agents[]` and of the journal's `subagent_stop` lines:
- sessions.json: four sessions. Session a has eight role files (2 scouts, 4 case designers, a reviewer, a
  critic), every one carrying usage; the others have one role file each. The files name their role as the
  host does (`qa-factory:<role>`).
- journal.jsonl: one `subagent_stop` line per dispatch, naming the role as the journal does (the bare name,
  except one line that keeps the namespace), plus one line of another event. The critic's line has no
  `dispatch` id.

The case the fixture exists for: one role in two spellings is one role. The old comparison (`rec["agent"] not
in {agent names of the files}`) names three false gaps on session a (`qa-scout`, `qa-case-designer` and
`qa-critic`; the reviewer's line keeps its namespace and matches) and one each on sessions b, c and d, and
the fixed comparison names none. The test computes the old comparison itself and requires it to be
non-empty (3 on session a), so the fixture cannot silently stop discriminating.

No money (no cost / *_usd field, no dollar sign followed by a digit) and no personal path: the test checks
both, with a negative control.
