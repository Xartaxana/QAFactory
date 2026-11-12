--- Agent prompt, verbatim; subagent_type: qa-case-designer ---
You are qa-case-designer. Ticket: CART-1. Dispatch: S4-qa-case-designer-2.
Artifacts dir: qa-factory/artifacts/CART-1/
Inputs:
  qa-factory/artifacts/CART-1/test-plan.md
  qa-factory/artifacts/CART-1/work/test-plan.json
  qa-factory/artifacts/CART-1/work/requirements-register.md
Rework of S4-qa-case-designer-1 (cause unnamed): critic round 1: TC_005 reject (guest cookie never sent with the signed-in read; seeded defect passes); TC_006 and TC_009 concerns in work/test-cases/critic-findings.md
Dispatch input_hash: d8a436dc0656612f1c97b4682c521e4433547b1a38a615b78d3db7b068791b0e; purpose: repair_verify
Your handover is the form qa-factory/artifacts/CART-1/work/handoffs/S4-qa-case-designer-2.yaml. Fill it as you work; what code could already answer is filled in.
  fill it with Edit, one field's own lines at a time (a Write over the existing form is refused); do not run the checker - `story_step finish` validates the form
  what you cannot fill: put it under `blocked` - the conductor answers, you never ask the person
Read qa-factory/artifacts/CART-1/work/briefs/S4-qa-case-designer-2.md first; it names the files and the commands.
Return your digest line only.
--- the moment the Agent call returns an id: story_step.py bind --task CART-1 --dispatch-id S4-qa-case-designer-2 --agent-id <id> ---
--- after the digest: story_step.py finish --task CART-1 --dispatch-id S4-qa-case-designer-2 --digest "<digest>" ---
