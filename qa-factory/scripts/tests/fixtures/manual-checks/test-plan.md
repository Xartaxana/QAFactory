---
task: T-1
---
# Test plan - T-1

## Plan

| TS | what we verify | R | defect hypothesis | impact class | priority | observable | oracle | disposition + reason | fit | level | technique |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TS-1 | cancel from settings | R-1 | state @ cancel | degraded | P2 | diff:src/a.py:1 | requirement:R-1 | `manual-agent` - an agent checks it in the running product | new | manual-agent | walkthrough |
| TS-2 | paid period | R-2 | boundary @ period end | money | P0 | diff:src/b.py:1 | requirement:R-2 | `manual-agent` - an agent checks it in the running product | new | manual-agent | walkthrough |
| TS-3 | old invoices | R-3 | contract @ reader | blocked-flow | P1 | diff:src/c.py:1 | requirement:R-3 | `manual-agent` - an agent checks it in the running product | new | manual-agent | walkthrough |
| TS-4 | export order | R-4 | order @ export | degraded | P2 | diff:src/d.py:1 | requirement:R-4 | `automate` - core AC | new | api | decision table |

## Recommended regression

1. run the billing suite
