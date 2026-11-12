<!-- generated from plugin:references/coverage-design.md for qa-doc-scribe by scripts/contract_slices.py; edit the source, never this file -->
# Coverage design

Use this reference in S1–S4 to turn bounded discovery into reviewable coverage obligations.
It defines design evidence; execution results remain in the existing run lifecycle.

### Evidence freshness

A reviewed assertion link is still only reviewed coverage until it has fresh execution
evidence; never merge evidence from two tests into one assertion claim. A ledger row that
reports a reviewed link as verified states an execution that never happened.
