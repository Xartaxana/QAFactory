# Repairing the factory's own state — by code, never by hand

The doctor is where a person comes with a story that will not move. When what stops it is
the factory's own bookkeeping — a stage shown `running` with no open dispatch, a projection
that lags its journal — the person must not be told to "fix pipeline.json", and the doctor
does not edit it either. There is exactly one repair the doctor may run, because it is
deterministic code that ships with the factory, idempotent, and journalled:

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/controller.py" \
  --task-root qa-factory/artifacts/<TICKET> --operation recover
```

Run it for a story when step 4 shows a stage `running` or `halted` and the person says no
session is working on that story right now (a live orchestrator owns its own state — ask
once; this is a decision, not a fact). It rebuilds the projections from the journal and
records a `state_repair` event for a state its own receipts contradict. It never invents a
stage result, never accepts a dispatch, never touches an artifact a role wrote.

Report what it printed, verbatim and short:

- `reprojected_stages` / `journalled_repairs` non-empty → one line per stage
  (`S3: running → done, repaired by recover`), `owner: factory`, nothing wanted from the
  person; the story's next action is the `next_action` it printed.
- both empty → the state was consistent; say so, and do not run it again.
- an error → `unknown / owner: factory`, the error line, and the recommendation to report
  it. Do not read the controller's code, do not retry with variations, do not edit state.

When `recover` leaves a dispatch open and the person says nobody is working on it, their
word is the repair — and a guard that no longer parses this host is checked below.

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/controller.py" \
  --task-root qa-factory/artifacts/<TICKET> --operation release \
  --dispatch <id from next_action> --words-file <file>
```

Only on their word, never on elapsed time. `<file>` holds their words exactly as they said them
(written with the host's file tool to `qa-factory/artifacts/<TICKET>/state/words/<name>.txt`): a command line
cuts a multi-line text at the first line break. The artifacts the
role wrote stay, the stage is startable, and the printed `next_action` (`relaunch` carries
the ready dispatch request) is the story's next step. A guard refusal that repeats on a
different call ("event could not be parsed", "content could not be checked") is the guard's
own defect: the second one already recorded the finding — report it `owner: factory` with the
host version and stop; nothing is wanted from the person.

## Does the pre-tool guard still parse this host's events?

Part of step 1b, not a repair. The allow/deny pair proves the guard FIRES; it does not prove
the guard still reads the event shapes this host sends. When it stops, `PT-unparsed-event` /
`PT-patch-unchecked` refuse fail-closed and the second in a row sends the person here — so
the doctor checks it rather than asking them to describe it.

`host_probe.py --check` reports it as `guard_parse`, over the receipts the telemetry wrapper
already writes for every guard call of this session. Two ordinary events must have been
handled cleanly: a shell call (the ALLOW echo of step 1b is one) and a file write. If
`families.write` is still `unverified`, make one: `Write` a single throwaway line to
`qa-factory/state/doctor-guard-probe-<session>.txt`, then run `--check` again. Never feed a
synthetic event to the guard instead — that certifies nothing about this host.

- `verified` → one word in the READINESS block, nothing more.
- `unverified` → `owner: factory`, its `reason` verbatim; missing evidence, not a broken guard.
- `guard_defect` → the guard refused real calls it could not parse. Print its `reason` and the
  `host_version` when the receipts carry one, `owner: factory`, and stop: nothing here is the
  person's to repair, no plugin file is to be edited, and this never becomes the next action
  (verdict row 5a). The finding is already in `qa-factory/factory-backlog.md`.

Anything `recover` does not repair is outside the doctor: an audit finding, a broken
artifact, a failed capability are named with their owner, as always.
