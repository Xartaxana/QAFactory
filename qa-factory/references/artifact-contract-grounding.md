# Artifact contract — the grounding artifact

What S1 hands to every stage after it. Injected to the scout, which writes it.

Companion to `artifact-contract.md` (closed vocabularies and the markdown artifacts) and `artifact-contract-json.md` (the story's state files). Types: `str`, `int`, `bool`, `[]` list, `{}` object, `?` optional.

## `context-manifest.json`

**Writer** `qa-scout`, S1. **Readers** requirements tester, strategist, automator,
`ledger.py` (open subtasks).

`ticket` str · `issue_type` str? — the ticket's own `type`, verbatim and unmapped; `sizing.py`
caps a `bug`/`defect`/`incident` story at one regression case, and without it every bug is
sized as a feature · `acceptance_criteria` [] · `implementation` {} (`source`, `mr`, `branch`,
`commit`, `diff_path`) — the primary repo's, and the same object as `implementations[0]` ·
`implementations` []? of `{repo, source, mr, branch, commit, diff_path}` — **one entry per
declared repository the cascade ran in** (`config.code_repos[].name`, or `tests` for this
one); a change split across a backend and a UI repository has two · `observables` [] of
`{requirement, kind: api|ui|db|event|config|cli,
source: diff|current-code|expected-contract, path, line, note?}` (`requirement` empty for diff behaviour no requirement names) · `parent_feature` {}? ·
`related` []? of `{key, kind: implementation|blocker|bug|mention, source}` — tickets this
ticket NAMES, never the parent's other children · `subtasks` [] of `{key, status}` — any status outside `done`/`closed`
counts as open and becomes a `subtask_in_progress` ledger row · `existing_tests` [] ·
`test_path` {} (layers, fixtures, page objects, data) · `area_bugs` [] · `conflicts` [] ·
`witness` str.

**Checked** required keys `ticket`, `acceptance_criteria`, `implementation`; every `related` entry carries a `kind`
from the closed list and a non-empty `source` — an entry with no source is a ticket the
scout went looking for rather than one the ticket named; every `implementations` entry
names a `repo` and a `source` from the closed list, and the first one agrees with
`implementation`. An observable's `source` is not checked here: the requirements tester copies it into the
register's `observable` cell, and the S2 check refuses a cell that does not start with one of the closed words
or `none`.
