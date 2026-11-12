"""Validation and readiness helpers for extensible QA execution profiles.

The module is deliberately side-effect free: dependency descriptors are evidence, never an
instruction to install a tool.  Consumers may import the functions or use the small JSON CLI.
"""
from __future__ import annotations

import argparse
import json
import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import Any

PROFILE_STATUSES = {"ready", "unavailable", "unsupported", "unknown"}
# `person_confirmed` (t-300): the build under test is the person's word, not the factory's reading. It is the fifth
# word and it is NEVER `matched`: every reader that wants a verified build refuses it unless it says otherwise.
PROVENANCE_RESULTS = {"matched", "mismatched", "unknown", "not_applicable", "person_confirmed"}
COMMAND_KINDS = {"build", "collect", "run", "test", "typecheck", "lint", "setup"}
# `setup` is a command that brings the project's environment to its lock (`commands.install`, RH1-4): it runs no test, so it
# names no scope, no reporter and no selectors. The factory prints it and never runs it.
SETUP_KIND = "setup"
REPORT_FORMATS = {"pytest", "junit-xml", "trx", "none"}
LEVELS = {"unit", "component", "api", "integration", "e2e-ui"}
# The words for "the files" when a content word records none; ONE constant (SC2-33, AR-13), read by `report_facts` and `manual_evidence`.
CONTENT_FILES_FALLBACK = "the files of this story"


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _error(errors: list[str], path: str, message: str) -> None:
    errors.append(f"{path}: {message}")


def _in(value: Any, allowed) -> bool:
    """`value in allowed` for a set of words, never an exception: a list or an object is not hashable and is simply not one of
    the words (OH3-26: the validator is a gate now, and a gate that raises on a hostile shape passes nothing and says nothing)."""
    return isinstance(value, str) and value in allowed


def validate_profile(profile: dict, path: str = "profile") -> list[str]:
    errors: list[str] = []
    if not isinstance(profile, dict):
        return [f"{path}: must be an object"]
    for key in ("profile_id", "revision", "adapter_id", "adapter_version"):
        if not _nonempty(profile.get(key)):
            _error(errors, f"{path}.{key}", "must be a non-empty string")
    roots = profile.get("roots")
    if not isinstance(roots, dict) or not _nonempty(roots.get("test")):
        _error(errors, f"{path}.roots.test", "must name the profile test root")
    capabilities = profile.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        _error(errors, f"{path}.capabilities", "must be a non-empty list")
    elif any(not _nonempty(item) for item in capabilities):
        _error(errors, f"{path}.capabilities", "items must be non-empty strings")

    commands = profile.get("commands")
    if not isinstance(commands, dict) or not commands:
        _error(errors, f"{path}.commands", "must contain named commands")
    else:
        for name, command in commands.items():
            cp = f"{path}.commands.{name}"
            if not isinstance(command, dict):
                _error(errors, cp, "must be an object")
                continue
            argv = command.get("argv")
            if not isinstance(argv, list) or not argv or any(not _nonempty(x) for x in argv):
                _error(errors, f"{cp}.argv", "must be a non-empty string array")
            _env, env_problem = command_env(command)
            if env_problem:
                _error(errors, f"{cp}.env", env_problem)
            if not _nonempty(command.get("cwd")):
                _error(errors, f"{cp}.cwd", "must be a non-empty path")
            if not _in(command.get("kind"), COMMAND_KINDS):
                _error(errors, f"{cp}.kind", f"must be one of {sorted(COMMAND_KINDS)}")
            if command.get("kind") != SETUP_KIND and not _in(command.get("scope"), {"selected", "full_suite"}):
                _error(errors, f"{cp}.scope", "must be selected or full_suite")
            # New profiles declare execution facts on each command.  The legacy top-level
            # selector/reporter objects remain readable for old profiles only.
            for key in ("repo_id", "framework_adapter"):
                if key in command and not _nonempty(command.get(key)):
                    _error(errors, f"{cp}.{key}", "must be a non-empty string")
            reporter = command.get("reporter")
            if reporter is not None:
                if not isinstance(reporter, dict):
                    _error(errors, f"{cp}.reporter", "must be an object")
                elif not _in(reporter.get("format"), REPORT_FORMATS):
                    _error(errors, f"{cp}.reporter.format", f"must be one of {sorted(REPORT_FORMATS)}")
                elif (reporter.get("format") != "none" and
                      (not _nonempty(reporter.get("path_template")) or "{report_path}" not in reporter["path_template"])):
                    _error(errors, f"{cp}.reporter.path_template", "must contain {report_path} for job isolation")
            if "selectors" in command and not isinstance(command.get("selectors"), dict):
                _error(errors, f"{cp}.selectors", "must be an object")
    for key in ("selectors", "reporter", "quality_gates"):
        if not isinstance(profile.get(key), dict):
            _error(errors, f"{path}.{key}", "must be an object")
    gates = profile.get("quality_gates")
    named_commands = commands if isinstance(commands, dict) else {}
    for name, gate in (gates.items() if isinstance(gates, dict) else ()):
        gp = f"{path}.quality_gates.{name}"
        if not isinstance(gate, dict):
            _error(errors, gp, "must be an object")
            continue
        if not _nonempty(gate.get("command")) or gate.get("command") not in named_commands:
            _error(errors, f"{gp}.command", "must reference a named command")
        if not _in(gate.get("quality_kind"), {"build", "collect", "typecheck", "lint", "format"}):
            _error(errors, f"{gp}.quality_kind", "must classify the quality check")
        if not isinstance(gate.get("runs_tests"), bool):
            _error(errors, f"{gp}.runs_tests", "must be boolean after inspecting the wrapper")
    prerequisites = profile.get("execution_prerequisites")
    if not isinstance(prerequisites, dict):
        _error(errors, f"{path}.execution_prerequisites", "must be an object")
    else:
        for key in ("runtime", "package_manager", "dependency_state"):
            if not _nonempty(prerequisites.get(key)):
                _error(errors, f"{path}.execution_prerequisites.{key}", "must be recorded")
        if not isinstance(prerequisites.get("hook_executables"), list):
            _error(errors, f"{path}.execution_prerequisites.hook_executables", "must be an array")
    for key in ("conventions_refs", "environment_refs", "data_refs", "ownership_refs"):
        if not isinstance(profile.get(key), list):
            _error(errors, f"{path}.{key}", "must be an array")
    extensions = profile.get("extensions")
    if not isinstance(extensions, dict) or not _nonempty(extensions.get("schema_version")):
        _error(errors, f"{path}.extensions.schema_version", "must version adapter-specific extensions")
    execution = extensions.get("execution") if isinstance(extensions, dict) else None
    if execution is not None:
        ep = f"{path}.extensions.execution"
        if not isinstance(execution, dict) or execution.get("schema_version") != 1:
            _error(errors, f"{ep}.schema_version", "must equal integer 1")
        else:
            for name, command in named_commands.items():
                if not isinstance(command, dict):
                    continue
                cp = f"{path}.commands.{name}"
                # a `setup` command is a hint printed to a person and never run: no repo and no framework adapter to name
                for key in (() if command.get("kind") == SETUP_KIND else ("repo_id", "framework_adapter")):
                    if not _nonempty(command.get(key)):
                        _error(errors, f"{cp}.{key}", "is required by execution schema 1")
                if command.get("kind") != SETUP_KIND and not isinstance(command.get("reporter"), dict):
                    _error(errors, f"{cp}.reporter", "is required by execution schema 1")
                if _in(command.get("kind"), {"run", "test"}) and not isinstance(command.get("selectors"), dict):
                    _error(errors, f"{cp}.selectors", "is required for executable test commands")
            concurrency = execution.get("concurrency")
            if not isinstance(concurrency, dict):
                _error(errors, f"{ep}.concurrency", "must be an object")
            else:
                if not isinstance(concurrency.get("native_supported"), bool):
                    _error(errors, f"{ep}.concurrency.native_supported", "must be boolean")
                if not _in(concurrency.get("isolation"), {"verified", "shared", "unknown"}):
                    _error(errors, f"{ep}.concurrency.isolation", "must be verified, shared, or unknown")
                template = concurrency.get("native_worker_argv_template")
                if template is not None and (not isinstance(template, list) or
                        any(not _nonempty(item) for item in template)):
                    _error(errors, f"{ep}.concurrency.native_worker_argv_template",
                           "must be null or a string array")
                maximum = concurrency.get("verified_max_workers")
                if maximum is not None and (not isinstance(maximum, int) or maximum < 1):
                    _error(errors, f"{ep}.concurrency.verified_max_workers", "must be null or positive")
            resources = execution.get("resources")
            if resources and not isinstance(resources, list):
                _error(errors, f"{ep}.resources", "must be an array")
                resources = []
            for index, resource in enumerate(resources or []):
                rp = f"{ep}.resources[{index}]"
                if not isinstance(resource, dict) or not _nonempty(resource.get("key")):
                    _error(errors, f"{rp}.key", "must be a non-empty string")
                    continue
                for key in ("capacity", "units_per_worker"):
                    if not isinstance(resource.get(key), int) or resource[key] < 1:
                        _error(errors, f"{rp}.{key}", "must be a positive integer")
                if not isinstance(resource.get("exclusive"), bool):
                    _error(errors, f"{rp}.exclusive", "must be boolean")
            level_rules = execution.get("level_rules")
            if level_rules and not isinstance(level_rules, list):
                _error(errors, f"{ep}.level_rules", "must be an array")
                level_rules = []
            for index, rule in enumerate(level_rules or []):
                rp = f"{ep}.level_rules[{index}]"
                if not isinstance(rule, dict) or not _nonempty(rule.get("repo_id")):
                    _error(errors, f"{rp}.repo_id", "must be a non-empty string")
                if not isinstance(rule, dict) or not isinstance(rule.get("patterns"), list) or not rule.get("patterns"):
                    _error(errors, f"{rp}.patterns", "must be a non-empty array")
                if isinstance(rule, dict) and not _in(rule.get("level"), LEVELS):
                    _error(errors, f"{rp}.level", f"must be one of {sorted(LEVELS)}")
            ownership = execution.get("ownership")
            if ownership is not None and (not isinstance(ownership, dict) or
                    any(not isinstance(ownership.get(key), list) for key in
                        ("qa_paths", "developer_paths", "evidence_refs"))):
                _error(errors, f"{ep}.ownership", "must contain qa_paths, developer_paths, evidence_refs arrays")
    return errors


def resolve_level(profile: dict, repo_id: str, relative_path: str,
                  explicit_level: str | None = None) -> dict:
    """Resolve a test level without rule-order precedence."""
    if explicit_level in LEVELS:
        return {"level": explicit_level, "status": "explicit", "matches": []}
    import fnmatch
    execution = ((profile.get("extensions") or {}).get("execution") or {})
    normalized = relative_path.replace("\\", "/")
    matches = []
    for rule in execution.get("level_rules") or []:
        if rule.get("repo_id") == repo_id and any(fnmatch.fnmatch(normalized, pattern)
                                                   for pattern in rule.get("patterns") or []):
            matches.append(rule.get("level"))
    unique = sorted({value for value in matches if value in LEVELS})
    if len(unique) == 1:
        return {"level": unique[0], "status": "mapped", "matches": sorted(matches)}
    return {"level": "unknown", "status": "ambiguous" if len(unique) > 1 else "unknown",
            "matches": sorted(matches)}


# --- the ONE reader of `profiles[].commands` (OH3-27, AR-13) ---------------------------------------------------------
# A project's own config once carried `commands` as a LIST, and a dozen readers each parsed the shape their own way:
# one raised an AttributeError, one read a string `argv` letter by letter (a false "runnable"), one wrote over the
# list. These four functions are the only place the shape is read; every other module asks them and decides what a
# `problem` means for it (the census test in test_profile_reader.py keeps it so). Pure, they never raise.
SHAPE_FILE = "references/profile-shape.json"   # the sample of the shape, named in every problem (FR-2: the door)
_SHAPE_DOOR = f", see {SHAPE_FILE}"
_COMMAND_SHAPE = "{argv, cwd, kind, scope}"


def _a_kind(value) -> str:
    """`value` as a noun phrase for a problem sentence: 'a list', 'a string', 'a number', 'a boolean', 'an object', 'null'."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, (list, tuple)):
        return "a list"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, (int, float)):
        return "a number"
    return "a value of another kind"


def profile_commands(profile) -> tuple[dict, str]:
    """`(commands, problem)` of one profile row. A profile that is not an object, a missing `commands`, `null` and `{}`
    are `({}, "")`: absence is not a wrong shape, and "there is no command" is the caller's to say in its own words. A
    `commands` that is a list, a string or a number is a FOREIGN shape: `({}, problem)`, named and never read as `{}`."""
    if not isinstance(profile, dict):
        return {}, ""
    commands = profile.get("commands")
    if commands is None or isinstance(commands, dict):
        return (commands or {}), ""
    return {}, f"commands is {_a_kind(commands)}; expected an object keyed by command name{_SHAPE_DOOR}"


def profile_command(profile, name: str = "one_test") -> tuple[dict, str]:
    """`(spec, problem)` of the command `name` of one profile: the command object, `{}` when there is none (absence is no
    problem), or `({}, problem)` when `commands` or the command is not an object. It reads nothing but `name`."""
    commands, problem = profile_commands(profile)
    if problem:
        return {}, problem
    spec = commands.get(name)
    if spec is None or isinstance(spec, dict):
        return (spec or {}), ""
    return {}, f"commands.{name} is {_a_kind(spec)}; expected an object {_COMMAND_SHAPE}{_SHAPE_DOOR}"


def command_argv(spec, *, drop_placeholders: bool = False) -> tuple[list, str]:
    """`(words, problem)`: the words of ONE command object, the only parsing of an `argv` (AR-13). No `argv`, or `[]`, is
    `([], "")`. An `argv` that is a string is never read letter by letter: `([], problem)`; so is a list that holds a
    boolean, an object, a list or a null (junk is not a word of a launch command). Strings and numbers are `str(word)`;
    an empty or blank word is dropped (it makes no command). `drop_placeholders` also drops a `<x>` word: the reading
    `execution_request` builds a run from. That is NOT `launch_check.strip_placeholders` (which removes the data-named
    positional placeholders together with the flag they are the value of): a different operation, not a copy of it."""
    if spec is None:
        return [], ""
    if not isinstance(spec, dict):
        return [], f"the command is {_a_kind(spec)}; expected an object {_COMMAND_SHAPE}{_SHAPE_DOOR}"
    argv = spec.get("argv")
    if argv is None:
        return [], ""
    if not isinstance(argv, (list, tuple)):
        return [], f"argv is {_a_kind(argv)}; expected an array of words{_SHAPE_DOOR}"
    words = []
    for word in argv:
        if isinstance(word, bool) or not isinstance(word, (str, int, float)):
            return [], f"argv holds {_a_kind(word)}; expected only words (strings){_SHAPE_DOOR}"
        text = str(word)
        if not text.strip() or (drop_placeholders and text.startswith("<") and text.endswith(">")):
            continue
        words.append(text)
    return words, ""


REPORT_HOLDER = "{report_path}"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")   # used with `fullmatch`: a `$` would let a trailing newline through
_ENV_DOOR = (f"a value here is exactly {REPORT_HOLDER}; a value of your own lives in your .env{_SHAPE_DOOR}")


def command_env(spec) -> tuple[dict, str]:
    """`(env, problem)`: the variables ONE command object sets for its launch, the only parsing of an `env` (EP1-22, AR-13).
    No `env`, `null` and `{}` are `({}, "")`: an absent `env` is the command as it always was. An `env` that is not an
    object, a name that is not a plain variable name, a value that is not exactly `{report_path}` (a secret or a path of this
    machine must never be written into the config the team shares, I-3) is a FOREIGN shape: `({}, problem)`, named and never
    read as `{}`. Pure, never raises. A spec that is not an object is `({}, "")`: `command_argv` already names that."""
    if not isinstance(spec, dict):
        return {}, ""
    env = spec.get("env")
    if env is None:
        return {}, ""
    if not isinstance(env, dict):
        return {}, f"env is {_a_kind(env)}; expected an object of variable name to {REPORT_HOLDER}{_SHAPE_DOOR}"
    for name, value in env.items():
        if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
            return {}, f"env names a variable {name!r} that is not a plain variable name (letters, digits, underscore){_SHAPE_DOOR}"
        if value != REPORT_HOLDER:
            return {}, f"env.{name} is not exactly {REPORT_HOLDER}: {_ENV_DOOR}"
    return dict(env), ""


def command_identity(spec) -> list:
    """The words that say WHICH command this is, the single input of every digest of a command (EP1-22 B-2, AR-13): the
    words of `argv` as `command_argv` reads them, and, when `env` is set, a separator word and `NAME=value` by sorted name
    (values as written, with `{report_path}`, never substituted). A command with no `env` is its `argv` words, byte for
    byte as before; the same words with another `env` are another command; `A={report_path}` as an argv word and `env: {A: ..}`
    are not the same command (the separator). Never raises; a foreign `env` reads as none (its problem is named elsewhere)."""
    words, _ = command_argv(spec)
    env, _ = command_env(spec)
    if env:
        words = words + ["\u0000env"] + [f"{name}={env[name]}" for name in sorted(env)]
    return words


def one_test_argv(profile, *, drop_placeholders: bool = False) -> tuple[list, str]:
    """`(words, problem)` of `commands.one_test.argv`: `profile_command` then `command_argv`. It does NOT read `run`,
    `install` or `collect` (a caller that falls back to another command asks `profile_command` for it by name)."""
    spec, problem = profile_command(profile, "one_test")
    if problem:
        return [], problem
    words, problem = command_argv(spec, drop_placeholders=drop_placeholders)
    return words, (f"commands.one_test.{problem}" if problem else "")


def selectors_verified(profile, root) -> bool:
    """Does this profile's selector contract count as verified? The ONE answer (AR-13): the probe's shape check
    (`probe_by_code.run_shape_checks`) and the typed run's request (`execution_request.build_mine_request`) both ask it.

    The hand wins, in both directions: a literal `selectors.verified` of `false` is False, of `true` is True. With no literal
    the profile's one-test command must be one the run-form table knows how to select a test with
    (`launch_check.runner_identity(argv)["selection"]`) AND the onboarding's durable record must say THIS command was rehearsed
    (`onboarding_probe.earlier_proof(root, profile_id, argv)["state"] == "same_command"`, with `argv` the one
    `onboarding_probe._one_test_argv` reads). That record proves that **the command with this digest was rehearsed, not that the
    selector selects**; it is enough for the gate only because a report row is bound by id (`red_sandbox.bind_row`): a selector
    that selected nothing leaves `not_executed` and one that selected too much binds the same row, so a wrong True never
    gives a pass. `root` is the PROJECT, never a sandbox clone (`--sandbox-root`): a clone holds no record, so it is False there.

    Error direction: False (the gate refuses and names its door). Another argv than the record's, no record, a table or a
    record that cannot be read, a `root` that is no directory, and any exception at all give False; nothing is written."""
    try:
        verified = (profile.get("selectors") or {}).get("verified") if isinstance(profile, dict) else None
        if verified is False:
            return False
        if verified is True:
            return True
        if not isinstance(profile, dict) or root is None:
            return False
        import launch_check
        import onboarding_probe
        argv = onboarding_probe._one_test_argv(profile)
        if not argv or not launch_check.runner_identity(argv)["selection"]:
            return False
        proof = onboarding_probe.earlier_proof(root, str(profile.get("profile_id") or ""), argv)
        return proof.get("state") == "same_command"
    except Exception:       # noqa: BLE001 - a gate that cannot tell says False, the safe side
        return False


def resolve_profile_command(profile: dict, command_name: str,
                            repo_roots: dict[str, Path], job_report_path: Path) -> dict:
    """Resolve one command against its own repository and reporter contract. A profile whose commands cannot be read
    is a ValueError that says so (the shape problem), as an unknown command is."""
    commands, problem = profile_commands(profile)
    if problem:
        raise ValueError(f"profile command {command_name!r}: {problem}")
    command = commands.get(command_name)
    if not isinstance(command, dict):
        raise ValueError(f"unknown profile command {command_name!r}")
    words, problem = command_argv(command)
    if problem:
        raise ValueError(f"profile command {command_name!r}: {problem}")
    repo_id = str(command.get("repo_id") or "")
    if repo_id not in repo_roots:
        raise ValueError(f"command repository {repo_id!r} is not resolved")
    root = Path(repo_roots[repo_id]).resolve()
    cwd = Path(str(command.get("cwd") or ""))
    cwd = cwd if cwd.is_absolute() else root / cwd
    reporter = command.get("reporter") or {}
    template = str(reporter.get("path_template") or "")
    report_path = str(job_report_path.resolve())
    env, problem = command_env(command)
    if problem:
        raise ValueError(f"profile command {command_name!r}: {problem}")
    argv = [part.replace("{report_path}", report_path) for part in words]
    return {"repo_id": repo_id, "framework_adapter": command.get("framework_adapter"),
            "kind": command.get("kind"), "scope": command.get("scope"), "argv": argv,
            "env": {name: value.replace("{report_path}", report_path) for name, value in env.items()},
            "cwd": str(cwd.resolve()), "reporter": {"format": reporter.get("format"),
            "path": template.replace("{report_path}", report_path)},
            "selectors": command.get("selectors") or {}}


def validate_implementation_repo(repo: dict, path: str = "implementation_repo") -> list[str]:
    errors: list[str] = []
    for key in ("repo_id", "role", "local_path", "remote_identity", "source_ref",
                "source_sha", "execution_profile_id"):
        if not _nonempty(repo.get(key)):
            _error(errors, f"{path}.{key}", "must be a non-empty string")
    if not isinstance(repo.get("write_target"), bool):
        _error(errors, f"{path}.write_target", "must be boolean")
    if repo.get("write_target"):
        for key in ("working_branch", "base_sha"):
            if not _nonempty(repo.get(key)):
                _error(errors, f"{path}.{key}", "is required for a write target")
    if not isinstance(repo.get("readiness_evidence"), list):
        _error(errors, f"{path}.readiness_evidence", "must be an array")
    return errors


def validate_config(cfg: dict) -> list[str]:
    """Validate only the new contract. A legacy config with no profiles remains valid."""
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return ["config: must be an object"]
    profiles = cfg.get("profiles")
    if profiles is None:
        return errors
    if not isinstance(profiles, list):
        return ["profiles: must be an array"]
    ids: set[str] = set()
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            errors.append(f"profiles[{index}]: must be an object")
            continue
        errors.extend(validate_profile(profile, f"profiles[{index}]"))
        pid = profile.get("profile_id")
        if _nonempty(pid) and pid in ids:
            errors.append(f"profiles[{index}].profile_id: duplicate {pid!r}")
        if _nonempty(pid):
            ids.add(pid)       # a list or an object as an id is already an error above, and is no id to be named
    repos = cfg.get("implementation_repos")
    if repos and not isinstance(repos, list):
        errors.append("implementation_repos: must be an array")
        repos = []
    for index, repo in enumerate(repos or []):
        if not isinstance(repo, dict):
            errors.append(f"implementation_repos[{index}]: must be an object")
            continue
        errors.extend(validate_implementation_repo(repo, f"implementation_repos[{index}]"))
        pid = repo.get("execution_profile_id")
        if _nonempty(pid) and pid not in ids:
            errors.append(f"implementation_repos[{index}].execution_profile_id: unknown profile {pid!r}")
    dependencies = cfg.get("managed_dependencies")
    if dependencies and not isinstance(dependencies, list):
        errors.append("managed_dependencies: must be an array")
        dependencies = []
    for index, dep in enumerate(dependencies or []):
        dp = f"managed_dependencies[{index}]"
        if not isinstance(dep, dict):
            errors.append(f"{dp}: must be an object")
            continue
        for key in ("dependency_id", "upstream_source", "exact_version_or_revision",
                    "capability", "consumer", "owner"):
            if not _nonempty(dep.get(key)):
                errors.append(f"{dp}.{key}: must be a non-empty string")
        if not _in(dep.get("status", "unknown"), PROFILE_STATUSES):
            errors.append(f"{dp}.status: must be one of {sorted(PROFILE_STATUSES)}")
    return errors


def selected_profiles(cfg: dict) -> list[dict]:
    """The profiles that take part: the `selected` ones (a profile with no `selected` key is selected, `selected: false` sits
    out), or all of them when none is selected. The one reading (AR-13): `execution_request` and the dependency checks both read
    this one function (the request builder keeps no copy of the rule)."""
    profiles = [p for p in (cfg.get("profiles") or []) if isinstance(p, dict) and p.get("profile_id")]
    return [p for p in profiles if p.get("selected", True)] or profiles


def _said(value) -> str:
    """A value of a foreign type as a short word for a gap (never raises, never long)."""
    return (value if isinstance(value, str) else repr(value))[:80]


def _word_list(value, what: str) -> tuple[list, str]:
    """(words, problem): a list of strings, or [] and the sentence that names what it was instead (OH3-30). Absent / empty is []."""
    if not value:
        return [], ""
    if not isinstance(value, list) or not all(isinstance(w, str) for w in value):
        return [], f"`{what}` is not a list of words"
    return value, ""


def capability_gaps(cfg: dict, profile: dict) -> list[dict]:
    """The capability gaps of ONE profile (OH3-30; the one reading, AR-13: `profile_readiness` and the onboarding listing both
    read it). A capability that is not in `supported_capabilities` is `unsupported`; one whose adapter has no matrix, or a matrix
    that does not list it, is `unknown` / `unsupported`. A value of a foreign type is a gap `unknown` that says so and never an
    exception: the ERROR DIRECTION is toward "not ready", never toward a pass (AR-28)."""
    wanted = profile.get("capabilities")
    if wanted is None:          # absent or null: no declaration, as before (a setup-only profile; pinned by two neighbour tests)
        wanted = []
    if not isinstance(wanted, list):
        # the type is checked BEFORE any default: `{}`, `0`, `""` and `False` are a declaration of a foreign type, never a
        # pass (AR-28); `[]` and an absent key keep their reading, queued for the Lead
        return [{"capability": "capabilities", "status": "unknown", "note": "`capabilities` is not a list of words"}]
    supported, supported_problem = _word_list(cfg.get("supported_capabilities"), "supported_capabilities")
    matrix = cfg.get("adapter_capabilities") or {}
    matrix_problem = "" if isinstance(matrix, dict) else "`adapter_capabilities` is not an object"
    adapter_id = profile.get("adapter_id")
    adapter_caps, adapter_problem = None, ""
    if not matrix_problem:
        try:
            adapter_caps = matrix.get(adapter_id)
        except TypeError:           # an unhashable id is no key at all
            adapter_problem = "the adapter id is not a word"
    gaps: list[dict] = []
    for capability in wanted:
        word = _said(capability)
        if not isinstance(capability, str):
            gaps.append({"capability": word, "status": "unknown", "note": "this capability is not a word"})
        elif supported_problem or matrix_problem or adapter_problem:
            gaps.append({"capability": word, "status": "unknown",
                         "note": supported_problem or matrix_problem or adapter_problem})
        elif capability not in supported:
            gaps.append({"capability": capability, "status": "unsupported",
                         "note": "capability is absent from the supported catalogue"})
        elif not isinstance(adapter_caps, list):
            gaps.append({"capability": capability, "status": "unknown",
                         "note": f"adapter {adapter_id!r} has no verified capability matrix"})
        elif capability not in adapter_caps:
            gaps.append({"capability": capability, "status": "unsupported",
                         "note": f"adapter {adapter_id!r} does not support this capability"})
    return gaps


def profile_readiness(cfg: dict, selected: list[str] | None = None,
                      root: Path | None = None) -> dict[str, dict]:
    """Return scoped readiness. Unselected profiles and their tools cannot block the result."""
    # only a row that is an object with a STRING id is keyed: a list as an id is no key at all (it was a TypeError, and the
    # config the validator now refuses by name must still be readable here: OH3-27)
    rows = cfg.get("profiles")
    profiles = {p["profile_id"]: p for p in (rows if isinstance(rows, list) else [])
                if isinstance(p, dict) and isinstance(p.get("profile_id"), str)}
    wanted = selected if selected is not None else list(profiles)
    deps = cfg.get("managed_dependencies")
    catalogue = {d["dependency_id"]: d for d in (deps if isinstance(deps, list) else [])
                 if isinstance(d, dict) and isinstance(d.get("dependency_id"), str) and d["dependency_id"]}
    result: dict[str, dict] = {}
    base = (root or Path.cwd()).resolve()
    for pid in wanted:
        profile = profiles.get(pid)
        if not profile:
            result[pid] = {"status": "unknown", "owner": "user", "note": "profile is not configured"}
            continue
        gaps: list[dict] = capability_gaps(cfg, profile)
        dep_ids = profile.get("dependency_ids") or []
        if not isinstance(dep_ids, list):       # a foreign shape is named, never raised (the OH3-30 point 4 class)
            gaps.append({"dependency_id": _said(dep_ids), "status": "unknown", "note": "`dependency_ids` is not a list of words"})
            dep_ids = []
        for dep_id in dep_ids:
            dep = catalogue.get(dep_id) if isinstance(dep_id, str) else None
            if not dep:
                gaps.append({"dependency_id": _said(dep_id), "status": "unknown",
                             "note": "dependency is undeclared" if isinstance(dep_id, str) else "this dependency id is not a word"})
                continue
            status = dep.get("status", "unknown")
            executable = str(dep.get("executable") or "").strip()
            located = shutil.which(executable) if executable else None
            if executable and not located:
                gaps.append({"dependency_id": dep_id, "status": "unavailable",
                             "note": f"declared executable {executable!r} was not found"})
            elif status != "ready":
                gaps.append({"dependency_id": dep_id, "status": status,
                             "note": dep.get("note", "dependency has no verified installation")})
        commands, problem = profile_commands(profile)
        if problem:     # a foreign shape is named, never read as "no commands" (OH3-27)
            gaps.append({"command": "commands", "status": "unavailable", "note": problem})
        for name, command in commands.items():
            if not isinstance(command, dict) or command.get("kind") == SETUP_KIND:
                continue        # a `setup` command is printed to a person, never run: it never makes a profile unavailable
            cwd = Path(str(command.get("cwd") or ""))
            cwd = cwd if cwd.is_absolute() else base / cwd
            if not cwd.is_dir():
                gaps.append({"command": name, "status": "unavailable",
                             "note": f"command cwd does not exist: {cwd}"})
            argv, problem = command_argv(command)
            if problem:     # a string `argv` is not read by its letters: the command is unavailable, and says why
                gaps.append({"command": name, "status": "unavailable", "note": problem})
                continue
            executable = argv[0] if argv else ""
            resolved = shutil.which(executable)
            if executable and not resolved:
                candidate = cwd / executable
                if not candidate.is_file():
                    gaps.append({"command": name, "status": "unavailable",
                                 "note": f"command executable was not found: {executable}"})
        status = "ready"
        for candidate in ("unsupported", "unavailable", "unknown"):
            if any(g.get("status") == candidate for g in gaps):
                status = candidate
                break
        result[pid] = {"status": status, "owner": profile.get("readiness_owner", "user"), "gaps": gaps}
    return result


def implementation_repo_readiness(cfg: dict, profiles: dict[str, dict],
                                  root: Path | None = None) -> list[dict]:
    """Project source identity and write baseline readiness, kept per repository."""
    records: list[dict] = []
    base = (root or Path.cwd()).resolve()
    for repo in cfg.get("implementation_repos") or []:
        if not isinstance(repo, dict):
            continue
        errors = validate_implementation_repo(repo)
        local = Path(str(repo.get("local_path") or ""))
        local = local if local.is_absolute() else base / local
        if not local.is_dir():
            errors.append(f"implementation_repo.local_path: checkout does not exist: {local}")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", str(repo.get("source_sha") or "")):
            errors.append("implementation_repo.source_sha: must be an immutable hexadecimal SHA")
        profile_id = repo.get("execution_profile_id")     # a list is no key: unknown, not a TypeError (OH3-30)
        profile = profiles.get(profile_id, {"status": "unknown"}) if isinstance(profile_id, str) else {"status": "unknown"}
        status = "ready" if not errors and profile.get("status") == "ready" else profile.get("status", "unknown")
        if errors:
            status = "unavailable"
        records.append({"repo_id": repo.get("repo_id", ""), "status": status,
                        "source_ref": repo.get("source_ref", ""),
                        "source_sha": repo.get("source_sha", ""),
                        "execution_profile_id": repo.get("execution_profile_id", ""),
                        "readiness_evidence": repo.get("readiness_evidence", []), "errors": errors})
    return records


NO_CHANGED_FILE = "no_changed_file"   # `reason_code` of a probe that compared nothing: the story's diff has no file here
IMAGE_IDENTITY_RE = re.compile(r"image:sha256:[0-9a-f]{64}")
CONTENT_SHA64 = re.compile(r"[0-9a-f]{64}")


def no_changed_file(record) -> bool:
    """A probe answer `not_applicable` whose FIELD `reason_code` says the story changes no file of this
    profile's checkout (runtime_probe.py, t-238 W4). Such a probe names no stand to identify, so it is enough
    on ANY stand kind - a docker stand included - and not only on a verified local_source profile (t-279 K-NA).
    The reason is read from the field and never from the `reason` sentence (FR-12): a `not_applicable` with no
    `reason_code` (a probe file of an older release, a hand-written one) is not this, and keeps the old rule."""
    return (isinstance(record, dict) and record.get("result") == "not_applicable"
            and record.get("reason_code") == NO_CHANGED_FILE)


def image_identity(record) -> bool:
    """A probe answer that is `unknown` and still names WHICH image the container runs
    (`image:sha256:<64 hex>`, runtime_probe.py on a container with no sources, t-279 K-IMG): an honest weaker
    identity. It is never `matched` and satisfies no rule that asks for `matched`. Since t-300 N2 (Q18-B, FR-59) NO reader
    accepts it - the manual capture and its record used to, and refuse it now: an `unknown` is taken by no token, and the
    person's word at the build question (`person_confirmed`) is the door for such a stand. The function stays as the way to
    ask "does this unknown still name an image" (a reader that wants to say so in its refusal), not as a pass."""
    return (isinstance(record, dict) and record.get("result") == "unknown"
            and bool(IMAGE_IDENTITY_RE.fullmatch(str(record.get("observed_runtime_identity") or ""))))


def validate_runtime_provenance(record: dict) -> dict:
    """Validate an execution identity without upgrading weak evidence to `matched`."""
    declared = record.get("result")
    errors: list[str] = []
    for key in ("profile_id", "timestamp", "environment_id", "expected_source_revision"):
        if not _nonempty(record.get(key)):
            errors.append(f"{key} is required")
    if declared not in PROVENANCE_RESULTS:
        errors.append(f"result must be one of {sorted(PROVENANCE_RESULTS)}")
    if declared != "not_applicable" and not _nonempty(record.get("observed_runtime_identity")):
        errors.append("observed_runtime_identity is required")
    evidence = record.get("evidence_refs")
    if not isinstance(evidence, list) or (declared == "matched" and not evidence):
        errors.append("evidence_refs must be a non-empty array for matched provenance")
    try:
        datetime.fromisoformat(str(record.get("timestamp", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("timestamp must be ISO-8601")
    provenance = record.get("provenance") or {}
    technical = bool(provenance.get("technical_verification"))
    linkage = provenance.get("source_linkage")
    if declared == "matched" and (not technical or linkage not in {"exact", "verified_content"}):
        errors.append("matched requires technical verification and exact or verified_content source linkage")
    expected_mr = record.get("mr_source_revision")
    expected_source = record.get("expected_source_revision")
    deployed_source = provenance.get("deployed_source_revision")
    verified_revisions = provenance.get("verified_source_revisions")
    if verified_revisions is not None and (not isinstance(verified_revisions, list) or not verified_revisions or
            any(not _nonempty(value) for value in verified_revisions)):
        errors.append("verified_source_revisions must be a non-empty string array when provided")
        verified_revisions = []
    verified_revisions = set(verified_revisions or [])
    required_content_revisions = {value for value in (expected_source, expected_mr) if value}
    content_bound = (linkage == "verified_content" and technical and bool(evidence) and
                     required_content_revisions.issubset(verified_revisions))
    # A person's word is a record of its own kind (t-300): it carries the words, the time and the revision the
    # person named, it never claims a technical verification, and `identity_kind: person_confirmed` belongs to it
    # alone - a `matched` record that carries it is the word dressed up as a reading, which is refused.
    if declared == "person_confirmed":
        confirmation = record.get("person_confirmation")
        if not isinstance(confirmation, dict) or not _nonempty(confirmation.get("words")) \
                or not _nonempty(confirmation.get("at")):
            errors.append("person_confirmed requires person_confirmation with the person's words and the time")
        if technical:
            errors.append("person_confirmed is the person's word: technical_verification must be false")
        if provenance.get("identity_kind") != "person_confirmed":
            errors.append("person_confirmed requires provenance.identity_kind person_confirmed")
        tested = record.get("tested_build")
        if tested is not None and (not isinstance(confirmation, dict) or tested != confirmation.get("revision")):
            errors.append("tested_build must be the revision the person confirmed (person_confirmation.revision)")
    elif provenance.get("identity_kind") == "person_confirmed":
        errors.append("identity_kind person_confirmed belongs to a person_confirmed record only")
    effective = declared if declared in PROVENANCE_RESULTS else "unknown"
    if declared == "person_confirmed":
        # Never upgraded and never downgraded: a deployed revision that differs from the expected one is exactly
        # the `test deployed` case (the person tests what is there), and the record says both revisions. An
        # invalid one is `unknown`: a word that does not hold together answers nothing.
        effective = "unknown" if errors else "person_confirmed"
    elif declared == "not_applicable":
        # A probe that does not apply compared nothing (runtime_probe.py: the story changes no file
        # of this checkout), so there is no deployed revision for it to disagree with: never
        # downgraded to `mismatched`, whatever a `deployed_source_revision` field next to it says
        # and whether or not the record is content-bound (t-238 W4).
        pass
    elif expected_mr and deployed_source and expected_mr != deployed_source and not content_bound:
        effective = "mismatched"
    elif expected_source and deployed_source and expected_source != deployed_source and not content_bound:
        effective = "mismatched"
    elif declared == "matched" and errors:
        effective = "unknown"
    return {"valid": not errors, "result": effective, "errors": errors}


# The three words of a person's confirmation that can reach a run (stand_identity.CONFIRM_KINDS without `withdrawn`, which
# is no word at all): `deployed` = "this story's build is on the stand", `test_deployed` = "test the build that is there",
# `content_accepted` = "test the stand as it is although these files differ" (bound to the bytes the probe compared).
PERSON_KINDS = ("deployed", "test_deployed", "content_accepted")


def person_confirmed_problems(record, task=None) -> list:
    """What a person's word lacks to count at a run (t-300 N2 X5/X6, E2): it must SAY what it was given for - the kind,
    the story, the revision - and the revisions must agree with the record it sits in: a `deployed` word names this
    story's own commit (`expected_source_revision`); a `test_deployed` word names the build under test (`revision` =
    `tested_build`) and this story's commit (`story_revision` = `expected_source_revision`). With `task`, the word must
    be the one given for THAT story (one story's word never lets another's run start, E5). Empty list = nothing lacks.
    ERROR DIRECTION: only toward refusal; a word the probe wrote through `runtime_probe.confirm_record` has all of it."""
    if not isinstance(record, dict):
        return ["the record is not an object"]
    confirmation = record.get("person_confirmation")
    if not isinstance(confirmation, dict):
        return ["person_confirmation is missing"]
    problems = []
    kind = confirmation.get("kind")
    if kind not in PERSON_KINDS:
        problems.append("person_confirmation.kind must be one of " + ", ".join(PERSON_KINDS))
    for key in ("task", "revision"):
        if not _nonempty(confirmation.get(key)):
            problems.append(f"person_confirmation.{key} is required: the word must say what it was given for")
    expected = record.get("expected_source_revision")
    if kind == "deployed" and confirmation.get("revision") != expected:
        problems.append("a `deployed` word must name this story's commit (person_confirmation.revision must equal "
                        "expected_source_revision)")
    if kind == "test_deployed":
        if confirmation.get("story_revision") != expected:
            problems.append("a `test_deployed` word must name this story's commit (person_confirmation.story_revision "
                            "must equal expected_source_revision)")
        if not _nonempty(record.get("tested_build")) or record.get("tested_build") != confirmation.get("revision"):
            problems.append("a `test_deployed` word names the build under test: tested_build must equal "
                            "person_confirmation.revision")
        if _nonempty(confirmation.get("revision")) and confirmation.get("revision") == confirmation.get("story_revision"):
            # t-300 N2 F5: a word that says "ANOTHER build" while naming this story's own commit is a `deployed` word in
            # disguise - and it would fingerprint like the factory's own `matched` reading of that commit
            problems.append(say_refusal("confirmation_same_build"))
    if kind == "content_accepted":
        if confirmation.get("revision") != expected:
            problems.append("a `content_accepted` word must name this story's commit (person_confirmation.revision must "
                            "equal expected_source_revision)")
        identity = record.get("content_identity")
        if not (isinstance(identity, str) and CONTENT_SHA64.fullmatch(identity)
                and confirmation.get("content") == identity):
            problems.append("a `content_accepted` word names the content it was given for: person_confirmation.content must "
                            "equal the record's content_identity (64 hex)")
        accepted = record.get("accepted_files")
        if not (isinstance(accepted, list) and any(_nonempty(f) for f in accepted)):
            problems.append("a `content_accepted` word names the files it accepts: accepted_files must be a non-empty list")
        if record.get("tested_build") is not None:
            problems.append("a `content_accepted` word names no other build: tested_build must be absent")
    if task is not None and _nonempty(confirmation.get("task")) and confirmation.get("task") != task:
        problems.append(f"the person's word was given for story {confirmation.get('task')}, and this is story {task}")
    return problems


def person_confirmed(record, task=None) -> bool:
    """A probe answer that is the PERSON'S WORD about the build (t-300): `result: person_confirmed`, valid by
    `validate_runtime_provenance` (the words and the time, no technical verification, a non-empty identity, a
    `tested_build` that is the revision the person confirmed) AND bound to what it was given for
    (`person_confirmed_problems`: kind, story, revisions - t-300 N2 X6). It is never `matched`; a reader that wants a
    verified build refuses it, and the one that accepts a word says so by name (`acceptable_provenance`)."""
    if not isinstance(record, dict) or record.get("result") != "person_confirmed":
        return False
    checked = validate_runtime_provenance(record)
    return (bool(checked["valid"]) and checked["result"] == "person_confirmed"
            and not person_confirmed_problems(record, task))


ACCEPTS = ("matched", "person_confirmed", "not_applicable:no_changed_file")
# What a rehearsal view puts in the place of the evidence file a rehearsal never writes (FR-45): the record is
# validated as if its one evidence reference were there, and that is the only rule it is excused from.
REHEARSAL_EVIDENCE = "rehearsal:no-evidence-written"


def rehearsal_view(record):
    """The record as a REHEARSAL reader validates it: a `matched` that says it was observed without an evidence file
    (`observed_without_evidence: true`, `evidence_refs: []` - what `runtime_probe.py --no-evidence` prints) with the
    evidence rule satisfied by a stand-in. Anything else comes back as it is. This is the ONLY excuse a rehearsal
    has, and `validate_runtime_provenance` itself never gives it: a caller that wants it asks for the view by name
    (`acceptable_provenance(rehearsal=True)`, and `execution_request` for the fingerprint of a freshness read)."""
    if (isinstance(record, dict) and record.get("result") == "matched" and record.get("observed_without_evidence") is True
            and record.get("evidence_refs") == []):
        return dict(record, evidence_refs=[REHEARSAL_EVIDENCE])
    return record


def acceptable_provenance(record, accepts, *, rehearsal: bool = False, task=None) -> bool:
    """Whether this probe answer is one the caller may take, by the caller's own list (t-300 F11: ONE reading, so a
    reader never spells its own). `accepts` holds tokens from `ACCEPTS`; any other token is a programming error
    (ValueError), never a silent refusal. ERROR DIRECTION: only toward refusal - the exact word (`MATCHED` is not
    `matched`), a record that validates, and an effective result equal to the declared one (a `matched` record that
    `validate_runtime_provenance` reads as `mismatched` is refused). `task` (t-300 N2 X5): the story the caller serves;
    a person's word given for another story is refused (the word is bound to its story, E5).

    `rehearsal=True` is for a caller that RAN the probe with `--no-evidence` (a rehearsal writes nothing, FR-45): it
    excuses ONE rule, "a matched record names an evidence file", and only for a record that says it was observed
    without one (`observed_without_evidence: true`, `evidence_refs: []`). The marker without `rehearsal=True` is
    refused, and so is `rehearsal=True` without the marker: the strict reader (`validate_runtime_provenance`,
    `run_suite.probe_runtime`) is unchanged."""
    unknown = [token for token in accepts if token not in ACCEPTS]
    if unknown:
        raise ValueError(f"unknown acceptance token(s) {unknown}; the tokens are {list(ACCEPTS)}")
    if not isinstance(record, dict):
        return False
    declared = record.get("result")
    checked = validate_runtime_provenance(rehearsal_view(record) if rehearsal else record)
    if not checked["valid"] or checked["result"] != declared:
        return False
    if declared == "matched":
        return "matched" in accepts
    if declared == "person_confirmed":
        return "person_confirmed" in accepts and person_confirmed(record, task)
    if declared == "not_applicable":
        return "not_applicable:no_changed_file" in accepts and no_changed_file(record)
    return False


# --- the words of a refusal (t-300 N2, X10) -------------------------------------------------------------------------
# A reader that refuses a probe answer says WHAT the probe said, what was expected and the door (FR-1), in words that
# are DATA: the `refusals` block of references/build-identity-methods.json (FR-13). TEMPORAL: before that block exists
# (a package that has not got the file's N2 revision, an unreadable file) every refusal site must still produce a
# sentence, so the same texts stand here as a default - ONE place, read by every site through `refusal_words()`; once
# the block exists its text wins, key by key. The move that creates the block is t-300 N2 (the data file's revision).
REFUSAL_DEFAULTS = {
    "mismatched": "runtime probe returned mismatched: the stand runs {build} and this story is {expected}. Redeploy this "
                  "story's build, or the person answers `test deployed` to the build question at the stage entry.",
    "content_mismatch": "runtime probe returned mismatched: the stand serves other content for {files}. Redeploy this "
                        "story's build, or the person answers `test as is` to the build question at the stage entry when "
                        "those files do not change what the tests check.",
    "files_more": " and {more} more",
    "other": "runtime probe returned {word}: {reason}",
    "no_reason": "the probe gave no reason",
    "voided": "The person's word of {date} no longer holds: {what}",
    "not_applicable": "runtime not_applicable requires a verified local_source profile contract, or a probe that says "
                      "`reason_code: no_changed_file` (the story changes no file of this profile's checkout)",
    "invalid": "runtime probe returned unverified provenance: {problems}",
    "not_a_record": "runtime probe did not return a provenance record (a JSON object)",
    "build_unknown": "another build",
    "commit_unknown": "a commit it could not name",
    "probe_failed": "runtime probe failed: {why}",
    "probe_failed_silent": "it exited with code {code} and printed no reason on stderr",
    "probe_not_json": "runtime probe did not return JSON: {why}",
    "probe_not_json_line": "it printed: {line}",
    "probe_not_json_silent": "it printed nothing",
    "person_confirmed": "the build was confirmed by the person ({words}, {date}), not read by the factory",
    "person_tested": "the build under test is {tested}, not this story's {expected}",
    "confirmation_same_build": "a `test_deployed` word names the build under test and this story's commit as the SAME build: "
                               "that is a `deployed` word, not another build - answer `deployed`, or name the other build",
    "person_runtime_off": "a person's word (person_confirmed) stands only on a run whose stand the probe re-reads at launch: "
                          "this request says runtime_required false, so it is refused",
    "baseline_person": "manual baseline runtime provenance is unverified: a baseline is a measured old build, and a person's "
                       "word does not stand in for it",
    "remedy_other_build": "this story's build is not on the stand: the person redeploys it, or answers `test deployed` at the "
                          "build question of the stage entry. Do not capture this case again before that",
    "remedy_other_content": "this story's files are not what the stand serves: the person redeploys this story's build, or "
                            "answers `test as is` at the build question of the stage entry when those files do not change "
                            "what the tests check. Do not capture this case again before that",
    "person_content": "the person said to test the stand as it is although {files} differ from this story's ({words}, "
                      "{date}); the factory compared the other files",
    "remedy_unknown_asks": "which build the stand runs is not known here: the person answers the build question of the stage "
                           "entry (their decision is kept in {registry}). Do not capture this case again before that",
    "remedy_other_story": "the person's word on record was given for another story: the person answers the build question of "
                          "the stage entry for THIS story (their decision is kept in {registry}). Do not capture this case "
                          "again before that",
    "remedy_retry": "bring the stand up on the build under test, then capture again",
    "cause_build": "the stand does not hold this story's build (or nobody could say which build it holds), so a new capture "
                   "would meet the same stand",
    "door_build": "once the person has answered the build question for this story, or the stand runs its build, a later "
                  "dispatch starts a new attempt (leave --attempt out)",
}
REFUSAL_DATA = Path(__file__).resolve().parent.parent / "references" / "build-identity-methods.json"
SHORT_SHA = 12        # the shape of a commit in a sentence: 12 characters, never the whole 40
FILES_SHOWN = 3       # the files of a content mismatch a sentence names; the rest are counted


def refusal_words(path=None) -> dict:
    """The refusal sentences: the defaults, with the data file's `refusals` block over them key by key. A missing or
    unreadable file, or a file with no block, leaves the defaults (the temporal edge above): a refusal never goes
    silent because its words could not be read."""
    words = dict(REFUSAL_DEFAULTS)
    try:
        block = json.loads(Path(path or REFUSAL_DATA).read_text(encoding="utf-8-sig")).get("refusals")
    except (OSError, ValueError, AttributeError):
        block = None
    if isinstance(block, dict):
        words.update({k: v for k, v in block.items() if k != "note" and isinstance(v, str) and v.strip()})
    return words


def say_refusal(key: str, table=None, **slots) -> str:
    """One refusal sentence with its slots filled (`table`: the words already read by the caller, else read now). A
    template that names a slot the caller did not give comes back as written (an unfilled sentence still says what is
    wrong), never as a raise inside a refusal."""
    template = str((table or refusal_words()).get(key) or REFUSAL_DEFAULTS.get(key) or key)
    try:
        return template.format(**slots)
    except (KeyError, IndexError, ValueError):
        return template


def _first_line(text, limit=200) -> str:
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()[:limit]
    return ""


def probe_failed_text(returncode, stderr="") -> str:
    """A probe that exited non-zero, said with ITS reason: the first line it wrote to stderr (the real probe's exit 2 says
    "no story is running ... Pass --task"), never the bare "runtime probe failed" (t-300 N2 F4, FR-1)."""
    words = refusal_words()
    line = _first_line(stderr)
    return say_refusal("probe_failed", words, why=line or say_refusal("probe_failed_silent", words, code=returncode))


def probe_not_json_text(stdout="") -> str:
    words = refusal_words()
    line = _first_line(stdout, 120)
    return say_refusal("probe_not_json", words,
                       why=say_refusal("probe_not_json_line", words, line=line) if line
                       else say_refusal("probe_not_json_silent", words))


def shown_files(files, table=None) -> str:
    """The files a sentence names: the first `FILES_SHOWN`, the rest counted ("and N more"); "" when there are none. The ONE
    spelling, for the refusal, the manual evidence and the report line of a content mismatch."""
    names = [str(f) for f in files or [] if isinstance(f, str) and f.strip()]
    text = ", ".join(names[:FILES_SHOWN])
    if len(names) > FILES_SHOWN:
        text += say_refusal("files_more", table, more=len(names) - FILES_SHOWN)
    return text


def _short(value) -> str:
    return str(value or "").strip()[:SHORT_SHA]


def stand_runs_other_build(record) -> bool:
    """A probe answer that PROVES the stand runs a build that is not this story's (a sha that is another commit, or files
    whose content differs): the stand's own fact, which a role cannot fix and a person answers at the build question - as
    against an `unknown`, which says only that nothing could be read. Read from the effective result of the validator,
    never from a sentence (FR-12). Used to choose WHICH words a refusing reader says (t-300 N2 X9, X13)."""
    return isinstance(record, dict) and validate_runtime_provenance(record)["result"] == "mismatched"


def content_differs(record) -> bool:
    """A proven mismatch whose evidence is CONTENT (files that differ: `deployed_source_revision: content_mismatch` or
    `differing_files`), not a commit: there is no build to name, so `test deployed` is not offered; the door is the person's
    `test as is`, bound to the bytes (FB-8; draft R(cm), FR-10). Read from fields (FR-12)."""
    if not isinstance(record, dict):
        return False
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    return provenance.get("deployed_source_revision") == "content_mismatch" or any(
        isinstance(f, str) and f.strip() for f in record.get("differing_files") or [])


def refusal_text(record, *, task=None) -> str:
    """The sentence that says why a probe answer was refused (t-300 N2): built from FIELDS of the record only (FR-12),
    its words from `refusal_words()`. A proven mismatch names the build the stand runs, this story's commit and the door
    (a redeploy; `test deployed` when the build is a commit); a content mismatch names the files; `unknown` quotes the
    probe's own `error` and `remedy`; a person's word that no longer holds says what moved (`voided`) - a moved
    `test_deployed` word comes back `mismatched` + `voided`, an unconfirmed one plain `mismatched`. A record that gave
    no reason says so - never the bare "unverified provenance"."""
    words = refusal_words()
    if not isinstance(record, dict):
        return say_refusal("not_a_record", words)
    checked = validate_runtime_provenance(record)
    declared = record.get("result")
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    voided = record.get("voided") if isinstance(record.get("voided"), dict) else {}
    clause = (say_refusal("voided", words, date=str(voided.get("earlier_at") or "")[:10] or "an earlier day",
                          what=str(voided.get("what")))
              if _nonempty(voided.get("what")) else "")
    if checked["result"] == "mismatched":
        deployed = provenance.get("deployed_source_revision")
        differing = [str(f) for f in record.get("differing_files") or [] if isinstance(f, str) and f.strip()]
        if content_differs(record):
            text = say_refusal("content_mismatch", words,
                               files=shown_files(differing, words) or CONTENT_FILES_FALLBACK)
        else:
            text = say_refusal("mismatched", words,
                               build=_short(deployed) or say_refusal("build_unknown", words),
                               expected=_short(record.get("expected_source_revision"))
                               or say_refusal("commit_unknown", words))
        return text + (" " + clause + "." if clause else "")
    if declared == "not_applicable" and checked["valid"]:
        return say_refusal("not_applicable", words)
    if declared in PROVENANCE_RESULTS and declared != "unknown":
        problems = list(checked["errors"])
        if declared == "person_confirmed":
            problems += [p for p in person_confirmed_problems(record, task) if p not in problems]
        if problems:
            return say_refusal("invalid", words, problems="; ".join(problems))
    parts = [str(record.get(key)).strip() for key in ("error", "remedy") if _nonempty(record.get(key))]
    if _nonempty(declared) and declared not in PROVENANCE_RESULTS:
        parts.append("its result is not one of " + ", ".join(sorted(PROVENANCE_RESULTS)))
    if clause:
        parts.append(clause)
    return say_refusal("other", words, word=declared if _nonempty(declared) else "no result",
                       reason=". ".join(parts) or say_refusal("no_reason", words))


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate QA profile contracts")
    parser.add_argument("config", type=Path)
    parser.add_argument("--profiles", default="", help="comma-separated selected profile ids")
    parser.add_argument("--provenance", type=Path)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    errors = validate_config(cfg)
    selected = [x.strip() for x in args.profiles.split(",") if x.strip()] or None
    out: dict[str, Any] = {"valid": not errors, "errors": errors,
                           "profiles": profile_readiness(cfg, selected)}
    if args.provenance:
        out["provenance"] = validate_runtime_provenance(
            json.loads(args.provenance.read_text(encoding="utf-8")))
    print(json.dumps(out, indent=2))
    raise SystemExit(0 if out["valid"] and out.get("provenance", {}).get("valid", True) else 1)


if __name__ == "__main__":
    main()
