# The handover form

Every handover between two roles has a contract in `handoffs/`, and the contract is both the
form the sending role fills and the schema the check enforces. `handoffs/README.md` documents
the contracts themselves - what each one hands over and why it carries the fields it does.
This file is the operational half: the commands, and what a refusal from them means.

The other half of a stage boundary. `start` writes the role's form from the contract in
`handoffs/` (which pair of roles gets which contract is `handoffs/index.yaml`, never a file
name), names it in the prompt, and `finish` accepts the dispatch on a green check and keeps
the form as evidence. `handoffs/README.md` is the contract's own documentation; these are the
three commands:

```text
python "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_init.py"  --task <T> --stage S<n> --role <role> [--to <role>] [--dispatch <id>] [--scope TC-1,TC-2]
python "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_check.py" --file work/handoffs/<dispatch>.yaml --task <T> [--fix] [--values FILE|-] [--set path=value] [--json]
python "${CLAUDE_PLUGIN_ROOT}/scripts/handoff_help.py"  --file work/handoffs/<dispatch>.yaml [--field F] [--problem "..."] [--candidate WORD]
```

- **`--fix` is the point.** Everything derivable from the artifacts is written in by code and
  recorded under `derived` (the field, and where the value came from): the
  run witness out of the manifest's own `runs[]`, the pinned case version out of
  `story-case-links.json`, the test files, the probes, the stand's provenance record. On
  TP1-13797 those refusals woke a role with 200k tokens of context again and again -
  twenty-three resumed sessions at S5 ($14.15) beside nineteen conductor sessions ($5.97).
- A refusal names the field, the problem and **the values that role may write** (narrowed by
  `used_by`/`restricted_to`, so a critic is not shown a strategist's dispositions). Nothing it
  says is about the quality of the work.
- A **claim** the form makes is verified against the artifacts. `every_instance_names_its_
  current_case_version: true` with ten stale links in the manifest is refused here - on that
  run it travelled instead to gate B as eleven delivery reasons owned by "product".
- With a judge configured, a word outside a closed list is mapped onto it by the question that
  already asks exactly that (`form_row_state` for a row's state, `form_digest_verdict` for a
  verdict, `form_unresolved_reason` for an `unresolved` reason) instead of a resumption; the
  mapping lands in the form's `judged[]` with `as_written`, and the receiving role may refuse
  it like any other claim.
- What a role cannot fill goes under `blocked` and to the CONDUCTOR (`handoff_help.py`,
  question `conductor_resolution`), never to the person. Its most useful field is `candidate`:
  the word the role would have written is how a hole in the vocabulary is found.
- **The form is required by default.** `finish` refuses a dispatch whose form the role never
  filled, and one it filled and left incomplete. A project that does not want the form sets
  `handoffs.required: false` in `qa-factory/config.json`; `finish --ignore-handoff` passes a
  single dispatch on the person's word, recorded like any other block by whoever records
  their words (the conductor with their words in the prompt, or the person).
