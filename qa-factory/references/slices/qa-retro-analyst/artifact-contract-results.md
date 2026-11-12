<!-- generated from plugin:references/artifact-contract-results.md for qa-retro-analyst by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract — what gate B and closure are built from

The documents S8–S9 produce. Where they live: `artifact-contract.md`. The values they are
checked against: `vocabularies.md`.

## `retro.md`

**Writer** `qa-retro-analyst`, S9 — the default, and what silence at gate B gets. The one
exception is the retro a person asked for by name: in `retro_mode: numbers` the writer is
`scripts/retro_numbers.py --write-retro`, which renders the file from the computed numbers
and the recorded gate answers. No third writer exists: the orchestrator never authors
`retro.md`, in any mode. `retro.md` **readers** the human, the dashboard.
It opens with *what went wrong and what to do about it* — three to five plain-language
lines, each a number with its diagnosis and the change it argues for — and only then gives
time per stage, human wait per gate, cost per role, marathons **with their tool
histograms**, the redundant-run count, rejects by reason family, gate-A disposition
overrides, forecast vs actual, and the human's verbatim answer to the one closing question.
A finding visible only to someone who reads to the end has not been reported.

**Validator** none beyond the language and size checks — this is a narrative artifact.

Nothing is handed to the next story through this folder. What outlives the run goes to the
project's documents: the S9 knowledge fold (`faq.md`, the glossary, `project-profile.md`,
`framework-rules.md` or `test-strategy.md`), and `obligations.md` for what stays open —
read by **S0 of the next story**, by trigger or by area. That is the only carrier between
stories.

Archiving is the **human's** flag: `pipeline.json` gets `"archived": true` only when a
person answers `qa-doctor`'s offer, and the folder never moves — moving it separates
`requirements-register.md` from the case files citing it, and every case then reads as
inventing its requirements.
