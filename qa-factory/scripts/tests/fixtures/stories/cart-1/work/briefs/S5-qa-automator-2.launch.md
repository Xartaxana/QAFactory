--- Agent prompt, verbatim; subagent_type: qa-automator ---
You are qa-automator. Ticket: CART-1. Dispatch: S5-qa-automator-2.
Artifacts dir: qa-factory/artifacts/CART-1/
Inputs:
  qa-factory/artifacts/CART-1/state/story-case-links.json
  qa-factory/artifacts/CART-1/test-plan.md
  qa-factory/artifacts/CART-1/work/context-bundle.json
Your handover is the form qa-factory/artifacts/CART-1/work/handoffs/S5-qa-automator-2.yaml. Fill it as you work; what code could already answer is filled in.
  when it is filled: python "<path-2>/ai-packages/qa-factory/scripts/handoff_check.py" --file qa-factory/artifacts/CART-1/work/handoffs/S5-qa-automator-2.yaml --task CART-1 --fix
  it refuses with the field, the problem and the values YOUR role may write; nothing it says is about the quality of your work
  what you cannot fill: put it under `blocked` and run handoff_help.py --file qa-factory/artifacts/CART-1/work/handoffs/S5-qa-automator-2.yaml - the conductor answers, you never ask the person
Read qa-factory/artifacts/CART-1/work/briefs/S5-qa-automator-2.md first; it names the files and the commands.
Return your digest line only.
--- the moment the Agent call returns an id: story_step.py bind --task CART-1 --dispatch-id S5-qa-automator-2 --agent-id <id> ---
--- after the digest: story_step.py finish --task CART-1 --dispatch-id S5-qa-automator-2 --digest "<digest>" ---
