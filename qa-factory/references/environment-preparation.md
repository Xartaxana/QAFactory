# Environment preparation

Environment preparation is runtime-first. Inspect the actual serving revision, provenance,
source mounts, startup command, dependency/runtime/base-image/build-argument/platform facts,
and selected-revision topology before choosing an action. The selected project adapter owns
provider-specific discovery and commands. The factory supplies no universal Docker, proxy,
network, cloud, mobile, or CLI repair.
Observed and target runtime records require a nonempty source revision, observation time, and
evidence references (a verified-absent observed runtime has no revision; see `create` below).
A mutation also requires an authorization reference bound to the exact
environment and target revision. Baseline capture is optional evidence work and never grants
mutation authority.

Call `plan_environment(request)` with `observed_runtime`, `target_runtime`, an adapter topology
verdict, and adapter `actions`. It returns `verify` when the approved revision is already
proven to serve, `reload` when compatible mounted source is consumed, `apply` when build facts
are compatible, and `rebuild` only when build compatibility facts changed. Unknown facts or
incompatible topology block mutation. Baseline absence never selects rollback: preparation
does not contain an automatic rollback action.
The returned SHA-256 fingerprints cover the complete observed and target runtime objects, so
callers can pin planning evidence rather than retaining only a compatibility boolean.

`create` is the fifth action and exists for an explicitly authorized NEW environment (FB-23).
The adapter reports `observed_runtime` with `state: absent` (exactly that word), the request's
`environment_id`, `absence_verified: true`, `resources: []`, an observation time and nonempty
evidence references; anything less is refused, and a runtime that exists but is unknown still
fails the identity rule ("source_revision is required"). The target still needs complete
identity and compatibility facts, and an incompatible topology blocks before `create`. The
authorization must also carry `create: true`, bound to the environment and the target revision;
without it, or without `actions.create`, the plan is `blocked` (no other action is borrowed),
and `create: true` changes nothing for an environment that exists. The factory does not assert
absence at the moment of creation: the adapter's create command rechecks it, and the
environment claim keeps a second key out. All locks and the five readiness probes apply.

Call `execute_environment(request, job_directory)` once with a stable `idempotency_key`.
Commands are argv arrays and run directly with `shell=False`. Each
step records command identity, PID and process-birth identity, exit code, elapsed time, and
separate complete stdout/stderr log paths. A failed action stops the sequence, so formatting,
tailing, a later command, or a green base-health probe cannot hide it.
Action deadlines are optional because a long build may be healthy while quiet; a declared
deadline is enforced. `stall_after_seconds` emits an advisory state transition without
canceling or retrying the action. Probe deadlines remain mandatory.

Adapters must declare one bounded probe for each layer: `process`, `base_health`,
`dependency_path`, `authentication`, and `provenance`. Every probe declares expected exit
codes and its own timeout; the batch has an overall timeout. Authentication semantics such as
an expected unauthenticated 401 belong in the adapter command and expected result. Probes use
application routes/assets and verify source or build provenance; test modules are not health
routes. The provenance probe's `expected_source_revision` must equal the target runtime's
exact source revision or preparation blocks before mutation. Its stdout must be one JSON
runtime-provenance receipt accepted as `matched` by `validate_runtime_provenance`, with exact
environment and revision binding. Exit zero alone cannot establish readiness.

Jobs move through `prepared`, `running`, `stalled`, `failed`, `ready`, and `blocked`.
`stalled` is a one-transition advisory based on absence of output; it does not retry, cancel,
or transfer ownership. After coordinator loss call `EnvironmentJobs.observe(key)`. It returns
`observe` for the same live PID and process birth, reuses a terminal record, and blocks an
unknown outcome. Never create another key to bypass that result. Raw logs remain filesystem
evidence and should not be copied into model context; callers may produce separately redacted
excerpts.
Claims are locked by environment identity as well as idempotency key. A second key cannot
launch while a prepared, live, stalled, or outcome-unknown job owns that environment.
The job retains both coordinator and current-child PID birth identities, so recovery does not
misclassify the interval between commands. A timed-out mutation remains blocked with
`uncertain_process: true`; it continues to own the environment.

Controller and handoff integrations use `read_environment_job(directory, key)` for the full
record or `environment_job_status(directory, key)` for a read-only projection. The projection
contains status, phase, action, active/settled flags, live process-identity evidence, current
step, last step, and update time. Reading status never launches, retries, or mutates a job.
The CLI exposes the same surfaces as `plan --request REQUEST.json`, `start --request
REQUEST.json --jobs DIRECTORY`, and `status --jobs DIRECTORY --key IDEMPOTENCY_KEY`. Resolve
an uncertain stopped job with one bounded read-only adapter probe using `reconcile --jobs
DIRECTORY --key IDEMPOTENCY_KEY --probe PROBE.json`. Its JSON stdout must report
`outcome_known: true`, `operation_running: false`, and the exact environment ID. The receipt
and logs are retained, and reconciliation settles the prior job as failed; it never infers
readiness or relaunches the mutation. Pass credentials through the probe environment or the
adapter's secret provider, never inline in argv.

## Minimal request

```json
{
  "idempotency_key": "TP3-1:S5:qa:newsha",
  "environment_id": "qa",
  "authorization": {"ref": "gate-a/42", "environment_id": "qa", "target_source_revision": "newsha"},
  "observed_runtime": {
    "source_revision": "oldsha", "observed_at": "2026-09-19T10:00:00Z",
    "evidence_refs": ["evidence/runtime-before.json"], "provenance_verified": true,
    "compatibility": {"dependencies": "lock-a", "runtime": "py312", "base_image": "base@sha256:x",
      "build_args": "args-a", "platform": "linux/amd64", "source_mounts": ["src:/app/src"],
      "startup_command": ["serve"]}
  },
  "target_runtime": {
    "source_revision": "newsha", "observed_at": "2026-09-19T10:00:01Z",
    "evidence_refs": ["work/source-inventory.json"], "provenance_verified": false,
    "compatibility": {"dependencies": "lock-a", "runtime": "py312", "base_image": "base@sha256:x",
      "build_args": "args-a", "platform": "linux/amd64", "source_mounts": ["src:/app/src"],
      "startup_command": ["serve"]}
  },
  "topology": {"status": "compatible", "evidence_refs": ["evidence/topology.json"]},
  "actions": {
    "verify": [],
    "reload": [{"name": "reload", "argv": ["adapter", "reload"], "stall_after_seconds": 300}],
    "apply": [{"name": "apply", "argv": ["adapter", "apply"]}],
    "rebuild": [{"name": "rebuild", "argv": ["adapter", "build"], "stall_after_seconds": 300}]
  },
  "probes": [
    {"name": "process", "layer": "process", "argv": ["adapter", "probe", "process"], "timeout_seconds": 5},
    {"name": "health", "layer": "base_health", "argv": ["adapter", "probe", "health"], "timeout_seconds": 5},
    {"name": "proxy", "layer": "dependency_path", "argv": ["adapter", "probe", "proxy"], "timeout_seconds": 8},
    {"name": "auth", "layer": "authentication", "argv": ["adapter", "probe", "auth"], "timeout_seconds": 8},
    {"name": "revision", "layer": "provenance", "argv": ["adapter", "probe", "provenance", "newsha"],
      "timeout_seconds": 8, "environment_id": "qa", "expected_source_revision": "newsha"}
  ],
  "probe_batch_timeout_seconds": 30
}
```
