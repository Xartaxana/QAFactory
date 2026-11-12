# The judge and one-command stage boundaries

Two things that remove model turns without removing a function. Both are optional; with
neither configured the factory behaves exactly as before.

## Stage boundaries — `story_step.py`

A stage boundary is deterministic: build the dispatch request, run the guard, record
`running`; later hash the evidence, accept, record `done`, ask what is next. Typed by hand it
cost six to ten orchestrator turns per role. It is one command each way:

```text
python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" start  --task <T> --stage S<n> --role <role> [--scope TC-1,TC-2] [--purpose repair_verify] [--id <dispatch id>]
python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" bind   --task <T> --dispatch-id <id> --agent-id <the host's id for the agent>
python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" finish --task <T> --dispatch-id <id> --digest "<digest line>" [--output work/<file>] [--not-complete]
python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" pause  --task <T> --dispatch-id <id> --reason "<why>" [--status blocked|paused|incomplete]
python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" resume --task <T> --dispatch-id <id> [--agent-id <the agent that continues>]
python "${CLAUDE_PLUGIN_ROOT}/scripts/story_step.py" where  --task <T>
```

That list is the whole interface — reading `--help` or grepping the plugin for it costs
turns the story does not have (21.09: about thirty of them).

- `start` prints the `Agent` prompt. Use it verbatim, adding only what the phase file says
  the person decided (flags, a recorded requirement/code decision). It never launches a role.
- **`bind` records the id of the `Agent` call.** On Claude the plugin's hook runs it when the call returns; run it by
  hand only on Codex or when the guard or `where` says the dispatch is unbound. It writes that id into
  `pipeline.json` (where the resume guard looks before it lets a follow-up reach the agent
  that still holds the context) and a receipt under `state/host-dispatches/` (where
  `dispatch_liveness.py` looks). `start` cannot do it: the id does not exist until the host
  has spawned the role, and on 21.09 the guard refused a follow-up for exactly that reason.
  `finish` marks the receipt terminal again.
- `finish` takes the role's digest line. A stage with two roles (S4, S5, S8) stays open after
  the first; `--not-complete` keeps it open after the last, for a review round that sends
  work back. `--output work/<file>` adds evidence the stage does not declare.
- `pause` checkpoints a dispatch that stops for the person — the S1 source review.
- `resume` puts a dispatch stopped for the person back to running; the same agent continues.
- A line starting `story_step: refused` is the controller's, the guard's or `stage_done`'s
  own refusal, verbatim: treat it as you would from that script. Nothing is decided here,
  and the requests in `controller-api.md` remain valid when this command cannot express one
  (`rework`, `gate-decision`, `revise_plan`, `recover` are already one command each).
- A `note:` line naming a script that "is not in this build" is not an error: that judge
  package has not landed here, and the role does the judgment itself, as always.
- S0 is unchanged: it writes `pipeline.json`, records itself with `stage_done.py` and
  initializes the controller.

`next:` is the controller's next action. `pipeline.stop_after` in `config.json` takes
`"gate_A"`, `"gate_B"` or nothing: that gate is presented and recorded as usual and the
answer after it is `{"action": "stop"}` — say `<T> stops after Gate A (pipeline.stop_after)`
and end.

The other half of a stage boundary - the handover form the role fills and
`handoff_check.py` repairs by code - is `references/handoffs.md`.

## The judge — `judge.py` and the judgment registry

A System One model answers typed questions — yes/no with a probability, one option of a
list, a level of a rubric — in about 100 ms, for cents per story. It writes nothing and
converses with nobody. The factory uses it for judgments that were one model turn each.

Every question lives in `references/judgments.json` (the calibrated S1–S4 set) or in one
`references/judgments.d/<subject>.json` beside it; `judge.py` reads them as one registry and
ids are unique across all of them.

| Stage | Script | What is asked | Who acts on the rest |
|---|---|---|---|
| S1 | `judge_sources.py` | is a mentioned ticket relevant, what it is to the story, is an attachment worth opening | `qa-scout` assesses undecided mentions |
| S1 | `judge_diff.py` | per diff hunk: which AC it implements, or unrelated / infrastructure | `qa-scout` reads the hunks left |
| S2 | `judge_requirements.py` | every pair of requirements: opposite or not; observation channel; outcome stated; which comments touch scope | `qa-requirements-tester` examines `conflicts` and `possible` |
| S3 | `judge_plan.py` | lowest sufficient test level; damage as a hint | `qa-test-strategist` |
| S4 | `judge_cases.py` | per case: Then observable, negative reachable, matches its plan row, catches a seeded defect | `qa-case-critic` reviews every flagged case in full |
| S5 | `judge_code.py` | per test function: assertion matches the Then, sleep justified, locator fragile, fixture unneeded, plus the code-review rubric; `--cause` maps a finding to `repair_cause` | `qa-code-critic` reviews every flagged test in full |
| S5 | `s5_precheck.py` | is a smell or a remaining oracle finding (case-is-oracle, dispute-unstated, the relative oracle) justified after all (mode `on` downgrades it to a hint); never `open-oracle-asserted`, which no judge sees, and never `changed-after-red`, which only a record and the critic's verdict answer | the precheck refuses as before |
| S5/S6 | `judge_run.py` | the culprit of a run, whether it is an environment block, and a remedy's kind and place | `execution_status` stays what the code derived |
| S5/S6 | `stand_health.py` | are two consecutive failures the same cause when their lines differ | exact-match stays the fast path |
| S1–S8 | `judge_form.py` | a digest, a row state, an `unresolved[]` reason or a test id that misses the vocabulary by its wording | the refusal fires as it does today |
| S0–S9 | `handoff_check.py` | a word outside a closed list of the handover form, mapped onto the list instead of a role resumption | the field is refused with the role's own values |
| S0–S9 | `handoff_help.py` | what kind of problem a role's filling question is: fill, correct the work, ask the person, change the contract | the conductor answers the same request file |
| any | `judge_calibration.py` | nothing - it reads the journal and says which question to keep, re-threshold or retire | a question nobody asks is a call site that does not exist |
| S6 | `judge_results.py --observation` | does the runner's observation match the Then | `qa-runner` records what it saw |
| S7 | `judge_results.py --triage` | triage verdict (`APP_BUG` as a leaning only), case defect, flaky mechanism | `qa-failure-analyst` |
| S8 | `judge_results.py --bugs` / `--ticket-diff` | draft duplicates an existing bug, priority from the damage line, severity of a ticket change | `qa-bug-reporter`, and the person at gate B |
| S9 | `judge_results.py --trap` | which document owns a recurring trap | `qa-retro-analyst` |
| Gates | `judge_reply.py` | what a person's answer means, which stand-gap option it is, whether two refusals share a cause | the orchestrator asks them, as before |
| Onboarding | `judge_discovery.py` | which candidate is the test command, the env file, the login site, the role of a key NAME | the interview asks |

`story_step.py` runs the ones a role cannot run for itself at the right boundary and passes
their files to the role: `judge_cases.py` before `qa-case-critic`, `judge_plan.py` before
`qa-test-strategist`, `judge_code.py` before `qa-code-critic`, `judge_results.py --triage`
before `qa-failure-analyst`, `--bugs` before `qa-bug-reporter` and again when S7 or S8 closes
with drafts on disk, so gate B's list carries them.

`config.json`:

```json
"judge": {"provider": "none", "mode": "shadow", "api_key_env": "TYPESAFE_API_KEY"}
```

- `provider: none` — nothing is sent anywhere. `typesafe` — questions and the ticket text
  they are about go to `api.typesafe.ai`. That is the project owner's decision, never the
  factory's; onboarding does not turn it on.
- `mode: shadow` — answers are journalled to `state/judgments.jsonl` and written beside the
  role's own work for comparison; no role acts on them. `mode: on` — a decided answer
  replaces the judgment it is registered for; an undecided one goes to the role as before.
- The key is read from the named environment variable, never from a file, never printed.
- `thresholds.<id>` overrides a registered threshold; `disabled: [<id>]` switches one off.

## The three classes of refusal

The factory's refusals are not one kind of thing, and only one of them stays hard.

| Class | What it is | Who decides |
|---|---|---|
| **Safety** | a write into application code (P-00), a secret, an external write, passing a gate, `deliver_with_risks` | code and the person. The judge is not asked, and an answer of its own would not be listened to: the state is ticket text and logs, which are untrusted, and the model is not hardened against instructions inside them. |
| **Form** | a digest worded differently, a state spelled another way, a reason outside the vocabulary, a test id carrying a plugin prefix, a shrunken manifest | the judge maps it to the vocabulary when it is sure; unsure, the old refusal fires unchanged. |
| **Diagnosis** | who is to blame for a run, stand or test, `repair_cause`, a triage verdict, a remedy's kind and place | the judge classifies; the role gets what it left undecided; the person gets the risk. |

A refusal of FORM or DIAGNOSIS may be a **judged refusal** (`judge.judged_refusal`): before
refusing, the code builds a small state — the thing in front of it and the rule's intent —
and asks whether it satisfies the intent. A confident yes in `mode: on` passes it and
journals a `pass` row; anything else refuses exactly as before. In `shadow` a would-be pass
is journalled and nothing changes.

**Every pass is shown to the person.** `judge.passes()` feeds the `## Judge` block of both
gate briefs — the refusal, the question that passed it and its probability, one line each —
and `story_step.py where|finish` prints the count. A block the judge let through that nobody
could have questioned is the failure mode this block exists to prevent; one word brings any
of them back.

Rules the code holds, in every mode:

- **An answer never lifts a block, passes a gate or authorises a write.** A judged source
  decision is a row of the person's source review like any other, and one word flips it.
- **Under its threshold an answer decides nothing.** The item goes where it went before.
- **The judge failing is not a halt.** No key, no network, an overloaded service: the
  script says `unavailable`, exits 3, and the role does the judgment.
- **Every question is registered**, with what it replaces, who gets an undecided item, and
  how it was calibrated. A question that failed calibration stays there, `enabled: false`,
  with the reason. The subject of a question is its own small state — one requirement, one
  pair, one case, one test function, one log head — never an id looked up in a large shared
  one, which is how the first calibration got confident wrong answers.
- The model does not count, compare dates or follow a chain of inferences. Those stay code
  or stay the role's.

`judge.py status --probe` checks the key and the service; `judge.py summary --ticket <T>`
prints the questions asked, the share decided and the money.
