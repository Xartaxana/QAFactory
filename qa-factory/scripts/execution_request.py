"""Typed, scoped execution requests and durable idempotency records."""
from __future__ import annotations

import configparser
import hashlib
import json
import math
import os
import posixpath
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import node_ids as _node_ids  # bound at import: the one predicate, the bounded launcher
from hooklib import read_json as _read_json  # the package's one JSON reader: a file that cannot be read is None here
from profile_contract import (ACCEPTS, acceptable_provenance, command_env, no_changed_file, one_test_argv, probe_failed_text,
                              probe_not_json_text, profile_command, refusal_text, rehearsal_view, say_refusal,
                              selected_profiles, stand_runs_other_build, validate_runtime_provenance)
from record_schema import validate_record
from execution_fingerprint import verify_files
from hooklib import sorted_paths, story_closure

PURPOSES = {"initial", "repair_verify", "red_probe", "diagnostic", "flaky_diagnostic",
            "build", "collect", "manual", "quality"}
BEHAVIORAL = PURPOSES - {"build", "collect", "manual", "quality"}
REPORTERS = {"pytest", "junit-xml", "trx", "none"}


class RequestError(ValueError):
    pass


# --- how many selected instances become ONE selection ------------------------------------------
#
# A runner whose selection is a single option (`dotnet test --filter <expression>`) takes ONE
# expression: repeating the option for every selected instance made it print its usage text and
# run nothing (legacy run TP2-2406, ten xUnit instances). How a runner combines its
# selectors is a fact about that runner, so it is DATA of its profile (FR-13):
# `profiles[].selectors.join`, copied into the request as `command.selector_join`. No runner is
# named here; an absent rule is today's behaviour, the option repeated per instance.

SELECTOR_JOIN_SHAPE = '{"option": "<flag>", "separator": "<text>", "group": ["<open>", "<close>"]}'


SELECTOR_JOIN_KEYS = ("option", "separator", "group")


def selector_join_problem(join) -> str:
    """Why `join` is not a usable rule ("" when it is): the same check for a profile and a request.

    A key the rule does not have is refused, with the keys it has: `groups` for `group` used to
    be ignored, and the launch went out with the values unwrapped and no word (FR-4)."""
    if not isinstance(join, dict):
        return "is not an object"
    unknown = [str(key) for key in join if key not in SELECTOR_JOIN_KEYS]
    if unknown:
        return (f"has the unknown key {', '.join(repr(key) for key in unknown)} (the allowed keys are "
                f"{', '.join(SELECTOR_JOIN_KEYS)})")
    for key in ("option", "separator"):
        if not isinstance(join.get(key), str) or not join[key]:
            return f"has no {key} (a non-empty string)"
    if "group" in join:
        group = join["group"]
        if not isinstance(group, list) or len(group) != 2 or any(not isinstance(x, str) for x in group):
            return "has a group that is not a list of two strings"
    return ""


def selection_argv(selected: list, selector_args: dict, join=None) -> list:
    """What the selection appends to the command's own argv.

    No rule, or exactly one selected instance: each instance's `selector_args` in order,
    unchanged (a lone instance is never wrapped). Two or more with a rule: ONE `[option, value]`
    where the value joins every distinct instance value in order of first appearance. The
    validator has already refused any instance whose `selector_args` is not `[option, <value>]`."""
    if not join or len(selected) < 2:
        return [token for key in selected for token in selector_args[key]]
    values: list = []
    for key in selected:
        value = selector_args[key][1]
        if value not in values:
            values.append(value)
    group = join.get("group")
    if group:
        values = [group[0] + value + group[1] for value in values]
    return [join["option"], join["separator"].join(values)]


class ProvenanceRefused(RequestError):
    """A probe answer a reader refused (t-300 N2): a `RequestError`, so every `except RequestError` that exists still
    holds, and it carries the record (`.record`) so the caller that must decide what to do - a capture (EnvBlocked), a
    `--mine` (the stand's refusal, not the call's) - reads FIELDS of it, never the sentence (FR-12). The message is
    `profile_contract.refusal_text`: what the probe said, what was expected, the door (FR-1)."""

    def __init__(self, record, *, task=None):
        super().__init__(refusal_text(record, task=task))
        self.record = record


def probe_record(result) -> dict:
    """The provenance record a finished probe process printed (`subprocess.CompletedProcess`), or a `RequestError`
    that says why there is none WITH THE PROBE'S OWN REASON: a non-zero exit quotes the first line of its stderr (the
    real probe's exit 2 says "no story is running ... Pass --task"), output that is not JSON says what it printed
    (t-300 N2 F4, FR-1). One reader for the strict probe (`run_suite.probe_runtime`) and the rehearsal one
    (`rehearsal_probe`): a probe that fails is said the same way at both (FR-17)."""
    if result.returncode != 0:
        raise RequestError(probe_failed_text(result.returncode, result.stderr))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RequestError(probe_not_json_text(result.stdout)) from exc


def validate_request(data: dict, project_root: Path, allow_exhausted_reuse: bool = False) -> dict:
    required_strings = ("task", "revision", "dispatch_id", "profile_id", "purpose",
                        "input_fingerprint", "reason", "idempotency_key")
    errors = [f"{key} is required" for key in required_strings
              if not isinstance(data.get(key), str) or not data[key].strip()]
    from baseline_contract import validate_baseline_request
    errors.extend(validate_baseline_request(data))
    from baseline_contract import validate_managed_gate
    errors.extend(validate_managed_gate(data, project_root))
    purpose = data.get("purpose")
    if purpose == "impact_regression":
        errors.append("impact_regression is recommendation-only and cannot be executed")
    elif purpose not in PURPOSES:
        errors.append(f"purpose must be one of {sorted(PURPOSES)}")
    selected = data.get("selected_instance_ids")
    scope = data.get("current_scope_instance_ids")
    if not isinstance(selected, list) or any(not isinstance(x, str) or not x for x in selected):
        errors.append("selected_instance_ids must be a string array")
        selected = []
    if not isinstance(scope, list) or any(not isinstance(x, str) or not x for x in scope):
        errors.append("current_scope_instance_ids must be a string array")
        scope = []
    outside = sorted(set(selected) - set(scope))
    if outside:
        errors.append("selected instances outside approved current scope: " + ", ".join(outside))
    if not isinstance(data.get("remaining_budget"), (int, float)) or data.get("remaining_budget", -1) < 0:
        errors.append("remaining_budget must be a non-negative number")
    elif purpose in BEHAVIORAL and data["remaining_budget"] == 0 and not allow_exhausted_reuse:
        errors.append("new behavioral execution requires remaining_budget greater than zero")
    if data.get("freshness") != "fresh":
        errors.append("freshness must be explicitly fresh; unknown/stale evidence cannot match")
    provenance = data.get("runtime_provenance")
    runtime_required = data.get("runtime_required", True)
    if not isinstance(provenance, dict):
        errors.append("runtime_provenance is required")
    else:
        checked = validate_runtime_provenance(provenance)
        if provenance.get("profile_id") != data.get("profile_id"):
            errors.append("runtime provenance profile_id must match the selected profile")
        # A probe that compared nothing because the story changes no file of this profile's checkout
        # (`reason_code: no_changed_file`, a FIELD - FR-12) is enough on ANY stand kind: the story's code
        # does not run through this checkout, so there is no runtime identity to verify (t-279 K-NA).
        # Every other `not_applicable` - including one with no reason_code, as an older probe wrote it - keeps
        # the rule below: it must come from a verified local_source profile. Invariant of the order: this
        # exemption is read from `provenance`, never from the request's own `target_kind`.
        local_source = data.get("runtime_required") is False and data.get("target_kind") == "local_source"
        said_local = False
        if checked["result"] == "not_applicable" and not no_changed_file(provenance) and not local_source:
            errors.append(say_refusal("not_applicable"))
            said_local = True
        if provenance.get("result") == "person_confirmed" and data.get("runtime_required") is False:
            # t-300 N2 X7: a person's word stands only where the probe re-reads the stand at launch (the pre-run and
            # post-run compare) - a request that skips the probe would run on a word nothing ever checks again
            errors.append(say_refusal("person_runtime_off"))
        # ONE predicate (t-300 N2, FR-17): `matched`, a person's word bound to THIS story (X5), and the probe that
        # compared nothing (`no_changed_file`). The local_source `not_applicable` stays the one literal beside it (X3).
        taken = acceptable_provenance(provenance, ACCEPTS, task=data.get("task"))
        if not (taken or said_local or (checked["valid"] and checked["result"] == "not_applicable" and local_source)):
            errors.append("runtime provenance must be valid matched, person_confirmed (the person's word, bound to "
                          "this story) or not_applicable: " + refusal_text(provenance, task=data.get("task")))
    if isinstance(provenance, dict):
        # C8 (PC-9b, t-2277 W1): only the record's own contradiction (the story's stand named as its reference too) is refused here; a run on a
        # reference stand is a sample and goes (its block carries the mark). Read from the probe's own record (`environment_id`).
        reference = reference_target_problem(project_root, data.get("task"), provenance.get("environment_id"))
        if reference:
            errors.append(reference)
    runtime_probe = data.get("runtime_probe")
    if runtime_required:
        if not isinstance(runtime_probe, dict):
            errors.append("runtime-required request needs a read-only runtime_probe")
        else:
            probe_argv = runtime_probe.get("argv")
            if (not isinstance(probe_argv, list) or not probe_argv or
                    any(not isinstance(x, str) or not x for x in probe_argv)):
                errors.append("runtime_probe.argv must be a non-empty string array")
            probe_cwd = Path(str(runtime_probe.get("cwd") or ""))
            probe_cwd = probe_cwd if probe_cwd.is_absolute() else project_root / probe_cwd
            if not probe_cwd.is_dir():
                errors.append("runtime_probe.cwd must be an existing directory")
            if not isinstance(runtime_probe.get("timeout_s"), (int, float)) or runtime_probe.get("timeout_s", 0) <= 0:
                errors.append("runtime_probe.timeout_s must be positive")
    components = data.get("fingerprint_components")
    if not isinstance(components, dict) or any(not isinstance(components.get(k), str) or not components[k]
                                               for k in ("source_sha", "test_content_sha", "config_sha")):
        errors.append("fingerprint_components requires immutable source_sha, test_content_sha, and config_sha")
    try:
        verify_files(data.get("fingerprint_files"))
    except ValueError as exc:
        errors.append(str(exc))

    command = data.get("command")
    if not isinstance(command, dict):
        errors.append("command must be an object")
        command = {}
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        errors.append("command.argv must be a non-empty string array")
    cwd_raw = command.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw:
        errors.append("command.cwd is required")
        cwd = project_root
    else:
        cwd = Path(cwd_raw)
        cwd = cwd if cwd.is_absolute() else project_root / cwd
        if not cwd.is_dir():
            errors.append(f"command.cwd does not exist: {cwd}")
    reporter = command.get("reporter")
    if reporter not in REPORTERS:
        errors.append(f"command.reporter must be one of {sorted(REPORTERS)}")
    if purpose in BEHAVIORAL and command.get("scope") == "full_suite":
        errors.append("behavioral RunRequest cannot execute a full_suite command")
    if purpose in {"build", "collect", "quality"}:
        if not isinstance(command.get("runs_tests"), bool):
            errors.append(f"{purpose} command must declare runs_tests boolean")
        elif command["runs_tests"]:
            errors.append(f"{purpose} command that runs tests is a hidden behavioral wrapper; split it into typed scoped requests")
    report_template = command.get("report_path", "")
    if reporter in {"junit-xml", "trx"} and report_template != "{report_path}":
        errors.append("external reporter command.report_path must be {report_path} for run-unique evidence")
    if reporter in {"junit-xml", "trx"}:
        # EXACTLY ONE argv token carries the placeholder, whole (`{report_path}`) or embedded (`trx;LogFileName=
        # {report_path}`): the runner substitutes inside the token (run_suite.main), as the gate's reporter probe does
        # (gate_preflight, FR-17: S5 and the probe agree on what a proven command is). Two tokens would write two
        # reports under one name; none would leave the run with no report of its own.
        # EP1-22: a runner that names its report by a variable (Playwright) holds the placeholder in a value of `command.env`
        # instead; holders are counted over the argv tokens and the env values TOGETHER, still exactly one.
        holders = [x for x in argv if isinstance(x, str) and "{report_path}" in x] if isinstance(argv, list) else []
        env_values = [v for v in command["env"].values()] if isinstance(command.get("env"), dict) else []
        holders += [v for v in env_values if isinstance(v, str) and "{report_path}" in v]
        if not holders:
            errors.append("external reporter command.argv must contain an explicit {report_path} token, or one value of "
                          "command.env must be {report_path}")
        elif len(holders) > 1:
            errors.append("external reporter command.argv must carry {report_path} in exactly one token, and "
                          f"{len(holders)} do: " + ", ".join(repr(x) for x in holders)
                          + " (the values of command.env count too)")
    if command.get("env") is not None:
        # a value of `env` is exactly `{report_path}` (a secret or a path of this machine is never written into a request
        # that is shared), and only an external reporter reads the file it names (a field nothing reads is a defect)
        _env, env_problem = command_env(command)
        if env_problem:
            errors.append(f"command.{env_problem}")
        elif _env and reporter not in {"junit-xml", "trx"}:
            errors.append("command.env sets the report file, but nothing reads this report: the reporter is "
                          f"{reporter!r}, and only junit-xml or trx is read from a file")
    join = None
    if "selector_join" in command:
        problem = selector_join_problem(command["selector_join"])
        if problem:
            errors.append(f"command.selector_join {problem}; expected {SELECTOR_JOIN_SHAPE} (`group` is "
                          "optional). A `--mine` request takes it from `profiles[].selectors.join` in "
                          "qa-factory/config.json; a hand-written one is corrected in the request "
                          "(`run_suite.py --template request` shows one)")
        else:
            join = command["selector_join"]
    execution = data.get("execution")
    if execution is not None:
        if not isinstance(execution, dict) or execution.get("schema_version") != 1:
            errors.append("execution.schema_version must equal integer 1")
        else:
            report = execution.get("reporter") or {}
            isolated = (reporter == "none" or
                        isinstance(report.get("path_template"), str) and
                        "{report_path}" in report.get("path_template", ""))
            if report.get("format") != reporter or not isolated:
                errors.append("execution.reporter must match command reporter and use a job-isolated {report_path}")
            seed = execution.get("data_seed_contract")
            if seed is not None and (not isinstance(seed, dict) or
                    seed.get("result") not in {"matched", "mismatched", "unknown"} or
                    not isinstance(seed.get("evidence_refs"), list)):
                errors.append("execution.data_seed_contract requires result and evidence_refs array")
            selection = execution.get("selection")
            if selection is not None and (not isinstance(selection, dict) or
                    selection.get("reason") not in {"missing_fresh_evidence", "failed_or_invalidated",
                                                    "diagnostic", "collection_only"} or
                    not isinstance(selection.get("evidence_refs"), list) or
                    not selection.get("evidence_refs")):
                errors.append("execution.selection requires a typed reason and non-empty evidence_refs")
    selector_args = command.get("selector_args")
    if purpose in BEHAVIORAL:
        if command.get("selector_contract_verified") is not True:
            errors.append("behavioral command requires a verified adapter selector contract")
        if not selected:
            errors.append("behavioral request must select at least one approved instance")
        if not isinstance(selector_args, dict):
            errors.append("behavioral command requires framework-specific selector_args mapping")
        else:
            unknown = [x for x in selected if x not in selector_args]
            if unknown:
                errors.append("unsupported selector for instances: " + ", ".join(unknown))
            for key in selected:
                value = selector_args.get(key)
                if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x for x in value):
                    errors.append(f"command.selector_args.{key} must be a non-empty string array")
                elif any("{report_path}" in x for x in value):
                    errors.append(f"command.selector_args.{key} contains the {{report_path}} placeholder; a "
                                  "selector is the identity of a test, not report plumbing - the "
                                  "placeholder belongs in command.argv")
                elif join and len(selected) >= 2 and not (len(value) == 2 and value[0] == join["option"]):
                    # The invariant: ONE valid selection that keeps every selected instance. A
                    # selector of another shape cannot be folded into the joined value, and leaving
                    # it out would launch a command that silently drops a test - so no word passes.
                    if is_pytest_command(argv):
                        # The fault is the profile's, not the manifest row's: a pytest selector is a
                        # node id the factory builds, and no manifest fragment can make it
                        # `[option, value]`. Naming `manifest_put.py` sent the role to a door that
                        # cannot open it (FR-2); the profile is the one place that can.
                        said = (f"command.selector_join is set on a pytest command, and its selectors are "
                                f"node ids, not [option, value]: remove selectors.join from "
                                f"profile {data.get('profile_id')}: pytest selectors are built by the factory "
                                "(`/qa-factory:qa-onboarding`, execution batch, corrects the profile). No "
                                "waiver passes this: launching it would drop a selected test without a word")
                        if said not in errors:  # one sentence, not one per selected instance
                            errors.append(said)
                    else:
                        errors.append(
                            f"command.selector_args.{key} is {value} but command.selector_join joins the "
                            f"instances through {join['option']}, so every selected instance needs exactly "
                            f"[{join['option']}, <value>]. Correct that instance's selector_args through "
                            "manifest_put.py. No waiver passes this: launching it would drop a selected test "
                            "without a word")
        contracts = data.get("instance_contracts")
        if not isinstance(contracts, dict):
            errors.append("behavioral request requires instance_contracts")
        else:
            report_ids = {}
            for key in selected:
                contract = contracts.get(key)
                if not isinstance(contract, dict) or not isinstance(contract.get("report_test_id"), str) or not contract["report_test_id"]:
                    errors.append(f"instance_contracts.{key}.report_test_id is required")
                    continue
                report_ids.setdefault(contract["report_test_id"], []).append(key)
                if not isinstance(contract.get("parameters", {}), dict):
                    errors.append(f"instance_contracts.{key}.parameters must be an object")
                if reporter == "trx" and contract.get("report_id_source") not in {
                        "collection", "catalog", "machine_report"}:
                    errors.append(f"instance_contracts.{key}.report_id_source must prove the exact TRX reporter ID")
            for report_id, instances in report_ids.items():
                if len(instances) > 1:
                    errors.append(f"report_test_id {report_id!r} maps ambiguously to instances: "
                                  + ", ".join(instances))
    if errors:
        raise RequestError("; ".join(errors))
    try:
        validate_record("RunRequest", data)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc
    resolved = dict(data)
    resolved["command"] = dict(command)
    resolved["command"]["cwd"] = str(cwd.resolve())
    resolved["resolved_argv"] = list(argv)
    if runtime_required:
        resolved["runtime_probe"] = {**runtime_probe, "cwd": str(probe_cwd.resolve())}
    if purpose in BEHAVIORAL:
        resolved["resolved_argv"].extend(selection_argv(selected, selector_args, join))
    return resolved


def request_digest(request: dict) -> str:
    material = {k: v for k, v in request.items()
                if k not in {"reason", "remaining_budget", "runtime_probe_before", "collect_memo"}}
    provenance = material.get("runtime_provenance")
    if isinstance(provenance, dict):
        material["runtime_provenance"] = {k: v for k, v in provenance.items()
                                          if k not in {"timestamp", "evidence_refs"}}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


class JobStore:
    def __init__(self, directory: Path):
        """A store NAMES a folder and creates nothing (CX1-18, I2): a lookup (`jobs`, `read`, `recover`, `last_run_of`)
        on a story that has no jobs yet used to bring `state/execution-jobs/` into being, and with it the story's whole
        folder when the key named none. The folder is made by the first WRITE (`begin`, `write`), under a root the
        caller has already shown to be a story (`hooklib.story_root`)."""
        self.directory = directory

    def _ensure(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = hashlib.sha256(key.encode()).hexdigest()
        return self.directory / f"{safe}.json"

    def read(self, key: str) -> dict | None:
        path = self._path(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            raise RequestError(f"corrupt persisted job for idempotency key: {exc}") from exc

    def write(self, job: dict) -> None:
        path = self._path(job["idempotency_key"])
        self._ensure()
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def begin(self, request: dict) -> tuple[str, dict]:
        existing = self.read(request["idempotency_key"])
        digest = request_digest(request)
        if existing:
            if existing.get("request_digest") != digest:
                raise RequestError("idempotency_key was already used for a different request")
            # `reused`: a green result stands. `already_run`: it finished any other way and is
            # recorded (a red is not "a run still in flight"). `duplicate`: not finished.
            action = ("duplicate" if existing.get("status") != "completed" else
                      "reused" if existing.get("execution_status") == "passed"
                      and existing.get("freshness") == "fresh" else "already_run")
            return action, existing
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job = {"job_id": digest[:20], "idempotency_key": request["idempotency_key"],
               "request_digest": digest, "status": "persisted", "created_at": now,
               "request": request}
        path = self._path(request["idempotency_key"])
        self._ensure()
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            # Another process won the claim between read and create. Re-evaluate its durable job.
            existing = self.read(request["idempotency_key"])
            if existing is None:
                raise RequestError("idempotency claim exists but cannot be read")
            if existing.get("request_digest") != digest:
                raise RequestError("idempotency_key was concurrently used for a different request")
            return "duplicate", existing
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(job, stream, indent=2)
            stream.write("\n")
        return "launch", job

    def update(self, job: dict, **changes: Any) -> dict:
        job = {**job, **changes, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.write(job)
        return job

    def recover(self, key: str, process_owned) -> dict:
        """Inspect a durable job once; never relaunch ambiguous or stopped work."""
        job = self.read(key)
        if not job:
            raise RequestError("unknown execution job")
        status = job.get("status")
        if status == "completed":
            return {"action": "reused" if job.get("execution_status") == "passed" else "complete",
                    "job": job}
        if status == "running" and process_owned(int(job.get("runner_pid") or 0),
                                                  str(job.get("runner_started_at") or "")):
            return {"action": "running", "job": job}
        reason = ("runner process stopped before a completion receipt" if status == "running"
                  else "launch ownership was not durably established")
        job = self.update(job, status="incomplete", execution_status="not_executed",
                          recovery_reason=reason)
        return {"action": "incomplete", "job": job}

    def jobs(self) -> list:
        """Every readable job of this story, oldest first. A corrupt file is skipped: this
        is a lookup for `--mine` and `--detail`, never the idempotency decision itself."""
        if not self.directory.is_dir():
            return []                  # no folder is no job; a lookup never makes the folder (I2)
        found = []
        for path in self.directory.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                written = path.stat().st_mtime_ns
            except (OSError, ValueError):
                continue
            if isinstance(job, dict) and isinstance(job.get("request"), dict):
                found.append((job, written))
        # Timestamps are whole seconds: two jobs of one second are told apart by when their
        # files were last written, so "the newest result" is never a coin toss.
        found.sort(key=lambda item: (str(item[0].get("updated_at") or item[0].get("created_at") or ""),
                                     item[1]))
        return [job for job, _written in found]

    def last_run_of(self, request: dict) -> dict | None:
        """The latest job of this request that left a summary on disk: the job under its own
        idempotency key first, else the newest one that ran any of the same instances.

        `--request FILE --detail TEST` asks "why did my test fail", and the role asking
        holds the request it ran — or the next one it has already written for the rerun. On
        TP1-15045 the automator's call answered with the whole duplicate job record and
        never reached the failure text; a fresh key would have launched the tests."""
        own = self.read(str(request.get("idempotency_key") or ""))
        if own and own.get("summary"):
            return own
        selected = set(request.get("selected_instance_ids") or [])
        reports = {str((c or {}).get("report_test_id") or "")
                   for c in (request.get("instance_contracts") or {}).values() if isinstance(c, dict)} - {""}
        for job in reversed(self.jobs()):
            old = job["request"]
            old_reports = {str((c or {}).get("report_test_id") or "")
                           for c in (old.get("instance_contracts") or {}).values() if isinstance(c, dict)}
            if job.get("summary") and (selected & set(old.get("selected_instance_ids") or [])
                                       or reports & old_reports):
                return job
        return None


# --- `run_suite.py --mine CASE[,CASE...]`: the request a role used to write by hand ---------
#
# Measured on TP1-15045 (session 57cf578c, 0.7.6): 106 request files under
# `work/requests/` for 16 S5 dispatches, every one typed by a role from the validator's error
# messages — dispatch id, revision, scope, fingerprints of a dozen files, a runtime probe and
# the reporter id of each instance. Thirteen of fifteen tests ended the story with no reporter
# row, because the hand-written `report_test_id` (`ui/workflows/test_x.py::test_fn`) was not
# what the junit report spells (`pkg.ui.workflows.test_x::test_fn`). Everything in such a
# request is already on disk: the controller knows the dispatch, the manifest knows the
# tests, the job store knows the command and the probe of the last run. The ordinary "run my
# test" is one flag; `--request` stays for everything that is not ordinary.

class MineRefusal(RequestError):
    """A plain sentence for the role: what is missing, whose gap it is, what to do next."""


class WindowFirst(MineRefusal):
    """Part of a window asked for while its neighbours in the same file have never run.

    Carries the payload the role reads (`status`, the neighbours, the one command that runs
    them all) so the runner prints it instead of a bare refusal sentence."""

    def __init__(self, message: str, payload: dict):
        super().__init__(message)
        self.payload = dict(payload)


MINE_PURPOSES = ("initial", "repair_verify", "red_probe")
SCOPE_BLOCK = "outside its scope"
WINDOW_BLOCK = "run the window first"

# The files whose bytes a run (the fingerprint) and a reporter proof (the D-0023 rehearsal key) depend on, B-407 B-deps.
# Closed variety lives in `references/dependency-files.json` (FR-13); these are only the FLOORS it falls back to, today's
# lists before the data existed, so an unreadable or malformed table never means FEWER watched files than there were.
DEPENDENCY_FILES_DATA = "dependency-files.json"
_DEPENDENCY_FLOOR = ("pyproject.toml", "poetry.lock", "requirements.txt", "setup.cfg",
                     "package.json", "package-lock.json")
_REPORT_CONFIG_FLOOR = ("pytest.ini", "tox.ini", "setup.cfg", "conftest.py")
_DEPENDENCY_KEYS = (("names", _DEPENDENCY_FLOOR), ("patterns", ()), ("report_config", _REPORT_CONFIG_FLOOR))


def dependency_table() -> dict:
    """`{"names", "patterns", "report_config", "problem"}`: the lists of `references/dependency-files.json`.

    A key that is absent, not a list of non-empty strings, or (for `names`, `report_config`) empty is replaced by its
    floor (`_DEPENDENCY_FLOOR`, `_REPORT_CONFIG_FLOOR`; `patterns` has none: no patterns) and named once in `problem`
    ('' when the table is whole). A pattern holding a path separator is malformed too: patterns read the top level of
    the cwd only (E-D-3). Never raises."""
    try:
        from hooklib import load_ref_json
        data = load_ref_json(DEPENDENCY_FILES_DATA)
    except Exception:
        data = {}
    data = data if isinstance(data, dict) else {}
    table, bad = {}, []
    for key, floor in _DEPENDENCY_KEYS:
        value = data.get(key)
        ok = (isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
              and (bool(value) or key == "patterns")
              and not (key == "patterns" and any("/" in v or "\\" in v for v in value)))
        table[key] = [v.strip() for v in value] if ok else list(floor)
        if not ok:
            bad.append(key)
    table["problem"] = (
        f"the factory's table of dependency files is unreadable or has no usable `{'`, `'.join(bad)}`, so the files "
        "it watched before that table existed are used in its place; a changed dependency file of another kind is "
        "not noticed until the table is repaired" if bad else "")
    return table


# The data's `names`: what the fingerprint and the key watch by name. Read once, at import (the floor on a bad table).
_DEPENDENCY_FILES = tuple(dependency_table()["names"])


def dependency_files(run_cwd, cfg) -> tuple:
    """`(paths, note)`: the dependency files that exist for a run in `run_cwd`, as `str(run_cwd / name)`, once each.

    The table's `names`, then its `patterns` (top level of `run_cwd` only: E-D-3), then `run.dependency_files` of the
    project's config (`cfg`; paths relative to `run_cwd`: the door for anything deeper, or any name the table lacks).
    `note` is '' or ONE sentence for the caller to say: the table could not be read (the floor was used), or the
    config's list is not a list of names (it is ignored). Both fail toward watching MORE, never fewer, files (E-D-4).

    A file that exists and is listed costs, at worst, one extra run or rehearsal (E-D-1, the allowed error); a
    precedent request keeps the list it recorded, and the caller does not ask here. TEMPORAL (E-D-5): a caller that
    has no config yet (the onboarding probe before `qa-factory/config.json` exists) passes {} and gets no
    `run.dependency_files`; a key built from that list never equals the gate's, which reads the config - one extra
    rehearsal, never a reused proof."""
    run_cwd = Path(run_cwd)
    table = dependency_table()
    run = (cfg or {}).get("run") if isinstance(cfg, dict) else None
    extra = run.get("dependency_files") if isinstance(run, dict) else None
    notes = [table["problem"]] if table["problem"] else []
    if extra is not None and not (isinstance(extra, list) and all(isinstance(v, str) and v.strip() for v in extra)):
        notes.append("`run.dependency_files` in qa-factory/config.json is not a list of file names, so it is ignored")
        extra = []
    names = list(table["names"])
    for pattern in table["patterns"]:
        try:
            names += sorted(match.name for match in run_cwd.glob(pattern) if match.is_file())
        except (OSError, ValueError):
            continue
    paths = []
    for name in names + [v.strip() for v in extra or []]:
        path = str(run_cwd / name)
        if (run_cwd / name).is_file() and path not in paths:
            paths.append(path)
    return paths, "; ".join(notes)


def is_pytest_command(argv) -> bool:
    """`pytest`, `py.test`, `python -m pytest`, behind any launcher (poetry, uv, tox -e)."""
    return _node_ids.is_pytest(argv)


def _pytest_ini_name(directory: Path) -> str:
    """The name of the file pytest takes as its ini-file in `directory`: `pytest.ini`, or `tox.ini` with
    `[pytest]`, `setup.cfg` with `[tool:pytest]`, `pyproject.toml` with `[tool.pytest.ini_options]` (in that
    order); "" when there is none."""
    if (directory / "pytest.ini").is_file():
        return "pytest.ini"
    for name, header in (("pyproject.toml", "[tool.pytest.ini_options]"),
                         ("tox.ini", "[pytest]"), ("setup.cfg", "[tool:pytest]")):
        try:
            text = (directory / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(line.strip() == header for line in text.splitlines()):
            return name
    return ""


def _has_pytest_config(directory: Path) -> bool:
    """Does `directory` hold the file pytest takes as its ini-file: `pytest.ini`, or `tox.ini`
    with `[pytest]`, `setup.cfg` with `[tool:pytest]`, `pyproject.toml` with
    `[tool.pytest.ini_options]`."""
    return bool(_pytest_ini_name(directory))


def pytest_rootdir(file_dir: Path, stop: Path):
    """The directory pytest reports node ids relative to: walking up from `file_dir`, the first
    directory with a pytest configuration, never above `stop` (the run's cwd). None when there
    is none: pytest then falls back to something this walk does not claim to know."""
    file_dir, stop = Path(file_dir).resolve(), Path(stop).resolve()
    if not file_dir.is_relative_to(stop):
        return None
    for directory in (file_dir, *file_dir.parents):
        if _has_pytest_config(directory):
            return directory
        if directory == stop:
            break
    return None


_INI_SECTION = {"pyproject.toml": "[tool.pytest.ini_options]", "tox.ini": "[pytest]", "setup.cfg": "[tool:pytest]"}


def _timeout_answer(state: str, limit_s, source: str, why: str = "") -> dict:
    return {"state": state, "limit_s": limit_s, "source": source, "why": why}


def _timeout_tokens(tokens):
    """The raw value of the LAST `--timeout=N` / `--timeout N` among `tokens` (stopping at a bare `--`), or None."""
    found = None
    for index, token in enumerate(tokens):
        if token == "--":
            break
        if token == "--timeout":
            found = tokens[index + 1] if index + 1 < len(tokens) else ""
        elif token.startswith("--timeout="):
            found = token.split("=", 1)[1]
    return found


def _timeout_reading(raw, source: str) -> dict:
    """The answer for a raw timeout value, read the way pytest-timeout reads it (`float(value)`): a number or a numeric
    string; 0 switches the timeout off; anything else (a bool, a word, a negative, a non-finite number) is unreadable."""
    try:
        value = float(raw.strip() if isinstance(raw, str) else raw) if not isinstance(raw, bool) else None
    except (TypeError, ValueError):
        value = None
    if value is None or not math.isfinite(value) or value < 0:
        return _timeout_answer("unreadable", None, source, f"the timeout value {str(raw)[:40]!r} is not a number of seconds")
    if value == 0:
        return _timeout_answer("disabled", None, source, "timeout = 0 switches it off")
    return _timeout_answer("configured", value, source)


def _ini_options(path: Path, name: str) -> tuple:
    """`(options, problem)`: the pytest options table of the ini-file `path` (`name` is its file name)."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        return None, f"{name} cannot be read ({type(exc).__name__})"
    if name == "pyproject.toml":
        try:
            import tomllib
        except ImportError:
            return None, f"{name} cannot be read here: this python has no tomllib (3.11 or newer)"
        try:
            data = tomllib.loads(text)
        except ValueError as exc:
            return None, f"{name} cannot be read ({type(exc).__name__})"
        tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
        pytest_table = tool.get("pytest") if isinstance(tool.get("pytest"), dict) else {}
        options = pytest_table.get("ini_options")
        return (options if isinstance(options, dict) else {}), ""
    section = _INI_SECTION.get(name, "[pytest]").strip("[]")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        return None, f"{name} cannot be read ({type(exc).__name__})"
    return (dict(parser[section]) if parser.has_section(section) else {}), ""


def _timeout_in_ini(directory: Path, root: Path):
    """The timeout answer of the pytest ini-file in `directory`, or None when it holds none. Pytest 9 names this reader
    does not read (`pytest.toml`, `.pytest.toml`, and `.pytest.ini` when it outranks the file found) are `unreadable`:
    reading them as "no timeout" would print a false fact."""
    name = _pytest_ini_name(directory)
    rel = directory.relative_to(root).as_posix()
    prefix = "" if rel == "." else rel + "/"
    newer = [n for n in ("pytest.toml", ".pytest.toml") if (directory / n).is_file()]
    if (directory / ".pytest.ini").is_file() and name != "pytest.ini":
        newer.append(".pytest.ini")
    if newer:
        return _timeout_answer("unreadable", None, prefix + newer[0],
                               f"{prefix + newer[0]} is a pytest 9 config file this reader does not read")
    if not name:
        return None
    label = prefix + name
    options, problem = _ini_options(directory / name, name)
    if problem:
        return _timeout_answer("unreadable", None, label, problem)
    addopts = options.get("addopts")
    if isinstance(addopts, str):
        try:
            tokens = shlex.split(addopts)
        except ValueError:
            return _timeout_answer("unreadable", None, label + " addopts", "addopts cannot be split into arguments")
    elif isinstance(addopts, list):
        tokens = [str(item) for item in addopts]
    elif addopts is None:
        tokens = []
    else:
        return _timeout_answer("unreadable", None, label + " addopts", "addopts is neither a string nor a list")
    raw = _timeout_tokens(tokens)
    if raw is not None:
        return _timeout_reading(raw, label + " addopts")
    section = _INI_SECTION.get(name)
    source = f"{label} {section} timeout" if section else f"{label} timeout"
    if "timeout" in options:
        return _timeout_reading(options["timeout"], source)
    return _timeout_answer("none", None, label, f"{label} sets no timeout")


def pytest_timeout_setting(cwd, argv, stop) -> dict:
    """The ONE reader of the project's pytest per-test timeout (RH2-9, AR-13): `{state, limit_s, source, why}`,
    `state` one of `configured` (`limit_s` seconds), `none`, `disabled` (`timeout = 0`), `unreadable` (`why` says what
    could not be read). Precedence, highest first, as pytest-timeout applies what this reader can see: `--timeout` in
    `argv` (the profile's command), `--timeout` inside the ini-file's `addopts`, the ini-file's `timeout`. The ini-file
    is the first of the locator `_pytest_ini_name` finds walking up from `cwd`, never above `stop` (the project root).
    BLIND SPOTS, stated: the `PYTEST_TIMEOUT` environment variable, `-c/--config-file`, `-p no:timeout`, and an ini
    `timeout` whose plugin is not installed (pytest only warns) are not read, so `configured` is "the project sets",
    not "the run applies". Never raises."""
    try:
        raw = _timeout_tokens([str(a) for a in argv or []])
        if raw is not None:
            return _timeout_reading(raw, "the profile's command")
        root, here = Path(stop).resolve(), Path(cwd).resolve()
        if not here.is_relative_to(root):
            return _timeout_answer("none", None, "", "the working directory is outside the project; no ini-file was read")
        for directory in (here, *here.parents):
            answer = _timeout_in_ini(directory, root)
            if answer is not None:
                return answer
            if directory == root:
                break
        return _timeout_answer("none", None, "", "no pytest ini-file between the working directory and the project root")
    except Exception as exc:  # a reader's own defect is "cannot tell", never a crash and never "none"
        return _timeout_answer("unreadable", None, "", f"the timeout reader failed ({type(exc).__name__})")


def node_report_id(node_id: str, cwd=None) -> str:
    """The junit row of a pytest node id, as `run_suite.parse_junitxml` spells it.

    `a/b/test_x.py::TestC::test_fn[p]` is reported as classname `a.b.test_x.TestC`, name
    `test_fn[p]`, and read back as `a.b.test_x.TestC::test_fn[p]` - relative to pytest's
    rootdir, not to where the command ran. On TP1-13797 the command ran in `test-harness`,
    the node was `testproject1_test_harness/tests/webhook/test_x.py::TestC::test_fn`, and the
    rootdir `testproject1_test_harness` (it holds pytest.ini) made the junit row
    `tests.webhook.test_x.TestC::test_fn`. Given `cwd` (the request's `command.cwd`), the
    node's file is resolved against it and the module path is taken relative to the first
    directory, walking up to `cwd`, with a pytest configuration; none found (or no `cwd`) keeps
    the path as written. Only a directory found this way is ever used: no name fragments."""
    text = str(node_id or "").replace("\\", "/")
    parts = text.split("::")
    if len(parts) < 2:
        return text
    file = parts[0]
    if cwd:
        base = Path(cwd).resolve()
        target = (base / file).resolve()
        root = pytest_rootdir(target.parent, base)
        if root is not None and target.is_relative_to(root):
            file = target.relative_to(root).as_posix()
    module = file[:-3] if file.endswith(".py") else file
    classname = ".".join([module.strip("/").replace("/", ".")] + parts[1:-1])
    return f"{classname}::{parts[-1]}"


def expand_selector(selector: str) -> list:
    """Manifest selectors are written by roles for people: `test_a | test_b[p1|p2]` names
    three tests. One selector part per node; parameters split on the same bar."""
    text = str(selector or "").strip()
    if not text:
        return []
    parts, depth, current = [], 0, ""
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        if char == "|" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    out = []
    for part in (p.strip() for p in parts):
        if not part:
            continue
        if "[" in part and part.endswith("]"):
            head, params = part[:-1].split("[", 1)
            values = [v.strip() for v in params.split("|") if v.strip()]
            out.extend(f"{head.strip()}[{value}]" for value in values or [params])
        else:
            out.append(part)
    return out


def running_dispatches(controller: dict) -> list:
    rows = ((controller or {}).get("dispatches") or {}).values()
    return [d for d in rows if isinstance(d, dict) and d.get("status") == "running"]


def retry_ancestors(controller: dict, dispatch: dict) -> list:
    """The dispatch ids this one resumes, nearest parent first.

    A `parent_retry` dispatch is the same piece of work carried on from its checkpoint, the
    way `controller.repair_ledger` walks the chain when it counts rounds."""
    rows = (controller or {}).get("dispatches") or {}
    rows = rows if isinstance(rows, dict) else {}
    chain, seen = [], {str(dispatch.get("id") or "")}
    parent = str(dispatch.get("parent_retry") or "")
    while parent and parent not in seen:
        chain.append(parent)
        seen.add(parent)
        record = rows.get(parent)
        parent = str((record or {}).get("parent_retry") or "") if isinstance(record, dict) else ""
    return chain


def find_active_dispatch(artifact_root: Path, task: str = "", dispatch_id: str = "",
                         cases=(), notes: list | None = None) -> tuple:
    """(task, controller, dispatch) of the one dispatch this call belongs to."""
    artifact_root = Path(artifact_root)
    if task:
        candidates = [artifact_root / task]
    else:
        candidates = sorted_paths(p for p in artifact_root.glob("*") if p.is_dir()) if artifact_root.is_dir() else []
    found = []
    for directory in candidates:
        controller = _read_json(directory / "state" / "controller.json")
        if not isinstance(controller, dict):
            continue
        for dispatch in running_dispatches(controller):
            found.append((directory.name, controller, dispatch))
    if dispatch_id:
        exact = [row for row in found if row[2].get("id") == dispatch_id]
        if not exact:
            # TP1-15045: after a `checkpoint blocked` the orchestrator opened the work
            # again as a `parent_retry` dispatch, while the role's own prompt still carried the
            # id it was started with. Two `mine_refused` and ten minutes went on a piece of the
            # controller's bookkeeping. An id the running dispatch resumes IS this dispatch.
            resumed = []
            for row in found:
                records = row[1].get("dispatches") or {}
                old = records.get(dispatch_id) if isinstance(records, dict) else None
                role = str((old or {}).get("role") or "") if isinstance(old, dict) else ""
                if dispatch_id in retry_ancestors(row[1], row[2]) and role in {
                        "", str(row[2].get("role") or "")}:
                    resumed.append(row)
            if len(resumed) == 1 and notes is not None:
                notes.append(f"dispatch {dispatch_id} was resumed as {resumed[0][2].get('id')} "
                             "through parent_retry; this run belongs to the open one")
            exact = resumed
        found = exact
    if not found:
        where = f"story {task}" if task else "this project"
        raise MineRefusal(
            f"no active dispatch in {where}: `--mine` builds the run of the dispatch the "
            "controller has open, and none is open"
            + (f" under the id {dispatch_id}" if dispatch_id else "")
            + ". Inside a story the orchestrator opens one (controller.py --operation prepare); "
              "outside a story run tests with --task/--label.")
    if len(found) > 1:
        wanted = {str(c) for c in cases}
        narrowed = [row for row in found if wanted <= {str(s) for s in row[2].get("scope") or []}]
        found = narrowed or found
    if len(found) > 1:
        names = ", ".join(f"{row[0]}/{row[2].get('id')}" for row in found[:4])
        raise MineRefusal(f"several dispatches are open ({names}); say which one is yours: "
                          "--dispatch ID (and --task TICKET when they belong to different stories)")
    return found[0]


def s6_close_dispatch(task_root, cases) -> dict:
    """The stand-in dispatch of the S6 CLOSE CONTEXT (HF3-6): `{"id", "stage": "S6", "scope", "budget": {}}`, or `MineRefusal`.

    The code close of S6 proves a stale live check again when no dispatch is open (`probe_by_code --s6-close`). The
    context exists exactly when the controller would take the S6 code-only receipt: `controller.code_close_conflicts`
    is empty (ONE predicate, AR-13), and the story is not closed. Pure: it reads `state/controller.json` and
    `pipeline.json` and writes nothing, so a caller asks it BEFORE it touches a byte.

    The direction of error is the refusal (M4). A false refusal costs a digest line (S6 closes anyway); a false "yes"
    would let a probe mutate the author's test while a role works on the tree, or after S6 was closed. So: a state
    that cannot be read, any running dispatch (of any stage), a prior stage not completed, S6 completed, a closed
    story, a case outside the story's scope, and an EMPTY scope are all refused; nothing is read as "all closed" or
    "all in scope" for being empty. Each refusal names a door its receiver (the driver or the conductor) can use.

    `s6_close_dispatch` reads the state; `s6_close_from_state` decides over a state already read, so a caller that
    needs the state for more than the decision (`build_mine_request`) reads it ONCE."""
    task_root = Path(task_root)
    return s6_close_from_state(task_root, _read_json(task_root / "state" / "controller.json"), cases)


def s6_close_from_state(task_root, state, cases) -> dict:
    """`s6_close_dispatch` over a `state` the caller has read (`None` or a non-dict: a state that cannot be read)."""
    task_root = Path(task_root)
    task = task_root.name
    if not isinstance(state, dict):
        raise MineRefusal(
            "the close of S6 is read from state/controller.json of this story, which cannot be read; nothing was "
            f"changed. Rebuild it: `controller.py --task {task} --operation recover`")
    import controller as _controller
    # TR4-7 (AR-13, FR-59): the liveness of the running rows is read by the controller's one reader (`_close_verdicts`), so a dispatch
    # whose session is over does not hold the context, exactly as it does not hold the code close that follows; a reader that cannot be
    # built or fails leaves every row a holder (no verdicts: the old reading, the refusal side).
    try:
        verdicts = _controller.Controller(task_root)._close_verdicts(state, "S6")
    except Exception:
        verdicts = None
    conflicts = _controller.code_close_conflicts(state, "S6", verdicts)
    # The DETAILS of a refusal come from the predicate's own facts (AR-13), never from a second scan of the state.
    facts = _controller.code_close_facts(state, "S6", verdicts)
    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    s6 = stages.get("S6") if isinstance(stages.get("S6"), dict) else {}
    if facts["running"]:
        ids = facts["running"]
        # every holder gets its own door, in the state's order: none is picked by position (A-K2: every id and `--dispatch`)
        under = (f"a probe runs under it, `--dispatch {ids[0]}`" if len(ids) == 1
                 else "a probe runs under the one that works on the case, "
                 + " or ".join(f"`--dispatch {ident}`" for ident in ids))
        raise MineRefusal(
            f"a dispatch is open in this story ({', '.join(ids)}): {under}; "
            "the S6 close context is only the code close of S6, when nothing is open"
            + (_controller._code_close_holders_words(state, ids, verdicts, checkpoint=True) if verdicts is not None else "")
            + ". Nothing was changed.")
    if facts["behind"]:
        behind, status = facts["behind"]
        raise MineRefusal(
            f"S6 has not started: {behind} is {status or 'not recorded'}; a probe outside a dispatch runs only in the "
            f"code close of S6. Close {behind} first (or skip it with a recorded reason); a probe inside a dispatch "
            "is `--dispatch <id>`. Nothing was changed.")
    if facts["completed"]:
        by = str(s6.get("receipt_id") or "") or "by its runner"
        raise MineRefusal(
            f"S6 is already closed ({by}): no evidence is added to a closed stage; a test changed after S6 is "
            "proved again when S6 runs again (`controller.py --operation rework --stage S6 ...`). "
            "Nothing was changed.")
    if conflicts:
        # a sentence of the predicate this reader has no facts for is still a refusal, in the controller's own words
        raise MineRefusal(f"the controller would not take the code close of S6 now ({conflicts[0][1]}); the S6 close "
                          "context is only that close. Nothing was changed.")
    pipeline = _read_json(task_root / "pipeline.json")
    if not isinstance(pipeline, dict):
        # whether the story is closed cannot be known: not read as "open" (FR-59)
        raise MineRefusal(
            "whether this story is closed is read from pipeline.json, which cannot be read; nothing was changed. "
            f"Rebuild it: `controller.py --task {task} --operation recover`")
    if story_closure(pipeline)["state"] != "open":      # closed, or executing the orders of gate B: S6 is over either way
        raise MineRefusal(
            "S6 is already closed (the story is closed): no evidence is added to a closed stage; a test changed after "
            "S6 is proved again when S6 runs again (`controller.py --operation rework --stage S6 ...`). "
            "Nothing was changed.")
    scope = [str(s) for s in state.get("scope") or []] if isinstance(state.get("scope"), list) else []
    outside = [str(c) for c in cases if str(c) not in scope]
    if outside or not scope:
        raise MineRefusal(
            f"{', '.join(outside) or 'the case'} is not in the story's approved scope; the close of S6 proves only "
            "its own cases. A case outside the scope is probed under the dispatch that holds it "
            "(`--dispatch <id>`). Nothing was changed.")
    # the id is a file-name part of the job and the record: only `[A-Za-z0-9-]` (a revision is an event sequence number)
    revision = "".join(ch if (ch.isascii() and ch.isalnum()) or ch == "-" else "-" for ch in str(state.get("revision") or "0"))
    return {"id": "S6-close-r" + revision, "stage": "S6", "scope": list(scope), "budget": {}}


def person_word(task_root: Path, stage: str, message: str) -> dict:
    """`{"decision", "at"}` of the person's recorded words that passed this block, else {}."""
    try:
        from waiver import split_overridden
        pipeline = _read_json(Path(task_root) / "pipeline.json") or {}
        _blocking, passed = split_overridden([message], pipeline, str(stage or ""))
        return ({"decision": str(passed[0].get("decision") or ""), "at": str(passed[0].get("at") or "")}
                if passed else {})
    except Exception:
        return {}


def person_passed(task_root: Path, stage: str, message: str) -> str:
    """The person's recorded words when they passed this block, else "". A check stops a
    silent pass, never an informed one (0.7.4): `stage_overrides[]` is where the word lives."""
    return person_word(task_root, stage, message).get("decision", "")


def scope_refusal(cases, dispatch_id, scope, stage) -> str:
    """The ONE sentence of the scope block (FR-1, FR-2): which cases are outside the dispatch, what it was given,
    and the two doors a refused role can use. `build_mine_request` refuses with it, and `probe_debt` (its
    pre-check `_scope_word` and the `outside_scope` words of `settle`) says the same sentence and looks the
    person's word up by it (`person_passed` matches the stage's overrides by this text), so the three never drift."""
    return (f"{', '.join(cases)} is {SCOPE_BLOCK}: dispatch {dispatch_id} was given "
            f"{', '.join(scope) or 'no cases'}. A dispatch runs only the cases it was given; nothing "
            "is wrong with your test. Hand the case back in your digest — the orchestrator "
            "dispatches it, or records the person's word for it (waiver.py, stage "
            f"{stage}, block \"{SCOPE_BLOCK}\").")


def _node_rows(node_ids, manifest):
    """The manifest rows of the given test nodes, by the one rule `proof_level.node_selects_row` (the function
    name against the row's ids and aliases, in the row's own file); None when any node has no function or no row."""
    import contract as C
    import proof_level as PL
    entries = []
    for node in node_ids:
        file, _chain, function, _params = _split_node(node)
        selected = _instance_name(str(node).replace("\\", "/").split("::", 1)[-1])
        found = [e for e in C.manifest_tests(manifest) if PL.node_selects_row(e, selected, file, strict=True)]
        if not found or not function:
            return None
        entries.extend(found)
    return entries


def _admitted_outside(outside, cases, node_ids, manifest, task_root, dispatch, purpose, evidence_only) -> tuple:
    """`(admitted, instance ids)`: is this red probe of cases OUTSIDE the dispatch a RE-probe of live checks
    that went stale (FB-10)? Only for a `red_probe` of the dispatch of a `qa-code-critic`, never an
    `evidence_only` read, and only when EVERY row the request would run for the outside cases is admitted by
    `proof_level.reprobe_admitted` (a stale receipt exists): a test with no receipt, a fresh one, a node with no
    row, or anything that cannot be told keeps today's refusal. With `node_ids` a node is its row by
    `_node_rows` (the one rule `proof_level.node_selects_row`, also `_newest_request`'s) and `node_ids` name
    the tests of ONE case. Reads only; an error is "not admitted"."""
    if purpose != "red_probe" or evidence_only or str(dispatch.get("role") or "") != "qa-code-critic":
        return False, []
    try:
        import contract as C
        import proof_level as PL
        if node_ids:
            entries = _node_rows(node_ids, manifest) if len(cases) == 1 else None
            if not entries:
                return False, []
        else:
            entries = []
            for case in outside:
                rows, _files = manifest_rows(manifest, case, strict=True, store_root=task_root)
                if not rows:
                    return False, []
                entries.extend(row["entry"] for row in rows)
        if not entries or not all(PL.reprobe_admitted(e, manifest, task_root)[0] for e in entries):
            return False, []
        return True, list(dict.fromkeys(C.test_instance_id(e) for e in entries))
    except Exception:   # a refusal of the strict reader, or anything unreadable: the block stands
        return False, []


def _instance_name(selector_part: str) -> str:
    """`TestC::test_fn[p]` -> `test_fn[p]` through the one definition of an instance id."""
    tail = selector_part.split("::")[-1]
    function, _, params = tail.partition("[")
    try:
        from contract import instance_id
        return instance_id(function, params.rstrip("]") or None) or tail
    except Exception:
        return tail


def _held_keys(entries: list, number: str, keys_of, split) -> list:
    """The area-qualified keys of `number` (`feedback-api/TC-003`) these entries carry, sorted."""
    return sorted({key for entry in entries for key in keys_of(entry)
                   if split(key)[0] and split(key)[1] == number})


def _store_index(store_root):
    """The story's case index, read through `contract.case_index` - the construction the controller's
    `stage_scope` uses (`Controller._case_index`): a number two areas hold is keyed `<area>/TC-NNN`
    there. None when there is no store root, or when the index cannot be built (no cases yet, an
    unreadable or colliding case file, no contract module): that counts as one area - today's
    behaviour, no new refusal for a story whose store cannot be read."""
    if store_root is None:
        return None
    try:
        from contract import case_index
        return case_index(Path(store_root))
    except Exception:
        return None


def _areas_in(index, number: str, split) -> list:
    """The areas `index` holds `number` under, sorted; [] when it holds it under one area or none."""
    if index is None:
        return []
    try:
        keys = index.matching(number)
    except Exception:
        return []
    return sorted({split(key)[0] for key in keys if split(key)[0]}) if len(keys) > 1 else []


def _store_areas(store_root, number: str, split) -> list:
    """The areas the story's case store holds `number` under (see `_store_index`, `_areas_in`)."""
    return _areas_in(_store_index(store_root), number, split)


def _no_test_refusal(case: str, files) -> str:
    """The sentence for a case the manifest names no runnable test for. ONE text, raised at two sites of
    `build_mine_request`: before the profile is chosen (a case with no row and no file says THIS, never
    "cannot tell which execution profile" - the FB-19 text for another cause) and where a file with no
    selector meets a command that cannot collect it."""
    return (f"the manifest names no test for {case} yet"
            + (f" (only the file {files[0]})" if files else "")
            + ". Put the test there through manifest_put.py (file + selector), or name it "
              f"for this run: --mine {case} --node-id <file>::<test function>")


def _entries_of_case(entries: list, case: str, readers: tuple, strict: bool, notes,
                     stored=None) -> list:
    """The manifest entries one asked case selects. `readers` is (keys_of, split, answering).

    TP2-2406 S5-5 (FB-19, 19.10.2026): the dispatch handed out `feedback-api/TC-003`, the
    manifest row held it as `covers: ["feedback-api/TC-003"]`, and the row was never found - the
    old test was `case in manifest_test_links(entry)`, which answers in BARE ids on purpose, so
    the area the scope kept never matched and the role was refused about profiles. A qualified
    ask is compared with the area-aware keys; the bare links stay the form of 0.7.x rows and of
    a bare ask. `strict` is the asked case of `--mine`: the ambiguities refuse there; every
    other reader of this function (a probe, a sandbox, a scope walk) gets today's answer, no
    exception. The strict path is reached by `--mine` and, through `fresh_evidence`
    (`build_mine_request(evidence_only=True)`), by `story_run.s6_freshness` and `red_sandbox`; both
    catch the refusal and fall back (`undecided` / the probe's baseline).

    `stored(number)` answers which areas the story's case store holds a number under (`[]`: one area
    or none); `None` means the caller named no store (`manifest_rows(store_root=None)`) and then there
    is no 0.7.x compatibility at all: a qualified ask over an area-less row answers `[]`, the answer
    before t-1243 and the safe default (FR-59). The store gates two things: rule (b), area-less rows
    answer a qualified ask only while the store holds that number under at most one area (one bare row
    is never credited to two areas, FR-18, FR-58); and a BARE ask over a number the store holds under
    two areas is refused whatever the manifest holds, because one id that names two cases is not
    evidence for either (AR-28)."""
    keys_of, split, answering = readers
    area, number = split(case)
    # `answering` is `contract.entries_for_case`, the one predicate "this entry answers this asked
    # case" that `s5_precheck` shares (t-044); the compatibility and strict rules stay here.
    hits = answering(entries, case)
    if not area:
        held = _held_keys(hits, number, keys_of, split)
        if strict:
            areas = sorted({split(k)[0] for k in held} | set(stored(number) if stored else []))
            if len(areas) > 1:
                spelled = [f"{a}/{number}" for a in areas]
                raise MineRefusal(f"{case} is held under more than one area ({', '.join(spelled)}); name the "
                                  f"one you mean: --mine {spelled[0]}"
                                  " (if your dispatch was given the bare id, hand it back in your digest)")
        return hits
    if hits:
        return hits
    bare = answering(entries, number)
    held = _held_keys(bare, number, keys_of, split)
    if bare and not held:
        if stored is None:
            return []  # no store named: no compatibility rule to apply (F1, FR-59)
        several = stored(number)
        if several:
            # The store holds the number under several areas: a row that names none is no evidence for any one.
            if strict:
                raise MineRefusal(
                    f"{case}: the manifest row names no area and the story holds {number} under "
                    f"{', '.join(several[:-1])} and {several[-1]}; "
                    "correct the row's covers through manifest_put.py, or hand the case back in your digest")
            return []
        # 0.7.x rows name no area anywhere: compatibility, said out loud (FR-41).
        if notes is not None:
            notes.append(f"{case}: the manifest names no area for {number}; ran its rows")
        return bare
    if held and strict:
        unlabelled = any(not _held_keys([e], number, keys_of, split) for e in bare)
        if not unlabelled and stored is not None and area in stored(number):
            # The asked area exists and its row is simply not there yet: the caller's "names no test" speaks.
            # Naming another area's correct row as the one to rewrite would credit it to the wrong case.
            return []
        raise MineRefusal(
            f"{case}: the manifest holds {number} only under {', '.join(held)}; the dispatch scope and "
            "the manifest disagree on the area - correct the row's covers through manifest_put.py, or "
            "hand the case back in your digest"
            + (f" (a row of {number} that names no area is not run on a guess once another row names "
               "one)" if unlabelled else ""))
    return []


def manifest_rows(manifest: dict, case: str, *, strict: bool = False, notes: list | None = None,
                  store_root=None) -> tuple:
    """(rows, files): the runnable tests the manifest names for one case, and the files of
    its entries that name no test yet. A row: instance_id, node (file::selector), entry.

    `strict=True` (the asked case of `build_mine_request`) raises MineRefusal for an ambiguous
    ask; the default keeps every other caller exception-free. `notes`, when given, receives the
    compatibility note of a qualified ask answered by area-less rows. `store_root` is the task's
    artifacts folder (see `_entries_of_case`): the case index is built from it at most once per call,
    on first use. None means no store was named and no area-less row answers a qualified ask; a store
    that cannot be read counts as one area."""
    try:
        import contract
        tests, keys_of, identity, split, answering = (
            contract.manifest_tests, contract.manifest_test_keys,
            contract.test_instance_id, contract.split_case_key, contract.entries_for_case)
    except Exception:  # a broken sibling module must not take the runner down with it
        def tests(m):
            return [t for t in (m.get("tests") or []) if isinstance(t, dict)]

        def keys_of(e):
            return [str(e.get("case") or "")]

        def identity(e):
            return str(e.get("instance_id") or "")

        def split(key):
            return "", str(key)

        def answering(entries, asked):
            return [e for e in entries if asked in keys_of(e)]
    built: list = []

    def stored(number):
        if not built:
            built.append(_store_index(store_root))
        return _areas_in(built[0], number, split)

    rows, files, seen = [], [], set()
    for entry in _entries_of_case(tests(manifest or {}), case, (keys_of, split, answering),
                                  strict, notes, stored if store_root is not None else None):
        file = str(entry.get("file") or "").replace("\\", "/")
        explicit_nodes = entry.get("node_ids") or ([entry["node_id"]] if entry.get("node_id") else [])
        parts = [str(n) for n in explicit_nodes] or expand_selector(
            entry.get("selector") or entry.get("test_function") or entry.get("function") or "")
        if not parts:
            if file and file not in files:
                files.append(file)
            continue
        for part in parts:
            node = part.replace("\\", "/") if ".py::" in part or not file else f"{file}::{part}"
            if node in seen:
                continue
            seen.add(node)
            name = identity(entry) if len(parts) == 1 else ""
            rows.append({"instance_id": name or _instance_name(part), "node": node, "entry": entry,
                         "report_test_id": (str(entry.get("report_test_id") or "")
                                            if len(parts) == 1 else "")})
    return rows, files


def _same_file(named: str, files) -> bool:
    """The manifest, a node id and a sandbox copy spell one file three ways; a tail on a
    directory boundary is the same file."""
    named = str(named or "").replace("\\", "/").lower()
    for other in files:
        other = str(other or "").replace("\\", "/").lower()
        if named and other and (named == other or named.endswith("/" + other)
                                or other.endswith("/" + named)):
            return True
    return False


def covered_by(instance_id: str, known) -> bool:
    """Is this manifest instance one of `known`?

    A manifest row that names a function without parameters becomes one instance per collected
    parameter (`test_x` -> `test_x[chromium-1]`, `test_x[chromium-2]`), so a run that carries
    every parameter of it carries the row. A row that names a parameter of its own is itself
    and nothing else — that is exactly the shape a single-instance run picks out."""
    instance_id = str(instance_id)
    if instance_id in known:
        return True
    return "[" not in instance_id and any(str(k).startswith(instance_id + "[") for k in known)


def window_neighbours(manifest: dict, scope: list, rows: list, selected: list) -> list:
    """Tests of this dispatch's own scope that live in the files this run touches and are left
    out of it. `--mine TC-012` already runs all five instances of TC-012 in one pytest call;
    what this finds is the sixth test in the same file that the call leaves behind."""
    files = {str((row.get("entry") or {}).get("file") or "")
             or str(row.get("node") or "").split("::")[0] for row in rows}
    out, seen = [], set()
    for case in scope:
        for row in manifest_rows(manifest, case)[0]:
            file = str((row.get("entry") or {}).get("file") or "") or row["node"].split("::")[0]
            instance = row["instance_id"]
            if instance in seen or covered_by(instance, selected) or not _same_file(file, files):
                continue
            seen.add(instance)
            out.append({"case": case, "instance_id": instance, "node": row["node"]})
    return out


def never_ran(jobs: list, instance_id: str) -> bool:
    """No finished run of this story ever selected this instance. A red probe proves nothing
    about a test: it runs mutated code on purpose."""
    for job in jobs:
        request = job.get("request") or {}
        if (job.get("status") == "completed" and request.get("purpose") != "red_probe"
                and covered_by(instance_id, request.get("selected_instance_ids") or [])):
            return False
    return True


def functions_naming_case(path: Path, case: str) -> list:
    """Test functions of a Python file whose decorators, leading comment or docstring name
    the case — the marker convention the automator already follows (`marker: TC-008`)."""
    import ast
    import re
    try:
        source = Path(path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return []
    lines = source.splitlines()
    pattern = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(case) + r"(?![A-Za-z0-9_-])")
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
            continue
        first = min([d.lineno for d in node.decorator_list] + [node.lineno])
        while first > 1 and lines[first - 2].lstrip().startswith("#"):
            first -= 1
        last = node.lineno
        body = node.body[0] if node.body else None
        if isinstance(body, ast.Expr) and isinstance(getattr(body, "value", None), ast.Constant):
            last = getattr(body, "end_lineno", None) or last
        if pattern.search("\n".join(lines[first - 1:last])) and node.name not in found:
            found.append(node.name)
    return found


def _split_node(node: str) -> tuple:
    """(file, class chain, function, params or None) of a pytest node id."""
    parts = str(node).replace("\\", "/").split("::")
    tail = parts[-1] if len(parts) > 1 else ""
    function, bracket, params = tail.partition("[")
    return parts[0], tuple(parts[1:-1]), function, (params[:-1] if bracket and params.endswith("]") else None)


def _conftest_chain(test_files, run_cwd: Path) -> list:
    """The `conftest.py` files above the test files, up to the run directory, nearest to a test
    first - the order pytest resolves a fixture in. One derivation for the run (`build_mine_request`)
    and for the re-measurement of one test later (`instance_shas`): two would drift (FR-17)."""
    chain = []
    for file in test_files:
        directory = Path(file).parent
        while directory == run_cwd or directory.is_relative_to(run_cwd):
            candidate = directory / "conftest.py"
            if candidate.is_file() and str(candidate) not in chain:
                chain.append(str(candidate))
            if directory == run_cwd:
                break
            directory = directory.parent
    return chain


def _helper_paths(chain, inherited, test_files) -> list:
    """What a test's `function_sha` reads besides its own file, in this order: the conftest chain,
    the helpers this story's earlier runs declared (sorted), then the other test files of the run,
    because a test module may import from its neighbour. Each path once, at its first place."""
    found = []
    for candidate in list(chain) + sorted(inherited) + list(test_files):
        if str(Path(candidate)) not in found:
            found.append(str(Path(candidate)))
    return found


def instance_shas(project_root, request: dict, instance_id: str) -> dict:
    """`{"instance_content_sha", "instance_code_sha", "scope"}` of ONE instance of a request, measured
    over the bytes on disk NOW with the derivation `build_mine_request` used for that request's
    `instance_contracts`: the same run directory, test files and inherited helpers, read from the
    request's own `fingerprint_files`, and the same `function_sha`. `{}` when this cannot be measured
    - the command is not pytest, the request has no selector for the instance, no file is there, or
    `function_sha` raises. Never a sha for a missing file: `function_sha` gives "" for one, and this
    says nothing at all, so no caller can mistake it for an identity.

    An inherited helper that is also a test file of the run sits in a different place here than in
    the run's own list (the request's `helper_files` leave the test files out): the shas then differ,
    and the safe direction is the only error there is - one more run, one more probe."""
    try:
        root = Path(project_root).resolve()
        command = request.get("command") if isinstance(request.get("command"), dict) else {}
        args = (command.get("selector_args") or {}).get(instance_id)
        if not (isinstance(args, list) and args and isinstance(args[0], str) and args[0]):
            return {}
        cwd = Path(str(command.get("cwd") or "."))
        run_cwd = (cwd if cwd.is_absolute() else root / cwd).resolve()
        if not is_pytest_command(command.get("argv")):
            # EP1-37: a test file the language data reads. The file is the contract's own (`file`), looked up in the same
            # order as the pytest branch; no `file` (an older request) or no entry for it is `{}`, as it always was.
            contract = (request.get("instance_contracts") or {}).get(instance_id)
            named = str(contract.get("file") or "") if isinstance(contract, dict) else ""
            path = next((p for p in (run_cwd / named, root / named) if named and p.is_file()), None)
            if path is None:
                return {}
            import test_source
            return test_source.instance_shas_of(path.resolve(), str(contract.get("report_test_id") or ""),
                                                contract.get("report_match"), _title_join(command.get("argv")))
        records = [r for r in request.get("fingerprint_files") or [] if isinstance(r, dict) and r.get("path")]
        test_files = [str(r["path"]) for r in records if r.get("kind") == "test_files"]
        inherited = [str(r["path"]) for r in records if r.get("kind") == "helper_files"]
        file, classes, function, _params = _split_node(args[0])
        path = next((p for p in (run_cwd / file, root / file) if p.is_file()), None)
        if path is None:
            return {}
        from execution_fingerprint import function_sha
        chain = _conftest_chain(test_files, run_cwd)
        measured = function_sha(path.resolve(), function, classes, _helper_paths(chain, inherited, test_files))
    except Exception:
        return {}
    return {"instance_content_sha": str(measured.get("sha") or ""),
            "instance_code_sha": str(measured.get("code_sha") or ""),
            "scope": str(measured.get("scope") or "")}


def _title_join(argv) -> str:
    """What the runner joins a test's group titles with in its report name: the `title_join` of the `selection` of the run
    form `launch_check.runner_identity` finds; one space when the form states none (a title path is then not found by its raw
    text, and the identity is `{}` - the safe side)."""
    import launch_check
    selection = launch_check.runner_identity(argv)["selection"]
    return str(selection.get("title_join") or " ") if isinstance(selection, dict) else " "


def selector_file(request: dict, selected: str):
    """The test file the job selected `selected` in: the contract's own `file` when it has one (a runner whose selector is
    `file:line`, whose first token is no node id), else the first `selector_args` token read as a pytest node id, as
    before. None when the request names neither. The ONE reader (`proof_level._newest_request`), so a file:line selector is
    not mistaken for a file called `a.x:12` (B-2)."""
    contracts = request.get("instance_contracts") if isinstance(request.get("instance_contracts"), dict) else {}
    contract = contracts.get(selected)
    if isinstance(contract, dict) and isinstance(contract.get("file"), str) and contract["file"]:
        return contract["file"]
    command = request.get("command") if isinstance(request.get("command"), dict) else {}
    selectors = command.get("selector_args")
    node = ((selectors or {}).get(selected) or [None])[0] if isinstance(selectors, dict) else None
    return _split_node(node)[0] if isinstance(node, str) and node else None


def code_selection(entry: dict, argv, run_cwd, project_root):
    """The selector and the report identity of ONE manifest row, built by code from the file as it is now, or None.

    The ONE builder (EP1-36 calls it, no copy). It needs a run form whose data states a `selection`
    (`launch_check.runner_identity`) and a test file `test_source` reads in which exactly one declaration is the row's (its
    `bare_title` makes the row's instance id). `selector_args` is the form's `args` with `{file}` (the path from the run
    directory, `/` slashes; escaped when the form says `escape_file`, with a `/` before it, so `a.x:12` does not select
    `data.x:12`) and `{line}` (the line of the test call in the bytes read NOW). `report_test_id` is the form's
    `report_id` with `{classname}` the plain file and `{title_path}` the group titles and the title joined by `title_join`. A
    templated or looped declaration also returns `report_match` (the pattern of its whole report name). None means "not
    built": no selection in the data, no file, a file nobody reads, no declaration or more than one for the id."""
    import contract as C
    import launch_check
    import re
    import test_source
    selection = launch_check.runner_identity(argv)["selection"]
    named = str((entry or {}).get("file") or "")
    if not isinstance(selection, dict) or not named:
        return None
    path = next((p for p in (Path(run_cwd) / named, Path(project_root) / named) if p.is_file()), None)
    if path is None:
        return None
    read = test_source.read_file(path, named)
    if read["why_not"] or not read["language"]:
        return None
    wanted = {C.test_instance_id(entry), *C.instance_id_aliases(entry)} - {""}
    found = [d for d in read["declarations"] if C.instance_id(d["bare_title"], None) in wanted]
    if len(found) != 1:
        return None
    decl = found[0]
    try:
        shown = path.resolve().relative_to(Path(run_cwd).resolve()).as_posix()
    except ValueError:
        shown = named.replace("\\", "/")
    token = ("/" + re.escape(shown)) if selection.get("escape_file") else shown
    join = str(selection.get("title_join") or " ")
    args = [str(a).replace("{file}", token).replace("{line}", str(decl["line"])) for a in selection.get("args") or []]
    report = (str(selection.get("report_id") or "{classname}::{title_path}")
              .replace("{classname}", shown).replace("{title_path}", join.join(decl["title_path"])))
    out = {"selector_args": args, "report_test_id": report, "file": named}
    if selection.get("classname"):
        out["classname_match"] = str(selection["classname"])
    if decl["pattern"]:
        out["report_match"] = {"pattern": test_source.path_pattern(decl, join)}
    return out


_BROWSER_TOKENS = ("chromium-", "firefox-", "webkit-")


def _spell_as_collected(rows: list, command: dict, run_cwd: Path, collect, notes: list) -> tuple:
    """Rows respelled from a real collect, and whether every row was found in it.

    What a report calls a test is decided by the project's plugins and its rootdir, not by
    the path a role typed: on TP1-15045 `testproject1_test_harness/tests/ui/.../test_x.py::
    test_fn` was reported as `tests.ui....test_x::test_fn[chromium]`, so every hand-written
    `report_test_id` missed its row and the run block said `report row missing` about tests
    that had run. A collect answers both questions at once — which parameter ids exist, and
    how the report will spell them. A function named without parameters becomes one instance
    per collected parameter; no collect (module absent, or it failed) leaves the rows as they
    were, and the run checks the ids itself.

    The second element is a PROOF, not a hint (HF2-10): `True` means every row was found, once and by its own
    file, in a collect that was PARSED and non-empty, so nobody checks the ids again - the runner no longer
    collects a second time. It errs only towards False ("not verified"): a collect that raised or timed out, an
    empty list, a row missing from the list, a parametrized row with no candidate or with several, an id that is
    another file's or that a banner has glued to, all leave it False, and the ids are then checked against the SAME
    list (`run_suite.verify_node_ids`) or, when there is none, by the run (pytest's own `not found`)."""
    if collect is None or not rows:
        return rows, False
    files = sorted({row["node"].split("::")[0] for row in rows})
    try:
        collected = [str(n).strip().replace("\\", "/") for n in collect(list(command["argv"]), str(run_cwd), files)]
    except Exception as exc:  # ImportError of the collector included: a convenience, never a gate
        if not isinstance(exc, ImportError):
            notes.append(f"node ids were not checked while building the request ({type(exc).__name__}: "
                         f"{str(exc)[:160]}); report ids are predicted from the paths")
        return rows, False
    if not collected:
        return rows, False
    index = [(node, *_split_node(node)) for node in collected]
    out, all_found = [], True
    # Case is folded where the file system folds it (`_path_key`): on a case-sensitive one `tests/A.py` and
    # `tests/a.py` are two files, and a row of one must never be found in the other, or counted as "two
    # parametrizations" of itself.
    fold = str.lower if os.name == "nt" else str
    for row in rows:
        file, chain, function, params = _split_node(row["node"])
        absolute = fold(row["path"].as_posix())
        same = [item for item in index if item[3] == function and item[2] == chain
                and (absolute.endswith("/" + fold(item[1])) or fold(item[1]).endswith("/" + fold(file))
                     or fold(item[1]) == fold(file))]
        if params is not None:
            exact = [item for item in same if item[4] == params]
            same = exact or [item for item in same if item[4] is not None and (
                item[4].endswith("-" + params)
                or any(item[4] == token + params for token in _BROWSER_TOKENS))]
            if len(same) != 1:
                all_found = False  # the runner's check names the nearest ids before launch
                out.append(row)
                continue
        if not same:
            all_found = False
            out.append(row)
            continue
        if len(same) > 1:
            notes.append(f"{row['node'].split('::', 1)[-1]} is {len(same)} parametrized tests; each ran as "
                         "its own instance. One manifest row per parameter (manifest_put.py) lets "
                         "their results join the cases.")
        for real, _file, _chain, _function, real_params in same:
            tail = function + (f"[{real_params}]" if real_params is not None else "")
            node = "::".join([file, *chain, tail])
            if len(same) == 1 and real_params != params and params is not None:
                notes.append(f"{row['node']} is collected as [{real_params}]; ran the real id")
            out.append(dict(row, node=node if (len(same) > 1 or params is not None) else row["node"],
                            instance_id=row["instance_id"] if len(same) == 1 else _instance_name(tail),
                            # `real` is a collected id: pytest already spelled it relative to
                            # its own rootdir, so the rootdir rule must not be applied again.
                            report_test_id=node_report_id(real), collected=True))
    return out, all_found


def _path_key(path) -> str:
    """One spelling of a project-relative path, for comparing it with a profile's `roots.test`: backslashes become
    slashes, `./`, `a//b` and `a/../b` are folded, the outer slashes are cut, and on Windows the case is folded
    (that file system does not tell `Tests` from `tests`). '' for none. Invariant: `tests`, `./tests/` and, on
    Windows, `Tests` are one key, so no reader sees one root as two (AR-13)."""
    text = str(path or "").replace("\\", "/").strip()
    text = posixpath.normpath(text) if text else ""
    text = "" if text == "." else text.strip("/")
    return text.lower() if os.name == "nt" else text


def path_under(path_key: str, root_key: str) -> bool:
    """Whether the `_path_key` spelling `path_key` is the root `root_key` or lies below it. False when either is empty
    (no path, or no root: nothing is under nothing). The one comparison of "under a root" (`profiles_owning`,
    `probe_by_code._in_test_root`); both keys must come from `_path_key` (AR-13)."""
    if not path_key or not root_key:
        return False
    return path_key == root_key or path_key.startswith(root_key + "/")


def profiles_owning(cfg: dict, rel_path) -> list:
    """The ids of the profiles whose `roots.test` holds `rel_path` (project-relative), in config order: those with
    the DEEPEST such root. [] when no root holds it; one id when one profile owns it; MORE THAN ONE when several
    profiles share that deepest root - a tie the path cannot break and no caller may break by taking the first.
    The one predicate of "which profiles own this path" (`_profile_for`, `probe_by_code._profile_cwd`,
    `gate_preflight.Rehearsal._profiles_sharing_root`), with one normalisation (`_path_key`)."""
    key = _path_key(rel_path)
    deepest, owners = -1, []
    for profile in selected_profiles(cfg):
        root = _path_key((profile.get("roots") or {}).get("test"))
        if not path_under(key, root):
            continue
        pid = str(profile["profile_id"])
        if len(root) > deepest:
            deepest, owners = len(root), [pid]
        elif len(root) == deepest and pid not in owners:
            owners.append(pid)
    return owners


def entry_profile_id(entry) -> str:
    """The profile a manifest entry names (`profile_id`, or the older `profile`), or ''. The one reader."""
    entry = entry if isinstance(entry, dict) else {}
    return str(entry.get("profile_id") or entry.get("profile") or "")


def known_profile_ids(cfg: dict) -> list:
    """The ids of EVERY profile config.json holds (selected or not), in config order."""
    return [str(p["profile_id"]) for p in (cfg.get("profiles") or []) if isinstance(p, dict) and p.get("profile_id")]


def known_profile(cfg: dict, profile_id) -> bool:
    """Whether config.json holds a profile of this id. The one predicate of "is this a profile": `_profile_for` (a
    `--profile` flag or a manifest row names it) and `probe_by_code._profile_cwd` both ask it, so a name the config
    does not hold is refused in the same words in both and is never read as a path (AR-13). A profile that sits out
    (`selected: false`) is known: a name given outright is not cancelled in silence (A-E5)."""
    return bool(profile_id) and str(profile_id) in known_profile_ids(cfg)


NAMED_BY_ROW, NAMED_BY_FLAG = "the manifest row", "--profile"


def unknown_profile_refusal(cfg: dict, profile_id, source: str) -> str:
    """The refusal for a profile the config does not hold: whose name it is (`source`: the manifest row or the
    `--profile` flag - the owner of the mistake is the call, never the onboarding, FR-46), which ids are known, and
    the one door that source has (FR-1, FR-2). The one text of both readers of `known_profile`."""
    known = known_profile_ids(cfg)
    door = ("pass one of them with --profile ID" if source == NAMED_BY_FLAG
            else "write one of them as `profile_id` on the manifest row (manifest_put.py --fragment)")
    return (f"{source} names the execution profile `{profile_id}`, which qa-factory/config.json does not hold "
            f"(profile_id there: {', '.join(known) or 'none'}); {door}")


def _row_profile_of_file(rows: list, file) -> str:
    """The profile the manifest rows of `file` (rows of ONE case) name, or '' - the answer only when EVERY such row
    names the same one. A row of that file that names none, two rows that name two, and a file no row names give ''
    and the caller falls back to today's answer (the path, or the refusal): a test's profile is never taken from a
    neighbour that may not be its own (A-E8, EP1-10). Spelled by `_path_key`, like `profiles_owning`."""
    key = _path_key(file)
    named = [entry_profile_id(r.get("entry")) for r in rows if _path_key(str(r.get("node") or "").split("::")[0]) == key]
    return named[0] if named and len(set(named)) == 1 else ""


def _test_root_of(cfg: dict, profile_id: str) -> str:
    """`roots.test` of the profile as written (slashes forward, outer slashes cut), for a refusal's words."""
    for profile in selected_profiles(cfg):
        if str(profile.get("profile_id")) == profile_id:
            return str((profile.get("roots") or {}).get("test") or "").replace("\\", "/").strip("/")
    return ""


def _profile_for(cfg: dict, files: list, wanted: str, entries: list, precedent_jobs: list,
                 cases: list | None = None, *, profile_door: bool = True, notes: list | None = None) -> str:
    """The profile that runs these files. `profile_door` says whether the CALLER accepts `--profile ID`
    (`run_suite --mine` does, `probe_by_code` does not): a refusal names only a door its receiver can use (FR-2).
    `notes` takes the line that says an explicit profile overrode what the rows name.

    Invariant (FR-59, AR-28): the profile is never decided by an unknown. A path under a root several profiles
    share, a row beside rows that name another profile, and rows that name two profiles are each refused, never
    run under the first profile or under the one profile that happened to be named. A name the config does not
    hold - the caller's or a row's - is refused naming the ids it does hold, never run under another profile."""
    named = {entry_profile_id(e) for e in entries} - {""}
    if wanted:
        # `profile_door` tells who named it: a caller with the `--profile` door was given the flag, one without
        # (`probe_by_code`) hands over the profile of the manifest row.
        source = NAMED_BY_FLAG if profile_door else NAMED_BY_ROW
        if not known_profile(cfg, wanted):
            raise MineRefusal(unknown_profile_refusal(cfg, wanted, source))
        others = sorted(named - {wanted})
        if others and notes is not None:
            notes.append(f"the profile `{wanted}` ({'given with --profile' if profile_door else 'named by the caller'}) "
                         f"runs; the manifest names {', '.join('`' + o + '`' for o in others)}, which does not decide "
                         "this run (the explicit profile wins)")
        return wanted
    door = "name it on the manifest row (`profile_id`)" + (" or with --profile ID" if profile_door else "")
    if len(named) > 1:
        raise MineRefusal("these cases run under different profiles ("
                          + ", ".join(sorted(named)) + "): one run has one command, so run them "
                          "in separate calls, one `--mine` per profile")
    if len(named) == 1:
        if not known_profile(cfg, next(iter(named))):
            raise MineRefusal(unknown_profile_refusal(cfg, next(iter(named)), NAMED_BY_ROW))
        # An unnamed row beside a named one is not the named one's by default: when its file lies under a root
        # several profiles share, the path cannot tell whose it is, and running it under the profile the OTHER
        # rows named is the EP1-10 silence again (a ui row run under api, or an api row under ui).
        for entry in entries:
            if entry_profile_id(entry):
                continue
            own_file = str(entry.get("file") or "").replace("\\", "/") if isinstance(entry, dict) else ""
            for file in ([own_file] if own_file else files):
                owners = profiles_owning(cfg, file)
                row = (entry.get("instance_id") or entry.get("test") or file) if isinstance(entry, dict) else file
                if len(owners) == 1 and owners[0] != next(iter(named)):
                    # EP1-12 [F-8]: the path says another profile, while the other rows name this one; it is not
                    # run under the named profile by default. No owner at all (no root) stays as before: the
                    # refusal is only where the path says something else.
                    raise MineRefusal(
                        f"the manifest row {row} names no profile, and its file {file} lies under the test root of "
                        f"`{owners[0]}` (`{_test_root_of(cfg, owners[0])}`), while another row names "
                        f"`{next(iter(named))}`: the path says the row is `{owners[0]}`'s and it does not run under "
                        f"the other row's profile by default; {door}")
                if len(owners) > 1:
                    raise MineRefusal(
                        f"the manifest row {row} names no profile, and its file {file} lies under the test root "
                        f"`{_test_root_of(cfg, owners[0])}` that profiles {', '.join(owners)} share, while another "
                        f"row names `{next(iter(named))}`: the path cannot tell which of them runs it, and it does "
                        f"not run under the other row's profile by default; {door}")
        return next(iter(named))
    selected = selected_profiles(cfg)
    best, shared = {}, {}
    for file in files:
        owners = profiles_owning(cfg, file)
        best[file] = owners[0] if len(owners) == 1 else ""
        if len(owners) > 1:
            shared[file] = owners
    if shared:
        # Two profiles own the same test root (an api and a ui profile over one `tests/`): the first in the list
        # used to win in silence, and every ui row ran under the api command (EP1-10). The root cannot tell them
        # apart, so nothing here may; the row names its profile, or the caller does.
        file = sorted(shared)[0]
        raise MineRefusal(f"profiles {', '.join(shared[file])} share the test root "
                          f"`{_test_root_of(cfg, shared[file][0])}`, so the path of {file} cannot tell which "
                          f"execution profile runs it; {door}")
    hits = set(best.values())
    if len(hits) == 1 and "" not in hits:
        return hits.pop()
    if len(hits) > 1 and "" not in hits:
        raise MineRefusal("these cases run under different profiles ("
                          + ", ".join(sorted(hits)) + "): one run has one command, so run them "
                          "in separate calls, one `--mine` per profile")
    if len(selected) == 1:
        return str(selected[0]["profile_id"])
    seen = [str(j["request"].get("profile_id") or "") for j in precedent_jobs]
    if seen and len(set(seen)) == 1:
        return seen[-1]
    subject = ", ".join(str(c) for c in (cases or [])) or ", ".join(files) or "these cases"
    if not selected:
        # TP2-2553: `profiles` was absent from config.json, so this refusal met the
        # automator inside S5 with no name for what was missing and no way out but typing 106
        # request files by hand. The gap belongs to the onboarding, and the gate asks about it.
        raise MineRefusal(f"no execution profile in qa-factory/config.json runs {subject}; this "
                          "is a gap of the onboarding, not of your test — the gate-A rehearsal "
                          "asks the person (answer a/b/c); to onboard now: "
                          "`/qa-factory:qa-onboarding`")
    names = ", ".join(str(p["profile_id"]) for p in selected)
    raise MineRefusal(f"the factory cannot tell which execution profile runs {', '.join(files) or 'these cases'} "
                      f"(profiles: {names}); name it: " + ("--profile ID" if profile_door
                                                           else "`profile_id` on the manifest row"))


def _profile_argv(profile: dict) -> list:
    """The profile's one-test argv with its `<placeholder>` tokens taken out - the reading
    `_command_from_profile` builds a command from, and the one a precedent's argv is compared
    with (one reading, so "the same command" means the same thing in both places). It reads through the ONE reader
    (`profile_contract.one_test_argv`, AR-13) and NEVER raises or refuses: a profile whose command cannot be read gives
    `[]`, which the comparison with a precedent reads as "not compared" - the precedent is used as it always was (a
    profile in a foreign shape does not turn a good precedent into a refusal; `_command_from_profile` refuses, where a
    command is built from the profile)."""
    return one_test_argv(profile, drop_placeholders=True)[0]


def _profile_env(profile: dict) -> tuple[dict, str]:
    """`(env, problem)` of the profile's one-test command, through the ONE reader (`profile_contract.command_env`, AR-13).
    Never raises or refuses: like `_profile_argv`, a profile whose `env` cannot be read is "not compared" with a precedent."""
    return command_env(profile_command(profile, "one_test")[0])


def _command_from_profile(profile: dict, skipped_ids: list | None = None) -> dict:
    argv, problem = one_test_argv(profile, drop_placeholders=True)
    if not problem:
        env_problem = _profile_env(profile)[1]
        problem = f"commands.one_test.{env_problem}" if env_problem else ""
    if problem:
        # the shape is wrong, which is not the same as "no command": the door is the same (the onboarding), the sentence says what
        raise MineRefusal(f"profile {profile.get('profile_id') if isinstance(profile, dict) else None}: {problem}. That is a "
                          "gap of the onboarding, not of your test: report it in your digest, and write this one run "
                          "with --template request. To record the command once and for all: "
                          "`/qa-factory:qa-onboarding` (execution batch).")
    spec = profile_command(profile, "one_test")[0]
    if not argv:
        # TP1-13797: a story whose only typed runs never ran a test was told it had "no
        # earlier typed run" - false, and it hid that the runs it did have were the cause.
        earlier = (f"the earlier typed runs of this story never ran a test ({', '.join(skipped_ids)}), "
                   "so there is no command to copy from them" if skipped_ids
                   else "this story has no earlier typed run to copy the command from")
        raise MineRefusal(f"profile {profile.get('profile_id')} has no commands.one_test.argv in "
                          f"qa-factory/config.json, and {earlier}. That is a gap of the "
                          "onboarding, not of your test: "
                          "report it in your digest, and write this one run with --template request. "
                          "To record the command once and for all: `/qa-factory:qa-onboarding` "
                          "(execution batch).")
    declared = str(((profile.get("reporter") or {}).get("kind")) or "")
    reporter = declared if declared in REPORTERS else ("pytest" if is_pytest_command(argv) else "none")
    command = {"argv": argv, "cwd": str(spec.get("cwd") or "."), "scope": "selected", "reporter": reporter}
    if reporter in {"junit-xml", "trx"}:
        command["report_path"] = "{report_path}"
    env = _profile_env(profile)[0]
    if env:
        command["env"] = env     # the template, `{report_path}` as written: `run_suite.main` puts the run's own file in
    return command


_SHARED_COMPONENTS = ("source_sha", "config_sha", "dependency_sha", "runtime_sha", "policy_revision")


# --- the run budget (D-0017 / D-0018 / D-0019) ---------------------------------------------
#
# The owner's budget: a result of a test is reused while its bytes, the environment and the
# deployed version are unchanged, and only a person's word repeats one. On TP1-13797 the
# same seven instances ran green twice on identical bytes (`again-2` of the S5 repair run, then
# again in S6), and every red probe ran the mutated test three times through `--reruns 2`. The
# question "is this instance already answered?" has ONE predicate, `covered`, and every site
# that asks it (the `--mine` builder, the `--request` runner, the schedule label, the
# whole-run wrapper `green_over_same_bytes`) reads it from here (FR-17).

RUN_BUDGET_FILE = "run-budget.json"
_REQUIRED_WORDS = ("green", "red", "hint", "again_note", "partial_note", "word_note", "redeploy_note",
                   "not_observed", "request_partial", "flaky_stage", "flaky_one", "flaky_cap",
                   "flaky_word_note", "reruns_removed", "unobserved_repeat")
# Where a `covered` answer of "no" fell in the chain, for choosing the most informative `why`.
_WHY_RANK = {"result": 0, "selector": 1, "shared": 2, "bytes": 3, "stand": 4}


def _budget_problem(data) -> str:
    """Why a parsed run-budget.json cannot be used, or ""."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return "schema_version is not 1"
    for key in ("result_purposes", "exempt_purposes", "strip_reruns_purposes", "rerun_flags"):
        if not isinstance(data.get(key), list) or any(not isinstance(x, str) for x in data[key]):
            return f"{key} is not a list of strings"
    regex = data.get("rerun_flags_regex", [])
    if not isinstance(regex, list) or any(not isinstance(x, str) for x in regex):
        return "rerun_flags_regex is not a list of strings"
    if not isinstance(data.get("block"), str) or not data["block"].strip():
        return "block is missing"
    if not isinstance(data.get("flaky_stage"), str):
        return "flaky_stage is missing"
    failed = data.get("failed_result_policy")
    if (not isinstance(failed, dict) or isinstance(failed.get("covers_after_failures"), bool)
            or not isinstance(failed.get("covers_after_failures"), int)
            or failed["covers_after_failures"] < 0):
        return "failed_result_policy.covers_after_failures is not a whole number"
    if data.get("author_run_reading") not in {"per_code_version", "per_story"}:
        return "author_run_reading is not per_code_version or per_story"
    words = data.get("words")
    if not isinstance(words, dict):
        return "words is missing"
    absent = [k for k in _REQUIRED_WORDS if not isinstance(words.get(k), str) or not words[k].strip()]
    return ("words." + absent[0] + " is missing") if absent else ""


def load_run_budget(path=None) -> tuple:
    """(policy, note): the run budget from `references/run-budget.json`, or (None, the one
    sentence that says it is not enforced). Code tells, never stops (P1): an absent or broken
    data file leaves a run to behave as it did before the budget, and says so."""
    def unreadable(why: str) -> tuple:
        return None, (f"{RUN_BUDGET_FILE} unreadable ({why}): the run budget is not enforced for "
                      "this run")
    try:
        if path is None:
            from hooklib import ref
            path = ref(RUN_BUDGET_FILE)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return unreadable(f"{type(exc).__name__}: {str(exc)[:120]}")
    problem = _budget_problem(data)
    return unreadable(problem) if problem else (data, "")


def say(policy: dict, key: str, **fields) -> str:
    """One of the budget's sentences, filled in. The wording lives in the data (FR-13)."""
    fields.setdefault("block", policy.get("block", ""))
    try:
        return str(policy["words"][key]).format(**fields)
    except (KeyError, IndexError, ValueError):
        return str(policy["words"].get(key, key))


def _fallback_policy() -> dict:
    """What `covered` means when the data file is not there: the rule that stood before the
    budget - any finished, non-probe behavioral run is a result, and only a green one answers."""
    return {"result_purposes": sorted(BEHAVIORAL - {"red_probe"}), "exempt_purposes": ["red_probe"],
            "failed_result_policy": {"covers_after_failures": 0},
            "author_run_reading": "per_code_version"}


def _when(text):
    """An ISO time as a datetime, or None. Both spellings of UTC (`Z` and `+00:00`)."""
    try:
        value = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def stand_reset_at(project_root) -> str:
    """When a person last reset the stand's record (`stand_health.py --reset`), or "".
    A missing or broken sibling never takes a run down (P1)."""
    try:
        import stand_health
        return str(((stand_health.status(project_root) or {}).get("reset") or {}).get("at") or "")
    except Exception:
        return ""


def run_block_reader(project_root):
    """`block_of(job) -> dict | None | False`: the immutable run block a finished job points at
    (`job["run_block"]`, a path from the project root). None: there is no block on record (the
    job names none, or its file is not there). False: a block is on record and cannot be read."""
    seen: dict = {}  # one read per block per reader: every instance of a job asks for the same one

    def block_of(job):
        named = str((job or {}).get("run_block") or "")
        if not named:
            return None
        if named not in seen:
            path = Path(project_root) / named.replace("\\", "/")
            data = _read_json(path) if path.is_file() else None
            seen[named] = (data if isinstance(data, dict) else False) if path.is_file() else None
        return seen[named]
    return block_of


def running_stage(task_root) -> str:
    """The stage a story is working in now (`pipeline.json`: the one whose status is `running`),
    or "". `run_suite.active_story_stage` reads the same file by task id; this one by the story's
    own directory, for callers that hold no project root of their own (the scheduler)."""
    data = _read_json(Path(task_root) / "pipeline.json")
    if not isinstance(data, dict):
        return ""
    for name, entry in (data.get("stages") or {}).items():
        if isinstance(entry, dict) and entry.get("status") == "running":
            return str(name)
    return ""


def _job_outcome(job: dict, instance_id: str, purposes, reset_at: str, block_of) -> tuple:
    """(outcome, why): `passed`, `failed`, or "" with the reason this job holds no result of
    this instance. A result is a completed job of a result purpose whose run gave THIS instance
    `passed` or `failed`, read from the job's run block row: a readable row that says anything
    else (`skipped`, `not_run`, a missing report row) is no result of that instance, for a green
    job as for a red one. A green job whose run block is not on record at all keeps the job's
    own status (small choice 2); a block that is on record and unreadable is no result."""
    old = job.get("request") or {}
    purpose = str(old.get("purpose") or "")
    if job.get("status") != "completed":
        return "", f"the earlier run of it did not complete (job status {job.get('status')})"
    if purpose not in purposes:
        return "", f"the earlier run was a {purpose} run, which is not a result of the test itself"
    if job.get("freshness") != "fresh":
        return "", "the earlier run's evidence is not marked fresh"
    if instance_id not in (old.get("selected_instance_ids") or []):
        return "", "no earlier run selected this test"
    status = job.get("execution_status")
    if status not in {"passed", "failed"}:
        return "", f"the earlier run ended {status}, which is not a result"
    block = block_of(job) if block_of else None
    if status == "passed" and block is None:
        return "passed", ""
    if block is None or block is False:
        return "", "the earlier run's own record cannot be read, so it does not say how this test ended"
    row = next((r for r in (block.get("results") or [])
                if isinstance(r, dict) and r.get("instance_id") == instance_id), None)
    if row is None:
        return "", "the earlier run's own record has no row for this test"
    outcome = str(row.get("status") or "")
    if outcome not in {"passed", "failed"} or row.get("report_matched", True) is False:
        reason = str(row.get("reason") or "").strip()
        return "", (f"the earlier run's own record says this test was {outcome or 'not run'}"
                    + (f" ({reason})" if reason else "") + ": not a result")
    if outcome == "failed" and reset_at:
        reset, made = _when(reset_at), _when(job.get("created_at"))
        if reset is not None and made is not None and made < reset:
            return "", ("the stand was repaired after that failure (stand_health.py --reset): "
                        "a red recorded before it is not a result")
    return outcome, ""


def same_instance_bytes(now: dict, before: dict) -> bool:
    """One identity of "the same test bytes" (the BYTES RULE of t-016 Amendment 3, applied to
    runs), decided by `proof_level.compare_identity` (the one comparison, AR-13): both code shas present
    -> they decide (a different code is NOT the same even when the content sha is equal, E2); else the
    content sha decides; a hand-written request or a job recorded before `instance_code_sha` carries only
    the content one. "unknown" is False here; the two callers fold it on their own sides: `_match` (a false
    "same" reuses the result of other bytes - it lies) and `_same_identity_for_count` (the flaky cap: a request with
    no sha is counted by id there, the budget side). Accepted (F2): a classifier change moves the code sha,
    so earlier flaky reruns across such an update are not counted - the cap is exceeded at most once."""
    import proof_level
    return proof_level.compare_identity(now, before)[0] == "same"


def _match(job: dict, request: dict, instance_id: str, policy: dict, reset_at: str,
           block_of) -> tuple:
    """(outcome, why, rank): the result this job holds of `instance_id` OVER THE SAME INPUTS as
    `request`, or "" with the FIRST difference, in this order: not a result, selector, a shared
    component (by name), instance bytes, stand identity not observed."""
    outcome, why = _job_outcome(job, instance_id, set(policy["result_purposes"]), reset_at, block_of)
    if not outcome:
        return "", why, _WHY_RANK["result"]
    old = job.get("request") or {}
    ours = ((request.get("command") or {}).get("selector_args") or {}).get(instance_id)
    theirs = ((old.get("command") or {}).get("selector_args") or {}).get(instance_id)
    if ours is None or ours != theirs:
        return "", "the selector of the test differs from the earlier run's", _WHY_RANK["selector"]
    identical = bool(request.get("input_fingerprint")) and (
        old.get("input_fingerprint") == request.get("input_fingerprint"))
    if not identical:
        now, was = request.get("fingerprint_components") or {}, old.get("fingerprint_components") or {}
        for key in _SHARED_COMPONENTS:
            if now.get(key) != was.get(key):
                meaning = str((policy.get("shared_meaning") or {}).get(key) or "")
                return "", f"{key} changed" + (f" ({meaning})" if meaning else ""), _WHY_RANK["shared"]
        if policy.get("author_run_reading") != "per_story" and not same_instance_bytes(
                (request.get("instance_contracts") or {}).get(instance_id),
                (old.get("instance_contracts") or {}).get(instance_id)):
            return "", ("instance bytes differ: the test, or something it depends on, was edited "
                        "since the earlier run"), _WHY_RANK["bytes"]
    if request.get("runtime_observed") is False:
        return "", "the stand's version was not observed", _WHY_RANK["stand"]
    return outcome, "", 5


def covered(job: dict, request: dict, instance_id: str, *, policy=None, reset_at: str = "",
            block_of=None, failed_seen: int = 1) -> tuple:
    """`(bool, why)`: does the result in `job` cover `instance_id` of `request`?

    Covered = some result of the instance exists over the same inputs (the shared components
    unchanged, the same selector, the same instance bytes) and the stand's identity was observed
    now. `why` names the FIRST difference. A red result covers only as far as the policy says:
    `failed_seen` is how many failed results over these inputs are on record (`covering` counts
    them); a green one covers at once. `policy` is `load_run_budget()`'s; None is the rule as it
    stood before the budget."""
    policy = policy or _fallback_policy()
    outcome, why, _rank = _match(job, request, instance_id, policy, reset_at, block_of)
    if not outcome:
        return False, why
    if outcome == "failed":
        needed = int((policy.get("failed_result_policy") or {}).get("covers_after_failures") or 0)
        if not needed:
            return False, "a red never covers under this policy: it is run again"
        if failed_seen < needed:
            return False, (f"it failed over these same bytes ({failed_seen} of {needed} failed "
                           "results on record): one repeat is allowed")
    return True, ""


def covering(jobs: list, request: dict, instance_id: str, *, policy=None, reset_at: str = "",
             block_of=None) -> dict:
    """The answer for ONE instance over all of a story's jobs (`jobs` oldest first, as
    `JobStore.jobs()` gives them): `{"covered", "outcome", "jobs", "why"}`.

    The NEWEST result over the same inputs decides. A green one covers. A red one is counted with
    the reds right behind it (up to the last green over these inputs, which it supersedes) and
    covers only once the policy's number of them is on record (F4: one repeat of a red is
    allowed, the next is answered) - so a green that a later red follows is no longer the answer,
    and a red that a repeat turned green ends green. `why` is the most telling difference among
    the jobs that did run the instance."""
    policy = policy or _fallback_policy()
    matches, best = [], (-1, "no earlier run of this test is on record")
    for job in reversed(jobs):
        outcome, why, rank = _match(job, request, instance_id, policy, reset_at, block_of)
        if outcome:
            matches.append((outcome, job))
        elif rank > best[0] and not why.startswith("no earlier run selected"):
            best = (rank, why)
    if not matches:
        return {"covered": False, "outcome": "", "jobs": [], "why": best[1]}
    if matches[0][0] == "passed":
        return {"covered": True, "outcome": "passed", "jobs": [matches[0][1]], "why": ""}
    red = []
    for outcome, job in matches:
        if outcome != "failed":
            break
        red.append(job)
    needed = int((policy.get("failed_result_policy") or {}).get("covers_after_failures") or 0)
    if needed and len(red) >= needed:
        return {"covered": True, "outcome": "failed", "jobs": red[:needed], "why": ""}
    why = (f"it failed over these same bytes ({len(red)} of {needed} failed results on record): "
           "one repeat is allowed" if needed else "a red never covers under this policy: it is run again")
    return {"covered": False, "outcome": "", "jobs": [], "why": why}


def green_over_same_bytes(job: dict, fingerprint: dict, selector_args: dict,
                          contracts: dict, selected: list) -> bool:
    """Is exactly this run already recorded green?

    Until 0.7.9 the answer came from the whole-file `input_fingerprint`, so a one-line edit
    anywhere in a test file made every earlier run of every test in it "other bytes" — on
    TP1-15045 that alone re-ran seven tests twice. It is now the budget's one predicate,
    `covered`, asked of every selected instance with the rule as it stood before the budget
    (a green run of a non-probe purpose): the wrapper `--mine` falls back on when
    `run-budget.json` cannot be read."""
    request = {"input_fingerprint": fingerprint["input_fingerprint"],
               "fingerprint_components": fingerprint["fingerprint_components"],
               "command": {"selector_args": selector_args}, "instance_contracts": contracts}
    return (job.get("execution_status") == "passed" and bool(selected)
            and all(covered(job, request, instance)[0] for instance in selected))


def _request_view(fingerprint: dict, selector_args: dict, contracts: dict, runtime: dict) -> dict:
    """The parts of a request `covered` reads, before the request itself is built."""
    view = {"input_fingerprint": fingerprint["input_fingerprint"],
            "fingerprint_components": fingerprint["fingerprint_components"],
            "command": {"selector_args": selector_args}, "instance_contracts": contracts}
    if runtime.get("runtime_observed") is False:
        view["runtime_observed"] = False
    return view


def _classify_evidence(policy, budget_note, jobs, fingerprint, selector_args, contracts, runtime,
                       selected, project_root, notes) -> dict:
    """D0: `{"instances": {iid: {state, outcome, job_id, why}}, "observed": bool}`.

    `result` - some result of it stands over these bytes on this stand and version (`outcome`
    and `job_id` say which); `stale` - it ran, and the result does not stand (`why` names the
    first difference); `missing` - nothing on record ever ran it; `unknown` - the stand's
    version could not be looked at, so no earlier result can be trusted (FR-41: an unknown is
    never reported as a fact). No budget data means nothing is decided: `observed` is False."""
    if policy is None:
        return {"instances": {}, "observed": False, "why": budget_note}
    view = _request_view(fingerprint, selector_args, contracts, runtime)
    observed = runtime.get("runtime_observed") is not False
    reset_at, block_of = stand_reset_at(project_root), run_block_reader(project_root)
    instances = {}
    for instance in selected:
        verdict = covering(jobs, view, instance, policy=policy, reset_at=reset_at, block_of=block_of)
        if not observed:
            instances[instance] = {"state": "unknown", "outcome": "", "job_id": "",
                                   "why": "the stand's version was not observed"}
        elif verdict["covered"]:
            instances[instance] = {"state": "result", "outcome": verdict["outcome"],
                                   "job_id": str(verdict["jobs"][0].get("job_id") or ""), "why": ""}
        else:
            instances[instance] = {"state": "missing" if never_ran(jobs, instance) else "stale",
                                   "outcome": "", "job_id": "", "why": verdict["why"]}
    return {"instances": instances, "observed": observed}


def fresh_evidence(project_root, task: str, cases, *, cfg=None, probe=None, collect=None) -> dict:
    """What the story already holds of these cases, per instance, with no dispatch open (D0):
    `{"instances": {iid: {"state": "result"|"stale"|"missing"|"unknown", "outcome", "job_id",
    "why"}}, "observed": bool}`. It is `build_mine_request`'s own builder, asked for the
    classification instead of a request, so the rows, contracts, stand observation and
    fingerprints are the ones a `--mine` would use and each instance is classified by `covered`.
    Nothing is launched, written or claimed. A profile it cannot pick, a case the manifest does
    not know and the like raise `MineRefusal`, as `--mine` would; the caller decides."""
    found, _notes, _reusable, _verified = build_mine_request(
        project_root, list(cases), cfg=cfg, task=task, probe=probe, collect=collect, evidence_only=True)
    return found


def _date_of(job: dict) -> str:
    return str(job.get("updated_at") or job.get("created_at") or "")[:10]


def _job_ids(jobs) -> str:
    return ", ".join(str(j.get("job_id")) for j in jobs)


def _unique_jobs(per: dict) -> list:
    out, seen = [], set()
    for verdict in per.values():
        for job in verdict["jobs"]:
            if job.get("job_id") not in seen:
                seen.add(job.get("job_id"))
                out.append(job)
    return sorted(out, key=lambda j: str(j.get("updated_at") or j.get("created_at") or ""))


def budget_answer(policy: dict, per: dict, cases, stage: str, again: bool = False) -> dict:
    """The answer of a run that is already answered (F3): `reused` when every instance holds a
    green result, `already_run` when any holds a red one, the covering jobs, and the words.
    Nothing was launched and nothing is written; the answer is what a role reads instead."""
    greens = [i for i, v in per.items() if v["outcome"] == "passed"]
    reds = [i for i, v in per.items() if v["outcome"] == "failed"]
    jobs = _unique_jobs(per)
    newest = jobs[-1]
    parts = []
    if greens:
        green_jobs = _unique_jobs({i: per[i] for i in greens})
        parts.append(say(policy, "green", n=len(greens), date=_date_of(green_jobs[-1]),
                         jobs=_job_ids(green_jobs),
                         summary=", ".join(str(j.get("summary") or "(no summary recorded)")
                                           for j in green_jobs)))
    if reds:
        red_jobs = _unique_jobs({i: per[i] for i in reds})
        parts.append(say(policy, "red", tests=", ".join(reds[:4]) + (f" and {len(reds) - 4} more"
                                                                    if len(reds) > 4 else ""),
                         date=_date_of(red_jobs[-1]), case=",".join(str(c) for c in cases),
                         first=reds[0], stage=stage))
    if again:
        parts.append(say(policy, "again_note", stage=stage))
    return {"status": "already_run" if reds else "reused", "jobs": jobs, "job_id": newest.get("job_id"),
            "covered": {i: v["jobs"][0].get("job_id") for i, v in per.items()},
            "words": " ".join(parts), "hint": say(policy, "hint", stage=stage)}


def _newest_created(jobs) -> str:
    """The `created_at` of the newest of these jobs, or ""."""
    stamped = [(when, str(j.get("created_at") or "")) for j in jobs
               for when in [_when(j.get("created_at"))] if when is not None]
    return max(stamped)[1] if stamped else ""


def word_passes(word: dict, newest_result: str) -> bool:
    """Does a person's recorded word pass THIS repeat? It passes ONE: it must have been said
    after the newest result it repeats (a word older than that result was spent on it). A word
    with no time, or one that cannot be read as a time, stands as it always did."""
    if not word.get("decision"):
        return False
    said, made = _when(word.get("at")), _when(newest_result)
    return not (said is not None and made is not None and said <= made)


def request_verdict(request: dict, jobs: list, *, policy: dict, task_root: Path, active_stage: str,
                    reset_at: str = "", block_of=None, narrow: bool = False) -> dict:
    """What the budget says of a typed request BEFORE anything is begun or claimed (A5/A6):
    `{"action": "proceed", "notes": [...]}`, `{"action": "answer", "answer": {...}}` (every
    selected instance is answered), `{"action": "refuse", "message": ...}`, or - only when
    `narrow` is asked for (the scheduler, which owns its groups) - `{"action": "narrow", "run":
    [ids with no result], "answer": <the answer of the covered ones>}`. Not asked of a request
    `--mine` built: its answer, and the person's word, were settled there.

    A person's word passes each refusal here as it does everywhere (FR-4); the pass is returned
    in `notes` with the words. The word passes one repeat, never the series (A6, F1)."""
    notes: list = []
    purpose = str(request.get("purpose") or "")
    selected = [str(i) for i in request.get("selected_instance_ids") or []]
    proceed = {"action": "proceed", "notes": notes}
    if purpose not in BEHAVIORAL or not selected:
        return proceed
    if purpose == "flaky_diagnostic":
        return _flaky_verdict(request, jobs, selected, policy, task_root, active_stage, block_of, notes,
                              reset_at)
    if purpose in policy["exempt_purposes"]:
        return proceed
    per = {i: covering(jobs, request, i, policy=policy, reset_at=reset_at, block_of=block_of)
           for i in selected}
    done = [i for i in selected if per[i]["covered"]]
    if not done:
        return proceed
    stage = active_stage or "S5"
    shown = {i: per[i] for i in done}
    cases = (request.get("built_by") or {}).get("cases") or []
    answer = budget_answer(policy, shown, cases, stage)
    if len(done) == len(selected):
        message = answer["hint"]
    else:
        message = say(policy, "request_partial", covered=", ".join(done),
                      jobs=_job_ids(_unique_jobs(shown)), stage=stage)
    word = person_word(task_root, stage, message)
    if word_passes(word, _newest_created(_unique_jobs(shown))):
        notes.append(say(policy, "word_note", covered=", ".join(done), word=word["decision"]))
        return proceed
    if len(done) == len(selected):
        return {"action": "answer", "answer": answer, "notes": notes}
    if narrow:
        return {"action": "narrow", "run": [i for i in selected if i not in done], "answer": answer,
                "notes": notes}
    return {"action": "refuse", "message": message, "notes": notes}


def _flaky_verdict(request, jobs, selected, policy, task_root, active_stage, block_of, notes,
                   reset_at: str = "") -> dict:
    """A6: `flaky_diagnostic` is S7's, one failed test at a time, and at most
    `contract.FLAKY_MIN_RERUNS` isolated reruns of a test over its bytes (jobs with no result
    do not count). Each limit has the person's word as its door."""
    proceed = {"action": "proceed", "notes": notes}
    stage_asked = active_stage or policy["flaky_stage"]
    checks = []
    if active_stage != policy["flaky_stage"]:
        checks.append((say(policy, "flaky_stage", stage=active_stage or "no running stage",
                           stage_asked=stage_asked), ""))
    if len(selected) != 1:
        checks.append((say(policy, "flaky_one", n=len(selected), stage=stage_asked), ""))
    else:
        instance = selected[0]
        try:
            from contract import FLAKY_MIN_RERUNS as cap
        except Exception:
            cap = None
            notes.append("the FLAKY cap could not be read (contract.py); it is not enforced for this run")
        # The same identity as `_match`, not a second one (one predicate): a result over the same
        # whole input fingerprint or the same instance bytes counts. A request that carries no
        # shas at all (a hand-written or `--template request` one) cannot be told by bytes, so it
        # is counted by the instance id alone - the direction that protects the budget.
        earlier = [j for j in jobs
                   if _job_outcome(j, instance, {"flaky_diagnostic"}, reset_at, block_of)[0]
                   and _same_identity_for_count(request, j.get("request") or {}, instance)]
        if cap is not None and len(earlier) >= cap:
            checks.append((say(policy, "flaky_cap", n=len(earlier), test=instance,
                               jobs=_job_ids(earlier), stage=stage_asked), _newest_created(earlier)))
    for message, latest in checks:
        word = person_word(task_root, stage_asked, message)
        if not word_passes(word, latest):
            return {"action": "refuse", "message": message, "notes": notes}
        notes.append(say(policy, "flaky_word_note", word=word["decision"]))
    return proceed


def _same_identity_for_count(request: dict, old: dict, instance: str) -> bool:
    """`_match`'s identity for one instance (equal whole input fingerprint, or the same instance
    bytes), and - for a request with no shas of its own - the instance id."""
    if request.get("input_fingerprint") and old.get("input_fingerprint") == request["input_fingerprint"]:
        return True
    mine = (request.get("instance_contracts") or {}).get(instance) or {}
    if same_instance_bytes(mine, (old.get("instance_contracts") or {}).get(instance)):
        return True
    return not (mine.get("instance_content_sha") or mine.get("instance_code_sha"))


def strip_rerun_flags(argv, flags, regex_flags=()) -> tuple:
    """(argv without the pytest rerun flags, the flags removed as they were spelled):
    `--reruns N`, `--reruns=N`, `--reruns-delay N`, `--only-rerun X`.

    A count or a delay eats the token after it only when that token is a number (digits, one
    optional point): a test path or node id that follows a bare `--reruns` stays. A flag in
    `regex_flags` (`--only-rerun`) takes a regular expression, which can look like anything -
    `.*\\.py`, `Error`, `-x` - so it always eats the token after it."""
    tokens, out, removed, index = [str(a) for a in argv or []], [], [], 0
    while index < len(tokens):
        token = tokens[index]
        name = token.split("=", 1)[0]
        if name in flags:
            spelled = token
            follower = tokens[index + 1] if index + 1 < len(tokens) else ""
            if "=" not in token and follower and (
                    name in regex_flags or follower.replace(".", "", 1).isdigit()):
                spelled += " " + follower
                index += 1
            removed.append(spelled)
        else:
            out.append(token)
        index += 1
    return out, removed


# Most specific first: a job that failed to launch also carries `execution_status: broken_run`.
# `not_executed` is NOT in the list: run_suite gives a summary with no totals that status only
# when the process exited 0 ("it ran and produced nothing to report", a reporter-less profile) -
# that run may have run every test, so it stays a precedent.
_NEVER_RAN_STATES = ("failed_to_launch", "broken_run")


ARGV_SHOWN = 160


def _shown_argv(argv) -> str:
    """An argv as it reads in a note: at most ARGV_SHOWN characters, and a cut one ends in "..."
    so a reader knows there is more."""
    text = " ".join(str(a) for a in argv)
    return text if len(text) <= ARGV_SHOWN else text[:ARGV_SHOWN] + "..."


def _job_summary(job: dict, project_root: Path):
    """The summary file a job names (`job["summary"]`, relative to the project root or absolute), as read, or None when
    the job names none or the file is absent or unreadable. The one reader of it: `_never_ran_a_test`, `_memo_of_jobs`."""
    summary_ref = job.get("summary")
    if not isinstance(summary_ref, str) or not summary_ref.strip():
        return None
    try:
        path = Path(summary_ref)
        return json.loads((path if path.is_absolute() else Path(project_root) / path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _never_ran_a_test(job: dict, project_root: Path) -> str:
    """The state word (`failed_to_launch`, `broken_run`) when this job's OWN summary proves that
    no test ran, else "" - and "" is the answer to every doubt: the allowed error direction is to
    copy the precedent as before, never to refuse a run that worked before.

    What it guards against: a typed run that never got as far as running a test (a bare `pytest`
    the system interpreter rejected: exit 4, no junit, no totals) being copied as the story's
    command. A job record carries no totals: they are in the summary file the job names
    (`job["summary"]`, relative to the project root or absolute). A run that finished with
    totals - red, a collection error (`tests=1 errors=1`), zero collected - ran; a summary that
    is absent, unreadable or not a record, a summary carrying a `parse_gap` (the run was not
    readable, which is not the same as nothing ran), and a status this list does not name
    (`not_executed`, unknown, absent, still in flight) - read from the JOB's `status` /
    `execution_status`, which every finished job carries - leave the job a precedent exactly as
    before (stories in flight and old records are not changed)."""
    summary = _job_summary(job, project_root)
    if summary is None:
        return ""
    if (not isinstance(summary, dict) or isinstance(summary.get("totals"), dict)
            or "parse_gap" in summary):
        return ""
    states = {str(job.get("status") or ""), str(job.get("execution_status") or "")}
    return next((state for state in _NEVER_RAN_STATES if state in states), "")


def rehearsal_probe(spec: dict, accepts=ACCEPTS) -> dict:
    """THE rehearsal reader of a runtime probe (t-300 B1): the one function every caller that only LOOKS at the stand
    reads it with - gate A's identity read (`gate_preflight._observed_identity`), the S6 freshness read
    (`fresh_evidence`), the build check. It runs the probe's argv as a rehearsal (`runtime_probe.rehearsal_argv`:
    `--task-root` and `--no-evidence`, this script only) and takes the RAW record through
    `acceptable_provenance(..., rehearsal=True)`, which excuses exactly one rule - a matched record names an
    evidence file - and only for a record that says it was observed without one.

    It is NOT `run_suite.probe_runtime`, which stays strict (a `matched` with no evidence file raises there): the
    S5 run path, the post-run probe and the manual capture write evidence and need it. A refusal here is the same
    `RequestError` the strict reader raises, so a caller that treats "could not be looked at" as unobserved (FR-41)
    changes nothing. `spec["task_root"]` (an extra key the caller may add; the strict reader ignores it) names
    the story. A rehearsal argv is never stored anywhere: it exists for this one call.

    ONE set (t-300 N2 X4): the default is `profile_contract.ACCEPTS` - `matched`, a person's word, and a probe that
    compared nothing - the same tokens the run path takes, so what the stage ENTRY accepts the RUN accepts. A refusal is
    a `ProvenanceRefused` (what the probe said, what was expected, the door), a probe that failed says its own reason."""
    from runtime_probe import rehearsal_argv
    result = _node_ids.run_captured(rehearsal_argv(spec["argv"], spec.get("task_root")), spec["cwd"], None, spec["timeout_s"])
    value = probe_record(result)
    if acceptable_provenance(value, accepts, rehearsal=True):
        return value
    raise ProvenanceRefused(value)


def _stand_refusal(policy, exc, environment: str = "") -> str:
    """The sentence a role reads when the stand could not be taken for a run (t-300 N2 X9): a probe that proves the stand
    runs another build says THAT (`build_refused`: the stand's fact, the person's door at the build question); every
    other answer is "cannot be observed" with the refusal's own reason quoted (`not_observed`) - a refused `unknown` its
    sentence, a probe that raised `Type: message`. `policy` is the run budget, or None when `run-budget.json` is not
    readable: there is then no word table to say it with, and the refusal's own sentence stands (it already names the
    build and the door). `environment` falls back to the one the probe's record names."""
    record = getattr(exc, "record", None)
    environment = environment or (str(record.get("environment_id") or "") if isinstance(record, dict) else "") \
        or "<environment>"
    if isinstance(exc, ProvenanceRefused):
        said = str(exc)
        if stand_runs_other_build(record):
            return (say(policy, "build_refused", error=said, environment=environment)
                    if policy is not None and "build_refused" in policy.get("words", {}) else said)
    else:
        said = f"{type(exc).__name__}: {str(exc)[:160]}".strip()
    return said if policy is None else say(policy, "not_observed", error=said, environment=environment)


def _strict_probe(probe) -> bool:
    """Is this callable `run_suite.probe_runtime` - the reader that validates strictly and writes for a real run?"""
    return getattr(probe, "__name__", "") == "probe_runtime" and getattr(probe, "__module__", "") == "run_suite"


def registered_probe(cfg: dict, profile: str) -> dict | None:
    """The `execution.runtime_probes` entry of this profile (else of `*`) as THIS machine runs it:
    `{argv, cwd, timeout_s}`, or None when the project registered none. The config stores the
    PORTABLE argv (`{python}`, `{plugin_root}`; t-238 W5); the machine's own interpreter and plugin
    location are filled in here, at run time, and nothing else in the argv is touched - an argv
    written before that holds absolute paths and is executed as it stands (A20 reports it).
    `cwd` absent is the project root, as it always was: the probe finds the story from there."""
    probes = ((cfg.get("execution") or {}).get("runtime_probes") or {})
    spec = probes.get(profile) or probes.get("*") if isinstance(probes, dict) else None
    if not (isinstance(spec, dict) and spec.get("argv")):
        return None
    from runtime_probe import resolve_argv
    return {"argv": [str(a) for a in resolve_argv(spec["argv"])], "cwd": str(spec.get("cwd") or "."),
            "timeout_s": spec.get("timeout_s") or 30}


def reference_target_problem(project_root, task, environment) -> str:
    """C8 (t-2181 PC-9b, rewritten t-2277 W1, owner 11.11.2026): "" unless the story's own record contradicts itself. A run aimed at a
    reference stand of the story is NO LONGER refused: it goes, and its run block carries the mark `stand_identity.reference_run_mark`
    (a sample, never the story's evidence). What stays refused is the DATA CONTRADICTION: the story's own stand (`pipeline.environment`)
    is also named as the reference of a side, so the factory cannot tell which version a run there shows; the door is the record, never
    the same stand (FR-1, FR-2). Data only: the stands come from `stand_identity.reference_stands`, never from a word list. An empty
    `environment`, an unreadable record or a story that names no reference reads "" (see `reference_stands`: no refusal on a record
    nobody could read)."""
    name = str(environment or "").strip()
    if not name or not str(task or "").strip():
        return ""
    import stand_identity as SI
    side, own = SI.reference_side(project_root, str(task), name)      # the one reader (F3): the probe's skip reads the same answer
    if not side:
        return ""
    if own == name:
        # the record contradicts itself: the story's own stand is also named as the reference of `side`. The same stand is no door (FR-2);
        # the door is the record, which a person or `stage_done.py` corrects (FR-57)
        return (f"the story's record names the stand `{name}` both as its own stand (`pipeline.json` `environment`) and as the reference "
                f"(the OLD version) of the `{side}` side, so the factory cannot tell which version a run there would show. Door: correct the record - "
                f"`stage_done.py --task {task} --set sides.{side}.reference=<the stand that runs the old version>` (or clear it), or "
                "tell the conductor which stand runs the new version")
    return ""      # a reference stand that is not the story's own: the run goes and is recorded as a sample (`reference_run_mark`)


def stand_probe_spec(cfg: dict, profile: str, environment: str = "", story: str = "") -> tuple:
    """`(spec, why)`: the probe that identifies this profile's stand - the project's `execution.runtime_probes` entry when it
    has one (`registered_probe`, which wins: P4), else the default IN MEMORY, never written to the config (FR-45): the
    factory's own `runtime_probe.py` over the profile's checkout, with no container. `why` is "" with a spec, else the
    reason there is none, in words a person reads: no recorded checkout (`remedy_no_checkout`), two repositories or two
    stands that cannot be told apart (the refusal of `pick_checkout` / `pick_environment`, as it says it).
    DIRECTION OF ERROR (D-0021): the default can only ask more often, never pass more: its answer goes through the same
    `acceptable_provenance`, and without a container and without an entry a probe cannot say `matched`."""
    spec = registered_probe(cfg, profile)
    if spec is not None:
        return spec, ""
    import runtime_probe as rp
    none = say_refusal("remedy_no_checkout", profile=profile)
    if not rp.has_checkout(cfg, profile):
        return None, none
    where, refusal = rp.pick_checkout(cfg, profile, "")
    if refusal:
        return None, refusal       # the `Refusal` itself (a str): a person's line reads its `.plain` half, the role the whole
    # EP1-41c: a device row is not a stand of a web profile; PC-9b: a reference stand is not picked when nobody named a stand
    import stand_identity as SI
    stand, refusal = rp.pick_environment(cfg, environment, profile, () if environment else SI.reference_of_running_story(story))
    if refusal:
        return None, refusal
    if not str(where or "").strip():
        return None, none
    argv = [*rp.PORTABLE_HEAD, "--profile", profile, *(["--environment", stand] if stand else []), "--checkout", str(where),
            *(["--task", story] if story else [])]
    return {"argv": [str(a) for a in rp.resolve_argv(argv)], "cwd": ".", "timeout_s": 30, "derived": True}, ""


def ordinary_jobs(jobs: list, profile: str) -> list:
    """The ORDINARY behavioural jobs of this profile, newest first.

    A red-probe job is never in it: its request carries the absolute directory of a clone that
    is thrown away, and the probe after it inherited that path (legacy run TP2-2406), and
    a red probe is no precedent for the command, the fingerprint list or the profile choice.
    `build`/`collect`/`manual`/`quality` jobs are not behavioural."""
    return [j for j in reversed(jobs)
            if j["request"].get("purpose") in BEHAVIORAL
            and j["request"].get("purpose") != "red_probe"
            and j["request"].get("profile_id") == profile]


def ordinary_precedent(jobs: list, profile: str) -> dict | None:
    """The request of the latest ORDINARY behavioural job of this profile, else None
    (the first of `ordinary_jobs`)."""
    found = ordinary_jobs(jobs, profile)
    return found[0]["request"] if found else None


def attempt_identity(selector_args: dict, input_fingerprint: str, purpose: str, run_dir,
                     unobserved: bool = False) -> str:
    """The `what` of an attempt's idempotency key: the instances over the bytes.

    A run whose stand was not observed (`runtime_observed: false`) never lands on the key of an
    observed one: it carries the word "unobserved" in its material (upstream, F3). A red probe
    also hashes the directory it ran in: two clones of one tree hold the same selectors and (for
    a non-pytest runner, whose test file used to be looked up in the author's tree) could hold
    the same fingerprint, so two probes were one attempt. Every other purpose ignores the
    directory, and an observed run adds nothing, so an observed non-probe key is the one it always
    was - an old red-probe key never equals a new one, because the material differs."""
    material = [sorted(selector_args.items()), input_fingerprint]
    if unobserved:
        material.append("unobserved")
    if purpose == "red_probe":
        material.append(str(run_dir))
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:12]


def _sandbox_refusal(what: str, door: str) -> MineRefusal:
    return MineRefusal(f"{what}. {door}")


def sandbox_run_directory(project_root: Path, sandbox_root, profile_doc: dict,
                          precedent: dict | None) -> Path:
    """Where a run happens inside a clone: `sandbox_root / rel`, the profile's own directory kept.

    `rel` is, in order, the profile's `commands.one_test.cwd`; else the ordinary precedent's
    `command.cwd` when it is an absolute path inside the project root (a job on disk carries the
    resolved, absolute one); else `.`. Before this a probe run in a clone ran in the clone's
    root and lost the profile's subdirectory (`backend`), or inherited a clone that was gone."""
    project_root = Path(project_root).resolve()
    profile_name = str((profile_doc or {}).get("profile_id") or "this profile")
    # `cwd` through the ONE reader (AR-13); a profile whose commands cannot be read names no directory here - the run is
    # refused earlier, in `_command_from_profile`, with the shape problem, so the precedent branch below is unchanged
    one_test, _problem = profile_command(profile_doc, "one_test")
    named = str(one_test.get("cwd") or "")
    config_door = (f"Correct `commands.one_test.cwd` of profiles[{profile_name}] in qa-factory/config.json "
                   "(`/qa-factory:qa-onboarding` writes it)")
    rel = Path(".")
    if named:
        configured = Path(named)
        if configured.is_absolute():
            try:
                rel = configured.resolve().relative_to(project_root)
            except ValueError:
                raise _sandbox_refusal(f"the run directory {named} of profiles[{profile_name}] is outside "
                                       f"the project root {project_root}, so it has no place in a clone",
                                       config_door + " to a path inside the project") from None
        else:
            rel = Path(os.path.normpath(project_root / configured))
            try:
                rel = rel.relative_to(project_root)
            except ValueError:
                raise _sandbox_refusal(f"the run directory {named} of profiles[{profile_name}] escapes the "
                                       f"project root {project_root} through `..`",
                                       config_door + " to a path inside the project") from None
    else:
        prior = str(((precedent or {}).get("command") or {}).get("cwd") or "")
        if prior and Path(prior).is_absolute():
            try:
                rel = Path(prior).resolve().relative_to(project_root)
            except ValueError:
                rel = Path(".")  # the path of another tree or a clone gone since: not this project's
    sandbox = Path(sandbox_root)
    clone_door = ("`red_sandbox.py --probe` prepares a clone that holds it and passes --sandbox-root "
                  "itself; or name the one directory to run in with --cwd <directory>")
    if not sandbox.is_dir():
        raise _sandbox_refusal(f"the sandbox root {sandbox} is not a directory", clone_door)
    sandbox = sandbox.resolve()
    target = (sandbox / rel).resolve()
    if not target.is_relative_to(sandbox):
        raise _sandbox_refusal(f"the run directory {rel.as_posix()} resolves to {target}, which is not "
                               f"inside the sandbox {sandbox} (a link leads out of the clone)", clone_door)
    if not target.is_dir():
        raise _sandbox_refusal(f"the run directory {rel.as_posix()} is missing inside the sandbox "
                               f"{sandbox} ({target} does not exist)",
                               "The clone must hold the profile's directory: " + clone_door)
    return target


def _place_rows(rows: list, run_cwd: Path, project_root: Path) -> None:
    """Give every pytest row that has no `path` yet the test file it names, and spell its node relative to the run
    directory. A file nobody can find is refused (no process is run to learn it: this is a static refusal, and it
    comes before the stand and the collect). A row already placed is left alone, so the rows a bare-file
    fallback adds later are placed by the same call."""
    for row in rows:
        if "path" in row:
            continue
        file = row["node"].split("::")[0]
        path = next((p for p in (run_cwd / file, project_root / file) if p.is_file()), None)
        if path is None:
            raise MineRefusal(
                f"{row['case']}: the manifest names {file}, and no such file is under {run_cwd}. "
                "Correct `file` through manifest_put.py (a path relative to the project root), "
                "or pass --cwd when the test lives in a sandbox.")
        row["path"] = path.resolve()
        if row["path"].is_relative_to(run_cwd):
            row["node"] = row["path"].relative_to(run_cwd).as_posix() + row["node"][len(file):]


PROBE_DOOR_NAMES = 5     # containers named in the refusal: a big stand still leaves the role its door (B-2)


def _probe_gap(cfg: dict, profile: str) -> tuple:
    """`(unusable, others)`: `unusable` - this profile's key is PRESENT in `execution.runtime_probes` with a value the
    reader cannot use (no `argv`, or not an object); `others` - some profile has a usable entry (`*` included)."""
    probes = ((cfg.get("execution") or {}).get("runtime_probes") or {}) if isinstance(cfg, dict) else {}
    if not isinstance(probes, dict):
        return False, False
    own = probes.get(profile)
    return (bool(own) and not (isinstance(own, dict) and own.get("argv")),
            any(isinstance(v, dict) and v.get("argv") for v in probes.values()))


def _word(text: str) -> str:
    """A profile or container name as a shell word: bare when plain, double-quoted otherwise."""
    return text if text and all(c.isalnum() or c in "._-:" for c in text) else '"' + text.replace('"', "") + '"'


def _has_checkout(cfg: dict, profile: str) -> bool:
    """`runtime_probe.has_checkout`, with doubt read as "no": a door that writes a lasting entry is withheld, never guessed."""
    try:
        import runtime_probe
        return bool(runtime_probe.has_checkout(cfg, profile))
    except Exception:
        return False


def _narrowed_names(cfg: dict, profile: str, rows: list, task_root, project_root) -> list:
    """The names of the running containers `rows`, narrowed to those that hold the story's files when the story is known
    (the gate-A reader `runtime_probe.content_candidates`, ONE `docker exec` per container, only on this refusal path).
    No story, no diff on record, nothing of it in the checkout, a checkout that cannot be told, none holding the files
    (a built bundle) or ANY failure: all the names - the role chooses, the refusal never claims "none" from a filter."""
    names = [str(n) for n, _image in rows]
    if task_root is None or project_root is None or len(names) < 2:
        return names
    try:
        import runtime_probe as rp
        where, refusal = rp.pick_checkout(cfg, profile, "")
        if refusal or not str(where or "").strip():
            return names
        checkout = (Path(project_root) / where).resolve()
        files = rp.diff_files(Path(task_root))
        if not rp.compared_files(files, checkout):
            return names
        return [str(n) for n in rp.content_candidates(files, checkout, rp.APP_ROOT, rows, cfg=cfg)] or names
    except Exception:
        return names


def _probe_door(cfg: dict, profile: str, task_root=None, project_root=None) -> str:
    """The ready command that writes this profile's runtime probe, as the S5 refusal's first door (EP1-24 B1), or "".

    ONE container (after the story's files narrow the list, when `task_root` is known): the command names it. Two or
    more (at most PROBE_DOOR_NAMES named, then `(+N more)`): the command without `--container` and the names, so the role
    (or the person) says which one runs the application. None, or docker silent (`containers()` raising counts as
    silent): the command without `--container` and the words that the stand must be up. INVARIANT: building this text
    never raises and never changes the answer's class (the caller raises the same `MineRefusal` either way); a
    profile that already HAS an entry (usable or not: `--suggest --write` refuses to replace one without `--force`)
    gets no door, `--force` is never advised (the project's own entry wins, P4); a profile with no recorded checkout
    gets none either - gate A refuses to derive a probe there, and the entry would compare the wrong tree."""
    if registered_probe(cfg, profile) is not None or _probe_gap(cfg, profile)[0] or not _has_checkout(cfg, profile):
        return ""
    command = f'python "${{CLAUDE_PLUGIN_ROOT}}/scripts/runtime_probe.py" --suggest --write --profile {_word(profile)}'
    try:
        import runtime_probe
        running = _narrowed_names(cfg, profile, list(runtime_probe.containers()), task_root, project_root)
    except Exception:       # the refusal is the answer; a docker that failed is only a door without a name
        running = []
    if not running:
        return (f"Register the probe with `{command}` (the stand must be up: if docker names no running container, bring "
                f"the stand up first, or add --no-container if the application does not run in one: `{command} --no-container`).")
    if len(running) == 1:
        return f"Register the probe with `{command} --container {_word(running[0])}`."
    shown = ", ".join(running[:PROBE_DOOR_NAMES]) + (f" (+{len(running) - PROBE_DOOR_NAMES} more)"
                                                     if len(running) > PROBE_DOOR_NAMES else "")
    return (f"Several containers could be the stand ({shown}): say which one runs the application under test, then register "
            f"the probe with `{command} --container <name>`.")


def _probe_refusal(cfg: dict, profile: str, spec, evidence_only: bool, task_root=None, project_root=None) -> str:
    """The text of the S5 refusal for a first typed run with no way to identify the stand (EP1-24 B1, B-10, F1, F5).

    Opening words and tail as ever (`--template request` is always a door); between them, what is missing in words
    (no entry / no entry for THIS profile while others have one / an entry with no `argv` / no way to look at the stand),
    then ONE door when there is one: the write command (`_probe_door`) - and when there is none for a reason the role
    can act on (no recorded checkout), that reason. A freshness read (`evidence_only`) is not a "no probe" and gets
    neither (B-4)."""
    unusable, others = _probe_gap(cfg, profile)
    if spec is not None:
        missing = "this run was given no way to look at the stand"
    elif unusable:
        missing = (f"the `execution.runtime_probes` entry for profile {profile} in qa-factory/config.json has no `argv`, so it "
                   "cannot identify the stand (the factory does not rewrite a project's own entry)")
    else:
        missing = ("no `execution.runtime_probes` entry in qa-factory/config.json" + (f" for profile {profile}" if others else ""))
    door = "" if evidence_only else _probe_door(cfg, profile, task_root, project_root)
    none_why = ""
    if not (evidence_only or door or spec is not None or unusable):
        none_why = (f"No probe can be registered for profile {profile} from here: qa-factory/config.json records no checkout "
                    "for it (`implementation_repos[].local_path`), so there is no code to compare the stand with.")
    return ("this is the story's first typed run on profile " + profile + ", and the factory does not know how to identify "
            "what the stand runs: there is no earlier request to copy the runtime probe from, and " + missing
            + ". That is the factory's gap, not your test's. "
            + (door + " Or write" if door else (none_why + " Write" if none_why else "Write"))
            + " this one request from `run_suite.py --template request`; every later `--mine` copies its probe and provenance.")


def _observe_stand(cfg: dict, profile: str, policy, purpose: str, probe, probe_extra: dict, project_root: Path,
                   runtime_precedent, evidence_only: bool, notes: list, task_root=None) -> dict:
    """The stand block of a request: `{runtime_required, runtime_probe, runtime_provenance, ...}`, looked at NOW.

    It runs BEFORE the collect (HF2-10): a refusal that does not depend on the collect ("no `runtime_probes` entry
    and no earlier request to copy from", a stand the probe refuses) must not wait for ~100 s of collect first, and
    the one probe the build takes is the one the run reuses (`run_suite --mine` carries it to the `--request`
    check). Invariant: every input refused here before is refused here now, with the same class and opening words;
    only the place in the build moved, and (EP1-24) the S5 refusal's tail now carries the probe's write door.
    `task_root` is the story's folder: with it the refusal's door can narrow the containers by the story's files."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if runtime_precedent:
        runtime = {k: runtime_precedent[k] for k in ("runtime_required", "target_kind", "runtime_probe")
                   if k in runtime_precedent}
        runtime["runtime_provenance"] = dict(runtime_precedent.get("runtime_provenance") or {},
                                             timestamp=now)
        # B-150: an earlier result is worth what the stand ran when it was recorded. The stand
        # is looked at NOW, and the request carries what was seen - so a redeploy makes a new
        # run (its `runtime_sha` moves) instead of an `invalid_request` at the launch check, and a
        # stand nobody could look at is never reported as unchanged (FR-41). A red probe runs in
        # a sandbox by definition and keeps copying (its own gate is the launch check).
        if policy is not None and purpose != "red_probe" and runtime.get("runtime_required", True) is not False:
            old_probe = runtime.get("runtime_probe")
            if probe is None or not isinstance(old_probe, dict) or not old_probe.get("argv"):
                runtime["runtime_observed"] = False
            else:
                old_view = runtime["runtime_provenance"]
                probe_cwd = Path(str(old_probe.get("cwd") or "."))
                try:
                    seen = probe({**old_probe, "cwd": str(probe_cwd if probe_cwd.is_absolute()
                                                          else project_root / probe_cwd), **probe_extra})
                except Exception as exc:  # a stand that cannot be looked at: the stand's gap, not the test's
                    unseen = _stand_refusal(policy, exc, str(old_view.get("environment_id") or "<environment>"))
                    if not evidence_only:
                        raise MineRefusal(unseen) from exc
                    notes.append(unseen)  # a question about evidence, not a run: unknown, said as such
                    runtime["runtime_observed"] = False
                    seen = None
                if seen is not None:
                    moved = (seen.get("observed_runtime_identity") != old_view.get("observed_runtime_identity")
                             or seen.get("expected_source_revision") != old_view.get("expected_source_revision")
                             or (seen.get("provenance") or {}).get("deployed_source_revision")
                             != (old_view.get("provenance") or {}).get("deployed_source_revision"))
                    if moved:
                        notes.append(say(policy, "redeploy_note",
                                         identity=str(seen.get("observed_runtime_identity") or "")[:24],
                                         source=str(seen.get("expected_source_revision") or "")[:12],
                                         old=str(old_view.get("observed_runtime_identity") or "")[:24]))
                    runtime["runtime_provenance"] = dict(seen, timestamp=now)
        return runtime
    spec = registered_probe(cfg, profile)
    if not (spec is not None and probe is not None):
        raise MineRefusal(_probe_refusal(cfg, profile, spec, evidence_only, task_root, project_root))
    probe_cwd = Path(spec["cwd"])
    try:
        observed = probe({**spec, "cwd": str(probe_cwd if probe_cwd.is_absolute()
                                             else project_root / probe_cwd), **probe_extra})
    except ProvenanceRefused as exc:
        # t-300 N2: the probe ANSWERED and the answer is refused (a build that is not the story's, `unknown`, a word
        # that does not hold): the stand's refusal said as that, never `mine_unavailable` with a `--template request`
        # door (the factory did not fail to build the request; the stand is not ready). A freshness read
        # (`evidence_only`) keeps today's raise: its caller answers "not decided" (K33, FR-41).
        if evidence_only:
            raise
        raise MineRefusal(_stand_refusal(policy, exc)) from exc
    if task_root and not evidence_only:
        # C8 (PC-9b, t-2277 W1): the contradiction is refused HERE, before the collect and before a request file is written; a `--mine` aimed at a
        # reference stand goes on (a sample)
        reference = reference_target_problem(project_root, Path(task_root).name, (observed or {}).get("environment_id"))
        if reference:
            raise MineRefusal(reference)
    return {"runtime_required": True, "runtime_probe": spec, "runtime_provenance": observed}


# What pytest reads besides the code of the tests when it collects: the files that name its configuration.
_MEMO_CONFIG_NAMES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "tox.ini", "setup.cfg",
                      "pyproject.toml", "conftest.py")
_MEMO_IMPORT_CAP = 300  # files followed through imports; more is "not computed", never a partial key


def _collect_memo_key(argv, run_cwd, test_files, helpers, dependency_paths, config_files, provenance,
                      project_root=None) -> str:
    """The key under which the list a collect gave is remembered (EP1-23 B2): a sha256, or "" - "not computed",
    and "" is the answer to every doubt, so the caller collects for real (AR-28).

    What a collect answers - which ids exist, what a function with no parameters expands to, how the report spells a
    name - depends on everything below and on nothing else that an edit of a test BODY touches:
    the argv, the run directory, the `PYTEST_*` environment, the SKELETON of every test file (its syntax tree with the
    body of each `test*` function emptied: decorators, signatures, helpers and the module level stay whole), the raw
    bytes of the conftest chain (`helpers`), of the configuration and dependency files and of the project modules
    the test files, the conftests and those modules import (one closure), and the stand's identity (`provenance` is
    the stand block `_observe_stand` returned; a stand that was not observed, or an unread identity of a stand
    that is required, gives ""). Allowed error: a key that moves for no reason (one collect more). Never allowed: a
    key that stays when the collect would answer otherwise, so a `parametrize` whose values are not a literal (a
    call, a name, a comprehension), a `pytest_generate_tests`, a file that cannot be read or parsed all give ""
    - the values may come from the stand. Never raises.

    The error direction is one way (F-2): the key is used only when it proves the collect would answer the same, so
    anything it cannot read gives "": see `_tree_blind_spot`, `_argv_blind`, `_config_blind`."""
    try:
        if not (isinstance(argv, list) and argv and test_files):
            return ""
        runtime = provenance if isinstance(provenance, dict) else {}
        identity = str((runtime.get("runtime_provenance") or {}).get("observed_runtime_identity") or "")
        if runtime.get("runtime_observed") is False or (runtime.get("runtime_required", True) is not False
                                                       and not identity):
            return ""
        if _argv_blind(argv) or _config_blind(config_files):
            return ""
        roots = [Path(run_cwd).resolve()] + ([Path(project_root).resolve()] if project_root else [])
        closure = _memo_closure(test_files, [str(p) for p in list(helpers) + list(dependency_paths) + list(config_files)],
                                roots)
        if closure is None or any(_tree_blind_spot(tree) for tree in closure[0].values()):
            return ""
        trees, whole, test_paths = closure
        referenced = _referenced_names(trees.values())
        tests = {p: _skeleton_digest(trees[p], referenced) for p in test_paths}
        material = {"v": 2, "argv": [str(a) for a in argv], "cwd": str(Path(run_cwd).resolve()),
                    "env": {k: v for k, v in sorted(os.environ.items()) if k.startswith("PYTEST_")},
                    "identity": identity, "tests": tests, "files": whole}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()
    except Exception:  # unreadable, unparsable, anything this cannot place: not computed, so collected for real
        return ""


# Collection hooks: a conftest or plugin that has one decides what is collected by code the key does not read.
_COLLECTION_HOOKS = ("pytest_generate_tests", "pytest_collect", "pytest_pycollect", "pytest_ignore_collect",
                     "pytest_make_collect", "pytest_deselected", "pytest_itemcollected", "pytest_load_initial_conftests",
                     "pytest_cmdline")


def _argv_blind(argv) -> bool:
    """True when the argv names a file or module a collect reads and the key does not hash: a plugin (`-p x`,
    `-px`; `no:...` only switches one off), a `-c` / `--config-file`, `--pyargs`."""
    tokens = [str(a) for a in argv]
    for i, token in enumerate(tokens):
        if token in ("-c", "--pyargs") or token.startswith("--config-file"):
            return True
        if token == "-p" and not (i + 1 < len(tokens) and tokens[i + 1].startswith("no:")):
            return True
        if token.startswith("-p") and token != "-p" and not token[2:].startswith("no:"):
            return True
    return False


def _config_blind(config_files) -> bool:
    """True when a configuration file sets `pythonpath`: the modules the tests import then live where the key does not
    look (`src` layouts). A named gap: that project's collect is never remembered."""
    for path in config_files:
        if Path(path).suffix != ".py" and "pythonpath" in Path(path).read_text(encoding="utf-8").lower():
            return True
    return False


def _literal(node) -> bool:
    import ast
    try:
        ast.literal_eval(node)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def _call_blind(call) -> bool:
    """A call that sets what a collect expands, with values that are not a literal: `parametrize` (names, values,
    `ids`, `indirect`, `scope`), a fixture's `params` / `ids`, any call's `params=` / `ids=`, a `**` spread into either."""
    name = getattr(call.func, "attr", "") or getattr(call.func, "id", "")
    if name in ("parametrize", "fixture", "yield_fixture") and any(k.arg is None for k in call.keywords):
        return True
    if any(k.arg in ("params", "ids", "argvalues", "argnames") and not _literal(k.value) for k in call.keywords):
        return True
    if name != "parametrize":
        return False
    has_values = len(call.args) > 1 or any(k.arg == "argvalues" for k in call.keywords)
    return not has_values or not all(_literal(a) for a in call.args)


def _tree_blind_spot(tree) -> bool:
    """True when this module has something a collect answers by and the key does not read (F-2): a collection hook,
    `pytest_plugins`, `sys.path` or a dynamic import, `parametrize` / `fixture` under another name (an alias, a string),
    values or `ids` that are not a literal. The caller gives "" for the whole closure on one such module."""
    import ast
    nodes = list(ast.walk(tree))
    called = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    decorators = {id(d) for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  for d in n.decorator_list}
    for n in nodes:
        word = n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else ""
        if word in ("pytest_plugins", "__import__", "import_module") or word.startswith(_COLLECTION_HOOKS):
            return True
        if isinstance(n, ast.Attribute) and n.attr == "path" and getattr(n.value, "id", "") == "sys":
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith(_COLLECTION_HOOKS):
            return True
        if isinstance(n, ast.Constant) and n.value in ("parametrize", "pytest_plugins", "fixture"):
            return True  # the word as a string: getattr(pytest.mark, "parametrize")
        if isinstance(n, ast.alias) and n.asname and n.name in ("parametrize", "fixture"):
            return True
        if isinstance(n, ast.Call) and _call_blind(n):
            return True
        # an alias: `P = pytest.mark.parametrize` is neither called nor (for a fixture) a bare decorator
        if word == "parametrize" and id(n) not in called:
            return True
        if word in ("fixture", "yield_fixture") and id(n) not in called and id(n) not in decorators:
            return True
    return False


def _memo_closure(test_files, seeds: list, roots: list):
    """`(trees, whole, test_paths)` or None. `trees`: the syntax tree of every Python file read (the test files and the
    closure); `whole`: sha256 of the raw bytes of every file followed besides the test files (conftests, configuration,
    dependency files, imported project modules, the `__init__.py` on the way); None for more than _MEMO_IMPORT_CAP
    files: "not computed", never a partial key."""
    import ast
    trees, whole = {}, {}
    test_paths = [str(Path(p).resolve()) for p in test_files]
    queue = list(seeds)
    for path in test_paths:
        trees[path] = ast.parse(Path(path).read_bytes().decode("utf-8"))
        queue.extend(_project_imports(trees[path], Path(path), roots))
        queue.extend(str(d / "__init__.py") for d in _bases_of(Path(path), roots) if (d / "__init__.py").is_file())
    seen = set(test_paths)
    while queue:
        path = Path(queue.pop(0)).resolve()
        if str(path) in seen:
            continue
        seen.add(str(path))
        data = path.read_bytes()
        whole[str(path)] = hashlib.sha256(data).hexdigest()
        if len(whole) > _MEMO_IMPORT_CAP:
            return None
        if path.suffix == ".py":
            trees[str(path)] = ast.parse(data.decode("utf-8"))
            queue.extend(_project_imports(trees[str(path)], path, roots))
    return trees, whole, test_paths


def _referenced_names(trees) -> set:
    """Every name any module of the closure uses or imports: a `test*` function that is referenced is a helper (its body
    can feed a `params=`), not a test whose body is free to change."""
    import ast
    names: set = set()
    for tree in trees:
        for n in ast.walk(tree):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.alias):
                names.add(n.name.split(".")[-1])
    return names


def _mentions_fixture(node) -> bool:
    import ast
    return any((isinstance(n, ast.Name) and "fixture" in n.id) or (isinstance(n, ast.Attribute) and "fixture" in n.attr)
               for n in ast.walk(node))


def _skeleton_digest(tree, referenced: set) -> str:
    """sha256 of the tree of a test file with the body of each `test*` function emptied - unless it is a fixture or is
    referenced anywhere in the closure (`params=testdata()`): decorators, signatures, helpers and the module level
    stay whole. Mutates `tree`."""
    import ast

    class Skeleton(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if (node.name.startswith("test") and node.name not in referenced
                    and not any(_mentions_fixture(d) for d in node.decorator_list)):
                node.body = [ast.Pass()]
            return node  # a helper is kept whole and is not entered: a test defined in it is not collected

        visit_AsyncFunctionDef = visit_FunctionDef
    return hashlib.sha256(ast.dump(Skeleton().visit(tree)).encode("utf-8")).hexdigest()


def _bases_of(owner: Path, roots: list) -> list:
    """The directories from the file's own up to the run directory or the project root."""
    return [d for d in (owner.parent, *owner.parent.parents)
            if any(d == root or d.is_relative_to(root) for root in roots)]


def _project_imports(tree, owner: Path, roots: list) -> list:
    """The project files a module imports, as paths that exist: `import a.b`, `from a.b import c` (a module or a name),
    and a relative import from the importing file's own directory; with the `__init__.py` of every package on the
    dotted way. Searched under the directories from the file's
    own up to the run directory or the project root, and under those two; a name that matches no file is a
    third-party package or the standard library, left to the dependency files. Over-reading is the allowed error."""
    import ast
    bases = _bases_of(owner, roots)
    bases.extend(roots)
    found = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [(module, node.level)] + [((module + "." if module else "") + alias.name, node.level)
                                              for alias in node.names]
        for dotted, level in names:
            parts = [p for p in dotted.split(".") if p]
            where = bases
            if level:
                base = owner.parent
                for _ in range(level - 1):
                    base = base.parent
                where = [base]
            for base in where:
                candidates = [base.joinpath(*parts[:k]) / "__init__.py" for k in range(1, len(parts) + 1)] or [
                    base / "__init__.py"]
                if parts:
                    candidates.append(base.joinpath(*parts).with_suffix(".py"))
                for candidate in candidates:
                    if candidate.is_file() and str(candidate) not in found:
                        found.append(str(candidate))
    return found


def _memo_of_jobs(jobs: list, key: str, project_root: Path):
    """`(job id, ids)` of the collect remembered under `key`, or None. The NEWEST ordinary job (never a red probe) that
    carries `request.collect_memo.key == key` decides, and only it: when it proves that no test ran - `_never_ran_a_test`,
    or a summary that says `blocked: node_id_mismatch`, pytest's own "not found" on a list that went stale - there is
    no answer, so the next launch collects for real and writes a memo of its own: stale, `not found`, stale again is
    not reachable (AR-28). An old record with no `collect_memo`, an empty key and an empty or malformed list: None."""
    if not key:
        return None
    for job in reversed(jobs):
        request = job.get("request") if isinstance(job, dict) else None
        if not isinstance(request, dict) or request.get("purpose") == "red_probe":
            continue
        memo = request.get("collect_memo")
        if not (isinstance(memo, dict) and memo.get("key") == key):
            continue
        ids = memo.get("ids")
        if not (isinstance(ids, list) and ids and all(isinstance(i, str) and i for i in ids)):
            return None
        if _never_ran_a_test(job, project_root):
            return None
        summary = _job_summary(job, project_root)
        if summary is not None:
            try:
                from run_suite import NODE_ID_BLOCK  # the one spelling of the word; lazy: run_suite imports this module
            except Exception:
                return None  # the word cannot be read: the memo is not trusted
            if isinstance(summary, dict) and summary.get("blocked") == NODE_ID_BLOCK:
                return None
        return str(job.get("job_id") or "<unknown job>"), list(ids)
    return None


def _memo_key_of_rows(rows: list, command: dict, run_cwd: Path, project_root: Path, cfg, runtime: dict) -> str:
    """The `_collect_memo_key` of the test files the rows name, with the conftest chain and the configuration files
    on their way up to the project root (or the run directory)."""
    placed = list(dict.fromkeys(str(row["path"]) for row in rows))
    configs = sorted({str(base / name) for path in placed for base in (Path(path).parent, *Path(path).parent.parents)
                      if base == project_root or base.is_relative_to(project_root) or base.is_relative_to(run_cwd)
                      for name in _MEMO_CONFIG_NAMES if (base / name).is_file()})
    return _collect_memo_key(list(command["argv"]), run_cwd, placed, _conftest_chain(placed, run_cwd),
                             dependency_files(run_cwd, cfg)[0], configs, runtime, project_root=project_root)


def _play_back_memo(rows: list, command: dict, run_cwd: Path, jobs: list, memo_key: str, project_root: Path,
                    notes: list) -> tuple:
    """`(rows, verified, collect_memo)`: the list an earlier job kept under `memo_key` played back through the one
    `_spell_as_collected`. A miss (no job, a stale list, a row the list does not hold) returns the rows untouched,
    `False`, None: the real collect then runs over them as they were."""
    known = _memo_of_jobs(jobs, memo_key, project_root)
    if known is None:
        return rows, False, None
    scratch: list = []
    played, hit = _spell_as_collected(list(rows), command, run_cwd, lambda *_: list(known[1]), scratch)
    if not hit:
        return rows, False, None
    notes.extend(scratch)
    notes.append(f"node ids are those of the collect of job {known[0]} over the same inputs; --again collects afresh")
    return played, True, {"key": memo_key, "ids": list(known[1])}


def build_mine_request(project_root: Path, cases: list, *, cfg: dict | None = None, task: str = "",
                       dispatch_id: str = "", purpose: str = "", profile_id: str = "",
                       cwd: str = "", sandbox_root: str = "", node_ids: list | None = None,
                       again: bool = False, reason: str = "", probe=None, collect=None,
                       evidence_only: bool = False, profile_door: bool = True, s6_close: bool = False) -> tuple:
    """(request, notes, reusable answer or None, node ids verified) for the active dispatch.
    `reusable` is `{"status": "reused"|"already_run", "jobs": [...], ...}` when every selected
    instance already holds a result over these bytes (see `budget_answer`): the caller prints it
    and launches nothing. `probe(spec) -> provenance` and `collect(argv, cwd, files) ->
    [node ids]` are injected by the runner; both are optional (no probe: the stand is not
    observed, and nothing is reused - `runtime_observed: false`).

    The fourth element is `True` only when a PARSED collect found every id (`_spell_as_collected`): nothing checks
    the ids again. `False` is "not proven" and says nothing else - an unreadable, empty or timed-out collect, an id
    missing from the list, or an explicit `--node-id` without parameters, which is never collected (the run answers
    for it). The order of the work is: the refusals that need no process, the stand, the collect, whatever reads the
    collect (HF2-10).

    `evidence_only` is `fresh_evidence`'s way in (D0): the same rows, contracts, stand and
    fingerprints, with no open dispatch, and the first element returned is the classification of
    each instance instead of a request - one builder, so what S6 reads as "has a result" is
    exactly what `--mine` would answer.

    `s6_close` is the code close of S6 (HF3-6): the dispatch is the stand-in `s6_close_dispatch` builds from the story's
    own state, allowed only where the controller would take the S6 code-only receipt, and only for a red probe;
    `dispatch_id`, `evidence_only` and a purpose other than `red_probe` are refused with it.

    `cwd` is the directory a run happens in, taken as given; `sandbox_root` is the root of a clone,
    and the run directory is worked out inside it (the two together are refused).

    `profile_door` says whether the caller accepts `--profile ID` (`run_suite --mine` does; `probe_by_code`, which
    has no such flag, passes False): the profile refusal names only a door its receiver can use (FR-2)."""
    from hooklib import artifact_root as _artifact_root, is_story_folder
    project_root = Path(project_root).resolve()
    cfg = cfg if isinstance(cfg, dict) else {}
    cases = [str(c).strip() for c in cases if str(c).strip()]
    if not cases:
        # The id is spelled in the project's own form (`case_id_form`), never as a `TC-` literal:
        # a project whose cases are `TP1-13797_TC_001` was told to type an id nothing accepts.
        import case_forms
        raise MineRefusal("--mine needs at least one case id: --mine "
                          + case_forms.example(task, cfg, 1) + "[," + case_forms.example(task, cfg, 2) + "]")
    if purpose and purpose not in MINE_PURPOSES:
        raise MineRefusal(f"--purpose is one of {', '.join(MINE_PURPOSES)}; any other purpose is "
                          "not the ordinary run and goes through --request (--template request)")
    if s6_close:
        # The S6 close context (HF3-6) is a different CALL from "the dispatch's run": a call that names a dispatch or
        # a freshness read, or that asks for anything but the red probe, is a wrong call (no result of the product
        # ever enters the history without a dispatch), refused before anything is read.
        if dispatch_id or evidence_only:
            raise MineRefusal("the S6 close context takes no dispatch id and is not a freshness read: `s6_close` "
                              "excludes `dispatch_id` and `evidence_only`; name one context")
        if purpose != "red_probe":
            raise MineRefusal("the S6 close context builds only a red probe; a run of tests belongs to a dispatch")
        if not task:
            raise MineRefusal("the S6 close context is asked of one story: name its task id")
    notes: list = []
    policy, budget_note = load_run_budget()
    if policy is None:
        notes.append(budget_note)
    if s6_close:
        if not is_story_folder(_artifact_root(root=project_root), task):
            raise MineRefusal(f"the S6 close context is asked of the story '{task}', which names no story folder under "
                              f"{_artifact_root(root=project_root)}; nothing was run or recorded. Name the task id of "
                              "a story that exists")
        # read afresh, never taken from the caller, and ONCE: the context's id and the request's revision come from the
        # same reading (A-K7)
        state_read = _read_json(_artifact_root(root=project_root) / task / "state" / "controller.json")
        dispatch = s6_close_from_state(_artifact_root(root=project_root) / task, state_read, cases)
        controller = state_read
    elif evidence_only:
        if not task:
            raise MineRefusal("fresh evidence is asked of one story: name its task id")
        if not is_story_folder(_artifact_root(root=project_root), task):
            raise MineRefusal(f"fresh evidence is asked of the story '{task}', which names no story folder under "
                              f"{_artifact_root(root=project_root)}; nothing was run or recorded. Name the task id of "
                              "a story that exists")
        controller = _read_json(_artifact_root(root=project_root) / task / "state" / "controller.json") or {}
        dispatch = {"id": "fresh-evidence", "stage": "S6", "scope": list(cases), "budget": {}}
    else:
        task, controller, dispatch = find_active_dispatch(_artifact_root(root=project_root), task,
                                                          dispatch_id, cases, notes)
    task_root = _artifact_root(root=project_root) / task
    # `evidence_only` only LOOKS at the stand (D0): the strict reader the runner injects (`run_suite.probe_runtime`)
    # would raise on a `matched` printed under `--no-evidence` and lose t-043 D1, and it would write evidence on a
    # read (FR-45). The rehearsal reader takes its place - and the story, so the probe never falls back to the newest
    # pipeline of the project. A custom callable a caller injects is honoured as given.
    probe_extra = {}
    if evidence_only:
        probe_extra = {"task_root": str(task_root)}
        if _strict_probe(probe):
            probe = rehearsal_probe
    scope = [str(s) for s in dispatch.get("scope") or []]
    outside = [c for c in cases if c not in scope]
    # read ONCE, above the scope check: the admission of a stale re-probe needs the rows, and the run reuses them
    manifest = (_read_json(task_root / "work" / "automation-manifest.json")
                or _read_json(task_root / "automation-manifest.json") or {})
    if outside:
        stage = str(dispatch.get("stage") or "S5")
        # BEFORE the person's word: a stale live check of the critic's window is admitted by code (nothing is
        # written or launched before this decision); a test with no receipt stays the orchestrator's or a person's
        admitted, iids = _admitted_outside(outside, cases, node_ids, manifest, task_root, dispatch, purpose,
                                           evidence_only)
        if admitted:
            notes.append(f"{', '.join(outside)} is outside the scope of {dispatch.get('id')}; admitted as a "
                         f"re-probe of a live check that went stale ({', '.join(iids)}); its review is not "
                         "re-checked here")
            scope = scope + outside
        else:
            message = scope_refusal(outside, dispatch.get("id"), scope, stage)
            word = person_passed(task_root, stage, message)
            if not word:
                raise MineRefusal(message)
            notes.append(f"{', '.join(outside)} is {SCOPE_BLOCK} of {dispatch.get('id')}; passed on a "
                         f"person's word: {word}")
            scope = scope + outside

    jobs = JobStore(task_root / "state" / "execution-jobs").jobs()

    # -- what to run ---------------------------------------------------------------------
    rows, bare_files = [], {}
    for case in cases:
        found, files = manifest_rows(manifest, case, strict=True, notes=notes, store_root=task_root)
        for row in found:
            row["case"] = case
        rows.extend(found)
        if not found:
            bare_files[case] = files
    if node_ids:
        if len(cases) != 1:
            raise MineRefusal("--node-id names the tests of ONE case; pass one case with it")
        # The rows are replaced by the ids asked for, but the PROFILE the manifest rows of the same case and file
        # name travels with each id (and nothing else of the row: its instance name, spelling and contract stay
        # the ids', F-A1): without it a root two profiles share refuses a test the row had already placed (EP1-16).
        # The one reader of the row's profile is `entry_profile_id`; the writer is manifest_put.
        asked = [str(n).replace("\\", "/") for n in node_ids]
        by_file = {n.split("::")[0]: _row_profile_of_file(rows, n.split("::")[0]) for n in asked}
        rows = [{"instance_id": _instance_name(n.split("::", 1)[-1]), "case": cases[0], "node": n,
                 "entry": {"profile_id": by_file[n.split("::")[0]]} if by_file[n.split("::")[0]] else {},
                 "report_test_id": ""} for n in asked]
        bare_files = {}
    # A case with no row and no file is refused HERE, before the profile is chosen: with several
    # profiles `_profile_for` would otherwise refuse "cannot tell which profile" for a case that has
    # nothing to run, naming the wrong unknown (FB-19). Only the sentence moves: every input refused
    # below is still refused, and a case that has a row or a file still reaches `_profile_for`.
    for case, files in bare_files.items():
        if not files:
            raise MineRefusal(_no_test_refusal(case, files))

    # The command comes before the collect fallback: it is what collects.
    files_hint = sorted({r["node"].split("::")[0] for r in rows}
                        | {f for fs in bare_files.values() for f in fs})
    # The precedent is the latest ORDINARY behavioural job of the profile, for an ordinary run and
    # for a red probe alike (see ordinary_precedent): a probe's own job holds a clone's path.
    ordinary = [j for j in jobs if j["request"].get("purpose") in BEHAVIORAL
                and j["request"].get("purpose") != "red_probe"]
    profile = _profile_for(cfg, files_hint, profile_id, [r["entry"] for r in rows],
                           ordinary or [j for j in jobs if j["request"].get("purpose") != "red_probe"],
                           cases, profile_door=profile_door, notes=notes)
    # `precedent` is the story's newest ORDINARY typed run on the profile, whatever it did: the
    # fingerprint file list and the source revision are read from it. Only the COMMAND is chosen
    # among the jobs that ran a test (`command_job`): a run that never ran one is no precedent for
    # how tests are launched. `matching` and `ordinary_precedent` are one definition
    # (`ordinary_jobs`): a red-probe job is never in it (L3).
    matching = ordinary_jobs(jobs, profile)
    precedent = matching[0]["request"] if matching else None
    # `runtime_precedent` is UNCHANGED: the stand's identity (runtime probe and provenance) is
    # copied from the latest job of the profile of any purpose, a red probe included - nothing
    # in it is a directory. (A probe-only story still copies from a probe job: queued, B-337.)
    runtime_precedent = precedent or next(
        (j["request"] for j in reversed(jobs) if j["request"].get("profile_id") == profile), None)
    profile_doc = next((p for p in (cfg.get("profiles") or [])
                        if isinstance(p, dict) and p.get("profile_id") == profile), {})
    skipped, command_job = [], None
    for job in matching:
        state = _never_ran_a_test(job, project_root)
        if not state:
            command_job = job
            break
        skipped.append((str(job.get("job_id") or "<unknown job>"), state))
    if skipped:
        notes.append(
            "typed runs of this story on profile " + profile + " that never ran a test (no test "
            "totals in their summaries) are not copied as the command precedent: "
            + ", ".join(f"{jid} ({state})" for jid, state in skipped))
    # The profile is the person's word about the command, and `config.json` is in the request
    # fingerprint, so the reuse identity already reads a change of it as a change: a result-bearing
    # precedent whose argv is not the profile's is therefore not copied. Compared: the argv as a
    # list of strings, the profile's with its `<placeholder>` tokens removed as
    # `_command_from_profile` does - not the cwd (a red probe's is its sandbox, by design) and
    # not the reporter. Direction of doubt: an argv that cannot be read on either side is NOT
    # "different" - the precedent is used as it always was, and a note says the two were not compared.
    command, copied_from = None, None
    if command_job is not None:
        old_argv = (command_job["request"].get("command") or {}).get("argv")
        new_argv = _profile_argv(profile_doc)
        # EP1-22: `env` is part of the command. A precedent without the `env` the profile now gives would run the command with
        # no report of its own (an `env`-only change leaves the argv equal), so a different `env` is a different command.
        # Absent and `{}` are equal; an `env` of the profile that cannot be read is "not compared", like an unreadable argv.
        new_env, new_env_problem = _profile_env(profile_doc)
        old_env_raw = (command_job["request"].get("command") or {}).get("env")
        old_env = old_env_raw if isinstance(old_env_raw, dict) else ({} if old_env_raw is None else {"?": old_env_raw})
        comparable = bool(new_argv) and isinstance(old_argv, list) and bool(old_argv) and not new_env_problem
        if comparable and ([str(a) for a in old_argv] != new_argv or dict(old_env) != dict(new_env)):
            notes.append(
                f"the command of typed run {command_job.get('job_id')} was not reused because it "
                "differs from the profile's command in qa-factory/config.json, and the profile's "
                f"is the command of record (the run's argv: {_shown_argv(old_argv)}; profile "
                f"{profile}'s commands.one_test.argv: {_shown_argv(new_argv)}"
                + ("" if dict(old_env) == dict(new_env) else
                   f"; the run's env variables: {sorted(old_env) or 'none'}; the profile's commands.one_test.env: "
                   f"{sorted(new_env) or 'none'}")
                + "). If the profile's "
                "command is the wrong one, a role does not change that file: say so in your "
                "digest as an onboarding gap, and write this one run with --template request. "
                "The fingerprint file list and runtime probe are still those of this story's "
                "last typed run on the profile")
        else:
            command = {k: v for k, v in (command_job["request"].get("command") or {}).items()
                       if k != "selector_args"}
            copied_from = command_job["request"]
            notes.append(
                f"the command is that of typed run {command_job.get('job_id')}, the latest that ran "
                "tests; the fingerprint file list and runtime probe are those of this story's last "
                f"typed run on profile {profile}" if skipped else
                "command, fingerprint file list and runtime probe are those of this story's "
                f"last typed run on profile {profile}")
            if not comparable:
                notes.append(f"profile {profile} has no readable commands.one_test.argv or env, or the "
                             "typed run recorded no argv: the two commands were not compared, and "
                             "the typed run's was copied as it is")
    if command is None:
        command = _command_from_profile(profile_doc or {"profile_id": profile},
                                        [jid for jid, _state in skipped] if command_job is None
                                        else None)
        if skipped and command_job is None:
            notes.append(f"no typed run of this story on profile {profile} ran a test: the command "
                         "is the profile's (commands.one_test in qa-factory/config.json); the "
                         "fingerprint file list and runtime probe are still those of this story's "
                         "last typed run on the profile")
    # Selector join (M18b), positioned AFTER `command` is final (copied or built) and BEFORE the run
    # directory is set: the join belongs to the command, and the run directory below only reads it.
    if profile_doc:
        # The profile exists: it decides, whether it has a join rule or not, and its answer
        # overrides a precedent's. With no profile document the precedent's rule is kept.
        selectors = profile_doc.get("selectors")
        if isinstance(selectors, dict) and "join" in selectors:
            problem = selector_join_problem(selectors["join"])
            if problem:
                raise MineRefusal(
                    f"profiles[{profile}].selectors.join in qa-factory/config.json {problem}; expected "
                    f"{SELECTOR_JOIN_SHAPE} (`group` is optional). That is a gap of the onboarding, "
                    "not of your test: report it in your digest. To correct it: "
                    "`/qa-factory:qa-onboarding` (execution batch).")
            join = selectors["join"]
            command["selector_join"] = {"option": join["option"], "separator": join["separator"],
                                        **({"group": list(join["group"])} if "group" in join else {})}
        else:
            command.pop("selector_join", None)
    if cwd and sandbox_root:
        raise MineRefusal("--cwd and --sandbox-root both say where the run happens: --cwd takes one "
                          "directory as given, --sandbox-root takes a clone and works the directory "
                          "out inside it. Pass one of them.")
    if cwd:
        command["cwd"] = cwd
    elif sandbox_root:
        # The run directory belongs to the command: the request it was copied from, else the
        # newest ordinary one (never a red probe's, so never a clone that has gone).
        command["cwd"] = str(sandbox_run_directory(project_root, sandbox_root, profile_doc,
                                                   copied_from or precedent))
    elif purpose == "red_probe":
        # Unconditional: a red-probe request resolves only to a directory its caller named (--cwd)
        # or one inside the named clone, never to the author's tree, whatever was copied.
        raise MineRefusal("a red probe runs inside the sandbox red_sandbox.py prepared, never in "
                          "the author's tree: pass --sandbox-root <the clone's root> (the profile's "
                          "directory is worked out inside it) or --cwd <the exact sandbox directory>. "
                          "`red_sandbox.py --probe` prepares the clone and passes it for you.")
    run_cwd = Path(command.get("cwd") or ".")
    run_cwd = (run_cwd if run_cwd.is_absolute() else project_root / run_cwd).resolve()
    pytest_run = is_pytest_command(command.get("argv"))

    # -- the order of the refusals (B-E8, HF2-10) --------------------------------------------------------------
    # 1. what needs no process: the refusals above, a case that names no test and no file, a test file nobody can
    #    find; 2. the stand (a probe is ~11 s); 3. the collect (~100 s); 4. whatever reads the collect. Invariant: an
    #    input refused without the collect is refused before it, and nothing accepted before is refused now or the
    #    other way round - only the place of the refusal moved.
    for case, files in bare_files.items():
        if not pytest_run or not files:
            raise MineRefusal(_no_test_refusal(case, files))
    if pytest_run:
        _place_rows(rows, run_cwd, project_root)
    runtime = _observe_stand(cfg, profile, policy, purpose, probe, probe_extra, project_root, runtime_precedent,
                             evidence_only, notes, task_root=task_root)

    for case, files in bare_files.items():
        for file in files:
            wanted = (functions_naming_case(run_cwd / file, case)
                      or functions_naming_case(project_root / file, case))
            collected = []
            if collect is not None:
                try:
                    collected = [str(n).replace("\\", "/")
                                 for n in collect(list(command["argv"]), str(run_cwd), [file])]
                except Exception as exc:  # the collect is a convenience here, never a gate
                    notes.append(f"collect of {file} failed ({type(exc).__name__}); ids come from the source")
            if collected:
                names = {n: n.split("::")[-1].split("[")[0] for n in collected}
                chosen = [n for n in collected if names[n] in wanted]
                if not chosen and len(set(names.values())) == 1:
                    chosen = collected
            else:
                chosen = [f"{file}::{name}" for name in wanted]
            if not chosen:
                raise MineRefusal(
                    f"the manifest names {file} for {case} but no test in it, and no test there "
                    f"mentions {case} in a marker, comment or docstring. Name the test: "
                    f"--mine {case} --node-id {file}::<test function>, then record it through "
                    "manifest_put.py so the next run needs no flag.")
            notes.append(f"{case}: the manifest has no selector yet; ran what {file} marks with "
                         f"{case}: " + ", ".join(n.split("::", 1)[-1] for n in chosen))
            entry = next((e for e in (manifest.get("tests") or []) if isinstance(e, dict)
                          and str(e.get("file") or "").replace("\\", "/") == file), {})
            rows.extend({"instance_id": _instance_name(n.split("::", 1)[-1]), "case": case,
                         "node": n, "entry": entry, "report_test_id": ""} for n in chosen)

    verified, collect_memo = False, None
    if pytest_run:
        _place_rows(rows, run_cwd, project_root)  # the rows a bare file added
        # An explicit `--node-id` whose file exists and whose id has no `[...]` is not collected: pytest itself
        # answers `ERROR: not found` in the first second of the run, and `run_suite` turns that into
        # `node_id_mismatch` (F-B2). An id with parameters still goes through the ONE collect - a plugin spells
        # them (pytest-playwright puts the browser first, TP1-15045) and only a collect says how.
        by_run = bool(node_ids) and not any("[" in str(n) for n in node_ids)
        # The collect is not asked again when its answer is already known (EP1-23 B2): the list an earlier job of this
        # story kept under the key of the same inputs - the skeleton of the test files, not their bodies, so the
        # ordinary "edit the body, run it" window does not pay ~100 s for the same list. The list is only PLAYED BACK
        # through `_spell_as_collected`: a row it does not find in it (False) throws the playback away and the real
        # collect runs over the rows as they were. Invariant: `verified` is True without a collect in this process
        # only for a key that moved nowhere; a wrong guess is loud (`not found`, `node_id_mismatch`), never green.
        # The key is computed for EVERY real collect that may run, and the list is always written under it; only the
        # READ is closed to `--again`, `--cwd` and `--sandbox-root` (F-1: a collect made under a door is the newest
        # answer, and the next plain call must not replay an older one). A stand nobody could read (`policy is None`,
        # the run budget unreadable) and a red probe, a freshness read or the S6 close get no key and no memory (F-3).
        memo = ""
        if (collect is not None and not by_run and rows and policy is not None
                and not (evidence_only or s6_close or purpose == "red_probe")):
            memo = _memo_key_of_rows(rows, command, run_cwd, project_root, cfg, runtime)
            if memo and not (again or cwd or sandbox_root):
                rows, verified, collect_memo = _play_back_memo(rows, command, run_cwd, jobs, memo, project_root, notes)
        if not verified:
            took: dict = {}

            def remembered(argv, where, files):
                took["ids"] = list(collect(argv, where, files))
                return took["ids"]
            rows, verified = _spell_as_collected(rows, command, run_cwd,
                                                 None if by_run or collect is None else remembered, notes)
            if verified and memo and took.get("ids"):
                collect_memo = {"key": memo, "ids": took["ids"]}

    # One instance id, one reporter row: a second test under the same id keeps its own spelling.
    by_id: dict = {}
    for row in rows:
        if row["instance_id"] in by_id and by_id[row["instance_id"]]["node"] != row["node"]:
            row["instance_id"] = row["node"].split("::", 1)[-1]
        by_id[row["instance_id"]] = row
    rows = list(by_id.values())

    selector_args, contracts, test_files = {}, {}, []
    for row in rows:
        entry, node = row["entry"], row["node"]
        if pytest_run:
            path = row["path"]
            selector_args[row["instance_id"]] = [node]
            report_id = row["report_test_id"] or node_report_id(node, run_cwd)
            if row["report_test_id"] and not row.get("collected"):
                # An id written before the rootdir rule spelled the node from the cwd; the
                # junit row is spelled from pytest's rootdir. Only an id that IS the old
                # spelling is replaced; a role-written id that is neither is the framework's
                # own and stays as written.
                fresh = node_report_id(node, run_cwd)
                if row["report_test_id"] != fresh and row["report_test_id"] == node_report_id(node):
                    notes.append(f"{row['instance_id']}: report id {row['report_test_id']} was spelled "
                                 f"from the cwd; pytest's rootdir spells it {fresh}, used that")
                    report_id = fresh
        else:
            args_of_entry = entry.get("selector_args")
            named = str(entry.get("file") or "")
            built = None
            if isinstance(args_of_entry, list) and args_of_entry and entry.get("report_test_id"):
                # the role's own value wins over the code's (the door of FR-2): a hand-written id is as honest as a built one
                selector_args[row["instance_id"]] = [str(a) for a in args_of_entry]
                report_id = str(entry["report_test_id"])
            else:
                built = code_selection(entry, command.get("argv"), run_cwd,
                                       Path(sandbox_root).resolve() if sandbox_root else project_root)
                if built is None:
                    import launch_check
                    no_form = launch_check.runner_identity(command.get("argv"))["no_direct_form"]
                    raise MineRefusal(
                        f"{row['case']}: profile {profile} does not run pytest, and the factory builds a "
                        "selector by itself only for pytest node ids. Give the manifest entry "
                        "`selector_args` (the framework's own arguments) and `report_test_id` through "
                        "manifest_put.py once; until then this run goes through --template request."
                        + (f" {no_form}; a profile with a form from run_forms (for example the runner's own direct "
                           "command) builds this by code" if no_form else ""))
                selector_args[row["instance_id"]] = built["selector_args"]
                report_id = built["report_test_id"]
            # In a clone the file is looked up in the clone ONLY: a non-pytest test file used to be
            # found under the run directory and then under the project root, so a probe's
            # fingerprint could cover the author's bytes and be the same in every clone - and
            # "first" still let a file the clone does not hold (gitignored, say) resolve to the
            # author's copy. A path that leaves the clone (`..`) is not the clone's file.
            if sandbox_root:
                clone = Path(sandbox_root).resolve()
                clone_file = (clone / named).resolve()
                path = clone_file if named and clone_file.is_relative_to(clone) and clone_file.is_file() else None
                if named and path is None:
                    raise MineRefusal(
                        f"the test file {named} is not in the sandbox clone {sandbox_root} - a red probe "
                        "runs only on files the clone holds; add it to the repository or run the probe "
                        "on a tracked copy")
            else:
                path = next((p.resolve() for p in (run_cwd / named, project_root / named)
                             if named and p.is_file()), None)
            row["source_path"] = path     # the cipher loop below measures a non-pytest test from here (B-3)
        if path is not None and str(path) not in test_files:
            test_files.append(str(path))
        links = entry.get("case_version_links") if isinstance(entry.get("case_version_links"), list) else []
        contract_row = {"report_test_id": report_id, "parameters": {},
                        "case_version_links": links}
        if not pytest_run:
            # the file the row's report is matched to (`red_sandbox.selection_rows`): always, so a role-written id is judged
            # by the same table as a built one; the matching data only when the code built the selector
            contract_row["file"] = named
            for key in ("classname_match", "report_match"):
                if built and built.get(key):
                    contract_row[key] = built[key]
        if isinstance(entry.get("obligation_ids"), list):
            contract_row["obligation_ids"] = entry["obligation_ids"]
        if command.get("reporter") == "trx":
            contract_row["report_id_source"] = str(entry.get("report_id_source") or "catalog")
        contracts[row["instance_id"]] = contract_row
    selected = list(selector_args)

    # -- one run per window -----------------------------------------------------------------
    # Tests are cheap to run and expensive to ask for: on TP1-15045 one automator spent 20
    # pytest launches on 4 cases, 15 of them one instance at a time, where 2 window runs would
    # have done. `--mine CASE[,CASE]` already runs every instance of the named cases in one
    # call and stays untouched. What is answered here is the OTHER shape — a run that picks
    # part of a case (`--node-id`) while a test of the same file, inside this dispatch's own
    # scope, has no evidence at all: the answer is the one command that runs them together,
    # given before an idempotency key is spent (the stand was looked at above, once, for the collect's sake: the
    # window answer reads the instances AFTER they are spelled, so it stays behind the collect, B-E8). `--purpose
    # repair_verify` is the role saying "only what I just repaired", `--again` is "this run
    # once more", and a red probe runs pinned mutated instances by definition.
    partial = [row["instance_id"] for case in cases for row in manifest_rows(manifest, case, store_root=task_root)[0]
               if not covered_by(row["instance_id"], selected)]
    if partial and purpose not in {"repair_verify", "red_probe"} and not again and not evidence_only:
        missing = [n for n in window_neighbours(manifest, scope, rows, selected)
                   if never_ran(jobs, n["instance_id"])]
        if missing:
            stage = str(dispatch.get("stage") or "S5")
            wanted = sorted(set(cases) | {n["case"] for n in missing})
            command_line = "run_suite.py --mine " + ",".join(wanted)
            shown = ", ".join(n["instance_id"] for n in missing[:4])
            message = (
                f"{len(missing)} test(s) of this dispatch's scope live in the same file and "
                f"have never run in this window ({shown}{', ...' if len(missing) > 4 else ''}). "
                f"One pytest call runs them all — `{command_line}` — and each extra call costs "
                "a turn of yours, not stand time. Nothing is wrong with these tests. Only what "
                "a repair touched: --purpose repair_verify. This exact run once more: --again. "
                f"A person's word passes it (waiver.py, stage {stage}, block \"{WINDOW_BLOCK}\").")
            word = person_passed(task_root, stage, message)
            if not word:
                raise WindowFirst(message, {
                    "status": "run_the_window_first", "command": command_line,
                    "never_ran": [n["instance_id"] for n in missing],
                    "cases": wanted, "selected": selected})
            notes.append(f"{len(missing)} neighbour(s) of this window have never run; passed on "
                         f"a person's word: {word}")

    command["selector_args"] = selector_args
    if pytest_run:
        command["selector_contract_verified"] = True  # a node id as an argument IS pytest's contract
    elif "selector_contract_verified" not in command:
        import profile_contract   # the ONE answer to "is this profile's selector contract verified" (the probe asks it too)
        command["selector_contract_verified"] = profile_contract.selectors_verified(profile_doc, project_root)   # the project, not a clone

    scope_ids = list(selected)
    for case in scope:
        for row in manifest_rows(manifest, case, store_root=task_root)[0]:
            if row["instance_id"] not in scope_ids:
                scope_ids.append(row["instance_id"])

    # -- the stand: looked at before the collect (`_observe_stand`, above) --------------------------------------
    provenance = runtime.get("runtime_provenance") or {}
    # The fingerprint validates strictly and reads a few stable fields of the provenance: a freshness read's `matched`
    # that was observed without an evidence file (a rehearsal) is shown to it in its rehearsal view, or the read
    # would end in "could not be fingerprinted" and S6 would never be decided (t-043 D1). A real run has its file.
    seen_by_fingerprint = rehearsal_view(provenance) if evidence_only else provenance
    inherited_from = precedent or runtime_precedent or {}
    # The build a run PROVES is the story's own commit - unless the person said `test deployed`: then the run stands on
    # the build they chose (`tested_build`), and `source_sha` carries THAT (t-300 N2 X11/F2, FR-18 - a run on D never
    # proves the story's own revision). Precedence: a `tested_build` on the FRESH provenance first; else what an earlier
    # run recorded - EXCEPT an earlier run that itself stood on a chosen build (its `source_sha` was D, never the story's;
    # a fresh record without a `tested_build` never inherits D); else the probe's expected revision; else the controller's.
    inherited_sha = str((inherited_from.get("fingerprint_components") or {}).get("source_sha") or "")
    if (inherited_from.get("runtime_provenance") or {}).get("tested_build"):
        inherited_sha = ""
    source = (str(provenance.get("tested_build") or "") or inherited_sha
              or str(provenance.get("expected_source_revision") or "")
              or str(controller.get("source_revision") or ""))

    # -- fingerprint ----------------------------------------------------------------------
    helpers = _conftest_chain(test_files, run_cwd)
    inherited = {"helper_files": [], "dependency_files": [], "config_files": []}
    if precedent and not cwd and not sandbox_root:
        for record in precedent.get("fingerprint_files") or []:
            if (isinstance(record, dict) and record.get("kind") in inherited
                    and Path(str(record.get("path"))).is_file()):
                inherited[record["kind"]].append(str(Path(record["path"]).resolve()))
    config_file = (project_root / "qa-factory" / "config.json").resolve()
    dependencies = inherited["dependency_files"]
    if not dependencies:
        dependencies, dependency_note = dependency_files(run_cwd, cfg)
        if dependency_note:
            notes.append(dependency_note)
    from execution_fingerprint import build as build_fingerprint
    try:
        fingerprint = build_fingerprint({
            "source_revision": source, "test_files": test_files,
            "helper_files": sorted({str(Path(p).resolve()) for p in helpers + inherited["helper_files"]}
                                   - set(test_files)),
            "config_files": sorted(set(inherited["config_files"]) | {str(config_file)}),
            "dependency_files": dependencies, "runtime_provenance": seen_by_fingerprint,
            "profile_id": profile, "project_config": str(config_file)})
    except ValueError as exc:
        raise MineRefusal(f"the inputs of this run could not be fingerprinted: {exc}") from exc

    # -- what each instance depends on, on its own -----------------------------------------
    # The conftest chain first, nearest to the test first: that is the order pytest resolves a
    # fixture in. Then the helpers this story's earlier runs declared, then the other test
    # files of this run, because a test module may import from its neighbour.
    from execution_fingerprint import function_sha
    helper_paths, sha_cache = _helper_paths(helpers, inherited["helper_files"], test_files), {}
    title_join = None
    for row in rows:
        contract = contracts.get(row["instance_id"])
        path = row.get("path")
        if not isinstance(contract, dict):
            continue
        if path is None and not pytest_run and row.get("source_path") is not None:
            # a test of a language `test_source` reads: ONE producer of the identity, the one `instance_shas` measures again
            # later (B-3). No entry for the file, or no declaration for the id, is no identity - never a guessed one.
            import test_source
            title_join = _title_join(command.get("argv")) if title_join is None else title_join
            shas = test_source.instance_shas_of(row["source_path"], contract.get("report_test_id"),
                                                contract.get("report_match"), title_join)
            if shas:
                contract["instance_content_sha"] = shas["instance_content_sha"]
                contract["instance_content_scope"] = shas["scope"]
                contract["instance_code_sha"] = shas["instance_code_sha"]
            continue
        if path is None:
            continue
        _file, chain, function, _params = _split_node(row["node"])
        measured = function_sha(path, function, chain, helper_paths, sha_cache)
        contract["instance_content_sha"] = measured["sha"]
        contract["instance_content_scope"] = measured["scope"]
        # Beside the raw sha, the same bytes with the comments, docstring lines and blank lines
        # (and, once the marker data lands, the factory's own marker) taken out: `covered` treats
        # equal code shas as the same test, so a cosmetic fix is not a reason to run.
        contract["instance_code_sha"] = measured.get("code_sha", "")

    # -- what is already answered ----------------------------------------------------------
    # D-0017/D-0018: an instance with a result over the same bytes, on the same stand and
    # version, is not run again - by anyone, in any dispatch of this story. Every selected
    # instance is asked of `covered` (through `covering`, which counts a red's repeats): all
    # covered is an answer and nothing is launched; some covered narrows the run to the rest
    # (an instance with no result is never dropped, and WindowFirst has already had its say over
    # the whole selection above); none covered is today's run. The door is a person's word.
    reusable, not_run_again = None, {}
    stage_of_dispatch = str(dispatch.get("stage") or "S5")
    if evidence_only:
        return (_classify_evidence(policy, budget_note, jobs, fingerprint, selector_args, contracts,
                                   runtime, selected, project_root, notes), notes, None, verified)
    if policy is None:
        # No budget data: the rule as it stood before it - a green run of these instances over
        # these bytes is this run, and `--again` says "once more".
        if purpose != "red_probe" and not again:
            found = next((j for j in reversed(jobs)
                          if j.get("status") == "completed" and j["request"].get("purpose") != "red_probe"
                          and green_over_same_bytes(j, fingerprint, selector_args, contracts, selected)),
                         None)
            if found:
                reusable = {"status": "reused", "jobs": [found], "job_id": found.get("job_id"),
                            "words": "", "hint": "", "covered": {i: found.get("job_id") for i in selected}}
    elif purpose != "red_probe":
        seen_now = _request_view(fingerprint, selector_args, contracts, runtime)
        reset_at, block_of = stand_reset_at(project_root), run_block_reader(project_root)
        per = {i: covering(jobs, seen_now, i, policy=policy, reset_at=reset_at, block_of=block_of)
               for i in selected}
        done = [i for i in selected if per[i]["covered"]]
        if done:
            word = person_word(task_root, stage_of_dispatch, say(policy, "hint", stage=stage_of_dispatch))
            if word_passes(word, _newest_created(_unique_jobs({i: per[i] for i in done}))):
                notes.append(say(policy, "word_note", covered=", ".join(done), word=word["decision"]))
            elif len(done) == len(selected):
                reusable = budget_answer(policy, per, cases, stage_of_dispatch, again)
            else:
                run_ids = [i for i in selected if i not in done]
                not_run_again = {i: per[i]["jobs"][0].get("job_id") for i in done}
                notes.append(say(policy, "partial_note", run=", ".join(run_ids), covered=", ".join(done),
                                 date=_date_of(_unique_jobs({i: per[i] for i in done})[-1]),
                                 jobs=_job_ids(_unique_jobs({i: per[i] for i in done}))))
                if again:
                    notes.append(say(policy, "again_note", stage=stage_of_dispatch))
                selector_args = {i: selector_args[i] for i in run_ids}
                contracts = {i: contracts[i] for i in run_ids}
                rows = [r for r in rows if r["instance_id"] in run_ids]
                selected = run_ids
                command["selector_args"] = selector_args

    # -- identity of this attempt ---------------------------------------------------------
    our_reports = {c["report_test_id"] for c in contracts.values()}

    def ran_before(job: dict) -> bool:
        old = job["request"]
        old_reports = {str((c or {}).get("report_test_id") or "")
                       for c in (old.get("instance_contracts") or {}).values() if isinstance(c, dict)}
        return (job.get("status") == "completed" and old.get("purpose") != "red_probe"
                and bool(set(old.get("selected_instance_ids") or []) & set(selected)
                         or old_reports & our_reports))

    earlier = [j for j in jobs if ran_before(j)]
    purpose = purpose or ("repair_verify" if earlier else "initial")
    # What ran is the instances over the bytes: `--node-id` runs another test of the same case.
    # A run made while the stand's version was not observed is not the run made while it was: the
    # observation state is part of what ran, so an unobserved request never lands on the key of
    # an observed job (and is never answered from it through the existing-key branch, F3).
    what = attempt_identity(selector_args, fingerprint["input_fingerprint"], purpose, run_cwd,
                            unobserved=runtime.get("runtime_observed") is False)
    base = ":".join([str(dispatch.get("id")), purpose, "+".join(cases), what])
    taken = {str(j.get("idempotency_key")): j for j in jobs}
    key, attempt = base, 1
    # A run that did not pass is never "the same run" to a role that has just repaired
    # something the fingerprint does not list (a page object, a fixture file, the stand): it
    # asked for a run, so it gets one. A green run over identical bytes IS the same run. Before
    # the budget `--again` was how a role said it wanted that one repeated too; now it repeats
    # nothing: the door for a repeat is a person's word, and only a red probe - which is never
    # answered - keeps `--again`. With the budget on, a request that reaches this point was NOT
    # answered (coverage said a run is due: a person's word, a red awaiting its repeat, a green
    # that a newer red on the same bytes superseded), so a key already taken is never reused -
    # the existing-key branch would answer that run with the very result it was due against.
    repeats = again if (purpose == "red_probe" or policy is None) else True
    while key in taken and (repeats or not (taken[key].get("status") == "completed"
                                            and taken[key].get("execution_status") == "passed")):
        attempt += 1
        key = f"{base}:again-{attempt}"
    if attempt > 1:
        notes.append(f"attempt {attempt} over unchanged fingerprinted inputs")
    budget = (dispatch.get("budget") or {}).get("requests")
    used = sum(1 for j in jobs if j["request"].get("dispatch_id") == dispatch.get("id"))
    remaining = (max(1, int(budget) - used)
                 if isinstance(budget, (int, float)) and not isinstance(budget, bool) else 1)
    if purpose == "red_probe":
        selection = {"reason": "diagnostic", "evidence_refs": [r["node"] for r in rows]}
    elif earlier:
        selection = {"reason": "failed_or_invalidated",
                     "evidence_refs": [str(earlier[-1].get("summary") or earlier[-1].get("job_id"))]}
    else:
        selection = {"reason": "missing_fresh_evidence", "evidence_refs": [r["node"] for r in rows]}
    execution = {"schema_version": 1, "selection": selection,
                 "reporter": {"format": command.get("reporter"), "path_template": "{report_path}"}}
    request = {
        "task": task, "revision": str(controller.get("revision") or "0"),
        "dispatch_id": str(dispatch.get("id")), "profile_id": profile, "purpose": purpose,
        "reason": reason or f"{dispatch.get('id')}: --mine {','.join(cases)} ({purpose})",
        "idempotency_key": key, **fingerprint, "freshness": "fresh", "remaining_budget": remaining,
        "selected_instance_ids": selected, "current_scope_instance_ids": scope_ids,
        **runtime, "command": command, "instance_contracts": contracts, "execution": execution,
        "built_by": {"tool": "run_suite.py --mine", "cases": cases},
    }
    if not_run_again:
        request["not_run_again"] = not_run_again
    if collect_memo:
        request["collect_memo"] = collect_memo  # the list this request's ids were spelled from; not in the digest
    return request, notes, reusable, verified


def write_mine_request(project_root: Path, request: dict) -> Path:
    """`work/requests/mine-<dispatch>-<cases>-<key>.json` — on disk, so the guard, the
    scheduler and a person can read exactly what ran."""
    import re
    from hooklib import artifact_root as _artifact_root
    directory = _artifact_root(root=Path(project_root)) / request["task"] / "work" / "requests"
    directory.mkdir(parents=True, exist_ok=True)
    cases = "+".join((request.get("built_by") or {}).get("cases") or [])
    stem = re.sub(r"[^A-Za-z0-9._+-]+", "-", f"mine-{request['dispatch_id']}-{cases}")[:96]
    suffix = hashlib.sha256(request["idempotency_key"].encode()).hexdigest()[:8]
    path = directory / f"{stem}-{suffix}.json"
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(request, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
