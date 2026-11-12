# 16 S3 question-branch finding(s), plan sha256 ac90eea42d0d, 2026-11-01T23:13:06+00:00
## Findings
- TS-2: `Q101` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-2: `Q101` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-5: `Q102` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-5: `Q102` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-11: `Q103` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-11: `Q103` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-14: `Q104` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-14: `Q104` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-23: `Q105` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-23: `Q105` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-24: `Q106` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-24: `Q106` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-25: `Q107` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-25: `Q107` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-26: `Q108` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row
- TS-26: `Q108` is not a question id of the register (ids are matched exactly: Q1 is not Q10, and an alias such as Q-R14 is no id); the register's ids are Q1, Q2, Q3, Q4, Q5, Q6 - the strategist's rework repairs this row

## Rows
Plan rows to repair, by id, in qa-factory/artifacts/LOCAL-1/work/test-plan.json. A row's lines move after any edit, so find a row afresh: `Grep -n` its quoted id in the plan, then `Read` with `offset`/`limit`; with a shell, `python "${CLAUDE_PLUGIN_ROOT}/scripts/plan_row.py" --task LOCAL-1 --show --row <id>` prints a row with its line numbers and `--map` lists every row.
- TS-2
- TS-5
- TS-11
- TS-14
- TS-23
- TS-24
- TS-25
- TS-26

Repair every finding above in qa-factory/artifacts/LOCAL-1/work/test-plan.json, then return your digest. Each finding names the field and the value it expects; read only the plan rows named above.
