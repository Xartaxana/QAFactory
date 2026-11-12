# Codex host notes

## The approved scope

`scope` holds pinned case ids, `[]` at S0, never the story's own key. At S4 the
pin step records them: `case_versions.py --task-root <root> --all` calls the
controller's `revise_plan` itself (read `scope` and `scope_note` in its answer);
the controller writes the keys the case index holds (`TC-001`, or
`<area>/TC-003` for a number two areas hold). `controller.py
--operation revise_plan` stays the hand door for a scope a person's words change;
a refusal that names it after a gate A decision is that door, then a new gate A decision.
A case nobody pinned is pinned first, with the same `--all`.

## The launch card

`story_step.py start` prints `dispatched <ID>` and `launch card: <path>` first and writes the
card (the Agent call to make) last. Output cut off before the card: run `story_step.py where
--task <T>`, never `start` again. `launch` (`card`, `subagent_type`, `bind`, `reason`): make that
call once, then `bind`; one from `where` is the launch, the late rest of `start`'s output is not
a second. `wait_start` (`card`, `age_s`, `rebuild`, `release`): `start` is still writing it; ask
again, no timeout. An agent id, receipt, return mark or denial for the dispatch means no `launch`;
with `start` gone, only the person's word (`release`) frees it.

## A packet committed outside `start`

`controller.py --operation rework` (and any packet `start` did not register) has no brief, form or
card: run `story_step.py materialize --task <T> --dispatch-id <ID>`, then launch the card it prints.
A second run writes nothing; a card that differs is refused, never replaced. `start --id` on that id
is refused.
