<!-- generated from plugin:references/artifact-contract-automation.md for qa-failure-analyst by scripts/contract_slices.py; edit the source, never this file -->
# Artifact contract — the automation artifact

What S5 produces and every later stage reads.

## Instance identity

One test is `<function>[<parameter>]`, built by `contract.instance_id`. Manifest, `stage-scope`, stage guard, RunRequests and `then_bindings`
use that one spelling; `instance_id_aliases(entry)` matches the older spellings to the same
row. **One `tests[]` entry per instance, never one per case.** An id names no case: an
instance proves the cases in its `covers` and the pinned `case_version_links[]`.

### `runs[]`

`runs[]` — **every** launch in this story, appended by its maker, never
rewritten; `scope` is the node ids run. `warranted` is `true` when `code_fingerprint` (short git
hash of the touched test files) differs from the last run of that scope or the run changed the
code on purpose; `false` re-proved an unchanged green, the retro counts it.
