# <TICKET-ID> — retro

<!-- Every number below is computed by scripts/retro_numbers.py into
     work/retro-numbers.md (rendered) and work/retro-numbers.json (facts).
     Quote them; never recompute them from journal.jsonl or state/cost/.
     Mode: pipeline.json.retro_mode — `full` (the default and what silence means:
     qa-retro-analyst writes the prose over the table), `numbers` (asked for by
     name: retro_numbers.py --write-retro writes this file, no dispatch and no
     model), `skip` (asked for by name: this file is not written at all). -->

## What went wrong, and what to do about it

Three to five lines, plain language, **first thing in the file**. Not a list of numbers —
a number, its diagnosis, and the action it argues for. A retro whose findings are only
visible to someone who reads to the end has not reported them. Nothing went wrong: say
exactly that, in one line, and move on.

- <what happened> — <the number, from retro-numbers.json> — <what should change>

## The numbers

<!-- Paste work/retro-numbers.md here unchanged: story spend and orchestrator share,
     cost and tokens per stage and per role, the three most expensive dispatches,
     rework, rejects and gate blocks, halts and human wait, time to the first test,
     estimate against actual. -->

When the table says **INCOMPLETE**, repeat the word in your own line too: a role whose
usage was not captured makes the total a floor, not a total, and no orchestrator share is
published while that holds. Never present a token count as if it were the cost, and never
report a 100% orchestrator share drawn from roles that read zero.

### Marathons

For each dispatch the table flags as expensive, its tool histogram from
`retro-numbers.json` — one line: role, requests, the two or three tools that dominate, and
the mechanism they point at. The count says a marathon happened; the histogram says what it
spent itself on, and only the second can be acted upon.

## Rejects and overrides

- Rejects × reason family: from the table.
- Disposition overrides at gate A (`overridden: true` rows in `test-plan.md`): <count, which
  rule was overridden most — a calibration signal, not a complaint>.

## Estimate vs fact

Forecast against actual, one line, appended to `records/estimation-ledger.jsonl` (an older project: `state/`).

## The human's answer

One necessary question at the end of S9: "What did you dislike in this session, what
should change?" — optional, recorded verbatim here and copied as a row into
`factory-backlog.md` (`scope: local-calibration` unless the human's own words point to
`local-urgent`). The orchestrator asks it before the retro runs, in every mode but `skip`.

> <verbatim answer, or "declined to answer">

## Findings → factory-backlog.md

- FB-n — <one line, if this story surfaced a finding about the factory itself>
