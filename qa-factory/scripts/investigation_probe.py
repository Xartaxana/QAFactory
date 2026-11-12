#!/usr/bin/env python3
"""investigation_probe.py - the ONE bounded, read-only tool of the S7 investigation pass (Problem 2, M3).

    investigation_probe.py http   --task-root T --dispatch D --target X --method GET --url U [--header "N: v"]... [--phase P]
    investigation_probe.py record --task-root T --dispatch D --target X --kind K --statement S --why-not-a-bug W --status V ...

`http` sends ONE read-only request to the configured stand, saves the answer under
`work/evidence/investigation/<root>/<X>/NNN-request-response.json` and counts it in `captures.jsonl` of the PASS (the
pass is the retry/relaunch chain of the investigation dispatch, named by its lineage root: a restart continues the counts
and the clock, it never refreshes them). Code enforces the limits P (probes per pass), R (probes per target) and T
(minutes from the first probe); the numbers and the allowed methods are DATA in `references/investigation-budget.json`
(AR-1). `record` writes what the role saw into the findings register, through the register's one writer, with the
`probes` counts taken from the captures (a role never types them) and only the statuses the captures support.

What the role still decides (AR-2 / AR-7): which target to probe, which URL and header, when to stop, what the findings
mean, and which status to record within the bounds. The tool never compares an answer with an expected value, never
writes a bug, a triage row or a ledger outcome, and never writes the word `investigated`.

HONEST BOUNDARY: these limits bound this tool only. A role that reaches the stand through Bash or another tool is not
counted and its request cannot be cited; two calls at the same moment can each pass the count before either is written;
a process killed between the request and its `captures.jsonl` line leaves a probe uncounted. Enforcing read-only access
beyond the tool (E1/E2) is deferred by the owner. See the changelog fragment p2-m3-investigation.md.

Every refusal is a `ValueError` under `role_cli.run_guarded`: exit 2, stdout empty, nothing sent and nothing written
(a missing or unreadable checker, budget, state, pipeline or captures file is a refusal, never a pass: AR-28).
`controller.s7_part_of`, `controller.lineage_root`, `investigation.*` and `exploratory_findings.*` are looked up when a
call needs them (`_required`): while one of them is not installed the call refuses and names it.
"""
import argparse
import importlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract
import controller as CT
import hooklib
import http_client
import install_paths
import manual_capture as MC
from role_cli import RefusingParser, command_from_argv, run_guarded

SCRIPT = "investigation_probe.py"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
BUDGET_PATH = PLUGIN_ROOT / "references" / "investigation-budget.json"
EVIDENCE_PARTS = ("work", "evidence", "investigation")
CAPTURES = "captures.jsonl"
LINEAGE_KEYS = ("parent_retry", "relaunch_of")        # the dispatch record fields that make a retry/relaunch continue a pass
NOT_INSTALLED_TAIL = "Finish your hand-back with what you have; this is a factory defect, not your mistake."
KINDS = ("observation", "unresolved_question", "coverage_gap")
STATUSES = ("unverified", "reproduced", "not_reproduced", "environment_event")
ORACLE_STATUSES = ("none", "documented_text_only", "owner_question")
ORACLE_DEFAULT = {"unresolved_question": "owner_question", "observation": "none", "coverage_gap": "none"}
CHAIN_NAMES = ("controller.s7_part_of", "controller.lineage_root", "investigation.pass_members",
               "investigation.unresolved_targets")
REGISTER_NAMES = ("exploratory_findings.read", "exploratory_findings.append", "exploratory_findings.chains_of")
METHOD_OVERRIDE_HEADERS = ("x-http-method-override", "x-http-method", "x-method-override")      # a GET that is not read-only
HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
NUMBER = re.compile(r"[0-9]{1,9}")
PREFIX = re.compile(r"([0-9]{1,9})-")
TITLE_CHARS = 120

NOW = None            # () -> aware datetime; production leaves it None (the clock is the system's). NOT a flag or an
                      # environment variable: the capped role could set those and move its own timebox (F-1).


def _now() -> datetime:
    moment = NOW() if NOW else datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _moment(text):
    """An aware datetime from an ISO text, else None."""
    try:
        moment = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _shown(value, limit=80) -> str:
    """A role's value as it is quoted back in a refusal: escaped, so a lookalike letter is visible, and cut."""
    return ascii(str(value))[:limit]


# --------------------------------------------------------------------------------------------
# what may be absent: the functions of modules that land later (the temporal rule)
# --------------------------------------------------------------------------------------------

def _required(names) -> list:
    """The functions `names` (`module.function`) in the order given, or a ValueError naming EVERY missing one in that order.
    A missing checker is never read as "no objection": no probe is sent and no line is written unless every check really ran."""
    found, missing = [], []
    for name in names:
        module_name, _, attribute = name.partition(".")
        module = CT if module_name == "controller" else None
        if module is None:
            try:
                module = importlib.import_module(module_name)
            except Exception:       # absent, or present and broken: either way its checks cannot run
                module = None
        function = getattr(module, attribute, None) if module is not None else None
        if callable(function):
            found.append(function)
        else:
            missing.append(name)
    if not missing:
        return found
    listed = ", ".join(f"`{name}`" for name in missing)
    if all(name in REGISTER_NAMES for name in missing):
        raise ValueError(f"the findings register is not installed ({listed}): nothing was recorded. {NOT_INSTALLED_TAIL}")
    raise ValueError(f"{listed} is not installed in this factory: the investigation's dispatch, chain and target checks "
                     f"cannot run, so no probe is sent. {NOT_INSTALLED_TAIL}")


def _ask(what: str, function, *args):
    """`function(*args)`, an exception of the checker ended as the refusal "whether <what> is unknown, so nothing is done"."""
    try:
        return function(*args)
    except Exception as exc:
        raise ValueError(f"{what} cannot be read ({exc.__class__.__name__}): whether this call may go on is unknown, "
                         "so nothing is done. Finish your hand-back with what you have; this is a factory defect, "
                         "not your mistake")


# --------------------------------------------------------------------------------------------
# the budget
# --------------------------------------------------------------------------------------------

def read_budget() -> dict:
    """The budget file, judged by `investigation.budget_problems` (ONE rule, ONE owner: no second predicate here).
    A non-empty answer refuses the call with the problems printed."""
    budget = hooklib.read_json(BUDGET_PATH, None, kind=dict)
    problems = _ask("references/investigation-budget.json", _required(["investigation.budget_problems"])[0], budget)
    if problems:
        raise ValueError("references/investigation-budget.json: " + "; ".join(str(p) for p in problems)
                         + ": the investigation's limits come from it, so no probe is sent. " + NOT_INSTALLED_TAIL)
    return budget


# --------------------------------------------------------------------------------------------
# the captures of a pass
# --------------------------------------------------------------------------------------------

def pass_dir(task: Path, root: str) -> Path:
    return Path(task).joinpath(*EVIDENCE_PARTS, root)


def _path_ok(path, root: str) -> bool:
    """A capture line's `path` is a task-relative posix path under THIS pass's folder (a hand-edited line cannot point elsewhere)."""
    if path is None:
        return True
    if not isinstance(path, str) or "\\" in path or "\x00" in path:
        return False
    parts = path.split("/")
    return ".." not in parts and path.startswith("/".join((*EVIDENCE_PARTS, root)) + "/")


def read_pass(task: Path, root: str) -> dict:
    """{"started": datetime|None, "captures": [line], "problem": str|""} of the pass's `captures.jsonl`.

    Absent file: no probes, no clock. A header is a line with `started_at` and no `n` (the FIRST one wins). A capture line has an
    int `n` (not a bool), a str `target` and a `path` that is null or inside the pass's folder; anything else - a line that is
    not a JSON object included - is DAMAGED and `problem` names the first one: the probes made cannot be counted. Captures
    with no header have no clock: also a problem. An unreadable file is a refusal (AR-28)."""
    path = pass_dir(task, root) / CAPTURES
    out = {"started": None, "captures": [], "problem": ""}
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return out
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"captures.jsonl of this investigation cannot be read ({exc.__class__.__name__}): the probes made "
                         "cannot be counted, so no probe is sent. Record what you have with `investigation_probe.py record`")
    for number, raw in enumerate(text.split("\n"), 1):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except ValueError:
            line = None
        if not isinstance(line, dict):
            out["problem"] = out["problem"] or f"line {number}"
            continue
        if "n" not in line and "started_at" in line:
            started = _moment(line["started_at"])
            if started is None:
                out["problem"] = out["problem"] or f"line {number}"
            elif out["started"] is None:
                out["started"] = started
            continue
        n = line.get("n")
        if (type(n) is not int or not isinstance(line.get("target"), str) or not _path_ok(line.get("path"), root)):
            out["problem"] = out["problem"] or f"line {number}"
            continue
        out["captures"].append(line)
    if out["captures"] and out["started"] is None and not out["problem"]:
        out["problem"] = "the header (started_at)"
    return out


def _damaged_refusal(problem: str) -> str:
    return (f"captures.jsonl of this investigation has a damaged line ({problem}): the probes made cannot be counted, so no "
            "probe is sent; record what you have with `investigation_probe.py record`")


def _citable(line: dict) -> bool:
    return line.get("path") is not None


def _reach(line, started):
    return _moment(line.get("captured_at")) or started or datetime.min.replace(tzinfo=timezone.utc)


def reached_limit(state: dict, target: str, budget: dict, now: datetime):
    """The first limit reached (the earliest reach moment; ties in order P, R, T) as its words, else None."""
    p_cap, r_cap, t_min = budget["probes_per_dispatch"], budget["reproductions_per_target"], budget["timebox_minutes"]
    started, captures = state["started"], state["captures"]
    options = []
    if len(captures) >= p_cap:
        options.append((_reach(captures[p_cap - 1], started), 0, f"{p_cap} probes in this investigation"))
    mine = [c for c in captures if c["target"] == target]
    if len(mine) >= r_cap:
        options.append((_reach(mine[r_cap - 1], started), 1, f"{r_cap} probes for target {target}"))
    if started is not None and now >= started + timedelta(minutes=t_min):
        options.append((started + timedelta(minutes=t_min), 2, f"the {t_min}-minute timebox"))
    return min(options)[2] if options else None


def next_number(task: Path, root: str, state: dict) -> int:
    """1 + the largest number in `captures.jsonl` and the largest NNN prefix of any file under the pass's folder."""
    biggest = max((c["n"] for c in state["captures"]), default=0)
    folder = pass_dir(task, root)
    if folder.is_dir():
        for sub in folder.iterdir():
            if sub.is_dir():
                for item in sub.iterdir():
                    found = PREFIX.match(item.name)
                    if found:
                        biggest = max(biggest, int(found.group(1)))
    return biggest + 1


def append_capture(task: Path, root: str, started: datetime, line: dict) -> None:
    """ONE `\\n`-terminated append (`hooklib.append_jsonl_line`, O_APPEND). When the file is absent or empty the header and
    the line go in the SAME write: a header without a probe cannot exist. A torn tail (no final newline) gets one first."""
    hooklib.append_jsonl_line(pass_dir(task, root) / CAPTURES, json.dumps(line, ensure_ascii=False),
                              header=json.dumps({"started_at": started.isoformat(timespec="seconds")}))


def capture_lines(task_root) -> list:
    """[capture line] of EVERY pass of the story (`work/evidence/investigation/<root>/captures.jsonl`, the header lines are not
    captures) - the ONE reader of the probes made, with `read_pass`'s own damaged-line rule. No folder: []. A pass whose file
    cannot be read or holds a damaged line is a ValueError (the probes cannot be counted: never a number that looks right).
    What the caller still decides: what an uncountable pass means for its own text."""
    base = Path(task_root).joinpath(*EVIDENCE_PARTS)
    out: list = []
    if not base.is_dir():
        return out
    for folder in sorted(base.iterdir()):
        if not folder.is_dir():
            continue
        held = read_pass(Path(task_root), folder.name)
        if held["problem"]:
            raise ValueError(_damaged_refusal(held["problem"]))
        out.extend(held["captures"])
    return out


# --------------------------------------------------------------------------------------------
# the checks both commands share (steps 3a, 3c, 3d)
# --------------------------------------------------------------------------------------------

def _dispatch_state(task: Path, dispatch: str, part_of) -> tuple:
    """(state, record) of D, which must be a RUNNING S7 dispatch whose purpose is `investigation`."""
    try:
        state = CT.Controller(task).state()
        dispatches = state["dispatches"]
        if not isinstance(dispatches, dict):
            raise TypeError("dispatches")
    except Exception as exc:
        raise ValueError(f"the controller's state cannot be read ({exc.__class__.__name__}): whether this dispatch may probe "
                         "is unknown, so no probe is sent")
    record = dispatches.get(dispatch)
    stage = record.get("stage") if isinstance(record, dict) else None
    purpose = _ask("the dispatch's purpose", part_of, record) if isinstance(record, dict) else None
    status = record.get("status") if isinstance(record, dict) else None
    if not (isinstance(record, dict) and stage == "S7" and purpose == "investigation" and status == "running"):
        raise ValueError(f"dispatch {_shown(dispatch)} is not a running S7 investigation ({stage}/{purpose}/{status}): only "
                         "the running investigation dispatch probes")
    return state, record


def _target_ok(target: str) -> bool:
    return isinstance(target, str) and MC._PART.fullmatch(target) is not None


def _not_a_target(target) -> ValueError:
    return ValueError(f"{_shown(target)} is not a target; `investigation.py unresolved --task-root <T>` lists them")


def _gate_b(task: Path) -> None:
    pipeline = hooklib.read_json(task / "pipeline.json", None, kind=dict)
    if pipeline is None:
        raise ValueError("pipeline.json cannot be read: whether gate B is answered is unknown, so no probe is sent")
    if contract.gate_answered(pipeline, "B"):
        raise ValueError("gate B is answered; no investigation after it")


def _chain_root(state: dict, dispatch: str, lineage_root, pass_members) -> str:
    """The lineage root of D (the pass's key); a member of the pass with another root is a SECOND investigation."""
    dispatches = state["dispatches"]
    root = _ask("the dispatch chain", lineage_root, dispatches, dispatch, LINEAGE_KEYS)
    if not _target_ok(root):
        raise ValueError(f"the chain root {_shown(root)} of dispatch {_shown(dispatch)} is not a usable folder name: no probe is sent")
    for member in _ask("the investigation's pass", pass_members, state):
        identifier = member.get("id") if isinstance(member, dict) else None
        if not isinstance(identifier, str) or _ask("the dispatch chain", lineage_root, dispatches, identifier,
                                                    LINEAGE_KEYS) != root:
            raise ValueError("a second investigation in one S7 chain is not run")
    return root


def _targets(task: Path, budget: dict, unresolved_targets) -> dict:
    answer = _ask("the investigation's targets", unresolved_targets, task, budget)
    if not isinstance(answer, dict) or not isinstance(answer.get("unresolved"), list):
        raise ValueError("the investigation's targets cannot be read (an unexpected answer): whether this target may be "
                         "probed is unknown, so nothing is done")
    return answer


def _resolved_why(answer: dict, target: str):
    for row in answer.get("resolved") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2 and row[0] == target:
            return row[1]
    return None


# --------------------------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------------------------

def _headers_of(raw_headers, url: str, cfg: dict) -> dict:
    headers = {}
    for raw in raw_headers or []:
        raw = str(raw)
        if any(ch in raw for ch in "\r\n\x00"):
            raise ValueError(f"--header {_shown(raw)} holds a line break or a NUL: a header is one line `Name: value`")
        name, sep, value = raw.partition(":")
        name = name.strip()
        if not sep or not name or not HEADER_NAME.fullmatch(name):
            raise ValueError(f"--header {_shown(raw)} is not `Name: value` (a name of letters, digits and - _ . only)")
        if name.lower() == "host":
            raise ValueError("the Host header is set by the URL; a probe never leaves the stand")
        if name.lower() in METHOD_OVERRIDE_HEADERS:
            raise ValueError(f"--header {name} asks the server to treat this request as another method: a read-only probe "
                             "carries no method override; send the method you mean in --method")
        headers[name] = value.strip()
    if any(ch in url for ch in "\r\n\x00"):
        raise ValueError("--url holds a line break or a NUL: a probe never leaves the stand")
    for text in [url, *(f"{k}: {v}" for k, v in headers.items())]:
        hit = MC.secret_pattern_hit(text, cfg)
        if hit is not None:
            raise ValueError(f"the request matches secret_content_patterns[{hit}] of config.json: nothing was sent or "
                             "saved. A credential never goes in a request you write; login is done by code")
    return headers


def _used(state_captures: list, target: str) -> tuple:
    return len(state_captures), sum(1 for c in state_captures if c["target"] == target)


def _report(budget: dict, captures: list, target: str, started: datetime, now: datetime) -> tuple:
    p, r = _used(captures, target)
    seconds = int((started + timedelta(minutes=budget["timebox_minutes"]) - now).total_seconds())
    return ({"p": p, "r": r},
            {"p": max(0, budget["probes_per_dispatch"] - p), "r": max(0, budget["reproductions_per_target"] - r),
             "seconds": max(0, seconds)})


def run_http(task: Path, args) -> int:
    budget = read_budget()
    method = str(args.method).upper()
    if method not in budget["methods"]:
        raise ValueError(f"--method {_shown(args.method)} is none of {', '.join(budget['methods'])} (read-only probes only); "
                         "a request that changes the stand is not made by this tool")
    part_of, lineage_root, pass_members, unresolved_targets = _required(list(CHAIN_NAMES))
    state, _ = _dispatch_state(task, args.dispatch, part_of)
    target = args.target
    if not _target_ok(target):
        raise _not_a_target(target)
    answer = _targets(task, budget, unresolved_targets)
    if target not in {t.get("id") for t in answer["unresolved"] if isinstance(t, dict)}:
        why = _resolved_why(answer, target)
        raise ValueError(f"{target} is resolved: {why}" if why is not None else str(_not_a_target(target)))
    _gate_b(task)
    root = _chain_root(state, args.dispatch, lineage_root, pass_members)
    # the caps: counts, file and clock are per PASS (the chain root), read before anything is sent
    held = read_pass(task, root)
    if held["problem"]:
        raise ValueError(_damaged_refusal(held["problem"]))
    now = _now()
    cause = reached_limit(held, target, budget, now)
    if cause:
        k = sum(1 for c in held["captures"] if c["target"] == target and _citable(c))
        raise ValueError(f"investigation probe limit reached ({cause}): record what you have - `investigation_probe.py record "
                         f"... --status unverified` ({k} of {budget['reproductions_per_target']}); more needs the person's "
                         "word at gate B")
    started = held["started"] or now
    spec_data = MC.spec()
    if args.phase not in spec_data["phases"]:
        raise ValueError(f"--phase {_shown(args.phase)} is none of {' | '.join(spec_data['phases'])}")
    cfg, project = MC.load_config(task)
    env = MC.environment_of(args.url, cfg, root=project)
    headers = _headers_of(args.header, args.url, cfg)
    timeout_s = MC.timeout_for(env)
    if not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = http_client.user_agent()
    MC.login_recipe(cfg, spec_data, "http")      # a malformed recipe is refused before any attempt exists
    login = None if MC.login_declared_none(cfg, "http") else MC.read_login(cfg, project)
    client = MC.HTTP or MC.UrllibHttp()
    if login is not None and not any(k.lower() == "authorization" for k in headers):
        # THE one non-GET call of this tool: manual_capture's own recipe, to the address http_login_source names, never to --url;
        # it is not a probe and is not counted. No token is kept.
        try:
            headers["Authorization"] = "Bearer " + MC._http_login(client, env, login, spec_data, cfg, timeout_s, project)
        except MC.EnvBlocked as exc:     # EP1-31: the project's sign-in is not a request the factory knows
            raise ValueError(f"{exc}; no probe was sent. Say so in your findings")
        except (MC.StepTimeout, MC.StepFailed) as exc:
            raise ValueError(f"login by code did not answer ({exc.__class__.__name__}); no probe was sent. Say so in your findings")
    # ---- the request: from here on the stand has been asked, so what happens is COUNTED (F-5)
    outcome, result = None, None
    try:
        result = client.request(method, args.url, dict(headers), None, timeout_s)
        if result.elapsed_s > timeout_s or getattr(result, "unreadable", False):
            outcome = "timeout"
    except MC.StepTimeout:
        outcome = "timeout"
    except Exception:
        outcome = "no_answer"
    state_now = read_pass(task, root)          # fresh: the numbers are taken as late as possible
    if state_now["problem"]:
        raise ValueError(_damaged_refusal(state_now["problem"]))
    n = next_number(task, root, state_now)
    name = f"{n:03d}"
    line = {"n": n, "dispatch": args.dispatch, "target": target, "method": method, "url": args.url, "status": None,
            "path": None, "sha256": None, "captured_at": _now().isoformat(timespec="seconds")}
    path = None
    if outcome is None:
        document = {"schema_version": 1, "dispatch": args.dispatch, "root": root, "target": target, "n": n,
                    "phase": args.phase,
                    "request": MC._side(None, headers, spec_data, method=method, url=args.url),
                    "response": MC._side(result.body, result.headers, spec_data, status=result.status,
                                         elapsed_s=round(result.elapsed_s, 3)),
                    "limit": None}
        if document["response"]["truncated"]:
            document["limit"] = MC._limit_words("response")
        elif document["request"]["truncated"]:
            document["limit"] = MC._limit_words("request")
        text = json.dumps(document, ensure_ascii=False, indent=2)
        if MC.secret_pattern_hit(text, cfg) is not None:
            outcome = "withheld_secret"          # the answer is not saved; the probe was made, so it is counted
        else:
            path = pass_dir(task, root) / target / f"{name}-request-response.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(path, "xb") as handle:
                    handle.write(text.encode("utf-8"))
            except FileExistsError:
                raise ValueError(f"another probe of this investigation took number {name}; run the probe again")
            line.update(status=result.status, path=path.relative_to(task).as_posix(),
                        sha256=install_paths.sha256_file(path))
    if outcome:
        line["outcome"] = outcome
    append_capture(task, root, started, line)          # LAST: a capture exists for the pass only once its line does
    after = state_now["captures"] + [line]
    used, left = _report(budget, after, target, started, _now())
    if outcome:
        print(json.dumps({"ok": False, "outcome": outcome, "used": used, "left": left}))
        return 1
    print(json.dumps({"ok": True, "capture": {"n": n, "path": line["path"], "sha256": line["sha256"],
                                              "status": line["status"]}, "used": used, "left": left}))
    return 0


# --------------------------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------------------------

def _numbers(text, held: dict) -> list:
    """The capture numbers `--reproduced-by` names (`001` = 1, duplicates collapse), each a SAVED capture of the target."""
    if text is None or not str(text).strip():
        return []
    found, seen = [], set()
    for piece in str(text).split(","):
        piece = piece.strip()
        if not NUMBER.fullmatch(piece):
            raise ValueError(f"--reproduced-by {_shown(piece, 40)} is not a capture number: name the captures as 1,2,3 "
                             f"(the `n` of the probe's answer); the numbers of this target are {held or 'none yet'}")
        if int(piece) not in seen:
            seen.add(int(piece))
            found.append(int(piece))
    return found


def _carrier_paths(target: dict) -> list:
    """The paths a target itself names (its carrier record and its evidence), as strings: the evidence of a record with no capture."""
    paths = []
    for value in (target.get("carrier"), target.get("evidence")):
        for item in (value if isinstance(value, (list, tuple)) else [value]):
            item = item.get("path") if isinstance(item, dict) else item
            if isinstance(item, str) and item and item not in paths:
                paths.append(item)
    return paths


def run_record(task: Path, args) -> int:
    if args.runs is not None or args.reproduced is not None:
        raise ValueError("counts come from the captures of this investigation; name the captures that reproduced it with "
                         "--reproduced-by")
    budget = read_budget()
    names = list(CHAIN_NAMES) + list(REGISTER_NAMES)
    part_of, lineage_root, pass_members, unresolved_targets, register_read, register_append, chains_of = _required(names)
    state, _ = _dispatch_state(task, args.dispatch, part_of)
    _gate_b(task)
    root = _chain_root(state, args.dispatch, lineage_root, pass_members)
    target, required = args.target, budget["reproductions_per_target"]
    if not _target_ok(target):
        raise _not_a_target(target)
    held = read_pass(task, root)
    mine = [c for c in held["captures"] if c["target"] == target and _citable(c)]
    answer = _targets(task, budget, unresolved_targets)
    entry = next((t for t in answer["unresolved"] if isinstance(t, dict) and t.get("id") == target), None)
    if entry is None and not mine:
        why = _resolved_why(answer, target)
        raise ValueError(f"{target} is resolved: {why}" if why is not None else str(_not_a_target(target)))
    runs = len(mine)
    reproduced_by = _numbers(args.reproduced_by, [c["n"] for c in mine])
    known = {c["n"] for c in mine}
    for number in reproduced_by:
        if number not in known:
            raise ValueError(f"capture {number} is not a saved capture of {target} in this investigation; its captures are "
                             f"{sorted(known) or 'none yet'}")
    reproduced = len(reproduced_by)
    status = args.status
    if status == "reproduced" and reproduced < required:
        raise ValueError(f"--status reproduced needs {required} of {required} captures reproducing it; you named {reproduced} "
                         f"of {required}: record `--status unverified` ({reproduced} of {required})")
    if status == "not_reproduced" and (runs < 1 or reproduced or held["problem"]):
        raise ValueError("--status not_reproduced needs at least one capture of the target, none of them reproducing it"
                         + (f" and an undamaged captures.jsonl ({held['problem']} is damaged: a hidden line could be a "
                            "reproduction)" if held["problem"] else "")
                         + f"; you have {runs} capture(s) and named {reproduced}: record `--status unverified` ({reproduced} "
                           f"of {required})")
    if status == "environment_event" and runs < 1:
        raise ValueError("--status environment_event needs at least one capture of the target; there is none: record "
                         f"`--status unverified` (0 of {required})")
    refs = []
    for item in mine:      # the capture line is the carrier of the hash: a file edited since is refused by `append`, not re-hashed
        recorded = item.get("sha256")
        if not isinstance(recorded, str) or not recorded.strip():
            raise ValueError(f"capture {item['n']} of {target} has no sha256 in captures.jsonl: it cannot be cited. Probe "
                             "the target again, or end your hand-back with it unverified")
        refs.append({"path": item["path"], "sha256": recorded})
    if not refs:
        for relative in _carrier_paths(entry):
            if (task / relative).is_file():
                refs.append({"path": relative, "sha256": install_paths.sha256_file(task / relative)})
    if not refs:
        raise ValueError(f"{target} has no capture and no carrier file to cite: nothing is recorded. Probe it with "
                         "`investigation_probe.py http` first, or end your hand-back with it unverified")
    environment = None
    if mine:
        try:
            cfg, project = MC.load_config(task)
            environment = MC.environment_of(mine[-1]["url"], cfg, root=project).get("name")
        except (ValueError, KeyError, AttributeError):
            environment = None
    kind = args.kind
    line = {"kind": kind, "title": args.title if args.title is not None else args.statement[:TITLE_CHARS],
            "statement": args.statement, "why_not_a_bug": args.why_not_a_bug, "verification_status": status,
            "oracle_status": args.oracle_status or ORACLE_DEFAULT[kind],
            "refs": [r.strip() for r in (args.refs or "").split(",") if r.strip()],
            "evidence_refs": refs,
            "probe": {"method": "api", "runs": runs, "reproduced": reproduced, "environment": environment,
                      "safe_to_break": None},
            "origin": {"dispatch": args.dispatch, "target": target}}
    for key, value in (("question", args.question), ("owner_role", args.owner_role),
                       ("missing_prerequisite", args.missing_prerequisite)):
        if value is not None:
            line[key] = value
    register = _ask("the findings register", register_read, task)
    active = register.get("active") if isinstance(register, dict) else None
    if not isinstance(active, dict):
        raise ValueError("the findings register cannot be read (an unexpected answer): nothing was recorded. "
                         + NOT_INSTALLED_TAIL)
    current = active.get(target)
    if isinstance(current, dict):
        line.update(op="correct", corrects={"id": current.get("id"), "reason": status})
    else:
        chain = _ask("the findings register", chains_of, [x for x in register.get("lines") or [] if isinstance(x, dict)]
                     ).get(target)      # the register's one derivation of a target's chain
        if chain:
            raise ValueError(f"{target} was withdrawn by {chain[-1].get('id')}: a withdrawn target is not recorded again")
        line["op"] = "add"
    identifier = register_append(task, line, by=args.dispatch)
    print(json.dumps({"ok": True, "id": identifier, "op": line["op"], "target": target, "verification_status": status,
                      "runs": runs, "reproduced": reproduced, "of": required}))
    return 0


# --------------------------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = RefusingParser(prog=SCRIPT, command=SCRIPT, description="The bounded, read-only probe of the S7 investigation "
                                                                    "(see the module's docstring).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("http", "record"):
        one = sub.add_parser(name, command=f"{SCRIPT} {name}")
        one.add_argument("--task-root", required=True, help="the story's folder, qa-factory/artifacts/<TICKET>")
        one.add_argument("--dispatch", required=True, help="the id of YOUR running investigation dispatch")
        one.add_argument("--target", required=True, help="a target id from `investigation.py unresolved`")
        if name == "http":
            one.add_argument("--method", required=True, help="GET | HEAD | OPTIONS (the budget file lists them)")
            one.add_argument("--url", required=True, help="an address on a configured stand")
            one.add_argument("--header", action="append", help='"Name: value"; repeatable; never a credential, never Host')
            one.add_argument("--phase", default="supporting", help="pre_action | post_action | supporting (kept in the capture file)")
        else:
            one.add_argument("--kind", required=True, choices=KINDS)
            one.add_argument("--statement", required=True, help="what you saw, in your words")
            one.add_argument("--why-not-a-bug", required=True, help="why this is an observation and not a product bug")
            one.add_argument("--status", required=True, choices=STATUSES)
            one.add_argument("--reproduced-by", help="the capture numbers (n) that reproduced it, e.g. 1,2,3")
            one.add_argument("--question", help="for an unresolved_question")
            one.add_argument("--owner-role", help="for an unresolved_question: who can answer")
            one.add_argument("--missing-prerequisite", help="for a coverage_gap")
            one.add_argument("--refs", help="R-n / TC-n ids, comma separated")
            one.add_argument("--oracle-status", choices=ORACLE_STATUSES)
            one.add_argument("--title", help="default: the statement cut at 120 characters")
            one.add_argument("--runs", help=argparse.SUPPRESS)
            one.add_argument("--reproduced", help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = hooklib.exact_options(build_parser()).parse_args(argv)
    task = hooklib.story_of(SCRIPT, root=args.task_root, key_flag=None).resolve()      # the story first (CX1-18)
    return run_http(task, args) if args.command == "http" else run_record(task, args)


def _command() -> str:
    command = command_from_argv(SCRIPT)
    first = sys.argv[1] if len(sys.argv) > 1 else ""
    return f"{SCRIPT} {first}" if command == SCRIPT and first in ("http", "record") else command


if __name__ == "__main__":
    sys.exit(run_guarded(_command(), main))
