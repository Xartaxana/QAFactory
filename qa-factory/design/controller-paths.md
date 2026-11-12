# Controller path inputs and recovery

Before initialization, run `controller.py --task-root TASK_ROOT --operation prepare`.
Copy its `resolved_paths` object into `known_paths` for initialization and dispatch.
It contains named `plugin_root`, `project_root`, `task_root`, and `repository_roots`.
Invalid path shapes are rejected before journaling.

Older initialization could commit an unnamed path list and then fail while projecting
the dashboard. Run `controller.py --task-root TASK_ROOT --operation recover` to rebuild
projections. Recovery preserves the list as `legacy_known_paths`, leaves those paths
unclassified, and retains the original event bytes. Run `prepare` afterwards to resolve
current named paths from the task's project config and active installation.

Do not edit the event log, repeat initialization, or infer names from list order.
Recovery does not complete stages, approve gates, select an environment, or launch workers.
