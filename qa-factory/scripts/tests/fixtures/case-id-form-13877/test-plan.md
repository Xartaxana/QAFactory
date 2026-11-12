# Test Plan - TP1-13877

**Ticket:** TP1-13877 - fix inverted `security_threshold` semantics (trimmed English copy of the live run, three manual-human rows)

## Plan table

| TS | R | what we verify | defect hypothesis | impact class | observable | disposition + reason | fit |
|---|---|---|---|---|---|---|---|
| TS-6 | R-6, R-7 | README threshold table and models.py docstring reflect LOW=permissive, HIGH=strict | state @ README.md:threshold_section | degraded | diff:src/README.md:25 | manual-human - documentation prose accuracy requires a person reading the diff | - |
| TS-9 | R-13 | README contains a migration note for operators with CODE_EXECUTOR_SECURITY_THRESHOLD=LOW | state @ README.md:migration_note_section | access | diff:src/README.md:25 | manual-human - migration note adequacy is a human prose judgment | - |
| TS-12 | R-12 | No downstream deployment or IaC file pins CODE_EXECUTOR_SECURITY_THRESHOLD=LOW | state @ external deployment repositories | access | none | manual-human - the deployment repositories are external to the factory | - |
