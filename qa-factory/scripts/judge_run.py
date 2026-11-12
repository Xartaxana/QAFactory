"""S5/S6: what broke this run, and what would unblock it - from the run's own evidence.

`execution_status` types a run from its exit code, which is all code can prove: a missing
pytest plugin, a test id spelled by a plugin, an account that is not on the stand and a real
defect of a test all arrive at the automator as `broken_run`. On TP1-15045 that cost
whole dispatches - two critic rounds on "a tooling blocker" whose explanation was one line
(`ERROR: not found: ...::test_x[buffer-R3-vs-selected-R1]`), and repair rounds spent on tests
whose stand had simply gone away (`NON_OWNER_EMAIL / NON_OWNER_PASSWORD must be set`).

Here the same lines are put to the judge as one small state - one run, one question -
and the answer is attached to the summary as `diagnosis`:

  {"culprit": environment | tooling | collection | test_defect | application |
               stand_degraded | unknown, "confidence": p, "sentence": one line}

In `judge.mode: on` a decided `run_env_blocked` on a run the exit code called `broken_run`
or `failed` rewrites `execution_status` to `env_blocked` and keeps the proven value in
`execution_status_raw`, so nothing is lost and the change is journalled as a judged pass the
gate brief prints. In `shadow` the diagnosis is a comparison record and nothing moves; with
`judge.provider: none` this module is never reached and the run is byte for byte what it was.

`--remedy` answers the second question the automator has to answer anyway: what kind of
thing is missing (contract.REMEDY_KINDS) and where it lives. The candidates are grepped by
code from the configuration files under the project's app roots, and from the NAMES of the
env files the config declares. A credential is named, never valued - no line printed here
carries a value that looks like a secret (contract.remedy_errors is the same rule).

  judge_run.py --task-root qa-factory/artifacts/<T> --summary <file|-> [--json]
  judge_run.py --task-root qa-factory/artifacts/<T> --remedy --error-head-file <f> [--case TC-7] [--json]
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import console_io  # noqa: E402  (the one ASCII fallback)
import hooklib  # noqa: E402
import judge  # noqa: E402
import test_files  # noqa: E402

CULPRITS = ("environment", "tooling", "collection", "test_defect", "application",
            "stand_degraded", "unknown")
# What each culprit means in one clause, for the sentence a person reads in the run report.
WHY = {
    "environment": "something the stand had to provide was missing or refused",
    "tooling": "the launcher, its plugins or the test selection broke before any test ran",
    "collection": "the test files themselves could not be loaded",
    "test_defect": "the test's own code, data or selectors are wrong",
    "application": "the product answered differently from what the test expects",
    "stand_degraded": "the stand answered too slowly or not at all while the tests waited",
    "unknown": "the log does not say who is at fault",
}
# The statuses a diagnosis is worth money for. A green run has nothing to diagnose, and
# `env_blocked` was already decided by the runner's own preflight.
DIAGNOSED = ("failed", "broken_run", "not_executed", "timeout", "inconclusive")
OVERRIDABLE = ("broken_run", "failed")
STATE_MAX_LINES = 25
STATE_LINE_CHARS = 300
CANDIDATE_MAX = 10
# Where a flag or a key can live. A repository is not searched beyond these: the grep runs
# inside a finished run's seconds, not a person's coffee break.
CONFIG_SUFFIXES = (".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next",
             "target", ".idea", ".mypy_cache", ".pytest_cache", "site-packages", ".tox",
             # Documentation and task journals mention a flag as often as the configuration
             # that holds it, and are never the place a stand is repaired.
             "docs", "doc"}
MAX_FILES_SCANNED = 2500
MAX_FILE_BYTES = 512_000
# A name worth grepping for: SCREAMING_SNAKE variables and the identifiers a log quotes.
_ENV_NAME = re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b")
_QUOTED_NAME = re.compile(r"[`'\"]([A-Za-z_][A-Za-z0-9_.-]{2,40})[`'\"]")
_FILE_NAME = re.compile(r"[\w./\\-]+\.(?:env|ya?ml|json|toml|ini|cfg|conf|properties)\b")
_SECRET_VALUE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9+/=_\-.]{16,}$")
_SECRET_NAME = re.compile(r"(pass|secret|token|key|credential|auth)", re.IGNORECASE)


def _plain(text) -> str:
    """ASCII, one line, no quotes of its own: this sentence is printed on whatever console
    the host has, and a UnicodeEncodeError here would be the judge breaking the runner."""
    return console_io.plain(text, one_line=True)


def _lines(summary: dict) -> list:
    """The lines that say what went wrong, whatever the run left behind: the error head the
    runner already captured, else the tail of the log, else the failures themselves."""
    out = []
    for key in ("error_head", "log_tail"):
        value = summary.get(key)
        if isinstance(value, list) and value:
            out = [str(line) for line in value]
            break
    if not out and str(summary.get("launch_error") or "").strip():
        out = [str(summary["launch_error"])]
    return [line.strip()[:STATE_LINE_CHARS] for line in out if str(line).strip()][:STATE_MAX_LINES]


def first_failure(summary: dict) -> str:
    """The first failure line of the run - the one a role would read first."""
    rows = summary.get("failed") if isinstance(summary.get("failed"), list) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get("why") or "").strip():
            return f"{row.get('test') or ''}: {' '.join(str(row['why']).split())}"[:600]
    rows = summary.get("results") if isinstance(summary.get("results"), list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("status") in ("failed", "error") and str(row.get("reason") or "").strip():
            return f"{row.get('test_id') or ''}: {' '.join(str(row['reason']).split())}"[:600]
    return ""


def state_of(summary: dict) -> dict:
    """One run, small enough that the questions are about it and not about its surroundings."""
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    state = {"exit_code": summary.get("exit_code"),
             "execution_status": str(summary.get("execution_status") or ""),
             "totals": {k: totals.get(k) for k in ("tests", "failures", "errors", "skipped")
                        if k in totals},
             "error_head": _lines(summary),
             "first_failure": first_failure(summary)}
    block = summary.get("timeout") if isinstance(summary.get("timeout"), dict) else {}
    if block.get("sentence"):  # RH2-9 (m-8): the judge reads the run's own word on a timeout, not only the dump
        state["timeout"] = _plain(block["sentence"])
    return state


def sentence(culprit: str, confidence, state: dict, overrode: str = "") -> str:
    """One ASCII line for the run report: what the judge read, and what it changed."""
    evidence = (state.get("error_head") or [state.get("first_failure") or ""])[0]
    text = (f"run diagnosis: {culprit} (p={confidence}) - {WHY.get(culprit, WHY['unknown'])}"
            + (f"; first line: '{_plain(evidence)[:200]}'" if evidence else ""))
    if overrode:
        text += (f". The judge reads this as an environment block, so execution_status "
                 f"{overrode} was recorded as env_blocked (the proven value stays in "
                 f"execution_status_raw); check the stand, not the test.")
    return _plain(text)


def diagnose(summary: dict, *, project_root=None, task=None, cfg=None) -> dict | None:
    """The diagnosis of one finished run, or None when the judge is off or unreachable.

    Two questions over the same small state, each its own request: the culprit, and - only
    for a run whose status the answer could change - whether this is an environment block.
    The second goes through `judged_refusal`, so a status the judge rewrote is journalled as
    a pass and the person sees it in the gate brief instead of finding it in a run report.
    """
    if not isinstance(summary, dict):
        return None
    cfg = cfg or judge.settings(project_root)
    if not judge.active(cfg):
        return None
    status = str(summary.get("execution_status") or "")
    state = state_of(summary)
    reply = judge.ask(state, {"culprit": {"judgment": "run_culprit"}}, ticket=task, stage="S5/S6",
                      project_root=project_root, cfg=cfg)
    if reply["status"] != "ok":
        return {"status": reply["status"], "reason": reply.get("reason")}
    answer = reply["answers"].get("culprit") or {}
    culprit = answer.get("value") if answer.get("value") in CULPRITS else "unknown"
    confidence = answer.get("confidence")
    out = {"culprit": culprit, "confidence": confidence, "sentence": "",
           "mode": cfg["mode"], "advisory": reply["advisory"],
           "leaning": answer.get("leaning"), "decided": bool(answer.get("decided"))}
    # RH2-9 (B-1): a run the PROJECT's own timeout killed (or failed a test of) is never asked "is this the environment?":
    # the question journals a judged pass, and a "yes" would put "check the stand" in the diagnosis the automator reads
    # (run 14857). The culprit stays advice; the status stays what the runner proved.
    import launch_check  # the one home of the words of a project-timeout outcome
    project_timeout = (summary.get("timeout") or {}).get("how") in launch_check.PROJECT_TIMEOUT_HOWS
    if status in OVERRIDABLE and not project_timeout:
        verdict = judge.judged_refusal(status, "run_env_blocked", state, ticket=task,
                                       stage="S5/S6", project_root=project_root, cfg=cfg)
        decision = verdict.get("decision") or {}
        out["env_blocked"] = {"value": decision.get("value"),
                              "probability": decision.get("probability"),
                              "passed": bool(verdict.get("passed"))}
        if verdict.get("passed"):
            out["overrode"] = status
    out["sentence"] = sentence(culprit, confidence, state, out.get("overrode", ""))
    return out


def attach(summary: dict, *, project_root=None, task=None, cfg=None) -> dict | None:
    """The seam run_suite.py calls once the summary is built. Mutates `summary` and returns
    the diagnosis, or None when there is nothing to ask or nobody to ask.

    Only `mode: on` may move a status, and only from what the exit code proved to
    `env_blocked`: the raw value is kept beside it, because a judged status that erased the
    measured one would be the factory lying about its own evidence.
    """
    if not isinstance(summary, dict) or str(summary.get("execution_status") or "") not in DIAGNOSED:
        return None
    found = diagnose(summary, project_root=project_root, task=task, cfg=cfg)
    if not found or "culprit" not in found:
        return None
    if found.get("overrode"):
        summary["execution_status_raw"] = found["overrode"]
        summary["execution_status"] = "env_blocked"
    summary["diagnosis"] = {k: found[k] for k in
                            ("culprit", "confidence", "sentence", "mode", "advisory", "overrode")
                            if k in found}
    return found


# --- the remedy: what kind of thing is missing, and where it lives --------------------------

def _names_a_test(name: str) -> bool:
    """Is a quoted identifier a test's own name (`test_login`, `tests.api.client`, `FooTests.Bar`)? Any segment
    (split on `.`, `/`, `::`) that names a test or is a test folder name says so. The usual names cannot be
    read: nothing is skipped (noise is cheaper than a missed name)."""
    return any(test_files.is_test_for("name", segment) is True
               for segment in re.split(r"\.|/|::", name) if segment)


def wanted_names(text: str) -> list:
    """The names worth grepping for, in the order a person would try them: the variables the
    log shouts, then the identifiers it quotes (a test's own name is not one). Nothing is invented - every
    name is in the text."""
    names, seen = [], set()
    for match in _ENV_NAME.findall(text or ""):
        if match not in seen and match not in ("ERROR", "WARNING", "TIMEOUT"):
            seen.add(match)
            names.append(match)
    for match in _QUOTED_NAME.findall(text or ""):
        if match not in seen and not _names_a_test(match):
            seen.add(match)
            names.append(match)
    return names[:6]


def _first_url(text: str) -> str:
    """The first address the failure names, without its query or userinfo: what a `service`
    remedy has to say is which door did not open."""
    match = re.search(r"https?://[^\s'\"<>,)]+", str(text or ""))
    if not match:
        return ""
    url = match.group(0).split("?", 1)[0]
    return url if "@" not in url else "the stand's address"


def _redact(line: str, name: str) -> str:
    """A configuration line as it may be printed: the key, and never the value behind it.
    A stand gap has been a credential once already; a diagnosis must not be how it leaks."""
    flat = " ".join(str(line or "").split())[:200]
    head, sep, tail = flat.partition("=") if "=" in flat and ":" not in flat.split("=")[0] else flat.partition(":")
    if not sep:
        return _plain(flat if not _SECRET_VALUE.match(flat) else name)
    value = tail.strip().strip("\"'")
    if _SECRET_NAME.search(head) or _SECRET_VALUE.match(value):
        return _plain(f"{head.strip()}{sep} <value hidden>")
    return _plain(f"{head.strip()}{sep} {value}"[:200])


def _hit(text: str, names: list) -> tuple | None:
    """(line number, name, what may be printed) - the ONE line of this file worth offering.

    A name that carries a value beats a name that is merely mentioned: on TP1-15045 the
    flag `subWorkflow` appears in `customer-config.yaml` first as part of `subWorkflowNode`
    and only three lines later as the entry that was off, and the first hit was the wrong
    one. The line under it comes along when it is nested, because `- id: "features:x"` says
    nothing without the `enabled:` beneath it."""
    lines = text.splitlines()
    best = None
    for number, line in enumerate(lines, 1):
        for name in names:
            if name not in line:
                continue
            after = line.split(name, 1)[1][:3].strip()
            # The name is the whole value (end of line) or carries one (`name: x`, `name=x`,
            # `"name":`); a name that merely starts a longer word (`subWorkflowNode`) is not.
            score = 2 if not after or after.startswith((":", "=", '"', "'")) else 1
            if best is None or score > best[0]:
                best = (score, number, name, line)
            break
        if best and best[0] == 2:
            break
    if not best:
        return None
    _, number, name, line = best
    shown = _redact(line, name)
    nested = next((row for row in lines[number:number + 3] if row.strip()), "")
    indent = len(line) - len(line.lstrip())
    if nested and len(nested) - len(nested.lstrip()) > indent:
        shown = f"{shown} | {_redact(nested, name)}"
    return number, name, shown[:200]


def _roots(project_root: Path, cfg: dict) -> list:
    """Where application configuration lives: the project itself and the app roots the
    project's config declares (app_root + protected_app_paths, code_repos)."""
    roots, seen = [], set()

    def add(path):
        try:
            resolved = Path(path).resolve()
        except (OSError, ValueError):
            return
        if resolved.is_dir() and str(resolved) not in seen:
            seen.add(str(resolved))
            roots.append(resolved)

    add(project_root)
    raw = str(cfg.get("app_root") or ".").strip()
    app_root = Path(raw) if Path(raw).is_absolute() else Path(project_root) / raw
    for part in cfg.get("protected_app_paths") or []:
        if isinstance(part, str) and part.strip():
            add(app_root / part.strip())
    for repo in cfg.get("code_repos") or []:
        if isinstance(repo, dict) and str(repo.get("path") or "").strip():
            path = Path(str(repo["path"]))
            add(path if path.is_absolute() else Path(project_root) / path)
    return roots[:6]


def _env_files(project_root: Path, cfg: dict) -> list:
    """The env files the project declares - by NAME. Their contents are never read here:
    the question is which file a key belongs in, and the answer must not cost a secret."""
    found = []
    env = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
    for value in [env.get("env_file")] + [stand.get("env_file") for stand in cfg.get("environments") or []
                                          if isinstance(stand, dict)]:
        name = str(value or "").strip().replace("\\", "/")
        if name and name not in found:
            found.append(name)
    return found


def candidates(project_root, names: list, cfg: dict | None = None) -> list:
    """[{id, where, name, line}] - the places under the app roots where these names already
    appear, plus the declared env files. Names and line numbers only."""
    project_root = Path(project_root)
    cfg = cfg if isinstance(cfg, dict) else {}
    found, scanned = [], 0
    for name in _env_files(project_root, cfg):
        found.append({"id": f"c{len(found) + 1}", "where": name, "name": "(declared env file)",
                      "line": "the project's env file, contents not read"})
    if not names:
        return found[:CANDIDATE_MAX]
    for root in _roots(project_root, cfg):
        # os.walk with the uninteresting directories pruned in place: rglob would descend
        # into node_modules and a virtualenv first and only then be told to ignore them.
        for folder, subfolders, files in os.walk(root):
            subfolders[:] = sorted(name for name in subfolders if name not in SKIP_DIRS
                                   and not name.startswith("."))
            if scanned >= MAX_FILES_SCANNED or len(found) >= CANDIDATE_MAX:
                break
            for name in sorted(files):
                path = Path(folder) / name
                if scanned >= MAX_FILES_SCANNED or len(found) >= CANDIDATE_MAX:
                    break
                if path.suffix.lower() not in CONFIG_SUFFIXES:
                    continue
                try:
                    if path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                scanned += 1
                hit = _hit(text, names)  # one hit per file: which file, not which line of it
                if not hit:
                    continue
                number, name, rendered = hit
                try:
                    shown = path.relative_to(project_root).as_posix()
                except ValueError:
                    shown = path.as_posix()
                found.append({"id": f"c{len(found) + 1}", "where": f"{shown}:{number}",
                              "name": name, "line": rendered})
    return found[:CANDIDATE_MAX]


def remedy(error_head: str, *, project_root=None, task=None, case=None, cfg=None) -> dict:
    """{kind, where, change, restart, candidates} - a suggestion for the automator's row,
    in the shape contract.remedy_errors accepts. Never a value, only names."""
    cfg = cfg or judge.settings(project_root)
    root = Path(cfg.get("project_root") or project_root or ".")
    try:
        config = json.loads((root / "qa-factory/config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        config = {}
    names = wanted_names(error_head)
    options = candidates(root, names, config if isinstance(config, dict) else {})
    out = {"kind": None, "where": None, "change": None, "restart": None,
           "candidates": options, "names": names, "status": "off"}
    if not judge.active(cfg):
        return out
    state = {"error_head": [line.strip()[:STATE_LINE_CHARS]
                            for line in str(error_head or "").splitlines() if line.strip()][:STATE_MAX_LINES],
             "case": str(case or ""), "names": names,
             "candidates": [{k: c[k] for k in ("id", "where", "name", "line")} for c in options]}
    questions = {"kind": {"judgment": "run_remedy_kind"}}
    if options:
        criteria = {c["id"]: f"{c['where']} - matched `{c['name']}`: {c['line']}" for c in options}
        criteria["none"] = "None of these places is the one to change, or the lines do not say which."
        questions["where"] = {"judgment": "run_remedy_where", "criteria": criteria}
    reply = judge.ask(state, questions, ticket=task, stage="S5/S6", project_root=project_root, cfg=cfg)
    out["status"] = reply["status"]
    if reply["status"] != "ok":
        out["reason"] = reply.get("reason")
        return out
    out["advisory"] = reply["advisory"]
    kind = (reply["answers"].get("kind") or {}).get("value")
    out["kind"] = kind
    out["kind_confidence"] = (reply["answers"].get("kind") or {}).get("confidence")
    chosen = (reply["answers"].get("where") or {}).get("value")
    picked = next((c for c in options if c["id"] == chosen), None)
    if picked:
        out["where"] = picked["where"]
        out["where_confidence"] = (reply["answers"].get("where") or {}).get("confidence")
    if kind:
        # A named kind is already worth the automator's row even when no candidate won: the
        # place is then theirs to fill, which is one question instead of two.
        out["change"] = _change(kind, picked or {}, names, _first_url(error_head))
        out["restart"] = _restart(kind)
    return out


def _change(kind, picked: dict, names: list, url: str = "") -> str:
    """What to set, as a name. `contract.remedy_errors` refuses a value that looks like a
    secret, and this sentence must never be the reason it has to."""
    found = str(picked.get("name") or "").strip()
    # The name as it is spelled in the file that was chosen beats the name as the log shouts
    # it - unless that "name" is a note of this module's own, which has spaces in it.
    name = found if found and found.replace("_", "").replace("-", "").replace(".", "").isalnum() \
        else (names[0] if names else "")
    if not name and not url:
        return ""
    if kind == "credential":
        return f"provide a value for {name} (the variable name only - never write the value into an artifact)"
    if kind == "flag":
        return f"turn on {name}" + (f" ({picked.get('line')})" if picked.get("line") else "")
    if kind == "data":
        return f"create the record or fixture {name} the test needs on this stand"
    if kind == "service":
        return f"start the service behind {url or name} and check it answers"
    return f"set {name}"


def _restart(kind) -> str:
    return {"flag": "the service that reads this configuration",
            "service": "the service itself"}.get(str(kind or ""), "")


def render_diagnosis(found: dict | None) -> str:
    if not found:
        return "judge_run: off - judge.provider is none, or this run has nothing to diagnose"
    if "culprit" not in found:
        return f"judge_run: {found.get('status')} - {found.get('reason') or 'the judge did not answer'}; read the log as usual"
    return found["sentence"]


def render_remedy(found: dict) -> str:
    if found.get("status") not in ("ok", "off"):
        return f"judge_run remedy: {found.get('status')} - {found.get('reason') or 'the judge did not answer'}"
    places = ", ".join(c["where"] for c in (found.get("candidates") or [])[:3]) or "none found"
    if not found.get("kind"):
        return _plain(f"judge_run remedy: undecided over {len(found.get('candidates') or [])} "
                      f"candidates ({places}) - write the remedy yourself")
    where = found.get("where") or f"undecided between {len(found.get('candidates') or [])} candidates ({places})"
    return _plain(f"judge_run remedy: {found['kind']} -> {where} - "
                  f"{found.get('change') or 'no change named'} "
                  f"(restart: {found.get('restart') or 'nothing'})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--summary", help="the run summary run_suite.py wrote, or - for stdin")
    parser.add_argument("--remedy", action="store_true")
    parser.add_argument("--error-head-file")
    parser.add_argument("--case")
    parser.add_argument("--json", action="store_true")
    args = hooklib.exact_options(parser).parse_args()
    task_root = hooklib.story_cli("judge_run.py", root=args.task_root, key_flag=None).resolve()   # first, even when the judge is off (E-4)
    cfg = judge.settings(task_root)
    if args.remedy:
        if not args.error_head_file:
            parser.error("--remedy needs --error-head-file")
        try:
            text = sys.stdin.read() if args.error_head_file == "-" else \
                Path(args.error_head_file).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"judge_run remedy: unreadable error head ({exc})")
            return 2
        found = remedy(text, project_root=task_root, task=task_root.name, case=args.case, cfg=cfg)
        print(json.dumps(found, indent=2, ensure_ascii=False) if args.json else render_remedy(found))
        return 0 if found.get("status") in ("ok", "off") else 3
    if not args.summary:
        parser.error("--summary or --remedy is required")
    try:
        raw = sys.stdin.read() if args.summary == "-" else \
            Path(args.summary).read_text(encoding="utf-8", errors="replace")
        summary = json.loads(raw)
    except (OSError, ValueError) as exc:
        print(f"judge_run: unreadable summary ({exc})")
        return 2
    found = diagnose(summary, project_root=task_root, task=task_root.name, cfg=cfg) \
        if isinstance(summary, dict) else None
    print(json.dumps(found or {"status": "off"}, indent=2, ensure_ascii=False) if args.json
          else render_diagnosis(found))
    return 0 if not found or "culprit" in found or found.get("status") == "off" else 3


if __name__ == "__main__":
    sys.exit(main())
