"""Is it the tests, or is it the stand? A rolling record of runs that can tell the two apart.

Why. TP1-15045, 2026-09-21: six UI cases out of six failed with the same line,
`AssertionError: Locator expected to be visible`, one after another over two hours; single
tests took 400-640 s where the same tests later passed in about 150 s. Every one of those
failures was handed to the automator as a defect of THAT test, and repair rounds — the most
expensive thing the factory does — were spent on a stand that had degraded. No role could
have seen it: each dispatch sees its own case, and the pattern only exists across cases.

`run_suite.py` calls `observe()` after every finished run. It keeps the last 30 runs of the
project in `qa-factory/state/stand-health.json` and answers with a signal when

- `same_failure`: at least `stand_health.same_failure_cases` (default 3) DIFFERENT cases
  failed in a row with the same normalized first failure line (digits, ids and quoted
  values stripped, so `Timeout 30000ms` and `Timeout 45000ms` are one line); or
- `slow_run`: the run lasted more than `stand_health.slow_factor` (default 3) times the
  median of at least three earlier runs of comparable size on the same test area.

The signal is a suspicion worded for a person, not a verdict and not a refusal: nothing is
blocked here. What the run record gains is `stand_signal`, and the orchestrator stops
spending repair rounds until the stand is looked at. `probe()` is that look: timed GETs of
the environment's URLs, found the way `env_probe.py` finds them.

Red-probe runs fail on purpose and runs where nothing executed say nothing about the stand;
both are recorded and neither counts. SECRETS ARE NEVER PRINTED: a URL is shown without
userinfo, query or fragment, and only keys `env_probe` would print in clear are read.

THE DEPENDENCY ORDER (RH1-7). A stand is a chain: the network, the API's own address, the frontend, and the frontend's
route to the API (`environment.frontend {url_key, api_path}`; a named `environments[]` entry may carry
`frontend {url, api_path}`). `probe` names the FIRST dead part of that chain in `diagnosis.part` and lists the rest in
`also`; a dead API is never reported as a frontend problem, and the frontend's route is judged only by an answer shown
to be the API's own (a page, a redirect or a foreign 4xx through it is `unknown`, never "proxy works"). What each answer
means, and the order itself, are rows of `references/stand-answers.json` read through `env_probe.stand_answers()`; the
code here only walks them. The probe never restarts anything: the recorded `bring_up` recipe is shown for the
conductor. The login line says "proved" only for a record with `outcome: ok`.

Usage:
    stand_health.py --probe [--env NAME] [--project-root DIR]   exit 0 healthy, 1 otherwise
    stand_health.py --status [--project-root DIR]
    stand_health.py --reset [--reason "the stand was restarted"] [--project-root DIR]
    stand_health.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import console_io  # noqa: E402  (the one ASCII fallback)
import config_contract  # noqa: E402  (LOGIN_OUTCOMES and API_PATH_RE: one copy each)
from launch_check import _LEGACY_NOT_EXECUTED  # noqa: E402  (the legacy codes, one copy; no run_suite import)

RUNS_KEPT = 30
DEFAULTS = {
    "same_failure_cases": 3,   # different cases in a row with one failure line
    "slow_factor": 3.0,        # a run this many times the median of its peers is slow
    "slow_min_s": 60.0,        # below this a run is never called slow: 9 s against 2.5 s is noise
    "probe_slow_ms": 3000.0,   # an answer slower than this makes the stand `degraded`
    "probe_on_signal": True,   # attach a probe to a signal; costs seconds only when one fires
}
MIN_PEERS = 3
EVIDENCE_ROWS = 6
LINE_CHARS = 120
# The runner's own 127 (the command did not launch): the stand was never exercised. Which of a
# runner's OWN exit codes mean "nothing was executed" is the runner row's fact, carried by the
# run summary as `exit_means_not_executed`; with no such fact the legacy codes apply.
LAUNCH_FAILURE_EXIT = 127

_QUOTED = re.compile(r"\"[^\"]*\"|`[^`]*`|(?<!\w)'[^']*'")
# `why` is cut at 160 characters by the summary writer, so a quoted value may never close.
_UNCLOSED = re.compile(r"\"[^\"]*$|`[^`]*$|(?<!\w)'[^']*$")
_IDS = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{12,}\b|0x[0-9a-f]+",
                  re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_BARE_EXCEPTION = re.compile(r"^[\w.]*(error|exception|failure)?:?$", re.IGNORECASE)


def normalize_line(text) -> str:
    """The failure line with everything run-specific removed. Empty when nothing is left to
    compare: three bare `AssertionError`s are not evidence of anything shared."""
    line = str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""
    line = _QUOTED.sub("", line)
    line = _UNCLOSED.sub("", line)
    line = _IDS.sub("", line)
    line = _DIGITS.sub("", line)
    line = re.sub(r"\s+", " ", line).strip().lower()[:LINE_CHARS].strip()
    return "" if _BARE_EXCEPTION.match(line) else line


def case_of(test_id) -> str:
    """The case a reporter identity belongs to: the test function, whatever its parameters.
    Six partitions of one parametrized test failing alike is one broken test, not six."""
    return str(test_id or "").split("[", 1)[0].strip()


def _area(test_ids: list) -> str:
    """The package directory of the first test — UI runs are compared with UI runs. A 300 s
    browser test is not slow because the API tests before it took 20 s."""
    for test_id in test_ids:
        module = str(test_id or "").split("::", 1)[0].replace("\\", "/").replace("/", ".")
        if module:
            return module.rsplit(".", 1)[0] if "." in module else module
    return ""


def _size_bucket(tests: int) -> int:
    """1 | 2-3 | 4-7 | 8-15 ... — comparable size without demanding the identical selection."""
    return max(0, int(tests)).bit_length()


def settings(project_root) -> dict:
    """`stand_health.*` from qa-factory/config.json; every key optional (0.7.x projects)."""
    values = dict(DEFAULTS)
    try:
        config = json.loads((Path(project_root) / "qa-factory" / "config.json")
                            .read_text(encoding="utf-8-sig"))
        section = config.get("stand_health") if isinstance(config, dict) else None
        for key, default in DEFAULTS.items():
            candidate = (section or {}).get(key)
            if isinstance(default, bool):
                if isinstance(candidate, bool):
                    values[key] = candidate
            elif isinstance(candidate, (int, float)) and not isinstance(candidate, bool) and candidate > 0:
                values[key] = type(default)(candidate)
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return values


def _paths(project_root) -> tuple[Path, Path]:
    path = Path(project_root) / "qa-factory" / "state" / "stand-health.json"
    return path, path.with_suffix(".lock")


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("runs"), list):
            value["runs"] = [row for row in value["runs"] if isinstance(row, dict)]
            return value
    except (OSError, ValueError):
        pass
    return {"schema_version": 1, "runs": []}


def _number(value, default=0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def _record(task: str, summary: dict) -> dict:
    """One run, reduced to what the two rules need. Works on the summary `run_suite.py` writes
    today (`failed[]`, `results[]`, `totals`, `duration_s`, `label`) and tolerates every
    field being absent or of the wrong type: a launch failure has almost none of them."""
    failed = [row for row in (summary.get("failed") or []) if isinstance(row, dict)] \
        if isinstance(summary.get("failed"), list) else []
    failures = [{"test": str(row.get("test") or ""), "why": str(row.get("why") or "")} for row in failed]
    results = [row for row in (summary.get("results") or []) if isinstance(row, dict)] \
        if isinstance(summary.get("results"), list) else []
    if not failures:
        failures = [{"test": str(row.get("test_id") or ""), "why": str(row.get("reason") or "")}
                    for row in results if row.get("status") in ("failed", "error")]
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    tests = int(_number(totals.get("tests")))
    label = str(summary.get("label") or "")
    purpose = str(summary.get("purpose") or label.split("-", 1)[0])
    probe_before = summary.get("runtime_probe_before")
    environment = str(summary.get("environment")
                      or (probe_before.get("environment_id") if isinstance(probe_before, dict) else "") or "")
    exit_code = summary.get("exit_code")
    not_executed = summary.get("exit_means_not_executed")
    if not isinstance(not_executed, bool):  # None or absent: no fact for this runner, the legacy rule
        not_executed = exit_code in _LEGACY_NOT_EXECUTED
    executed = tests > 0 and exit_code != LAUNCH_FAILURE_EXIT and not not_executed
    first = failures[0] if failures else None
    line = normalize_line(first["why"]) if first else ""
    cases = []
    for row in failures:
        case = case_of(row["test"])
        if case and normalize_line(row["why"]) == line and case not in cases:
            cases.append(case)
    ids = [row["test"] for row in failures] + [str(row.get("test_id") or "") for row in results]
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "task": str(task or summary.get("task") or ""), "label": label, "purpose": purpose,
        "environment": environment, "exit_code": exit_code if isinstance(exit_code, int) else None,
        "duration_s": round(_number(summary.get("duration_s")), 1), "tests": tests,
        "area": _area(ids), "failed": bool(failures),
        "line": line, "raw_line": (first["why"].strip().splitlines() or [""])[0][:LINE_CHARS] if first else "",
        "cases": cases,
        # A red probe fails because the factory broke the product on purpose.
        "counts": bool(executed and purpose != "red_probe"),
    }


def _same_stand(a: dict, b: dict) -> bool:
    return not a.get("environment") or not b.get("environment") or a["environment"] == b["environment"]


def _short(case: str) -> str:
    return case.rsplit("::", 1)[-1] or case


def _plain(text) -> str:
    """ASCII only, no quotes of its own: the sentence is printed by the runner on whatever
    console the host has, and a UnicodeEncodeError there would be this module raising into
    the runner by another door."""
    return console_io.plain(text)


def _same_failure(current: dict, earlier: list, limits: dict) -> dict | None:
    if not (current["counts"] and current["failed"] and current["line"]):
        return None
    cases, evidence = [], []
    for row in [current] + list(reversed(earlier)):
        if not row.get("counts") or not _same_stand(current, row):
            continue
        if not row.get("failed") or row.get("line") != current["line"]:
            break  # a green run, or a different failure: the row of identical failures ends here
        fresh = [case for case in row.get("cases") or [] if case not in cases]
        cases.extend(fresh)
        for case in fresh:
            evidence.append(f"{_short(case)}: {row.get('raw_line')} ({row.get('label')}, {row.get('duration_s')}s)")
    if len(cases) < int(limits["same_failure_cases"]):
        return None
    return {"reason": "same_failure", "evidence": evidence[:EVIDENCE_ROWS],
            "sentence": (f"{len(cases)} different tests in a row failed with the same line, "
                         f"`{_plain(current['raw_line'])}`, which points at the stand rather than at "
                         f"{len(cases)} separate test defects; check the stand before another repair round.")}


# Pairs of lines put to the judge at most: the row of failures in front of this run, never
# the whole history. One pair is one small state - the rule of references/judgments.json.
JUDGED_LOOKBACK = 6


def _similar_failure(current: dict, earlier: list, limits: dict, project_root) -> dict | None:
    """`_same_failure` for a stand that fails in more than one wording. Never raises.

    Exact equality of the normalised lines is what splits a degraded stand into separate test
    defects: on TP1-15045 the afternoon's failures were `Locator.fill: Timeout 30000ms`
    on setup and `Locator expected to be visible` in the body of the very same dead stand,
    and neither wording on its own reached three different cases. Each pair (this run's line,
    that run's line) is one `run_same_cause` request; a decided `true` joins the row, and an
    undecided or a `false` ends it exactly where exact matching ended it.

    Only `judge.mode: on` may raise a signal from this: in `shadow` the answers are
    journalled for comparison and None comes back, so nothing the factory does changes.
    """
    if not (current["counts"] and current["failed"] and current["line"]):
        return None
    chain = []
    for row in reversed(earlier):
        if not row.get("counts") or not _same_stand(current, row):
            continue
        if not row.get("failed") or not row.get("line"):
            break  # a green run, or a failure with nothing left to compare: the row ends here
        chain.append(row)
        if len(chain) >= JUDGED_LOOKBACK:
            break
    asked = [index for index, row in enumerate(chain) if row["line"] != current["line"]]
    if not asked:
        return None  # every line is identical: that is `_same_failure`'s question, not this one
    try:
        import judge
        cfg = judge.settings(project_root)
        if not judge.active(cfg, "run_same_cause"):
            return None
        replies = judge.ask_many(
            [({"line_1": current["line"], "line_2": chain[index]["line"]},
              {"same": {"judgment": "run_same_cause"}}) for index in asked],
            workers=4, ticket=current.get("task"), stage="S5/S6",
            project_root=project_root, cfg=cfg)
    except Exception:  # ImportError included: a judge is never the reason a run has no record
        return None
    answers = {index: ((reply.get("answers") or {}).get("same") or {})
               for index, reply in zip(asked, replies)}
    if any(reply.get("advisory", True) for reply in replies):
        return None  # shadow: journalled, compared, and acted on by nobody
    cases = list(current.get("cases") or [])
    evidence = [f"{_short(case)}: {current.get('raw_line')} ({current.get('label')}, "
                f"{current.get('duration_s')}s)" for case in cases]
    probabilities = []
    for index, row in enumerate(chain):
        note = ""
        if index in answers:
            answer = answers[index]
            if answer.get("value") is not True:
                break
            probabilities.append(answer.get("probability"))
            note = f" [judge: same cause p={answer.get('probability')}]"
        fresh = [case for case in row.get("cases") or [] if case not in cases]
        cases.extend(fresh)
        for case in fresh:
            evidence.append(f"{_short(case)}: {row.get('raw_line')} ({row.get('label')}, "
                            f"{row.get('duration_s')}s){note}")
    if not probabilities or len(cases) < int(limits["same_failure_cases"]):
        return None
    return {"reason": "same_failure", "matched": "judge", "evidence": evidence[:EVIDENCE_ROWS],
            "sentence": _plain(
                f"{len(cases)} different tests in a row failed with similar lines, starting with "
                f"'{_plain(current['raw_line'])}', which the judge reads as one cause "
                f"(run_same_cause p={min([p for p in probabilities if p is not None] or [0])} over "
                f"{len(probabilities)} pairs) rather than as {len(cases)} separate test defects; "
                "check the stand before another repair round.")}


def _slow_run(current: dict, earlier: list, limits: dict) -> dict | None:
    if not current["counts"] or current["duration_s"] < float(limits["slow_min_s"]):
        return None
    peers = [row for row in earlier
             if row.get("counts") and _same_stand(current, row)
             and row.get("area") == current["area"]
             and _size_bucket(row.get("tests") or 0) == _size_bucket(current["tests"])
             and _number(row.get("duration_s")) > 0]
    # A failing browser test waits out its timeouts and its reruns; compare like with like
    # when there is enough of it, so an honest red run is not called slow against green ones.
    alike = [row for row in peers if bool(row.get("failed")) == current["failed"]]
    peers = alike if len(alike) >= MIN_PEERS else peers
    if len(peers) < MIN_PEERS:
        return None
    median = statistics.median(_number(row.get("duration_s")) for row in peers)
    if median <= 0 or current["duration_s"] <= float(limits["slow_factor"]) * median:
        return None
    times = round(current["duration_s"] / median, 1)
    return {"reason": "slow_run",
            "evidence": [f"this run ({current['label']}): {current['duration_s']}s",
                         f"median of {len(peers)} earlier comparable runs: {round(median, 1)}s"]
            + [f"{row.get('label')}: {row.get('duration_s')}s" for row in peers[-(EVIDENCE_ROWS - 2):]],
            "sentence": (f"This run took {int(current['duration_s'])}s, {times} times the usual "
                         f"{int(median)}s for runs of this size on the same tests: the stand looks "
                         "slow; check it before trusting this result or repairing the test.")}


def _probe_sentence(result: dict) -> str:
    checks = result.get("checks") or []
    if not checks:
        return ""
    # What does not answer comes first: that is the part the person acts on.
    ordered = [c for c in checks if not c.get("alive")] + [c for c in checks if c.get("alive")]
    parts = [f"{c.get('name')} {'answered in ' + str(c.get('ms')) + ' ms' if c.get('alive') else 'did NOT answer'}"
             for c in ordered[:4]]
    return f" The stand's own check just now: {'; '.join(parts)}."


def _stamp_signal(path: Path, lock_path: Path, current: dict, reason: str) -> None:
    """The judged signal belongs to the run that raised it: the record was written before the
    judge answered, so the row is found again by its own timestamp and label and marked."""
    try:
        import event_store
        from event_store import atomic_json, hold_file_lock
        with hold_file_lock(lock_path, event_store.SHORT_RMW_LOCK_WAIT_S, purpose="stand health signal", record_holder=True):
            state = _read(path)
            for row in reversed(state["runs"]):
                if row.get("at") == current.get("at") and row.get("label") == current.get("label"):
                    row["signal"] = reason
                    break
            atomic_json(path, state)
    except Exception:
        pass  # the signal was returned; a record that missed it is not worth a failed run


def observe(project_root, task: str, summary: dict) -> dict | None:
    """Record one finished run; return a `stand_suspect` signal or None. Never raises: a
    defect here must not cost the person a run that has already finished."""
    try:
        if not isinstance(summary, dict):
            return None
        limits = settings(project_root)
        current = _record(task, summary)
        path, lock_path = _paths(project_root)
        import event_store
        from event_store import atomic_json, hold_file_lock
        with hold_file_lock(lock_path, event_store.SHORT_RMW_LOCK_WAIT_S, purpose="stand health record", record_holder=True):
            state = _read(path)
            earlier = list(state["runs"])
            found = _same_failure(current, earlier, limits) or _slow_run(current, earlier, limits)
            current["signal"] = found["reason"] if found else None
            state["runs"] = (earlier + [current])[-RUNS_KEPT:]
            state["updated_at"] = current["at"]
            atomic_json(path, state)
        if not found:
            # The judge is asked only where the exact rule stayed silent, and OUTSIDE the
            # lock: a request that waits on a network must never hold the record another
            # run is trying to write.
            found = _similar_failure(current, earlier, limits, project_root)
            if found:
                _stamp_signal(path, lock_path, current, found["reason"])
        if not found:
            return None
        signal = {"signal": "stand_suspect", **found}
        if limits["probe_on_signal"]:
            try:
                checked = probe(project_root, current["environment"])
                if checked.get("status") != "not_configured":
                    signal["probe"] = {"status": checked.get("status"), "checks": checked.get("checks")}
                    signal["sentence"] += _probe_sentence(checked)
            except Exception:
                pass
        return signal
    except Exception:
        return None


# --- the probe -----------------------------------------------------------------------------

def _display(url: str) -> str:
    """The URL as it may be printed: no userinfo, no query, no fragment."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return "(unprintable url)"


def _get(url: str, expect: list) -> dict:
    """The `env_probe.liveness` dict of one address, so the probe and the helper agree on what alive is. `probe` reads
    it through `_answer`, which also accepts a test's `(alive, note)` tuple."""
    import env_probe
    return env_probe.liveness(url, expect)


def _env_values(project_root, cfg: dict) -> dict:
    """The env file laid over the process environment - the values `_targets` and the remedy line read."""
    import os
    import env_probe
    values = dict(os.environ)
    rel = str(cfg.get("env_file") or "").strip()
    if rel:
        try:
            values.update(env_probe.parse_env_file(Path(project_root) / rel))
        except OSError:
            pass
    return values


_URL_SAFE = "/%:@!$&'()*+,;=-._~?"


def _api_check(root_url: str, api_path: str, texts: dict, notes: list):
    """`(shown path, url)` of the check of the frontend's API path, or None: absent path (E-F8), or a path that would
    leave the frontend's host (E-F9: said, never glued). The path is glued as given, only escaped for the wire."""
    from urllib.parse import quote
    from env_probe import fill
    if not api_path:
        return None
    if not config_contract.API_PATH_RE.match(api_path):  # one `/` first: a path is never glued to move the host
        notes.append(fill(texts.get("api_path_bad") or "frontend.api_path is not a path starting with one /"))
        return None
    try:
        parts = urlsplit(root_url)
        path = quote(api_path, safe=_URL_SAFE)
        return path, f"{parts.scheme}://{parts.netloc}{path}"
    except ValueError:
        notes.append(fill(texts.get("frontend_unreadable") or "frontend block unreadable"))
        return None


def _own_api(config: dict, environment: str):
    """`(url, codes)` of the named stand's OWN API address, resolved by the one resolver `env_probe.selected_probe_config`
    (FB-36, AR-13) - or None when the entry names no address of its own (then the block's address is the stand's)."""
    import env_probe
    cfg, base, error, source = env_probe.selected_probe_config(config, environment)
    if error or source != "own":
        return None
    url = env_probe.resolve_health(cfg, base) or base
    return (url, [c for c in cfg.get("health_expect") or [] if isinstance(c, int)]) if url else None


def _targets(project_root, config: dict, environment: str, notes=None) -> list:
    """(name, url, expected codes, role) — found the way env_probe finds them: the address under
    `environment.base_url_key` in the env file laid over the process environment, the
    liveness path glued to it, non-secret `extra_keys` that hold an http address (a UI stand
    keeps its frontend there), the integrations' own liveness URLs, and the named
    `environments[]` entry's addresses. `role` places a target in the stand's chain: `api` (the API's own address),
    `frontend` (its root), `frontend_api` (its API path, probed with NO declared codes: a declared code is the stand's
    norm for the API's own address), `extra`, `stand`, `integration`. What could not be probed is said into `notes`."""
    import env_probe
    notes = notes if notes is not None else []
    texts = env_probe.stand_answers().get("texts") or {}
    cfg = config.get("environment") if isinstance(config.get("environment"), dict) else {}
    values = _env_values(project_root, cfg)
    expect = [code for code in cfg.get("health_expect") or [] if isinstance(code, int)]
    found = []

    def add(name, url, codes=None, role="extra"):
        url = str(url or "").strip()
        if url.lower().startswith(("http://", "https://")) and url not in [row[1] for row in found]:
            found.append((name, url, list(codes if codes is not None else expect), role))

    def chain(label, ref, api_path, root_url, root_codes, frontend_name):
        """The frontend's root (unless already found) and its API path, behind the extras / the entry's own urls."""
        if root_url:
            add(frontend_name, root_url, root_codes, "frontend")
            checked = _api_check(root_url, api_path, texts, notes)
            if checked:
                add(f"{label} {checked[0]}", checked[1], [], "frontend_api")

    stand = None
    if environment:
        stand = next((s for s in config.get("environments") or []
                      if isinstance(s, dict) and str(s.get("name") or "") == environment), None)
    # The stand's frontend is read by the one reader (axis 29): the entry's own address, else - for the only entry, or
    # with no stand named - the block's. A stand among several is never qualified by another stand's frontend (E-F13).
    fe = env_probe.frontend_of(config, environment if stand is not None else "", values, entry=stand, root=project_root)
    notes.extend(n for n in fe["notes"] if n not in notes)
    from_block = fe["source"] == "environment.frontend.url_key"
    # a UI derived from the stand's own address (RN1-3) adds no target: the API target below IS that address
    from_entry = bool(fe["url"]) and not from_block and not fe["source"].endswith("(alias)") and not fe.get("same_origin")
    block = (fe["key"], fe["api_path"]) if from_block else None
    block_url = fe["url"] if from_block else ""
    entry_url, entry_path = (fe["url"], fe["api_path"]) if from_entry else ("", "")
    own = _own_api(config, environment) if from_entry else None
    if own:  # B1: a named stand with a frontend is judged against THAT stand's API, not the block's (FB-36)
        add(f"{environment}.api", own[0], own[1], "api")
    else:
        base = str(values.get(str(cfg.get("base_url_key") or ""), "") or "")
        health = env_probe.resolve_health(cfg, base)
        add("liveness", health, role="api")
        if not health:
            add("base_url", base, role="api")
    for key in cfg.get("extra_keys") or []:
        if isinstance(key, str) and not env_probe.SECRET_NAME.search(key):
            is_frontend = bool(block_url) and key == block[0]
            add(key, values.get(key, ""), role="frontend" if is_frontend else "extra")
    if block_url:
        chain(block[0], block[0], block[1], block_url, None, block[0])
    for integration in cfg.get("integrations") or []:
        if isinstance(integration, dict):
            add(f"integration {integration.get('name') or 'unnamed'}", integration.get("health_url"),
                [code for code in integration.get("health_expect") or [] if isinstance(code, int)],
                "integration")
    if stand is not None:
        for key, value in stand.items():
            if key.endswith("url") and isinstance(value, str) and not env_probe.SECRET_NAME.search(key):
                # The stand's address without a liveness path of its own: any HTTP
                # answer proves somebody is listening, which is all that is asked.
                same = bool(entry_url) and key == env_probe.FRONTEND_ALIAS_KEY and value.strip() == entry_url
                add(f"{environment}.{key}", value, expect + [401, 403, 404], "frontend" if same else "stand")
        if entry_url:
            chain(f"{environment}.frontend", entry_url, entry_path, entry_url, expect + [401, 403, 404],
                  f"{environment}.frontend")
    return found


# `diagnosis.part == "none"` iff the status is healthy or degraded (AC-9); a stand that could not be probed is `unknown`
_NOT_CONFIGURED = {"part": "unknown", "cause": None, "sentence": "", "remedy": "", "also": []}


def _answer(raw) -> dict:
    """One `_get` result as the probe reads it: the `env_probe.liveness` dict, or a test's `(alive, note)` tuple - which
    carries no `means`/`cause`, so the diagnosis places it by the target's role alone (E-F21)."""
    if isinstance(raw, dict):
        return {"alive": raw.get("verdict") in ("alive", "wants_login"), "note": str(raw.get("note") or ""),
                "means": raw.get("means"), "cause": raw.get("cause"), "code": raw.get("code"),
                "kind": raw.get("said_kind")}
    alive, note = raw
    return {"alive": bool(alive), "note": str(note), "means": None, "cause": None, "code": None, "kind": None}


def _cause_row(cause) -> dict:
    import env_probe
    return next((r for r in env_probe.stand_answers()["no_answer"] if r.get("cause") == cause), {})


def _table_row(check: dict) -> dict:
    """The table row that gave this check its `means` (an HTTP answer) or `cause` (an exception)."""
    import env_probe
    return _cause_row(check["cause"]) if check.get("cause") else env_probe.answer_meaning(check.get("code"), check.get("kind"))


def _through_class(check: dict) -> str:
    return str((_table_row(check).get("through_frontend") or {}).get("class") or "unknown")


def _tag(check: dict) -> str:
    """What the check's answer is called in the `order` rows: the `cause` or `means`, `fa:<class>` for the frontend's API
    path, `none` for a result that carries neither (a test's tuple)."""
    if not check.get("cause") and not check.get("means"):
        return "none"
    if check.get("role") == "frontend_api":
        return "fa:" + _through_class(check)
    return str(check.get("cause") or check.get("means"))


def _words(row: dict, check: dict) -> str:
    """The words of one dead check: the table row's own (the API's address: `direct`; the frontend's API path:
    `through_frontend`), else the order row's."""
    import env_probe
    words = ""
    if check.get("role") in ("api", "frontend_api") and (check.get("cause") or check.get("means")):
        block = _table_row(check).get("direct" if check["role"] == "api" else "through_frontend") or {}
        words = str(block.get("words") or "")
    shown = urlsplit(check.get("url") or "")
    return env_probe.fill(words or row.get("words"), url=check.get("url"), host=shown.netloc, code=check.get("code"),
                          path=shown.path, name=check.get("name"), note=check.get("note"))


def _diagnose(checks: list, answers=None) -> dict:
    """`{part, cause, sentence, remedy, also}` (+ the internal `chain`, popped by `probe`) - which part of the stand is
    dead. ONE loop over the `order` rows of `references/stand-answers.json`: each dead check goes to the first row that
    takes its role and tag; the first part found is the diagnosis, the rest are `also`. The order is data, never a
    branch here (AR-1). A dead API is never reported as a frontend problem (invariant D)."""
    import env_probe
    answers = answers or env_probe.stand_answers()
    texts = answers.get("texts") or {}
    dead = [c for c in checks if not c.get("alive")]
    if not dead:
        return {"part": "none", "cause": None, "sentence": "", "remedy": "", "also": []}
    if answers.get("table") != "ok":
        return {"part": "unknown", "cause": "table_unreadable", "remedy": "", "also": [], "chain": True,
                "sentence": str(texts.get("table_unreadable") or "The answer table could not be read.")}
    has_api = any(c.get("role") == "api" for c in checks)
    found, claimed = [], set()
    for row in answers["order"]:
        for index, check in enumerate(dead):
            roles = row.get("target_roles") or []
            when = row.get("dead_when") or []
            if index in claimed or not ("*" in roles or check.get("role") in roles) \
                    or not ("*" in when or _tag(check) in when):
                continue
            claimed.add(index)
            # `cause` is the word a person reads (the exception's cause or the answer's meaning), never the internal `fa:` tag
            part, cause, words = (env_probe.fill(row.get("part"), name=check["name"]),
                                  check.get("cause") or check.get("means") or "none", _words(row, check))
            if row.get("needs") == "api" and not has_api:
                part, cause, words = "unknown", "api_not_configured", str(texts.get("api_not_configured") or "")
            found.append((row, check, part, cause, words))
    for index, check in enumerate(dead):  # a table without a catch-all row: still a named part (AC-9)
        if index not in claimed:
            found.append(({}, check, "unknown", check.get("cause") or check.get("means") or "none",
                           f"{check['name']}: {check['note']}"))
    row, _, part, cause, words = found[0]
    chained = row.get("chain") is not False
    if not chained:
        sentence = "The stand does not answer: " + "; ".join(c["note"] for c in dead) + "."
    else:
        sentence = words
        if row.get("says_frontend_not_cause"):
            if any(r.get("frontend") for r, *_ in found[1:]):
                sentence += " " + str(texts.get("frontend_not_cause") or "")
            if any(c.get("role") == "frontend_api" and c.get("alive") and c.get("means") for c in checks):
                sentence += " " + str(texts.get("contradiction") or "")
    also = []
    for _, _, other, _, _ in found[1:]:
        if other != part and other not in also:
            also.append(other)
    return {"part": part, "cause": cause, "sentence": sentence.strip(), "remedy": "", "also": also, "chain": chained}


def _remedy(config: dict, environment: str, values: dict) -> str:
    """The restart line (R-1..R-4), printed only when the stand is down: the recorded recipe of the named
    `environments[]` entry (or of the only one), shown for the conductor and NEVER run here; every URL in it goes through
    `_display`, every value of a secret key is `<redacted>` (values shorter than 4 characters are not replaced)."""
    import env_probe
    table = env_probe.stand_answers().get("remedy") or {}
    entries = [e for e in config.get("environments") or [] if isinstance(e, dict)]
    chosen = next((e for e in entries if str(e.get("name") or "") == environment), None) if environment \
        else (entries[0] if len(entries) == 1 else None)
    recipe = chosen.get("bring_up") if isinstance(chosen, dict) else None
    if not isinstance(recipe, str) or not recipe.strip():
        return str(table.get("no_recipe") or "No restart recipe is recorded for this stand (environments[].bring_up).")
    text = re.sub(r"https?://[^\s'\"<>)]+", lambda m: _display(m.group(0)), recipe.strip())
    cfg = config.get("environment") if isinstance(config.get("environment"), dict) else {}
    secret_names = {str(k) for k in cfg.get("secret_keys") or []}
    secrets = {str(v) for k, v in (values or {}).items()
               if (str(k) in secret_names or env_probe.SECRET_NAME.search(str(k))) and isinstance(v, str) and len(v) >= 4}
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, "<redacted>")
    return env_probe.fill(table.get("with_recipe") or "{recipe}", name=str(chosen.get("name") or ""), recipe=text)


def _login_receipt(config: dict) -> dict:
    """What the project last PROVED about getting in, from `environment.access.login_probe`
    (a key NAME, a status code and a date — never a value), or why there is nothing to show.

    A stand that answers 302 to every path is not broken, and this probe must not let anyone
    read it as broken: the liveness question and the login question have separate answers, and
    this one was answered once, at onboarding, by a real login."""
    access = (config.get("environment") or {}).get("access") if isinstance(config.get("environment"), dict) else {}
    access = access if isinstance(access, dict) else {}
    receipt = access.get("login_probe") if isinstance(access.get("login_probe"), dict) else {}
    user_key = str(receipt.get("user_key") or "").strip()
    if not user_key:
        return {"recorded": False, "outcome": "none",
                "sentence": "No login has been proved on this stand (environment.access has no "
                            "login_probe): liveness is all this check can say."}
    import env_probe
    answers = env_probe.stand_answers()
    at = str(receipt.get("checked_at") or "").strip()
    date = f" on {at[:10]}" if at else ""
    # a status that is not an int (a string, a bool, a float) reads as no code recorded (E-L7); an outcome that is not
    # one of the four words reads as absent (E-L8); a table that cannot be read proves nothing (never "proved")
    code = receipt.get("status") if isinstance(receipt.get("status"), int) and not isinstance(receipt.get("status"), bool) else None
    word = receipt.get("outcome") if receipt.get("outcome") in config_contract.LOGIN_OUTCOMES else None
    if answers.get("table") != "ok":
        word = None
    recheck = "re-check the login" + (f": {answers['login_recheck']}" if answers.get("login_recheck") else "")
    again = " " + recheck[0].upper() + recheck[1:] + "."
    out = {"recorded": True, "user_key": user_key, "status": receipt.get("status"), "checked_at": at}

    def remedy(for_code, for_outcome):
        return _login_remedy(answers, for_code, for_outcome, user_key)
    if word == "ok" and code is not None and env_probe.answer_meaning(code, None).get("means") != "answered":
        # the outcome says success and the code says otherwise: a contradiction never resolves toward success (E-L6)
        out.update(outcome="unknown", sentence=f"The login record as {user_key} contradicts itself (outcome ok, HTTP {code}); "
                                               f"{recheck}.")
    elif word == "ok":
        user_field, secret_field = receipt.get("user_field"), receipt.get("secret_field")
        named = isinstance(user_field, str) and user_field.strip()  # FB-3: the body field the proof used, when it stored one
        what = (f"HTTP {code}" + (f", body field `{user_field.strip()}`" if named else "")) if code is not None \
            else "the project's login command"
        out.update(outcome="proved", sentence=f"Login was last proved as {user_key} ({what}){date}.")
        if named:
            out["user_field"] = user_field.strip()
            if isinstance(secret_field, str) and secret_field.strip():
                out["secret_field"] = secret_field.strip()
    elif word == "failed":
        said = f"HTTP {code}" if code is not None else "no code recorded"
        out.update(outcome="failed", sentence=f"The last login as {user_key} did not succeed ({said}){date}."
                                              + (" " + remedy(code, word) if remedy(code, word) else "") + again)
    elif word in ("skipped", "not_recorded"):
        why = (answers.get("texts", {}).get("login_not_tried") or {}).get(word) or word
        out.update(outcome="not_tried", sentence=f"The last login as {user_key} was not tried ({why}){date}."
                                                 + (" " + remedy(None, word) if remedy(None, word) else "") + again)
    else:
        # BEFORE the factory recorded outcomes (every config written earlier): the record does not say it succeeded, so it
        # is not a proof, whatever its code (owner's word 27.10.2026)
        said = f"recorded HTTP {code}" if code is not None else "no code recorded"
        hint = remedy(code, None)
        head = f"The login as {user_key}{date} is not confirmed ({said}, before the factory recorded outcomes)"
        out.update(outcome="unknown", sentence=(f"{head}. The recorded code suggests: {hint}" + again) if hint
                   else f"{head}; {recheck}.")
    return out


def _login_remedy(answers: dict, code, outcome, user_key: str) -> str:
    """The remedy by the recorded code (Table L, `login_remedies`): the first row that takes the code or the outcome."""
    from env_probe import _row_takes, fill
    for row in answers.get("login_remedies") or []:
        if _row_takes(row, code, None, outcome):
            return fill(row.get("remedy"), user_key=user_key).strip()
    return ""


def probe(project_root, environment: str = "") -> dict:
    """Timed GETs of the environment's URLs, plus what is recorded about logging in. Never raises.

    `{"environment", "status": healthy|degraded|down|not_configured, "checks": [{name, url,
    alive, ms, note}], "login": {...}, "sentence"}` — `degraded` is an answer slower than
    `stand_health.probe_slow_ms`, `down` is any URL that did not answer acceptably. A stand
    that only wants a login is alive (`env_probe.health`, no redirect followed).
    """
    environment = str(environment or "").strip()
    try:
        limits = settings(project_root)
        try:
            config = json.loads((Path(project_root) / "qa-factory" / "config.json")
                                .read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            config = {}
        config = config if isinstance(config, dict) else {}
        notes: list = []
        targets = _targets(project_root, config, environment, notes)
        login = _login_receipt(config)
        if not targets:
            return {"environment": environment, "status": "not_configured", "checks": [],
                    "login": login, "diagnosis": dict(_NOT_CONFIGURED),
                    "sentence": "No stand address is configured (the environment block of "
                                "qa-factory/config.json), so the stand could not be checked."}
        checks = []
        for name, url, expect, role in targets:
            began = time.monotonic()
            try:
                answer = _answer(_get(url, expect))
            except Exception as exc:
                import env_probe
                answer = {"alive": False, "note": f"NO ANSWER ({type(exc).__name__})", "means": None,
                          "cause": env_probe.no_answer_cause(exc).get("cause"), "code": None, "kind": None}
            shown = _display(url)
            check = {"name": name, "url": shown, "alive": answer["alive"],
                     "ms": int((time.monotonic() - began) * 1000),
                     "note": answer["note"].replace(url, shown), "role": role, "means": answer["means"],
                     "cause": answer["cause"], "code": answer["code"], "kind": answer["kind"]}
            if role == "frontend_api" and check["alive"] and check["means"] is not None \
                    and _through_class(check) != "api":
                # invariant C: a page, a redirect or an answer not shown to be the API's own, through the frontend's API
                # path, never proves the API - the check is not alive, and the diagnosis says `unknown`
                check["alive"] = False
            checks.append(check)
        dead = [c for c in checks if not c["alive"]]
        slow = [c for c in checks if c["alive"] and c["ms"] > float(limits["probe_slow_ms"])]
        status = "down" if dead else "degraded" if slow else "healthy"
        import env_probe
        answers = env_probe.stand_answers()
        diagnosis = _diagnose(checks, answers)
        chained = diagnosis.pop("chain", False)
        if dead:
            cfg = config.get("environment") if isinstance(config.get("environment"), dict) else {}
            diagnosis["remedy"] = _remedy(config, environment, _env_values(project_root, cfg))
            sentence = diagnosis["sentence"]
            if chained:
                sentence = (f"{sentence} {(answers.get('texts') or {}).get('per_address') or 'Per address:'} "
                            + "; ".join(c["note"] for c in dead) + ". " + diagnosis["remedy"])
        elif slow:
            sentence = "The stand answers, but slowly: " + "; ".join(
                f"{c['name']} took {c['ms']} ms" for c in slow) + "."
        else:
            sentence = "The stand answers: " + "; ".join(f"{c['name']} in {c['ms']} ms" for c in checks) + "."
        out = {"environment": environment, "status": status, "checks": checks, "login": login, "diagnosis": diagnosis}
        if notes:
            out["notes"] = notes
            sentence += " Not probed: " + "; ".join(notes) + "."
        out["sentence"] = sentence + " " + login["sentence"]
        return out
    except Exception as exc:
        return {"environment": environment, "status": "not_configured", "checks": [],
                "login": {"recorded": False, "sentence": ""}, "diagnosis": dict(_NOT_CONFIGURED),
                "sentence": f"The stand could not be checked ({type(exc).__name__})."}


def status(project_root) -> dict:
    state = _read(_paths(project_root)[0])
    runs = state["runs"]
    return {"runs": len(runs), "last_signal": next(
                ({"reason": row.get("signal"), "at": row.get("at"), "label": row.get("label")}
                 for row in reversed(runs) if row.get("signal")), None),
            "recent": [{key: row.get(key) for key in ("at", "task", "label", "duration_s", "tests",
                                                     "failed", "line", "cases", "counts", "signal")}
                       for row in runs[-10:]],
            "reset": state.get("reset")}


def reset(project_root, reason: str = "") -> dict:
    """Forget the record — the person restarted or repaired the stand, and yesterday's
    failures must not be counted against today's runs."""
    import event_store
    from event_store import atomic_json, hold_file_lock
    path, lock_path = _paths(project_root)
    with hold_file_lock(lock_path, event_store.SHORT_RMW_LOCK_WAIT_S, purpose="stand health reset", record_holder=True):
        dropped = len(_read(path)["runs"])
        atomic_json(path, {"schema_version": 1, "runs": [], "reset": {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "reason": reason,
            "dropped_runs": dropped}})
    return {"status": "reset", "dropped_runs": dropped}


def selftest() -> int:
    import shutil
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="qa-stand-health-"))
    failures = 0

    def case(name, ok):
        nonlocal failures
        failures += 0 if ok else 1
        print(("PASS " if ok else "FAIL ") + name)

    def summary(label, test, why, duration=300.0):
        failed = [{"test": test, "kind": "failure", "why": why}] if why else []
        return {"task": "T-1", "label": label, "exit_code": 1 if why else 0, "duration_s": duration,
                "totals": {"tests": 1}, "failed": failed,
                "results": [{"test_id": test, "status": "failed" if why else "passed", "reason": why}]}

    try:
        (root / "qa-factory").mkdir(parents=True)
        (root / "qa-factory" / "config.json").write_text(
            json.dumps({"stand_health": {"probe_on_signal": False}}), encoding="utf-8")
        case("digits, ids and quoted values are stripped",
             normalize_line("TimeoutError: Locator.fill: Timeout 30000ms exceeded for \"#a1\"")
             == normalize_line("TimeoutError: Locator.fill: Timeout 45000ms exceeded for \"#b2\""))
        why = "AssertionError: Locator expected to be visible"
        first = observe(root, "T-1", summary("initial-1", "tests.ui.a::test_one[chromium]", why))
        again = observe(root, "T-1", summary("initial-2", "tests.ui.a::test_one[chromium]", why))
        second = observe(root, "T-1", summary("initial-3", "tests.ui.a::test_two[chromium]", why))
        third = observe(root, "T-1", summary("initial-4", "tests.ui.b::test_three[chromium]", why))
        case("one case failing twice is not the stand", first is None and again is None and second is None)
        case("three different cases with one line is", bool(third) and third["reason"] == "same_failure")
        case("nothing raises on garbage", observe(root, "T-1", {"failed": 7, "totals": "x"}) is None
             and observe(root, "T-1", None) is None)
        case("reset forgets", reset(root, "selftest")["dropped_runs"] >= 4 and status(root)["runs"] == 0)
        for index in range(3):
            observe(root, "T-1", summary(f"initial-g{index}", "tests.ui.a::test_one[chromium]", "", 150.0))
        slow = observe(root, "T-1", summary("initial-slow", "tests.ui.a::test_one[chromium]", "", 518.0))
        case("a run over three medians is slow", bool(slow) and slow["reason"] == "slow_run")
        case("an unconfigured stand is not probed", probe(root)["status"] == "not_configured")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n=== stand_health selftest: {'ok' if not failures else str(failures) + ' failed'} ===")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Stand health: the rolling record and the probe")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--env", default="")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--reason", default="")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        raise SystemExit(selftest())
    if args.project_root:
        root = args.project_root.resolve()
    else:
        from hooklib import project_root
        root = project_root()
    if args.probe:
        result = probe(root, args.env)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        raise SystemExit(0 if result["status"] == "healthy" else 1)
    if args.status:
        print(json.dumps(status(root), ensure_ascii=False, indent=1))
        return
    if args.reset:
        print(json.dumps(reset(root, args.reason.strip()), ensure_ascii=False))
        return
    parser.error("--probe, --status, --reset or --selftest is required")


if __name__ == "__main__":
    main()
