"""Provider-neutral model resolution and bounded retry/checkpoint decisions."""
DEFAULT_LIMITS = {"discovery_batches_per_repo": 12, "discovery_batches_per_stage": 24,
                  "discovery_active_seconds": 900, "discovery_output_tokens": 12000,
                  "automator_active_seconds": 1200, "critic_active_seconds": 600,
                  "automator_requests": 39, "critic_requests": 15,
                  "runner_active_seconds": 1200, "runner_requests": 40,
                  # The retro writes prose over a table `retro_numbers.py` already computed,
                  # so it is the one discovery-shaped role with a blocking ceiling. Without
                  # one a pilot's retro agent walked the journals itself, passed 114k tokens
                  # and was stopped by hand; one story ate a weekly limit.
                  "retro_active_seconds": 420, "retro_requests": 14,
                  "retro_output_tokens": 8000,
                  "repair_cycles": 2, "design_repair_cycles": 2}

# What one window and one stage cost in orchestrator turns when this story has no measured
# history yet. `window_budget.py` prefers the stages this story actually paid for and falls
# back here. 120 is the outer bound a window should not pass (146 turns in one window
# measured 22.6M tokens against 9.7M for the same work in three); 35 is a healthy stage.
DEFAULT_WINDOW_TURNS = 120
DEFAULT_STAGE_TURNS = 35


def orchestrator_rollover_due(window_counters, context_percent=None):
    """Window policy is separate from role/story budgets and never blocks active work."""
    from session_handoff import rollover_status
    return rollover_status(window_counters, context_percent)


def resolve_model(role, parent, project, task, supported):
    """Inheritance is explicit in receipts; no named model defaults in role files."""
    desired = dict(parent)
    for source in (project.get("roles", {}).get(role, {}), task.get("roles", {}).get(role, {})):
        for key in ("model", "effort"):
            if source.get(key) not in (None, "inherit"):
                desired[key] = source[key]
    model, effort = desired.get("model"), desired.get("effort")
    if model not in supported or effort not in supported[model]:
        raise ValueError("unsupported model/effort; configure an explicit supported override")
    return dict(desired, role=role)


def retry_decision(error_code, retries_used, remaining_budget, retry_after=None):
    if error_code in {"ExceededBudget", "insufficient_quota", "BUDGET_EXHAUSTED"}:
        return {"action": "block", "reason": "INFRA/BUDGET_EXHAUSTED", "retry": False}
    if error_code not in {"503", "service_unavailable", "rate_limit_exceeded"}:
        return {"action": "diagnose", "retry": False}
    if retries_used >= 2 or remaining_budget <= 0:
        return {"action": "checkpoint", "reason": "retry_budget_exhausted", "retry": False}
    delay = retry_after if retry_after is not None else (5, 15)[retries_used]
    if delay > 15:
        return {"action": "checkpoint", "reason": "provider_wait", "retry": False}
    return {"action": "resume_remaining", "retry": True, "delay_seconds": max(0, delay)}


def checkpoint_due(role, counters, limits=None):
    policy = dict(DEFAULT_LIMITS, **(limits or {}))
    prefix = ("automator" if role == "qa-automator" else "critic" if role == "qa-code-critic"
              else "runner" if role == "qa-runner"
              else "retro" if role == "qa-retro-analyst" else "discovery")
    reasons = []
    for metric in ("active_seconds", "requests", "output_tokens"):
        cap = policy.get(prefix + "_" + metric)
        actual = counters.get(metric)
        if cap is not None and actual is not None and actual >= cap:
            reasons.append(metric)
    return {"checkpoint": bool(reasons), "blocking": bool(reasons) and prefix != "discovery", "warning": bool(reasons), "reasons": reasons,
            "telemetry_unknown": [key for key in ("active_seconds", "requests", "output_tokens")
                                  if counters.get(key) is None]}


def cumulative_budget(role, previous, current, limits=None):
    """Merge one dispatch's measured deltas into durable cumulative counters.

    Missing telemetry remains unknown instead of becoming a free zero. Callers persist the
    returned counters and pass them to every later dispatch for the same bounded scope.
    """
    metrics = ("active_seconds", "requests", "output_tokens", "repair_cycles", "batches_per_repo", "batches_per_stage")
    previous, current = previous or {}, current or {}
    counters = {}
    unknown = []
    for metric in metrics:
        before, delta = previous.get(metric), current.get(metric)
        if before is None or delta is None:
            counters[metric] = None
            unknown.append(metric)
            continue
        if not isinstance(before, (int, float)) or not isinstance(delta, (int, float)):
            raise ValueError(f"{metric} counters must be numeric or unknown")
        if before < 0 or delta < 0:
            raise ValueError(f"{metric} counters cannot decrease")
        counters[metric] = before + delta
    due = checkpoint_due(role, counters, limits)
    policy = dict(DEFAULT_LIMITS, **(limits or {}))
    repair_cap = policy.get("design_repair_cycles" if "case" in role else "repair_cycles")
    if repair_cap is not None and counters["repair_cycles"] is not None \
            and counters["repair_cycles"] >= repair_cap:
        due["checkpoint"] = True
        due["blocking"] = True
        due["reasons"] = [*due["reasons"], "repair_cycles"]
    due["counters"] = counters
    due["telemetry_unknown"] = sorted(set(due["telemetry_unknown"] + unknown))
    return due


def warning_milestones(counters, limits=None, emitted=None):
    """Return new soft discovery milestones; continuation inherits emitted markers."""
    policy = dict(DEFAULT_LIMITS, **(limits or {}))
    emitted = set(emitted or [])
    new = []
    for metric, key in (("output_tokens", "discovery_output_tokens"),
                        ("active_seconds", "discovery_active_seconds"),
                        ("batches_per_repo", "discovery_batches_per_repo"),
                        ("batches_per_stage", "discovery_batches_per_stage")):
        value, step = counters.get(metric), policy.get(key)
        if not isinstance(value, (int, float)) or not isinstance(step, (int, float)) or step <= 0:
            continue
        for multiple in range(1, int(value // step) + 1):
            marker = f"{metric}:{multiple * step:g}"
            if marker not in emitted:
                new.append(marker)
    return {"warning": bool(new), "new_markers": new,
            "emitted": sorted(emitted | set(new)), "blocking": False}
