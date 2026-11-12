# Step 6 — offer to archive what has stood still

Read by qa-doctor at step 6. The report (step 5) is already printed: this is a decision the person makes, never a condition for receiving a diagnosis.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/archive_task.py" --candidates --days 14
```

No output — say nothing and this step disappears. Otherwise the script has already split the
candidates, and the two classes are two different conversations.

**Clean candidates** (`clean — every stage done, both gates answered`) go into one message,
as a list with their ages, ending:

> Which of these should I archive? Names, `all`, or `none`. Archiving hides a story from the
> board and from this report; the folder and every artifact stay where they are.

**Candidates with open items** get **one message each**: the decision is per story. Name the
ticket, print its open items verbatim, and offer exactly three answers:

> `TP1-13958` has stood still for 21 days and still carries: <the items>.
> — **archive it, those questions are no longer relevant** (I close them with that as their
>   recorded reason) · **let us settle it** (I name what to do) · **leave it active**.

Then, per story the human named:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/archive_task.py" --task <TICKET> --words-file <file>
python "${CLAUDE_PLUGIN_ROOT}/scripts/archive_task.py" --task <TICKET> --force --words-file <file>
```

`<file>` holds their words exactly as they said them, written with the host's file tool to
`qa-factory/artifacts/<TICKET>/state/words/<name>.txt` (name it `archive-<YYYYMMDD-HHMMSS>.txt`:
never overwritten, never deleted; a command line cuts a multi-line text at the first line break).

The first form is for a clean story: it **exits 4 and writes nothing** if the story turns out
to carry an open item — the guard against archiving on a misread answer. The second is used
only after a person said the questions no longer matter, and the note is their sentence, not a
summary of it. `--undo` reverses either. Ask in plain text: this plugin ships four manifests
and the same skill runs where no question widget exists.

If a story you just archived was the source of step 5's next action, recompute the verdict
and print the new one-line action.

