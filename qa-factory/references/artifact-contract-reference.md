# Reference snapshot contract (S-c: "it must work as before")

A side of the story may carry a `reference`: a stand where the OLD version runs. The S1 reference window walks it (a `survey` walk on that
stand) and writes `work/reference-snapshot.yaml` through `reference_snapshot.py put`. Code writes the file; a role only reads it.

```yaml
reference_env: <stand name>
walked_at: <UTC time>
items:
  - id: <plain id: letters, digits, . _ ->   # the walk's item; a Then cites it as `reference:<id>`
    area: <where in the product>
    user_path: <what a user does>
    observed: <what the old version showed>
    evidence: [<capture path>]               # captures of THIS walk on THIS stand, kept as paths
    old_test: <file>:<line>                  # optional; an old autotest that checks the same
    locators_portable: yes | no | unknown    # may the old locator be reused on the new side
gaps: [<one line each>]                      # what could not be seen; `items: []` needs one
```

- **Evidence.** `put` takes `items[].evidence` as `{path, quote}`: the quote is words of the capture, found in it by code
  (`walk_session.capture_cited`, with the newest S1 dispatch whose purpose is `reference_walk` and the reference stand). A capture of a
  first-look walk, another walk, another item or another stand is refused. An item with no capture and no `old_test` is no observation.
  Code checks the words are there, never that they show what `observed` says.
- **Parity.** The requirements tester marks a requirement that says "as before" with `parity: yes` in its register row (the `parity`
  column; absent or any other word means no). A `precedent` Then cites `reference:<id>` only under a case `basis` of `requirement:R-n`
  with that row, and only for an item of the snapshot (C7).
- **Absent.** A story with no reference has no snapshot and never sees `reference:`; a refused `reference:` ref names this door.
- **Ways out.** `put --replace` after a new walk, or `rework S1`.
