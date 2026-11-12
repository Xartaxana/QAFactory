"""What the story's run blocks say about one test over time.

Two readers need it and neither owns it: the S5 exit check (`s5_precheck.py`, which turns a pair
into a finding) and the ones that only read (`handoff_check`, the window record, the brief, the
ledger). The block reader and the detector of "a test that went red and later passed on changed
code" (B-194) used to live inside `s5_precheck.py`, a 2,400-line file every reader had to import
whole. `s5_precheck` re-exports every public name below, so both import paths stay valid and name
the same objects.

Nothing here writes (FR-45). The two helpers that read a test FILE (`read_python`,
`resolve_test_file`) and the JSON reader stay in `s5_precheck.py`; they are imported where they are
used, inside the function, because `s5_precheck` imports this module at its top.
"""
import ast
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

BLOCK_STAMP_RE = re.compile(r"^(\d{8}T\d{6})(\d{0,6})Z-")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_time(value):
    """An ISO clock as an aware UTC datetime, or None when it is absent or unreadable."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _stamp_time(name: str):
    """The UTC stamp an ordinary run block's file name starts with, else None."""
    match = BLOCK_STAMP_RE.match(name)
    if not match:
        return None
    try:
        moment = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    return moment.replace(microsecond=int((match.group(2) + "000000")[:6]), tzinfo=timezone.utc)


def _block_attempt(data: dict, name: str) -> str:
    return str(data.get("attempt_id") or data.get("block_id") or "")


def read_run_blocks(task_root: Path) -> tuple:
    """`(blocks oldest first, names of files that are not a readable JSON object)`.

    ONE total order for every reader of the story's blocks: (time, reparse depth, file name).
    Time is the block's `attempt_started_at`, else the stamp its file name starts with. A
    `--reparse-block` block keeps the `attempt_started_at` of the block it supersedes and is
    named `<attempt>-reparse-<hash>.json`, so it has no stamp; sorting by file name alone put an
    attempt id that starts with `0` or `1` before every `2026...` block, and the original's
    `not_run` row then read as the NEWEST row of the instance (`check_run_mapping`) and the red
    of `expectation_changes` came after its own green. The depth puts a reparse right AFTER the
    block of the same attempt it supersedes, and a reparse of a reparse after that.

    Each block is `{"name", "data", "time", "started", "depth", "parent", "attempt"}`;
    `started` says whether an `attempt_started_at` (its own, or the superseded block's) stands
    behind `time`."""
    items, bad = [], []
    for path in sorted_paths((Path(task_root) / "work" / "run-blocks").glob("*.json")):
        try:
            # `utf-8-sig`: the other readers of a block (`acceptance._run_blocks`, `probe_by_code`)
            # take a file with a byte-order mark, and a reader they now share must not turn it
            # into "unreadable".
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            data = None
        if not isinstance(data, dict):
            bad.append(path.name)
            continue
        items.append({"name": path.name, "data": data, "attempt": _block_attempt(data, path.name)})
    by_name = {item["name"]: item for item in items}

    def is_reparse(item: dict) -> bool:
        data = item["data"]
        return bool(data.get("reparse_of") or data.get("supersedes_block_id")
                    or "-reparse-" in item["name"])

    originals: dict = {}
    for item in items:
        if not is_reparse(item):
            originals.setdefault(item["attempt"], item)

    def parent_of(item: dict):
        data = item["data"]
        named = by_name.get(Path(str(data.get("reparse_of") or "")).name)
        if named is not None and named is not item:
            return named
        return originals.get(str(data.get("supersedes_block_id") or "")) or originals.get(item["attempt"])

    def resolve(item: dict, seen: tuple = ()) -> tuple:
        """(time, started, depth) of one block; a reparse without a clock takes its parent's."""
        own = _parse_time(item["data"].get("attempt_started_at"))
        if not is_reparse(item):
            return (own or _stamp_time(item["name"]) or _EPOCH), own is not None, 0
        parent = parent_of(item)
        if parent is None or parent["name"] in seen or parent is item:
            return (own or _EPOCH), own is not None, 1
        moment, started, depth = resolve(parent, seen + (item["name"],))
        return (own or moment), (own is not None or started), depth + 1

    for item in items:
        item["time"], item["started"], item["depth"] = resolve(item)
        item["parent"] = parent_of(item) if is_reparse(item) else None
    items.sort(key=lambda item: (item["time"], item["depth"], item["name"]))
    return items, bad


# --- a test that changed between its red run and the next green run (B-194) --------------------
#
# The pairing lived inside `check_oracle`: a `failed` row and a later `passed` row of the same
# INSTANCE id whose FILE-level sha differed. On TP1-13797 it could not fire: every row of
# both blocks was `not_run` / "report row missing" (the reporter's ids are not the contract's),
# the parameter ids were renamed between the runs, and a reparse block carried no sha. The
# expected value of TC-002 changed and nothing said so. The rules below are the ones that
# shape hit: the key is the test FUNCTION (a rename of a parameter id cannot hide or double a
# change), red is confirmed against the raw report of the red block (an unmapped row proves
# nothing either way), and a sha nobody could read counts as CHANGED (`function_sha` may only err
# toward "different": SIBLING_MAP axis 7).
RED_STATUSES = ("failed", "error")
MISSING_ROW = "report row missing"
REPORT_REPORTERS = ("trx", "junit-xml", "pytest")
# Which sha answers "did this test change": the instance's own code sha (comments, docstrings and
# the factory's case marker do not move it), then its raw content sha, then the block's
# file-level sha (a neighbour's edit moves that one, which is the allowed error). The first two are
# compared by `proof_level.compare_identity`, the one "same test" comparison (RH1-9).
SHA_FIELDS = (("code", "instance_code_sha"), ("raw", "instance_content_sha"))
SHA_FIELDS_ORDER = ("code", "raw", "file")


def _function_identity(test_id, instance_id="") -> tuple:
    """`(module, class chain, function)` of one test, from its reporter id.

    The last module segment, the classes and the function: the package prefix in front of the
    module changes between runs (`testproject1_test_harness.tests.x.test_m` in the contract,
    `tests.x.test_m` in the report — the t-080 defect) and the parameter part never was part of
    the function. A pytest node id (`tests/test_m.py::TestC::test_x[p]`), a dotted junit name
    (`pkg.test_m.TestC::test_x`) and a dotted C# name all reduce the same way: a segment that
    starts with a capital letter opens the class chain, the segment before it is the module.
    With no reporter id there is only the instance's function name."""
    text = re.split(r"[\[(]", str(test_id or "").strip().replace("\\", "/"), maxsplit=1)[0].strip()
    parts = [p.strip() for p in text.split(C.INSTANCE_SEP) if p.strip()]
    fallback = ("", (), C.function_name(instance_id))
    if not parts:
        return fallback
    head, tail = parts[0], parts[1:]
    if "/" in head or head.endswith(".py"):
        if not tail:
            return fallback
        module, chain, names = Path(head).stem, [], tail
    else:
        segments = [s for s in head.split(".") if s]
        names = tail or segments[-1:]
        if not tail:
            segments = segments[:-1]
        upper = next((i for i, s in enumerate(segments) if s[:1].isupper()), None)
        if upper is None:
            module, chain = (segments[-1] if segments else ""), []
        else:
            module, chain = (segments[upper - 1] if upper else ""), segments[upper:]
    if not names:
        return fallback
    return module, tuple(chain + names[:-1]), names[-1]


def function_key(test_id, instance_id="") -> str:
    """The key `expectation_changes` pairs by: `<module>.<classes>.<function>`, parameters
    stripped — `function_name(instance_id)` alone when the row has no reporter id."""
    module, chain, function = _function_identity(test_id, instance_id)
    return ".".join(part for part in (module, *chain, function) if part)


def _job_records(task_root: Path) -> dict:
    """`job_id -> job record` of `state/execution-jobs/`; a run block's `attempt_id` is its
    job's `job_id`. A record that cannot be read is skipped: the sha then comes from a coarser
    level or is unknown, and unknown counts as changed."""
    found = {}
    for path in sorted_paths((task_root / "state" / "execution-jobs").glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(job, dict) and job.get("job_id"):
            found[str(job["job_id"])] = job
    return found


def _job_contract(job, instance_id: str) -> dict:
    request = job.get("request") if isinstance(job, dict) else None
    contracts = request.get("instance_contracts") if isinstance(request, dict) else None
    if not isinstance(contracts, dict):
        return {}
    hit = contracts.get(instance_id)
    if isinstance(hit, dict):
        return hit
    name = C.function_name(instance_id)
    found = [c for k, c in contracts.items() if isinstance(c, dict) and name and C.function_name(k) == name]
    if len(found) <= 1:
        return found[0] if found else {}
    # Several contracts under the bare function name: parameters of ONE function (equal, non-empty code and
    # content shas, `instance_content_scope: "function"`) keep the first - the renamed-parameter shape of
    # TP1-13797. Any other mix is twins of other tests: the sha of a stranger never decides "the same".
    # The comparison is `proof_level.compare_identity` (AR-13): ("same", "content") is code AND content
    # non-empty and equal on both; any other answer, "unknown" included, is no match (AR-28).
    import proof_level as PL
    if all(PL.compare_identity(found[0], c) == ("same", "content") for c in found[1:]):
        return found[0]
    return {}


def _shas(row: dict, item: dict, jobs: dict) -> dict:
    """`{"code", "raw", "file"}` — what says whether the test changed, "" where nothing does.

    Per level the first of: the row, the job record of the row's attempt, and — for a reparse —
    the row of the block it supersedes. Rows written before the producer wrote the code sha, and
    every reparse row before it carried any sha, are answered by the job record."""
    data = item["data"]
    fingerprint = data.get("source_fingerprint")
    out = {"code": "", "raw": "",
           "file": str(fingerprint.get("test_content_sha") or "") if isinstance(fingerprint, dict) else ""}
    iid = str(row.get("instance_id") or "")
    contract = _job_contract(jobs.get(item["attempt"]), iid)
    prior: dict = {}
    parent = item.get("parent")
    if parent is not None and isinstance(parent["data"].get("results"), list):
        prior = next((r for r in parent["data"]["results"]
                      if isinstance(r, dict) and str(r.get("instance_id") or "") == iid), {})
    for level, field in SHA_FIELDS:
        out[level] = str(row.get(field) or contract.get(field) or prior.get(field) or "")
    return out


def _compare_shas(red: dict, green: dict) -> tuple:
    """`(verdict, basis, red sha, green sha)`: the first basis present on BOTH sides decides.
    Nothing present on both is `unknown`, and unknown is never `same` (FR-41). The code and raw bases are
    decided by `proof_level.compare_identity` (the one "same test" comparison, AR-13); the record's basis is
    "code" when the code sha is present on both sides (rule 1 decided), else "raw"; `file` is another
    quantity (the block's test + helpers) and stays here."""
    import proof_level as PL
    pair = [{"instance_code_sha": side["code"], "instance_content_sha": side["raw"]} for side in (red, green)]
    verdict, _ = PL.compare_identity(*pair)
    if verdict != "unknown":
        basis = "code" if all(str(side["code"] or "").strip() for side in (red, green)) else "raw"
        return ("same" if verdict == "same" else "changed"), basis, red[basis], green[basis]
    if red["file"] and green["file"]:
        return ("same" if red["file"] == green["file"] else "changed"), "file", red["file"], green["file"]
    return "unknown", "unknown", _first_sha(red), _first_sha(green)


def _report_path(data: dict) -> str:
    for evidence in data.get("evidence") or []:
        if isinstance(evidence, dict) and evidence.get("reporter") in REPORT_REPORTERS \
                and evidence.get("report_path"):
            return str(evidence["report_path"])
    return ""


NAMED = "named"  # the raw report lists the function and it is not red there


def _without_extended_prefix(path: Path) -> Path:
    """The path without the Windows extended-length prefix: `\\\\?\\C:\\x` is `C:\\x`, and
    `\\\\?\\UNC\\host\\share` is `\\\\host\\share`. `Path.resolve()` of a long path comes back with
    the prefix while another path to the same place does not, and `is_relative_to` then says
    "outside" (cmp1, t-108: three false `red_unconfirmed` pairs)."""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + text[len("\\\\?\\UNC\\"):])
    if text.startswith("\\\\?\\"):
        return Path(text[len("\\\\?\\"):])
    return path


def _evidence_report(task_root: Path, data: dict):
    """`(report path, reporter)` of the block's OWN raw report, or None: no evidence, a path outside the story, an
    absolute one, a file that is gone or whose sha256 is not the recorded one. THE gate of every reader of a block's
    raw report (`_read_report`, `report_rows_of`): the same checks, in one place (AR-13)."""
    evidence = next((e for e in data.get("evidence") or []
                     if isinstance(e, dict) and e.get("reporter") in REPORT_REPORTERS
                     and e.get("report_path")), None)
    if evidence is None:
        return None
    try:
        raw = Path(str(evidence["report_path"]))
        report = (task_root / raw).resolve()
        inside = _without_extended_prefix(report).is_relative_to(
            _without_extended_prefix(task_root.resolve()))
        if raw.is_absolute() or not inside or not report.is_file():
            return None
        if hashlib.sha256(report.read_bytes()).hexdigest() != evidence.get("report_sha256"):
            return None
    except Exception:
        return None
    return report, evidence.get("reporter")


def report_rows_of(task_root: Path, data: dict) -> "list | None":
    """The rows of the block's own raw report as `reporters.read_rows` reads them (`{test_id, status, problems}`, the
    stack text included), or None when the report cannot be established (`_evidence_report`) or cannot be parsed."""
    found = _evidence_report(Path(task_root), data)
    if found is None:
        return None
    try:
        import reporters
        return reporters.read_rows(*found)
    except Exception:
        return None


def _read_report(task_root: Path, data: dict):
    """`{function key: "failed"|"error"|"named"}` from the block's OWN raw report, or None when
    it cannot be read: no evidence, a path outside the story, a file that is gone or whose sha256
    is not the recorded one, or a parse the package's own reader refuses. `named` is a function
    the report lists that is not red there; a function the report does not list is absent from
    the answer, which is NOT the same as passing (the reader cuts its list of passed rows).
    Read by `run_suite`'s junit/trx parser (a failed row is never dropped by its row cap)."""
    found = _evidence_report(task_root, data)
    if found is None:
        return None
    report, reporter = found
    try:
        import run_suite as RS
        parsed = RS.parse_trx(report) if reporter == "trx" else RS.parse_junitxml(report)
    except Exception:
        return None
    said: dict = {}
    for row in parsed.get("results") or []:
        if not isinstance(row, dict):
            continue
        key = function_key(row.get("test_id"))
        if not key:
            continue
        if row.get("status") in RED_STATUSES:
            said[key] = "failed" if "failed" in (row.get("status"), said.get(key)) else "error"
        else:
            said.setdefault(key, NAMED)
    return said


def _report_status(report: dict, key: str) -> str:
    """What the raw report says of this function: "failed", "error", "named" (listed, not red
    there) or "" (not listed at all). A bare name on either side (a trx test name, a row with no
    reporter id) matches by the function alone."""
    said = [status for name, status in report.items()
            if name == key or ("." not in name and key.rsplit(".", 1)[-1] == name)
            or ("." not in key and name.rsplit(".", 1)[-1] == key)]
    if "failed" in said:
        return "failed"
    return "error" if "error" in said else (NAMED if said else "")


def _dispatch_index(state: dict) -> dict:
    raw = state.get("dispatches")
    rows = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    out = {}
    for row in rows:
        if isinstance(row, dict):
            for ident in (row.get("id"), row.get("dispatch_id")):
                if ident:
                    out[str(ident)] = row
    return out


def _stage_of(data: dict, dispatches: dict) -> str:
    """The stage of the dispatch that wrote this block: the controller's record of it, else the
    `S<n>-` its id starts with, else "" (a block no dispatch owns)."""
    ident = str(data.get("dispatch_id") or "")
    stage = str((dispatches.get(ident) or {}).get("stage") or "").strip()
    if not stage:
        match = re.match(r"^(S\d+)(?:-|$)", ident)
        stage = match.group(1) if match else ""
    return stage


def _param_of(row: dict) -> str:
    """The parameter part of a row's test, `[P-new]`, or "" for a test that has none: the
    instance id's, else the reporter id's."""
    for text in (str(row.get("instance_id") or ""), str(row.get("test_id") or "")):
        at = text.find("[")
        if at >= 0:
            return text[at:]
    return ""


def _classify(key: str, rows: list, item: dict, failed_block: bool, task_root: Path,
              reports: dict) -> dict:
    """What one block says of one function: `red`, `passed` or "" (nothing that counts).

    Red is `failed`/`error`, and `red_unconfirmed` — an unmapped `not_run` row ("report row
    missing") of a block whose run failed. Never red: broken_run, not_executed, timeout,
    inconclusive, skipped. A candidate is CONFIRMED against the block's raw report: the function
    failed or errored there, else it is not red whatever its row says (on cmp1 two functions that
    passed in the junit sat in unmapped rows of a failed block and would each have been a false
    pair). The report decides only when it NAMES the function: a report that cannot be read, or
    that does not list the function at all (the reader cuts its list of passed rows, and a test
    that was not collected is not listed either), leaves the row's own word, marked as such —
    "not named" is not "passed".

    The entry also carries the parameters of the block's rows: `params` (every row),
    `red_params` (the candidates) and `passed_params` (the rows that passed), which
    `_expectation_changes` needs to tell a pass that covers a red from one that does not."""
    candidates = []
    for row in rows:
        status = C.result_status(row)
        if status in RED_STATUSES:
            candidates.append((row, status))
        elif status == "not_run" and failed_block \
                and (str(row.get("reason") or "").strip().lower() == MISSING_ROW or row.get("reason_code") == "id_not_in_report"):
            candidates.append((row, "red_unconfirmed"))
    entry = {"block": item, "rows": rows, "status": "", "red_status": "", "basis": "", "row": None,
             "params": {_param_of(r) for r in rows},
             "red_params": {_param_of(r) for r, _status in candidates},
             "passed_params": {_param_of(r) for r in rows if C.result_status(r) == "passed"}}
    if candidates:
        if item["name"] not in reports:
            reports[item["name"]] = _read_report(task_root, item["data"])
        report = reports[item["name"]]
        said = _report_status(report, key) if report is not None else ""
        if said in RED_STATUSES:
            entry.update(status="red", red_status=said, basis="report", row=candidates[0][0])
        elif said != NAMED:
            row, status = sorted(candidates, key=lambda c: c[1] == "red_unconfirmed")[0]
            entry.update(status="red", red_status=status, row=row,
                         basis="unconfirmed" if status == "red_unconfirmed" else "row")
    if entry["status"] != "red":
        row = next((r for r in rows if C.result_status(r) == "passed"), None)
        if row is not None:
            entry.update(status="passed", row=row)
    return entry


def _current_test_names(task_root: Path, manifest: dict) -> tuple:
    """`({file stem: every function name defined in it}, stems that cannot be read as Python,
    stems of files the manifest names that are gone)` — what the story's test files hold NOW."""
    from s5_precheck import read_python, resolve_test_file
    names: dict = {}
    unsure: set = set()
    gone: set = set()
    for entry in C.manifest_tests(manifest):
        relative = str(entry.get("file") or "") if isinstance(entry, dict) else ""
        if not relative:
            continue
        stem = Path(relative).stem
        resolved = resolve_test_file(task_root, relative)
        if resolved is None:
            gone.add(stem)
        elif resolved.suffix != ".py":
            unsure.add(stem)
        else:
            parsed, _problem = read_python(resolved)
            if parsed is None:
                unsure.add(stem)
            else:
                names.setdefault(stem, set()).update(
                    n.name for n in ast.walk(parsed.tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return names, unsure, gone


def _still_defined(identity: tuple, current: tuple):
    """True / False / None (cannot tell): is this function defined in the test file of its
    module NOW? A name absent from the file, or a file that is gone, is a rename, a move or a
    deletion."""
    names, unsure, gone = current
    module, _chain, function = identity
    if module:
        if module in names:
            return function in names[module]
        if module in gone:
            return False
        if unsure:
            return None  # a file that cannot be read as Python may be the one that holds it
        return False if (names or gone) else None
    if any(function in defined for defined in names.values()):
        return True
    if unsure:
        return None
    return False if (names or gone) else None


def _manifest_cases(manifest: dict, identity: tuple, cfg: dict) -> list:
    module, _chain, function = identity
    out: list = []
    for entry in C.manifest_tests(manifest):
        if not isinstance(entry, dict):
            continue
        raw = entry.get("test_function") or entry.get("function") or C.test_instance_id(entry)
        stem = Path(str(entry.get("file") or "")).stem
        if C.function_name(raw) != function or (module and stem and stem != module):
            continue
        out += [case for case in C.manifest_test_links(entry, cfg) if case not in out]
    return out


def expectation_records(manifest: dict) -> list:
    """The `expectation_changes[]` rows of the manifest that are objects; [] for a story in
    flight whose manifest has no such key, and for a key that is not a list."""
    rows = (manifest or {}).get("expectation_changes")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def record_functions(record: dict) -> list:
    """Every function a record names: `functions` (several that share one red and one green
    attempt), and `function` (the one-element form)."""
    names = [str(n) for n in record.get("functions") or []] if isinstance(record.get("functions"), list) else []
    if isinstance(record.get("function"), str) and record["function"] not in names:
        names.append(record["function"])
    return names


def record_for(pair: dict, records: list):
    """The record that answers this pair: it names the function and carries the same red and
    green attempts (`green_attempt` null for an orphaned red). The last one wins."""
    hit = None
    for record in records:
        if pair["function"] in record_functions(record) \
                and str(record.get("red_attempt") or "") == pair["red_attempt"] \
                and (record.get("green_attempt") or None) == pair["green_attempt"]:
            hit = record
    return hit


def expectation_changes(task_root, cases, manifest) -> dict:
    """`{"pairs": [...], "unmeasured": [...]}` — every test that went red and later passed on
    code that changed, or went red and then disappeared. Pure: it writes nothing (FR-45).

    A pair is the FIRST red of a function after its last pass, and the first later pass; it
    carries `function`, `instance_ids`, `cases`, `red_attempt`, `red_block`, `red_status`
    (failed | error | red_unconfirmed), `red_basis` (report | row | unconfirmed), `green_attempt`,
    `green_block`, `sha_basis` (code | raw | file | unknown), `red_sha`, `green_sha`,
    `red_evidence` (the red block's raw report), `stage_of_red`, `stage_of_green`, `orphan`,
    `owed`, `intermediate_shas`, `note` and `record` (the joined `expectation_changes[]` row, or
    None). A red whose function is gone from its test file has `green_attempt: None`: the
    expectation went somewhere and nothing says where. A test that still exists and is handed
    over RED (FR-34) has no pair — it is not a change.

    `owed` is true when the green attempt (the red attempt, for an orphan) is not a dispatch of
    another stage and one of the pair's cases is in `cases`; every other pair is listed only.

    Nothing here raises: an error becomes an `unmeasured` entry, because `detector_main` returns
    0 on any exception and a crash in this code would switch off the whole S5 check (R1a)."""
    try:
        return _expectation_changes(Path(task_root), list(cases or []), manifest or {})
    except Exception as exc:
        return {"pairs": [], "unmeasured": [
            f"the expectation-change measurement failed ({type(exc).__name__}: {exc}); "
            "nothing was compared, so a test changed after its red run would not be listed"]}


def _join_bare_keys(histories: dict, identities: dict) -> None:
    """A row with no reporter id has only the function's bare name for a key; the same test in
    another block, with its reporter id, is `<module>.<classes>.<function>`. Left apart, a red
    under one spelling and the green under the other never meet and the change passes silently.
    Every bare history is joined, in block order, into each qualified history of the same
    function name — a name shared by two classes or files joins both, which errs toward "changed"
    — and the bare key is dropped. A bare key with no qualified twin stays as it is."""
    for bare in [k for k, (module, chain, _f) in identities.items() if k in histories and not module and not chain]:
        twins = [k for k, (module, chain, function) in identities.items()
                 if k in histories and k != bare and (module or chain) and function == identities[bare][2]]
        if not twins:
            continue
        for twin in twins:
            histories[twin] = sorted(histories[twin] + histories[bare],
                                     key=lambda e: (e["order"], e["status"] != "red"))
        del histories[bare]


def _expectation_changes(task_root: Path, cases: list, manifest: dict) -> dict:
    from s5_precheck import _load
    cfg = C.case_config(task_root)
    blocks, bad = read_run_blocks(task_root)
    unmeasured = [f"work/run-blocks/{name} is not a readable JSON object, so a red or a green in "
                  "it may be missing from this list" for name in bad]
    jobs = _job_records(task_root)
    dispatches = _dispatch_index(_load(task_root / "state" / "controller.json"))
    reports: dict = {}
    identities: dict = {}
    histories: dict = {}
    for position, item in enumerate(blocks):
        data = item["data"]
        item["stage"] = _stage_of(data, dispatches)
        results = data.get("results")
        if not isinstance(results, list):
            continue
        failed_block = str(data.get("execution_status") or "") == "failed"
        by_key: dict = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            identity = _function_identity(row.get("test_id"), row.get("instance_id"))
            key = ".".join(part for part in (identity[0], *identity[1], identity[2]) if part)
            if key:
                identities.setdefault(key, identity)
                by_key.setdefault(key, []).append(row)
        for key, rows in by_key.items():
            entry = _classify(key, rows, item, failed_block, task_root, reports)
            entry["order"] = position
            histories.setdefault(key, []).append(entry)
    _join_bare_keys(histories, identities)

    current = None
    cannot_tell: list = []
    pairs: list = []
    for key in sorted(histories):
        entries = histories[key]
        pending, later, open_params, retired = None, [], set(), set()
        for index, entry in enumerate(entries):
            if entry["status"] == "red":
                if pending is None:
                    pending, later, open_params, retired = index, [], set(entry["red_params"]), set()
                else:
                    later.append(index)
                    open_params |= entry["red_params"]
            elif entry["status"] == "passed" and pending is not None:
                # A pass clears the pending red only when it covers the red's parameters: one
                # that ran OTHER parameters says nothing about the red one. A red parameter that
                # never appears in a later block is retired (renamed or dropped) and is not
                # waited for — cmp1 renamed every parameter id between its red and its green.
                uncovered = (open_params | retired) - entry["passed_params"]
                open_params = {p for p in uncovered
                               if any(p in later_entry["params"] for later_entry in entries[index + 1:])}
                retired = uncovered - open_params
                if open_params:
                    later.append(index)  # intermediate: its sha is listed, the red stays pending
                    continue
                pair = _make_pair(key, entries, pending, later, index, jobs)
                if pair is None and retired:
                    # The red's parameters were only RETIRED (renamed or dropped: no pass ever
                    # covered them), and this pass is the same bytes as the red: it covers nothing
                    # the red ran, so it clears nothing. The red stays pending for the next pass on
                    # changed bytes of the function (t-149, B2: P1 red on X, P2 alone passes on X,
                    # P1 renamed passes on Y used to give no pair and hide the change). The error
                    # direction is the allowed one: one record too many, never a change unsaid.
                    later.append(index)
                    continue
                if pair is not None:
                    pairs.append(pair)
                pending, retired = None, set()
        if pending is not None:
            current = current or _current_test_names(task_root, manifest)
            defined = _still_defined(identities[key], current)
            if defined is None:
                cannot_tell.append(key)
            elif defined is False:
                pairs.append(_make_pair(key, entries, pending, later, None, jobs))
    tool_lines: list = []
    if cannot_tell:
        # M-6: the reader is the factory's (it reads Python only), so this line is a gap of the TOOL, not of the product: it is
        # also listed in `unmeasured_tool`, and the report says so (FR-19). It stays a plain string in `unmeasured` for every
        # reader that adds text to it (`s5_precheck.check_expectation_changes`).
        line = ("a red run has no later pass for " + ", ".join(cannot_tell[:6])
                + (f" and {len(cannot_tell) - 6} more" if len(cannot_tell) > 6 else "")
                + ", and the test file that would say whether the test still exists cannot be read by this reader")
        unmeasured.append(line)
        tool_lines.append(line)

    records = expectation_records(manifest)
    for pair in pairs:
        identity = identities[pair["function"]]
        seen = list(pair.pop("_case_rows"))
        found: list = []
        for row in seen:
            found += [case for case in C.manifest_test_links(row, cfg) if case not in found]
        found += [case for case in _manifest_cases(manifest, identity, cfg) if case not in found]
        pair["cases"] = sorted(found)
        stage = pair["stage_of_red"] if pair["orphan"] else pair["stage_of_green"]
        in_scope = any(C.case_matches(case, wanted, cfg=cfg) for case in pair["cases"] for wanted in cases)
        pair["owed"] = in_scope and (not stage or stage == "S5")
        pair["record"] = record_for(pair, records)
    pairs.sort(key=lambda p: (p["function"], p["red_block"], p["green_block"] or ""))
    return {"pairs": pairs, "unmeasured": unmeasured, "unmeasured_tool": tool_lines}


def _make_pair(key: str, entries: list, red_at: int, later: list, green_at, jobs: dict):
    """One pair, or None when the two runs are provably the same bytes. `green_at` None: the red
    has no later pass and its function is gone (an orphaned red)."""
    red = entries[red_at]
    green = entries[green_at] if green_at is not None else None
    red_shas = _shas(red["row"], red["block"], jobs)
    note = ""
    if green is None:
        verdict, basis, red_sha, green_sha = "unknown", "unknown", _first_sha(red_shas), ""
    else:
        green_shas = _shas(green["row"], green["block"], jobs)
        verdict, basis, red_sha, green_sha = _compare_shas(red_shas, green_shas)
        if verdict == "same":
            return None
        one, two = red["block"], green["block"]
        if one["attempt"] != two["attempt"] and (
                not (one["started"] and two["started"]) or one["time"] == two["time"]):
            note = "attempt order unknown"
    intermediate: list = []
    for index in later:
        shas = _shas(entries[index]["row"], entries[index]["block"], jobs)
        value = _first_sha(shas)
        if value and value != red_sha and value not in intermediate:
            intermediate.append(value)
    end = green_at if green_at is not None else len(entries) - 1
    span = entries[red_at:end + 1]
    return {
        "function": key,
        "instance_ids": sorted({str(r.get("instance_id") or "") for e in span for r in e["rows"]} - {""}),
        "cases": [], "red_attempt": red["block"]["attempt"], "red_block": red["block"]["name"],
        "red_status": red["red_status"], "red_basis": red["basis"],
        "green_attempt": green["block"]["attempt"] if green else None,
        "green_block": green["block"]["name"] if green else None,
        "sha_basis": basis, "red_sha": red_sha, "green_sha": green_sha,
        "red_evidence": _report_path(red["block"]["data"]),
        "stage_of_red": red["block"].get("stage", ""), "stage_of_green": green["block"].get("stage", "") if green else "",
        "orphan": green is None, "owed": False, "intermediate_shas": intermediate,
        "note": note, "record": None,
        # when the pair came to exist: its green run's clock (an orphan: its red run's), "" when no
        # block carries a clock - a stage-wide word of a person covers the pairs that existed when it
        # was given (`s5_precheck.passed_by_word`)
        "pair_at": _iso_time((green or red)["block"]),
        "_case_rows": [r for e in span for r in e["rows"]]}


def _iso_time(block: dict) -> str:
    """The clock `read_run_blocks` put on a block as ISO text, "" when it had none (the epoch)."""
    moment = block.get("time")
    return "" if moment is None or moment == _EPOCH else moment.isoformat()


def _first_sha(shas: dict) -> str:
    return next((shas[b] for b in SHA_FIELDS_ORDER if shas[b]), "")


# --- public names for readers outside this file (t-183, B-208) ----------------------------------
# `finalize_task` needs the ONE definition of red and the ONE clock parser without reaching for an
# underscore name; these are thin wrappers, the rules stay where they are.

def parse_time(value):
    """An ISO clock as an aware UTC datetime, or None when it is absent or unreadable."""
    return _parse_time(value)


def same_function(left: str, right: str) -> bool:
    """Two `function_key`s name one function: equal, or one is a bare name (a row with no reporter
    id) and the other ends in it — the match `_report_status` uses. An error here only widens a
    history, which is the safe direction for every reader."""
    if not left or not right:
        return False
    return (left == right or ("." not in left and right.rsplit(".", 1)[-1] == left)
            or ("." not in right and left.rsplit(".", 1)[-1] == right))


def red_blocks(task_root, function: str, blocks=None, reports=None) -> list:
    """Positions, in the block order of `read_run_blocks`, of the blocks whose rows of `function` (a
    `function_key`) hold a red by R5/R5a (`_classify`): `failed`/`error`, or an unmapped `not_run`
    row of a failed block unless the block's own raw report names the function as not red.

    `blocks` is the list `read_run_blocks` returned (read when None) and `reports` the cache of raw
    reports a caller passes to read each one once. Writes nothing (FR-45)."""
    task_root = Path(task_root)
    items = blocks if blocks is not None else read_run_blocks(task_root)[0]
    cache = reports if reports is not None else {}
    found = []
    for position, item in enumerate(items):
        data = item["data"]
        results = data.get("results")
        rows = [row for row in results if isinstance(row, dict)
                and same_function(function_key(row.get("test_id"), row.get("instance_id")), function)] \
            if isinstance(results, list) else []
        if rows and _classify(function, rows, item, str(data.get("execution_status") or "") == "failed",
                              task_root, cache)["status"] == "red":
            found.append(position)
    return found
