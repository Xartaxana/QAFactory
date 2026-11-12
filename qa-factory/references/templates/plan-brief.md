# <TICKET-ID> — plan brief

<!-- Written by qa-test-strategist at S3. ≤ 15 rows; checked by validate_artifacts.py: the
     row count matches test-plan.md, or rows are explicitly grouped with an "and N more"
     line. Part two of the gate-A message. The full plan (test-plan.md) is linked, not
     required reading to decide. -->

| Row | What we verify | What can break | How painful | Disposition + why | Fit |
|---|---|---|---|---|---|
| TS-1 | <one line, the check> | <class @ place> | <impact class> | `automate` — <one-clause reason from the four inputs> | `extend <test>` |
| TS-2 | <one line> | <class @ place> | <impact class> | `manual-agent` — <reason> | `new` |
| TS-3 | <one line> | <class @ place> | <impact class> | `manual-human` — <reason> | — |
| TS-4 | <one line> | <class @ place> | <impact class> | `skip` — <reason> | — |
| TS-5 | <one line> | <class @ place> | <impact class> | `unverifiable` — <reason, fed back as a requirements defect> | — |

<!-- Disposition — closed list: automate · manual-agent · manual-human · skip ·
     unverifiable (automation-candidacy.md). Fit — closed list: extend <test> ·
     param <test> · new (embedding ladder, automation-candidacy.md); empty for
     non-automate rows. Impact class — closed list: data-loss · money · access ·
     blocked-flow · degraded · cosmetic · none; priority is derived from it, never
     assigned directly. More than 15 rows → group by area with a visible "+N more,
     see test-plan.md" line rather than truncating silently. -->

## Recommended regression

<Existing tests tied to this story's blast radius — a recommendation for the human to run
themselves, not something the factory executes in v0. A test this story writes is not
regression. Nothing to name: `No regression: <reason>`.>

Command: <the project's own test command, as the project runs it> <target> <target>
- `<path>` (blast:B-n) — stand: <what it needs | no stand requirements>
Developers: <component checks>
