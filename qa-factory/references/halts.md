# Halts

Loaded when a stage halts (`skills/qa-story/SKILL.md`, "Halts"). A halt stops the pipeline where it stands; the table says, per
digest or condition, what to read first and what is left for the person.

## Halts

Read what the halt left (the digest, the record or log it names) and settle what is yours; what is left goes to the person in the
human-questions form. "go on without it" is always an answer.

| Digest or condition | Read first | What is left for the person |
|---|---|---|
| `readiness.py --require` exits 1 | The capability records it printed. | The missing capabilities and owners, verbatim; nothing else. person-owned: access |
| `config.schema_version` mismatch | The two schema numbers in the config and in the factory. | Config is schema `<n>`, the factory needs `<m>`; `/qa-factory:qa-onboarding` migrates. person-owned: access |
| `qa-scout ... no diff` | The scout's digest and the story's branch record. | The fixed three-option question (`phases/s1.md`); never a search of your own. person-owned: requirement_intent |
| `qa-scout ... requirement/code conflict` | Both sources the scout quoted, with `path:line`. | Both quotes; go on only on a recorded decision. person-owned: requirement_intent |
| `qa-scout ... <capability> unavailable` | The scout's probe line for that capability. | What is unreachable, what is needed, from whom. person-owned: access |
| `qa-requirements-tester ... blocked` | The understanding brief and its question packet. | The brief alone, with its question packet, before any plan exists; the answers are recorded by code (`phases/s2.md`). person-owned: requirement_intent |
| Dirty working tree at S5 | `git status` of the story's repository. | "stash / commit / proceed with a warning / abort", recorded. person-owned: risk |
| `qa-automator ... not on story branch` | The branch the role reported against the story's branch. | Nothing: re-run the S5 entry steps; never let the role branch. factory: a finding, not a question |
| `qa-automator`/`qa-code-critic ... repair cap reached` | The unresolved table of the window. | The table of what is unresolved; no third round. person-owned: money |
| `qa-case-critic ... round cap` | The critic's digest. | Nothing: `done · verdict=reject` goes to gate A with the case ids. factory: a finding, not a question |
| `qa-automator ... contradicts_requirement` | The requirement, the expected and the observed in the handed-over test. | Nothing: the red test is the proof and S7 triages. factory: a finding, not a question |
| `stage_done.py` exits 3, `STORY BUDGET:` | The `STORY BUDGET:` line. | The stage is closed; show the line, ask; their word: `waiver.py --block "story budget"`. person-owned: money |
| `qa-runner ... env_blocked` | The stand-gap card and the runner's evidence. | The stand-gap card. person-owned: access |
| `qa-failure-analyst ... cannot triage` | What `env_probe`/`run_suite` reported. | What they reported, when the stand or the suite is the cause. person-owned: access |
| `env_probe.py` exits 1 | The blocking line (`liveness`/`login`/`keys`) and its cause. | The blocking line and its cause. person-owned: access |
| `run_suite: executor_unavailable` | The three options the suite printed. | Its three options; only (c) hands over (`--block "executor unavailable: <profile>"`). person-owned: access |
| `qa-doc-scribe ... cannot assemble gate B` | What the scribe reported. | Nothing: gate B never opens on a hand-built ledger; the scribe rewrites. factory: a finding, not a question |
| A `stage_guard` denial on a dispatch or a command | The guard's message. | The guard's message, verbatim, and stop. person-owned: gate_word |
