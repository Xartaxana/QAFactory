--- Agent prompt, verbatim; subagent_type: qa-automator ---
You are qa-automator. Ticket: CART-1. Dispatch: S5-qa-automator-6.
Artifacts dir: qa-factory/artifacts/CART-1/
Inputs:
  qa-factory/artifacts/CART-1/state/story-case-links.json
  qa-factory/artifacts/CART-1/test-plan.md
  qa-factory/artifacts/CART-1/work/context-bundle.json
Rework of S5-qa-automator-5 (cause test_defect): tests[] row for CART-1_TC_009 is NOT in the manifest (revision 23: 16 tests, none TC_009; only the unresolved contradicts_requirement row). Re-send it via manifest_put.py and verify by reading the manifest back.
You are resumed (same agent as S5-qa-automator-5): the brief is already read; read only qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6-delta.md. If you do not hold S5-qa-automator-5's context, read qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-6.md first.
Dispatch input_hash: ffc7c3737535a405008987b7660a0d29e57055aa7d7cb7f794ee3ac77ae6c40d; purpose: repair_verify
Your handover is the form qa-factory/artifacts/CART-1/work/handoffs/S5-qa-automator-6.yaml. Fill it as you work; what code could already answer is filled in.
  when it is filled: python "<path-2>/ai-packages/qa-factory/scripts/handoff_check.py" --file qa-factory/artifacts/CART-1/work/handoffs/S5-qa-automator-6.yaml --task CART-1 --fix
  it refuses with the field, the problem and the values YOUR role may write; nothing it says is about the quality of your work
  what you cannot fill: put it under `blocked` and run handoff_help.py --file qa-factory/artifacts/CART-1/work/handoffs/S5-qa-automator-6.yaml - the conductor answers, you never ask the person
Return your digest line only.
--- the moment the Agent call returns an id: story_step.py bind --task CART-1 --dispatch-id S5-qa-automator-6 --agent-id <id> ---
--- after the digest: story_step.py finish --task CART-1 --dispatch-id S5-qa-automator-6 --digest "<digest>" ---
