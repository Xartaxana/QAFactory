"""Fingerprint exact declared inputs from disk, never from a display name or claimed PASS.

`config_sha` (EP2-1, spec t-143) hashes the execution-relevant configuration of ONE profile, not the bytes of the
project's `qa-factory/config.json`: the spec names that file as `project_config`, and its record in the config list is
replaced by a projection - the run's profile row, `run`, `execution`, the `environment` pointers, the selected stand's
name and address, `tests_root`, minus every `note`/`*_note` - while every other config file is hashed whole, as before.
What is kept lives in data, `references/config-projection.json` (read by `projection_rules`, carrying the
`policy_revision` the fingerprint records); the code holds only the selectors. The rule (R5): a project config that
cannot be read as a JSON object, a malformed `profiles` list or `environment` block, a nesting the hash cannot serialise,
a `project_config` that is not one of the config files, or a malformed rule file is a named refusal line in the one
compound; nothing is hashed around and there is no whole-file fallback. A spec without `project_config` hashes every
config file whole. Any new execution-relevant config input requires, in one change: (1) adding the key to the
`projection` rules of references/config-projection.json, (2) renaming its `policy_revision`, (3) updating the
dependency trace (spec t-143 appendix A); `scripts/tests/test_config_projection.py` K-G1 is the regression guard."""
import argparse
import ast
import builtins
import hashlib
import json
import os
import re
import sys
from pathlib import Path
import hooklib
from diff_scope import executable_sha, marker_names
from detector_verdict import compound
from env_probe import STAND_ADDRESS_KEYS
from event_store import content_hash
from role_cli import command_from_argv, epilog, run_guarded
from profile_contract import ACCEPTS, acceptable_provenance, refusal_text, validate_runtime_provenance


RECORD_EXAMPLE = '{"path": "tests/test_x.py", "sha256": "<64 hex>"}'
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
# What `build` reads of a specification (AR-13, AR-10): the keys that must be there, and the keys that hold lists of inputs.
# The runner is told both before the work (agents/qa-runner.md, references/execution-lifecycle.md; t-1355 N2-K7).
SPEC_REQUIRED = ("source_revision", "test_files", "config_files", "dependency_files", "runtime_provenance", "profile_id")
SPEC_FILE_LISTS = ("test_files", "helper_files", "config_files", "dependency_files")


def _input_record(raw, require_sha, where=""):
    """The ONE reader of a fingerprint input (EP1-8, AR-13): `(path, claimed sha256 or None)` from a path string or a
    `{path, sha256, kind?}` record (the shape `fingerprint_files` itself holds). `build` reads a spec's file lists with
    `require_sha=False` (a bare path is fine, a record's claim is checked); `verify_files` reads a request's
    `fingerprint_files` with `require_sha=True` (only a record that carries its claim is a recorded input). A claim
    that is present is checked or refused, never skipped: an empty or non-hex `sha256` is refused by name, so it is
    never ignored and never reported as changed bytes. `where` names the position (`test_files[2]`) in a refusal."""
    at = (where + ": ") if where else ""
    if isinstance(raw, dict):
        path, claimed = raw.get("path"), raw.get("sha256")
        if not isinstance(path, str) or not path:
            raise ValueError(at + "a fingerprint record requires a `path` string, got "
                             + ("none" if path is None else type(path).__name__) + "; write it like " + RECORD_EXAMPLE)
        if "sha256" not in raw:
            if require_sha:
                raise ValueError(at + "fingerprint file " + path + " requires path and sha256; write it like "
                                 + RECORD_EXAMPLE)
            return path, None
        if not isinstance(claimed, str) or not _SHA256.fullmatch(claimed):
            raise ValueError(at + "sha256 of " + path + " must be its 64-hex digest")
        return path, claimed.lower()
    if require_sha:
        raise ValueError(at + "fingerprint file requires path and sha256: a recorded input is a record like "
                         + RECORD_EXAMPLE + ", got " + type(raw).__name__)
    if isinstance(raw, Path):
        raw = str(raw)
    if not isinstance(raw, str) or not raw:
        raise ValueError(at + "a fingerprint input must be a path string or a record like " + RECORD_EXAMPLE
                         + ", got " + ("an empty string" if raw == "" else type(raw).__name__))
    return raw, None


def file_hash(path):
    """The sha256 of one file given as a path (str or Path). It takes no claim, so a `{path, sha256}` record is
    refused here rather than read with its claim dropped: records go through `_input_record`."""
    if not isinstance(path, (str, Path)):
        raise ValueError("file_hash takes a path, got " + type(path).__name__
                         + "; a {path, sha256} record goes through build or verify_files")
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("fingerprint input is unavailable: " + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_claim(path, claimed):
    """ONE comparison of a claimed sha256 with the bytes on disk, for build and verify_files. Returns the actual
    sha256. A file that is not there is refused first (`fingerprint input is unavailable`, as before); a claim that
    differs names the file."""
    actual = file_hash(path)
    if claimed is not None and claimed != actual:
        raise ValueError("input bytes changed: " + str(path))
    return actual


def verify_files(records):
    if not isinstance(records, list) or not records:
        raise ValueError("fingerprint_files must enumerate actual input files")
    for index, record in enumerate(records):
        path, claimed = _input_record(record, True, "fingerprint_files[%d]" % index)
        _check_claim(path, claimed)
    return True


def build(spec):
    """The fingerprint of a specification, or ONE refusal listing every problem of it (t-1355 N2-K1): a specification
    that is not an object is told alone; otherwise every absent key, the provenance refusal and every bad input (by its
    list and position) are collected in that order by `spec_problems` and raised as one `compound`."""
    if not isinstance(spec, dict):
        raise ValueError("fingerprint specification must be a JSON object")
    provenance_problems = []
    if "runtime_provenance" in spec and not isinstance(spec["runtime_provenance"], dict):
        provenance_problems.append("runtime_provenance must be an object")
    elif "runtime_provenance" in spec:
        try:
            checked = validate_runtime_provenance(spec["runtime_provenance"])
            # ONE predicate (t-300 N2 S7, FR-17): `matched`, a person's word (the run it fingerprints stands on it, and says so:
            # `runtime_sha` differs from a `matched` over the same image because the deployed revision does, so a green under the
            # word is never reused as a `matched` result, FR-18) and a probe that compared nothing. ANY valid `not_applicable`
            # stays fingerprinted too (X3: the local_source request has no probe word; its own gate is validate_request). An
            # `unknown`, a `mismatched` or a record that does not validate is refused, as before.
            if not (acceptable_provenance(spec["runtime_provenance"], ACCEPTS)
                    or (checked["valid"] and checked["result"] == "not_applicable")):
                provenance_problems.append("runtime provenance is unverified/mismatched: "
                                           + refusal_text(spec["runtime_provenance"]))
        except ValueError as exc:
            provenance_problems.append(str(exc))
    problems, groups, records = spec_problems(spec, provenance_problems)
    if problems:
        raise ValueError(compound(problems))
    runtime = spec["runtime_provenance"]
    stable_runtime = {key: runtime.get(key) for key in
                      ("profile_id", "environment_id", "expected_source_revision", "observed_runtime_identity")}
    stable_runtime["deployed_source_revision"] = runtime.get("provenance", {}).get("deployed_source_revision")
    if runtime.get("result") == "person_confirmed":
        # t-300 N2 F5: a run that stands on the person's word never shares `runtime_sha` with a `matched` one on the same
        # image - whatever the other fields hold (a project's own probe may print a `matched` with no deployed revision, and
        # a `test_deployed` word names the same build twice). The key exists ONLY for the word, so no `matched` fingerprint
        # (and no stored result under one) changes, and nothing needs migrating (FR-18).
        stable_runtime["confirmed_by"] = "person"
        confirmation = runtime.get("person_confirmation")
        if isinstance(confirmation, dict) and confirmation.get("kind") == "content_accepted":
            # FB-8: a word that accepted these exact bytes: other accepted bytes are another run (the key exists for this kind only)
            stable_runtime["accepted_content"] = confirmation.get("content")
    components = {"source_sha": spec["source_revision"],
                  "test_content_sha": content_hash(groups["test_files"] + groups["helper_files"]),
                  "config_sha": groups["config_sha"],
                  "dependency_sha": content_hash(groups["dependency_files"]),
                  "runtime_sha": content_hash(stable_runtime),
                  "policy_revision": groups["policy_revision"]}
    return {"input_fingerprint": content_hash(components), "fingerprint_components": components,
            "fingerprint_files": records}


def spec_problems(spec, provenance_problems=()):
    """The collector: `(problems, groups, records)` of a specification; `problems` is empty when it is fit to fingerprint.
    The verdict on `runtime_provenance` is a registered gate site (references/gate-registry.json names `build` for it), so
    `build` judges it and hands the problems in; they are listed right after the absent keys, before the file lists.
    The projection group (R5.1) runs only when nothing else was refused, so a direct caller passes a valid provenance."""
    if not isinstance(spec, dict):
        raise ValueError("fingerprint specification must be a JSON object")
    problems = ["fingerprint specification missing " + key for key in SPEC_REQUIRED if key not in spec]
    if "profile_id" in spec and not (isinstance(spec["profile_id"], str) and spec["profile_id"]):
        problems.append("profile_id must be a non-empty string")
    problems += ["policy_revision is the factory's, not the specification's"] if "policy_revision" in spec else []
    problems += provenance_problems
    groups = {}
    records = []
    for key in SPEC_FILE_LISTS:
        group = []
        groups[key] = group
        if key not in spec:
            continue
        items = spec[key]
        if not isinstance(items, (list, tuple)):      # a string was iterated as one-letter paths; no list, no reading
            problems.append(key + " must be a list of paths or {path, sha256} records")
            continue
        for index, raw in enumerate(items):
            # a path, or a `{path, sha256}` record as the card writes it or as an earlier request's `fingerprint_files`
            # holds it: one reader, one claim check (EP1-8)
            where = "%s[%d]" % (key, index)
            try:
                given, claimed = _input_record(raw, False, where)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            try:
                path = str(Path(given).resolve())
                record = {"path": path, "sha256": _check_claim(path, claimed), "kind": key}
            except ValueError as exc:
                problems.append("%s (%s)" % (exc, where))
                continue
            group.append(record)
            records.append(record)
        groups[key] = sorted(group, key=lambda x: x["path"])
    # an empty list GIVEN is the refusal; a list whose items were refused is already named above
    if any(isinstance(spec.get(key), (list, tuple)) and not spec[key] for key in ("test_files", "config_files")):
        problems.append("test and configuration inputs must be explicit")
    if not problems:      # M-17: the projection never executes on an invalid specification
        _projection_group(spec, groups, problems)
    return problems, groups, records


def projection_rules():
    """The fingerprint rule set, references/config-projection.json (R6, FR-13), read through the package's one JSON
    reader (AR-13): the parsed object when it has the documented shape, else None, which `_projection_group` refuses
    (line 7) - never `"unknown"`, never a default. Read once per `build` and passed down, never loaded twice."""
    rules = hooklib.read_json(hooklib.ref("config-projection.json"), default=None, kind=dict)
    if rules is None:
        return None

    def strings(value):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    projection, strip, reasons = rules.get("projection"), rules.get("strip_keys"), rules.get("decision_only")
    shaped = (isinstance(rules.get("policy_revision"), str) and bool(rules["policy_revision"])
              and isinstance(projection, dict)
              and all(isinstance(rule, dict) and rule.get("keep") in ("whole", "row_by_profile_id", "entry_by_name")
                      and strings(rule.get("minus")) for rule in projection.values())
              and isinstance(strip, dict) and strings(strip.get("exact")) and strings(strip.get("suffix"))
              and isinstance(reasons, dict) and all(isinstance(why, str) for why in reasons.values()))
    return rules if shaped else None


def _projection_parts(cfg, profile_id, environment_id, rules):
    """The ONE resolver of the projection (R2): `(problems, parts)`. `problems` are the contract's own lines for a
    `profiles` that is not a list, a row that is not an object, an `environment` that is not an object (R5.1 lines 2-4,
    the predicate and text of `validate_config` and `environment_errors`, copied, not called). Otherwise `parts` holds,
    per top-level key of the rules, the kept value: `whole` as found, `row_by_profile_id` the first row of the run's
    profile, `entry_by_name` the one stand entry of the provenance's name reduced to `name` and its address keys, each
    minus its `minus` keys and with every `note`/`*_note` key stripped at any depth by an explicit-stack walk that
    copies (the caller's config is never changed). Absent, `null` or unmatched is `None`. Raises nothing of its own."""
    problems = []
    profiles, environment = cfg.get("profiles"), cfg.get("environment")
    if profiles is not None and not isinstance(profiles, list):
        problems.append("profiles: must be an array")
    elif isinstance(profiles, list):
        problems += ["profiles[%d]: must be an object" % i for i, row in enumerate(profiles) if not isinstance(row, dict)]
    if environment is not None and not isinstance(environment, dict):
        problems.append("environment must be an object")
    if problems:
        return problems, None
    kept = {}
    for top, rule in rules["projection"].items():
        value = cfg.get(top)
        if rule["keep"] == "row_by_profile_id":
            value = next((row for row in value or [] if row.get("profile_id") == profile_id), None)
        elif rule["keep"] == "entry_by_name":
            rows = [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []
            chosen = [entry for entry in rows if str(entry.get("name") or "") == environment_id]
            value = ({key: item for key, item in chosen[0].items() if key in ("name",) + STAND_ADDRESS_KEYS}
                     if len(chosen) == 1 else None)
        if isinstance(value, dict):
            value = {key: item for key, item in value.items() if key not in rule["minus"]}
        kept[top] = value
    exact, suffix = set(rules["strip_keys"]["exact"]), tuple(rules["strip_keys"]["suffix"])
    parts = {}
    stack = [(kept, parts)]
    while stack:
        source, target = stack.pop()
        for key, value in (source.items() if isinstance(source, dict) else enumerate(source)):
            if isinstance(source, dict) and (key in exact or str(key).endswith(suffix)):
                continue
            if isinstance(value, (dict, list)):
                copy = {} if isinstance(value, dict) else [None] * len(value)
                stack.append((value, copy))
                value = copy
            target[key] = value
    return [], parts


def config_projection(cfg, profile_id, environment_id, rules):
    """`(problems, P)`: the R3 payload of one profile's execution-relevant configuration, over the one resolver
    `_projection_parts`; `P` is None when the contract's lines 2-4 refuse. Catches nothing (R5.2)."""
    problems, parts = _projection_parts(cfg, profile_id, environment_id, rules)
    if problems:
        return problems, None
    return [], {"policy_revision": rules["policy_revision"], "profile_id": profile_id,
                "environment_id": environment_id, "projection": parts}


def _projection_group(spec, groups, problems):
    """R5.1, on a spec the earlier groups accepted: the rule set, the `project_config` membership, the read, the
    projection and the ONE `content_hash` of the R1 list (the project record replaced by its projection) that is
    `config_sha`. Appends to `problems`, stops at the first line; on success sets `groups["config_sha"]`/`["policy_revision"]`.
    `RecursionError` is handled at two sites only: the reader's `errors` door (line 1) and the list hash (line 5)."""
    rules = projection_rules()
    if rules is None:
        problems.append("the fingerprint rule set references/config-projection.json is not readable, "
                        "or not of the documented shape")
        return
    groups["policy_revision"] = rules["policy_revision"]
    items = list(groups["config_files"])
    if "project_config" in spec:
        given = spec["project_config"]
        try:
            path = str(Path(given).resolve()) if isinstance(given, str) and given else None
        except ValueError:
            path = None
        if path is None or path not in {record["path"] for record in items}:
            problems.append("project_config must be one of the config_files")
            return
        cfg = hooklib.read_json(path, default=None, errors=(OSError, ValueError, RecursionError), kind=dict)
        if cfg is None:
            problems.append("qa-factory/config.json is not a JSON object, so no projection can be built")
            return
        found, payload = config_projection(cfg, spec["profile_id"], spec["runtime_provenance"]["environment_id"], rules)
        if found:
            problems.extend(found)
            return
        items = [{"path": path, "kind": "config_files", "projection": payload} if record["path"] == path else record
                 for record in items]
    try:
        groups["config_sha"] = content_hash(items)
    except RecursionError:
        problems.append("qa-factory/config.json nests deeper than the fingerprint can hash, so no projection can be built")



# --- what ONE test depends on ----------------------------------------------------------------
# TP1-15045: a run's evidence was keyed on the hash of whole test FILES, so a one-line edit
# in one test made the evidence of the other six tests of that file stale and the automator
# re-ran everything — 20 pytest launches for 4 cases, none of them about stand time. What a
# test really depends on is its own source and the names it uses: the fixtures pytest resolves
# by parameter name (declared in the file itself or in a conftest of the run), the helpers it
# calls, the data it reads. That is what `function_sha` hashes. `test_content_sha` above stays
# the file-level hash every 0.7.x consumer was written against; this is a second, narrower
# measure beside it, never a replacement.
#
# Standard library only, one AST parse per file, nothing executed. The key of a part is a file
# NAME, not its path, so the same test fingerprints identically in the author's tree and in a
# red-probe sandbox copy of it.

FUNCTION_DEPTH = 6  # how far a name is followed through helpers before what is hashed is enough
_FIXTURE_MARK = "usefixtures"


def _parse(path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return text, ast.parse(text)
    except (OSError, SyntaxError, ValueError, RecursionError):
        return "", None


def _decodable(path) -> bool:
    """Does the file read as UTF-8 WITHOUT replacement? `_parse` reads with `errors="replace"`
    so that a stray byte never hides a whole test file; a code sha built over replaced text
    would compare characters that are not in the file, so an undecodable file has none."""
    try:
        Path(path).read_bytes().decode("utf-8")
        return True
    except (OSError, UnicodeDecodeError):
        return False


def _segment(text, node) -> str:
    try:
        return ast.get_source_segment(text, node) or ""
    except (ValueError, IndexError, AttributeError):
        return ""


def _bound(node) -> list:
    """The names one top-level statement binds — definitions, assignments and imports."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [a.asname or a.name.split(".")[0] for a in node.names]
    return []


class _Module:
    """One parsed Python file: what its top level binds, and the source behind each name."""

    def __init__(self, path):
        self.path = str(Path(path))
        self.key = Path(path).name
        self.text, tree = _parse(path)
        self.decodable = _decodable(path)
        self.bytes_sha = _whole_file_sha(path)  # "" when the file cannot be read at all
        # the lines the PARSER counts (\r\n, \r, \n). `str.splitlines` also breaks on \x0c, \x1c-\x1e,
        # \x85 and U+2028/2029, which `ast` does not: every line number below would then slide
        # and a slice of "the test's lines" would end above its last statement (critic t-066).
        self.lines = re.split(r"\r\n|\r|\n", self.text)
        self.parsed = tree is not None
        self.body = list(tree.body) if tree is not None else []
        self.bindings: dict = {}
        for statement in self.body:
            for name in _bound(statement):
                self.bindings.setdefault(name, []).append(statement)

    def raw(self, text: str) -> str:
        """The text of a part as the RAW sha takes it. `_parse` reads with `errors="replace"`, so
        two different files that do not decode both show U+FFFD where their bad bytes are: a raw
        sha over that text would call them the same bytes, and a result of the one would cover
        the other. A file that does not decode is therefore represented by its own bytes."""
        return text if self.decodable and self.parsed else "bytes:" + self.bytes_sha

    def source(self, node) -> str:
        return "\n".join([_segment(self.text, d) for d in getattr(node, "decorator_list", [])]
                         + [_segment(self.text, node)])

    def physical(self, node) -> str:
        """The node's own physical lines, from its first decorator's line through `end_lineno`.

        `ast.get_source_segment` drops the `@` of a decorator, so a marker decorator (D-0017's
        cosmetic case) would never match the shape data describes it by; `diff_scope.
        executable_sha` reads lines, so it is given lines, whole."""
        first = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])
        last = getattr(node, "end_lineno", None) or node.lineno
        return "\n".join(self.lines[first - 1:last])

    def decorators(self, node) -> str:
        """The physical lines of the decorators of a definition (a class part's decorators)."""
        return "\n".join("\n".join(self.lines[d.lineno - 1:(getattr(d, "end_lineno", None) or d.lineno)])
                         for d in getattr(node, "decorator_list", []))


def _module(path, cache) -> _Module:
    key = str(Path(path))
    if key not in cache:
        cache[key] = _Module(path)
    return cache[key]


def _dotted(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _dotted(node.value)
        return owner + "." + node.attr if owner else ""
    return ""


def _is_case_marker(decorator, markers) -> bool:
    """Is this decorator one of the factory's own case markers (`case-markers.json`, literal
    arguments only, no `**kwargs`)? The SAME shape `diff_scope` counts as cosmetic (D-0019): a
    marker names `pytest` only to bind the test to its case, so it must not pull `import pytest`
    into the test's parts. Any other decorator (skip, parametrize, usefixtures, a project's own)
    is code and stays."""
    if not markers:
        return False
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if _dotted(target) not in markers:
        return False
    if isinstance(decorator, ast.Call):
        for arg in list(decorator.args) + [k.value for k in decorator.keywords]:
            try:
                ast.literal_eval(arg)
            except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                return False
        if any(k.arg is None for k in decorator.keywords):
            return False
    return True


def _walk(node, markers=frozenset()):
    """`ast.walk` that does not enter a factory case marker decorator."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        skip = {id(d) for d in getattr(current, "decorator_list", []) if _is_case_marker(d, markers)}
        stack.extend(child for child in ast.iter_child_nodes(current) if id(child) not in skip)


def _mentioned(node, markers=frozenset()) -> set:
    """Every identifier a piece of source refers to: plain names (the root of an attribute
    chain is one of them), the parameters of the functions inside it — pytest resolves a
    fixture by parameter name — and the fixture names spelled as strings in `usefixtures`.
    The factory's own case markers (`markers`, dotted names) are not entered."""
    found = set()
    for child in _walk(node, markers):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spec = child.args
            found.update(a.arg for a in
                         list(spec.posonlyargs) + list(spec.args) + list(spec.kwonlyargs))
        elif isinstance(child, ast.Call):
            called = (child.func.attr if isinstance(child.func, ast.Attribute)
                      else getattr(child.func, "id", ""))
            if called == _FIXTURE_MARK:
                found.update(a.value for a in child.args
                             if isinstance(a, ast.Constant) and isinstance(a.value, str))
    return found


def _resolve(module, class_chain, function):
    """`(function node, the classes of the chain outermost first, the shadowed definitions)`.

    Python runs the LAST definition of a name, so the last one is the test (and the last class of
    each name is the class); every earlier definition of the same name is returned as `shadowed`
    and hashed as well - it costs an over-run when it is edited, never a missed change. The node
    is None when the chain or the function is not found at the top level."""
    body, classes, shadowed = module.body, [], []
    for name in class_chain or ():
        found = [n for n in body if isinstance(n, ast.ClassDef) and n.name == name]
        if not found:
            return None, [], []
        classes.append(found[-1])
        shadowed.extend(found[:-1])
        body = found[-1].body
    defs = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function]
    if not defs:
        return None, [], []
    return defs[-1], classes, shadowed + defs[:-1]


def _class_members(holder, on_chain=None) -> list:
    """The class around a test method WITHOUT its sibling tests: the class-level data, the
    setup/teardown and the fixtures declared in it. A sibling test is not something this test
    depends on — that separation is the whole point of a per-function fingerprint. Cut: the
    `test*` methods, the `Test*` classes inside it, and the next class of the chain (it has a part
    of its own)."""
    return [n for n in holder.body
            if n is not on_chain and not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                                          and _is_test_definition(n))]


def _helper_for(module_name, level, owner_path, helpers):
    """The helper file an import names: `pages.workflow_page` is `.../pages/workflow_page.py`,
    and a relative import counts from the importing file's own directory. An import that
    matches no helper of the run (a third-party package, the standard library) is left to the
    dependency and configuration hashes, which cover exactly that."""
    tail = "/".join(str(module_name or "").split("."))
    if level:
        base = Path(owner_path).parent
        for _ in range(int(level) - 1):
            base = base.parent
        wanted = (base / tail).as_posix().lower() if tail else base.as_posix().lower()
        endings = (wanted + ".py", wanted + "/__init__.py")
        return next((h for h in helpers if Path(h.path).as_posix().lower() in endings), None)
    if not tail:
        return None
    endings = ("/" + tail + ".py").lower(), ("/" + tail + "/__init__.py").lower()
    return next((h for h in helpers
                 if Path(h.path).as_posix().lower().endswith(endings)), None)


def _is_test_definition(node) -> bool:
    """A top-level definition pytest collects by name: `test*` functions and `Test*` classes."""
    return ((isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"))
            or (isinstance(node, ast.ClassDef) and node.name.startswith("Test")))


def _first_line(node) -> int:
    """A definition's first physical line: its first decorator's, else its own."""
    return min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno])


def _ignored_line(text: str, number: int) -> bool:
    """A line the interpreter ignores: blank, or a comment past the first two lines (a coding declaration)."""
    text = text.strip()
    return not text or (text.startswith("#") and number > 2)


def _test_gaps(module) -> set:
    """The line numbers the skeleton drops BESIDES the test definitions (FB-10, identity v2): the GAP
    directly before each top-level `def test*` / `async def test*` - the whitespace-only and comment-only
    lines after the previous top-level statement's `end_lineno` and before the definition's first
    decorator line (an added test brings its own gap) - and every whitespace-only line outside every
    top-level statement's span (such a line cannot lie inside a string: every multi-line literal is inside
    its statement's span). Error direction (R1a): a line this cannot place is kept - a statement with no
    `end_lineno` ends the gap computation and the blank-line cut alike - and the first two comment lines
    (a coding declaration) are never cut. Nothing evaluated at import leaves the skeleton: only lines the
    interpreter ignores."""
    lines = module.lines
    spans, gaps, previous = set(), set(), 0
    for node in module.body:
        end = getattr(node, "end_lineno", None)
        if end is None:
            return set()   # a statement that cannot be placed: keep every line (the safe direction)
        first = _first_line(node)
        spans.update(range(first, end + 1))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            gaps.update(n for n in range(previous + 1, first) if _ignored_line(lines[n - 1], n))
        previous = end
    gaps.update(n for n, line in enumerate(lines, 1) if n not in spans and not line.strip())
    return gaps


def _skeleton(module, class_chain) -> tuple:
    """The module skeleton (t-055): the test file's text WITHOUT its test definitions - what is
    left is the imports, `pytestmark`, module-level fixtures, helpers, constants and `if` blocks,
    plus the comments between them. A module-wide `pytestmark = pytest.mark.skip`
    changes what EVERY test of the file does though no name a test uses points at it, so it is
    part of every instance's identity; the other tests' own bodies are not (the D5 rule: fixing
    test_b never makes test_a's evidence stale). The class that holds THIS test is left out even
    when its name is not `Test*` (a `unittest.TestCase` named otherwise): it is hashed in whole
    but for its sibling tests by the class part, and its siblings must not come back through here.
    A definition is cut from its first decorator's line to its `end_lineno`.

    Identity v2 (FB-10) forgives exactly ONE difference, an ADDED test function: `_test_gaps` also cuts the
    gap (blank and comment lines) directly before each top-level `test*` function, and the blank lines
    outside every statement. Everything else stays in the text as before - assignments, imports of any
    kind, fixtures (a plugin fixture override included), helpers, classes, `setup()`, `pytestmark`,
    comments before a non-test statement, the gap of a `Test*` class - so each of them still stales every
    sibling (axis 7: the allowed error is "different"). An unparseable file has no skeleton at all (the
    caller falls back to the whole file). The code sha is byte-equal to the one before v2: the lines cut
    here are blank or comments, which `executable_sha` ignores.

    Returns `(text, the top-level statements that stayed)`: the caller follows the names those
    statements use (a `pytestmark = pytest.mark.usefixtures("x")` reaches the fixture `x`)."""
    outer = class_chain[0] if class_chain else None
    cut: set = set(_test_gaps(module))
    kept: list = []
    for node in module.body:
        if _is_test_definition(node) or (isinstance(node, ast.ClassDef) and node.name == outer):
            cut.update(range(_first_line(node), (getattr(node, "end_lineno", None) or node.lineno) + 1))
        else:
            kept.append(node)
    # `module.lines` are the parser's lines (\r\n, \r, \n), not `str.splitlines`'
    return "\n".join(line for number, line in enumerate(module.lines, 1) if number not in cut), kept


def function_sha(test_file, function, class_chain=(), helper_files=(), cache=None) -> dict:
    """`{"sha", "scope"}` for ONE test function.

    Hashed: the function's own source with its decorators; the class around it without its
    sibling tests; and every definition the two name, followed through the file itself and then
    through `helper_files` in the order given (the conftest chain nearest first, which is how
    pytest itself resolves a fixture). A `from x import y` adds the import line and follows `y`
    into the helper file `x` resolves to; a plain `import x` that resolves to a helper adds
    that whole file, because which of its names the test reaches cannot be told without running
    it. The module skeleton (`_skeleton`: everything at the top of the file but the test
    definitions - imports, `pytestmark`, module fixtures, helpers, constants) is one more part of
    both shas, so module-level code that changes what every test does invalidates every instance
    while another test's own body does not. Anything unresolved is a builtin, a pytest name or
    an attribute of an object — the run's own config, dependency and runtime hashes already
    cover those.

    The rule behind every part: this is the identity both for reuse and for proof, and its only
    allowed error is "different" - a missed code change would let an old result cover changed
    code. So it also hashes: every class of the chain (decorators, bases, keywords, class-level
    statements, all but the sibling tests); the bases of those classes, recursively (a `Test*`
    base included; a base imported from a project file as that file whole; a base nothing binds
    gives no identity); the `conftest.py` files above the test that the run lists and the
    `__init__.py` files of its package path, whole (coarse by design); the statements left in the
    module skeleton, followed by name (`pytestmark = ...usefixtures("x")`); and every
    same-name definition of the test (Python runs the last). The factory's own case markers are
    not entered when names are followed (D-0019), so adding one adds no `import pytest` part.

    Identity is never made of nothing: a part read from a file that does not decode as UTF-8 is
    hashed as that file's raw bytes (not as the replacement text `_parse` reads it as), and a
    test file or helper that cannot be read at all gives `sha` "" and `code_sha` "" - no identity,
    so no earlier result covers it and the run is due.

    `scope` is "function" when the function was found, and "file" when it was not: an
    unparsable file, a test generated at import time, or a non-Python framework falls back to
    the hash of the whole file, which is what 0.7.9 did for everything. A caller that compares
    two "file"-scope shas therefore behaves exactly as it did before.

    `code_sha` is the second, coarser measure beside `sha` (D-0017: "cosmetic is measured, not
    judged"): the same parts, each reduced by `diff_scope.executable_sha` over its full physical
    lines, so a comment, a docstring line, a blank line and (once the marker data lands) the
    factory's own case marker do not change it. It is the one classifier `diff_scope` already is
    — there is no second definition of "prose" here. "" when ANY part cannot be told - a file
    the parts come from does not read as UTF-8, is not `.py`, or a fragment does not tokenize:
    such an instance has only the raw rule."""
    cache = cache if cache is not None else {}
    test_file = str(Path(test_file))
    module = _module(test_file, cache)
    if not module.parsed:
        return {"sha": _whole_file_sha(test_file), "scope": "file",
                "code_sha": _whole_file_code_sha(test_file)}
    node, classes, shadowed = _resolve(module, class_chain, function)
    if node is None:
        return {"sha": _whole_file_sha(test_file), "scope": "file",
                "code_sha": _whole_file_code_sha(test_file)}
    helpers = [_module(p, cache) for p in helper_files if str(Path(p)) != test_file]
    if not module.bytes_sha or any(not h.bytes_sha for h in helpers):
        # a file of the run that cannot be read: no identity at all, so nothing covers it
        return {"sha": "", "scope": "function", "code_sha": ""}
    markers = marker_names()
    parts: list = []
    code_parts: list = []
    readable = module.decodable
    voided = False

    def add(key: str, name: str, source_module, raw_text: str, code_text: str) -> None:
        """One part of BOTH shas. A part the classifier cannot tell (`executable_sha` says "" - a
        fragment that does not tokenize, a file that is not `.py`) makes the WHOLE code sha "": an
        empty string hashed like any other value would be a stable identity for something nobody
        could read, and two such edits would compare equal. A file that cannot be read at all
        voids both shas."""
        nonlocal readable, voided
        if not source_module.bytes_sha:
            voided = True
        parts.append((key, name, source_module.raw(raw_text)))
        sha = executable_sha(code_text, source_module.key)
        if not sha or not source_module.decodable or not source_module.parsed:
            readable = False
        code_parts.append((key, name, sha))

    def add_file(target, suffix: str = "") -> None:
        add(target.key + suffix, "", target, target.text, target.text)

    add("test", function, module, module.source(node), module.physical(node))
    for other in shadowed:  # Python runs the LAST definition; an earlier one is hashed too
        add("shadowed", getattr(other, "name", ""), module, module.source(other), module.physical(other))
    skeleton, kept = _skeleton(module, class_chain)
    add("skeleton", "", module, skeleton, skeleton)
    wanted = set(_mentioned(node, markers))
    for statement in kept:  # `pytestmark = pytest.mark.usefixtures("db")` reaches the fixture `db`
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            wanted |= _mentioned(statement, markers)

    def project_module(module_name, level, owner_path):
        """The project file an import names: a helper of the run, else the file on disk (a
        relative import from the importer's directory; an absolute one from the importer's
        directory up). The standard library and third-party packages are None: the run's
        dependency hashes cover those."""
        found = _helper_for(module_name, level, owner_path, helpers)
        if found is not None:
            return found
        dotted = str(module_name or "")
        if not level and dotted.split(".")[0] in getattr(sys, "stdlib_module_names", ()):
            return None
        tail = "/".join(dotted.split(".")) if dotted else ""
        owner_dir = Path(owner_path).parent
        if level:
            base = owner_dir
            for _ in range(int(level) - 1):
                base = base.parent
            roots = [base]
        else:
            roots = [owner_dir] + list(owner_dir.parents)[:8]
        for root in roots:
            for candidate in ([root / (tail + ".py"), root / tail / "__init__.py"] if tail
                              else [root / "__init__.py"]):
                if candidate.is_file():
                    return _module(str(candidate), cache)
        return None

    def lookup(name, owner):
        statements = [(owner, s) for s in owner.bindings.get(name) or []]
        if not statements:
            found = next((h for h in helpers if name in h.bindings), None)
            statements = [(found, s) for s in (found.bindings[name] if found else [])]
        return statements

    based: set = set()
    from_bases: list = []

    def check_bases(cls, owner, depth: int) -> None:
        for base in cls.bases:
            for name in sorted(_mentioned(base, markers)):
                resolve_base(name, owner, depth)

    def resolve_base(name, owner, depth: int) -> None:
        """A base class is part of the test: its `setup_method` and autouse fixtures run for it.
        Bound in the file (or a helper) to a class: that class, whole, and ITS bases in turn - a
        `Test*` base included, it is cut from the skeleton but not from here. Imported from a
        project file: that file's code, whole (coarse). A builtin or a stdlib/third-party import:
        left to the dependency hashes. A name nothing binds: no identity - the test runs."""
        nonlocal voided
        if depth > FUNCTION_DEPTH or (owner.path, name) in based:
            return
        based.add((owner.path, name))
        statements = lookup(name, owner)
        if not statements:
            if hasattr(builtins, name):
                return
            stars = [s for s in owner.body if isinstance(s, ast.ImportFrom)
                     and any(a.name == "*" for a in s.names)]
            if not stars:
                voided = True
                return
            for star in stars:
                target = project_module(star.module, star.level, owner.path)
                if target is not None:
                    add_file(target)
            return
        from_bases.append((owner, name, depth))
        for source, statement in statements:
            if isinstance(statement, ast.ClassDef):
                check_bases(statement, source, depth + 1)
            elif isinstance(statement, ast.ImportFrom):
                original = next((a.name for a in statement.names if (a.asname or a.name) == name), name)
                target = project_module(statement.module, statement.level, source.path)
                if target is not None:
                    add_file(target)
                    if original in target.bindings:
                        resolve_base(original, target, depth + 1)
                sub = project_module((statement.module + "." if statement.module else "") + original,
                                     statement.level, source.path)
                if sub is not None and sub is not target:
                    add_file(sub)
            elif isinstance(statement, ast.Import):
                dotted = next((a.name for a in statement.names
                               if (a.asname or a.name.split(".")[0]) == name), "")
                target = project_module(dotted, 0, source.path)
                if target is not None:
                    add_file(target)
            else:  # an alias: `Base = other.Class`
                for other in sorted(_mentioned(statement, markers)):
                    resolve_base(other, source, depth + 1)

    for index, cls in enumerate(classes):
        following = classes[index + 1] if index + 1 < len(classes) else None
        members = _class_members(cls, following)
        segments = ([_segment(module.text, b) for b in cls.bases]
                    + [(k.arg + "=" if k.arg else "**") + _segment(module.text, k.value) for k in cls.keywords])
        add("class", cls.name, module,
            "\n".join([_segment(module.text, d) for d in cls.decorator_list] + segments),
            "\n".join([module.decorators(cls)] + segments))
        add("members", cls.name, module, "\n".join(module.source(n) for n in members),
            "\n".join(module.physical(n) for n in members))
        for decorator in cls.decorator_list:
            if not _is_case_marker(decorator, markers):
                wanted |= _mentioned(decorator, markers)
        for keyword in cls.keywords:
            wanted |= _mentioned(keyword.value, markers)
        for member in members:
            wanted |= _mentioned(member, markers)
        check_bases(cls, module, 0)

    # conftest.py of the test's directory and every directory above it that the run lists, and
    # the __init__.py of its package path: what pytest runs around every test under them (autouse
    # fixtures, hooks). Coarse by design - any code edit there is an edit of every instance under
    # it - and keyed by distance from the test, so a copy of the tree fingerprints the same.
    here = Path(os.path.abspath(test_file)).parent
    ancestors = [here] + list(here.parents)
    for hops, directory in enumerate(ancestors):
        wanted_path = os.path.normcase(str(directory / "conftest.py"))
        for helper in helpers:
            if helper.key == "conftest.py" and os.path.normcase(os.path.abspath(helper.path)) == wanted_path:
                add_file(helper, f"@{hops}")
    for hops, directory in enumerate(ancestors):
        init = directory / "__init__.py"
        if not init.is_file():
            break
        add_file(_module(str(init), cache), f"@{hops}")

    seen: set = set()
    queue = [(module, name, 0) for name in sorted(wanted)] + from_bases
    while queue:
        owner, name, depth = queue.pop(0)
        if depth > FUNCTION_DEPTH or (owner.path, name) in seen:
            continue
        seen.add((owner.path, name))
        for source, statement in lookup(name, owner):
            add(source.key, name, source, source.source(statement), source.physical(statement))
            if isinstance(statement, ast.ImportFrom):
                original = next((a.name for a in statement.names
                                 if (a.asname or a.name) == name), name)
                helper = project_module(statement.module, statement.level, source.path)
                if helper is None:
                    continue
                if original in helper.bindings:
                    queue.append((helper, original, depth + 1))
                else:  # `import *`, or a name this reader cannot place: the file, whole
                    add_file(helper)
            elif isinstance(statement, ast.Import):
                dotted = next((a.name for a in statement.names
                               if (a.asname or a.name.split(".")[0]) == name), "")
                helper = project_module(dotted, 0, source.path)
                if helper is not None:
                    add_file(helper)
            else:
                queue.extend((source, other, depth + 1)
                             for other in sorted(_mentioned(statement, markers)))
    if voided:  # a file of the run that cannot be read, or a base nothing binds: no identity
        return {"sha": "", "scope": "function", "code_sha": ""}
    return {"sha": content_hash(sorted(parts)), "scope": "function",
            "code_sha": content_hash(sorted(code_parts)) if readable else ""}


def _whole_file_sha(path) -> str:
    """sha256 of the file's bytes; "" when it cannot be read. Not the hash of empty bytes: two
    different files that are both missing would then be one identity, and a result over the one
    would cover the other - an unread file has no identity, so nothing is ever covered by it."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _whole_file_code_sha(path) -> str:
    """The `scope == "file"` code sha: `executable_sha` of the decoded file, named as the file is;
    "" when it cannot be read as UTF-8 or the classifier cannot tell it (the raw rule only)."""
    try:
        return executable_sha(Path(path).read_bytes().decode("utf-8"), Path(path).name)
    except (OSError, UnicodeDecodeError):
        return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     epilog=epilog("execution_fingerprint.py"),
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(json.loads(args.spec.read_text(encoding="utf-8")))))


if __name__ == "__main__":
    raise SystemExit(run_guarded(command_from_argv("execution_fingerprint.py"), main))
