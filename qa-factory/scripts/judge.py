"""Ask a System One model the factory's registered judgments; never decide control flow.

A judgment is one atomic, typed question (noul / choice / score) kept in
`references/judgments.json`. Code assembles the state, this module sends the questions,
applies the registered thresholds and appends every answer to `state/judgments.jsonl`.
The caller composes answers into a decision; an answer below its threshold is `decided:
false` and the caller hands that item to the LLM role exactly as it would without a judge.

`judge.provider` in the project's config.json:
  none      (default) nothing is sent anywhere; every helper reports `provider: none` and
            the factory behaves as it did before this module existed.
  typesafe  questions go to the TypeSafe System One endpoint.
`judge.mode`:
  shadow    answers are journalled, callers are told `advisory: true` and must not act on them.
  on        decided answers may replace the LLM judgment they are registered for.

An answer never lifts a block, never passes a gate and never authorises a write: the state
is ticket text, which is untrusted, and the model is not hardened against injected
instructions. The API key is read from the environment variable named by
`judge.api_key_env` (default TYPESAFE_API_KEY) and is never printed or persisted.

  judge.py status  [--project-root P]
  judge.py ask --judgments id[,id] --state state.json [--vars vars.json] [--ticket T] [--stage S]
  judge.py --selftest
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from hooklib import sorted_paths

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_KEY_ENV = "TYPESAFE_API_KEY"
# jev-1.13: 32k tokens for state + longest question, 64k per request. Estimates are in
# characters (about 3.2 per token for English JSON), kept well inside the documented limit.
STATE_CHAR_LIMIT = 84_000
REQUEST_CHAR_LIMIT = 170_000
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}
INPUT_USD_PER_MILLION = 0.042

_JOURNAL_LOCK = threading.Lock()

REGISTRY = Path(__file__).resolve().parent.parent / "references" / "judgments.json"
# One file per subject beside the root registry: `judgments.d/<subject>.json`, same shape.
# Packages that add questions own their file and never edit each other's; the root file
# stays the S1-S4 set the first experiment calibrated.
REGISTRY_DIR = REGISTRY.parent / "judgments.d"


def load_registry() -> dict:
    files = [REGISTRY] + sorted_paths(REGISTRY_DIR.glob("*.json")) if REGISTRY_DIR.is_dir() else [REGISTRY]
    registry = {}
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("judgments", []):
            if item["id"] in registry:
                raise ValueError(f"judgment {item['id']} is registered twice ({path.name})")
            item.setdefault("registry_file", path.name)
            registry[item["id"]] = item
    return registry


def registry_errors(registry: dict | None = None) -> list:
    errors = []
    try:
        registry = registry or load_registry()
    except Exception as exc:  # a registry nobody can read is the first finding
        return [f"judgments.json unreadable: {exc}"]
    for jid, item in registry.items():
        kind = item.get("type")
        if kind not in ("noul", "choice", "score"):
            errors.append(f"{jid}: type {kind!r}")
        if not item.get("instructions"):
            errors.append(f"{jid}: no instructions")
        if not item.get("stage") or not item.get("replaces"):
            errors.append(f"{jid}: stage and replaces are required")
        criteria = item.get("criteria")
        if kind == "choice" and not (isinstance(criteria, dict) and 2 <= len(criteria) <= 255):
            errors.append(f"{jid}: choice needs 2..255 described options")
        if kind == "score" and not (isinstance(criteria, list) and 2 <= len(criteria) <= 10):
            errors.append(f"{jid}: score needs 2..10 ordered levels")
        if kind == "noul":
            th = item.get("thresholds") or {}
            if not (0.5 < th.get("true_at", 0) <= 1 and 0 <= th.get("false_at", 1) < 0.5):
                errors.append(f"{jid}: noul thresholds need true_at in (0.5,1] and false_at in [0,0.5)")
        elif not 0.5 <= (item.get("thresholds") or {}).get("confidence", 0) <= 1:
            errors.append(f"{jid}: thresholds.confidence in [0.5,1] required")
    return errors


def _project_root(start=None):
    """The project at or above `start` (default: the working directory), or None - `runtime_paths.nearest_project`,
    the one walk. None is the judge off, never the start folder."""
    from runtime_paths import nearest_project
    return nearest_project(start or os.getcwd())


def settings(project_root=None) -> dict:
    """The judge's settings from the project's config, and `problems`: every coercion made on the
    way, said aloud (FR-41). A setting the code cannot honour never turns the judge ON: an unknown
    provider, an unreadable config or a non-object `judge` block leave provider `none` (and
    `off_reason` names why); an unknown mode stays `shadow` (advisory). No project, no config
    file to read, or no `judge` block is the default, not a problem."""
    root = _project_root(project_root)
    block, problems, off_reason = {}, [], ""
    if root:
        try:
            cfg = json.loads((root / "qa-factory/config.json").read_text(encoding="utf-8-sig"))
            if not isinstance(cfg, dict):
                raise TypeError(f"the top level is {type(cfg).__name__}, not an object")
            if "judge" in cfg and not isinstance(cfg["judge"], dict):
                off_reason = (f"the judge block in qa-factory/config.json is {type(cfg['judge']).__name__}, "
                              "not an object; the judge is off")
            else:
                block = cfg.get("judge") or {}
        except Exception as exc:
            off_reason = (f"qa-factory/config.json could not be read ({type(exc).__name__}: {str(exc)[:120]}); "
                          "the judge is off")
    provider = block.get("provider") or "none"
    if provider not in ("none", "typesafe"):
        off_reason = f"judge.provider {provider!r} is not one of none, typesafe; the judge is off"
        provider = "none"
    mode = "shadow"
    if "mode" in block:
        if block["mode"] in ("shadow", "on"):
            mode = block["mode"]
        else:
            problems.append(f"judge.mode {block['mode']!r} is not one of shadow, on; shadow (advisory) is used")
    return {"provider": provider, "mode": mode, "model": block.get("model") or DEFAULT_MODEL,
            "api_key_env": block.get("api_key_env") or DEFAULT_KEY_ENV,
            "thresholds": block.get("thresholds") if isinstance(block.get("thresholds"), dict) else {},
            "disabled": list(block.get("disabled") or []),
            "problems": ([off_reason] if off_reason else []) + problems, "off_reason": off_reason,
            "project_root": str(root) if root else None}


def _api_key(env_name: str):
    value = os.environ.get(env_name)
    if value:
        return value
    if os.name == "nt":
        # A variable stored for the user after the host application started is not in this
        # process's environment until the host restarts; the user's registry hive has it.
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return winreg.QueryValueEx(key, env_name)[0] or None
        except OSError:
            return None
    return None


def active(cfg: dict | None = None, judgment_id: str | None = None) -> bool:
    cfg = cfg or settings()
    if cfg["provider"] == "none":
        return False
    if judgment_id and judgment_id in cfg["disabled"]:
        return False
    return not judgment_id or load_registry().get(judgment_id, {}).get("enabled", True)


def _fill(value, variables: dict):
    if isinstance(value, str):
        for k, v in variables.items():
            value = value.replace("{" + k + "}", str(v))
        return value
    if isinstance(value, dict):
        return {k: _fill(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, variables) for v in value]
    return value


def build_question(item: dict, variables: dict | None = None, criteria=None) -> dict:
    question = {"type": item["type"], "instructions": _fill(item["instructions"], variables or {})}
    crit = criteria if criteria is not None else item.get("criteria")
    if crit:
        question["criteria"] = _fill(crit, variables or {})
    return question


def _post(payload: dict, key: str, timeout: float, attempts: int = 4) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    delay = 1.0
    last = "no attempt made"
    for attempt in range(attempts):
        request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
            "User-Agent": "qa-factory-judge/1"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code not in RETRY_STATUSES:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"connection: {exc}"
        if attempt < attempts - 1:
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(last)


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def decide(item: dict, answer: dict, overrides: dict | None = None) -> dict:
    """Apply the registered threshold. `value` is None when the model is not sure enough."""
    th = dict(item.get("thresholds") or {})
    th.update((overrides or {}).get(item["id"]) or {})
    kind = item["type"]
    if kind == "noul":
        p = float(answer.get("noul", 0.5))
        value = True if p >= th["true_at"] else False if p <= th["false_at"] else None
        return {"value": value, "decided": value is not None, "probability": round(p, 4),
                "confidence": round(abs(p - 0.5) * 2, 4)}
    conf = float(answer.get("confidence", 0))
    raw = answer.get("choice") if kind == "choice" else answer.get("score")
    if kind == "score":
        probs = answer.get("probabilities") or {}
        raw = int(max(probs, key=probs.get)) if probs else round(float(raw or 0))
    ok = conf >= th["confidence"]
    out = {"value": raw if ok else None, "leaning": raw, "decided": ok, "confidence": round(conf, 4)}
    if kind == "choice":
        out["probabilities"] = {k: round(float(v), 4) for k, v in (answer.get("probabilities") or {}).items()}
    if kind == "score":
        out["mean"] = round(float(answer.get("score", 0)), 3)
    return out


def journal_path(project_root) -> Path | None:
    return Path(project_root) / "qa-factory" / "state" / "judgments.jsonl" if project_root else None


def journal(project_root, rows: list) -> None:
    """Append rows to state/judgments.jsonl - the one writer every judge script shares."""
    _journal(project_root, rows)


def _journal(project_root, rows: list) -> None:
    path = journal_path(project_root)
    if not path or not rows:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _JOURNAL_LOCK, path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass  # a journal that cannot be written never fails the stage


def ask(state, questions: dict, *, ticket=None, stage=None, project_root=None,
        cfg: dict | None = None, timeout: float = 60.0) -> dict:
    """questions: {key: {"judgment": id, "vars": {...}, "criteria": optional override}}.

    Returns {"status": "ok"|"off"|"unavailable", "advisory": bool, "answers": {key: decision}}.
    Never raises: a judge that cannot answer is a reason to use the LLM path, not a halt.
    """
    cfg = cfg or settings(project_root)
    base = {"provider": cfg["provider"], "mode": cfg["mode"], "advisory": cfg["mode"] != "on",
            "answers": {}, "problems": list(cfg.get("problems") or [])}
    if cfg["provider"] == "none":
        return {**base, "status": "off", "reason": cfg.get("off_reason") or "judge.provider is none"}
    registry = load_registry()
    wanted = {k: q for k, q in questions.items()
              if q["judgment"] in registry and q["judgment"] not in cfg["disabled"]
              and registry[q["judgment"]].get("enabled", True)}
    if not wanted:
        return {**base, "status": "off", "reason": "no enabled judgment requested"}
    key = _api_key(cfg["api_key_env"])
    if not key:
        return {**base, "status": "unavailable",
                "reason": f"environment variable {cfg['api_key_env']} is not set"}
    if _size(state) > STATE_CHAR_LIMIT:
        return {**base, "status": "unavailable",
                "reason": f"state is {_size(state)} characters, limit {STATE_CHAR_LIMIT}; "
                          "the caller must trim it to what the questions need"}
    built = {k: build_question(registry[q["judgment"]], q.get("vars"), q.get("criteria"))
             for k, q in wanted.items()}
    batches, current, used = [], {}, _size(state)
    for k, q in built.items():
        cost = _size(q)
        if current and used + cost > REQUEST_CHAR_LIMIT:
            batches.append(current)
            current, used = {}, _size(state)
        current[k] = q
        used += cost
    batches.append(current)
    state_sha = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False)
                               .encode("utf-8")).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows, tokens, started = [], 0, time.time()
    for batch in batches:
        try:
            reply = _post({"state": state, "model": cfg["model"], "questions": batch}, key, timeout)
        except Exception as exc:
            _journal(cfg["project_root"], [{"ts": now, "kind": "error", "ticket": ticket,
                                            "stage": stage, "reason": str(exc)[:300]}])
            return {**base, "status": "unavailable", "reason": str(exc)[:300]}
        tokens += int((reply.get("usage") or {}).get("input_tokens") or 0)
        for k, answer in (reply.get("answers") or {}).items():
            item = registry[wanted[k]["judgment"]]
            decision = decide(item, answer, cfg["thresholds"])
            base["answers"][k] = {"judgment": item["id"], **decision}
            rows.append({"ts": now, "kind": "answer", "ticket": ticket, "stage": stage,
                         "judgment": item["id"], "key": k, "state_sha": state_sha,
                         "mode": cfg["mode"], "model": reply.get("model"),
                         **{**decision, "probabilities": answer.get("probabilities")}})
    rows.append({"ts": now, "kind": "request", "ticket": ticket, "stage": stage,
                 "provider": cfg["provider"], "model": cfg["model"], "requests": len(batches),
                 "questions": len(built), "input_tokens": tokens,
                 "cost_usd": round(tokens * INPUT_USD_PER_MILLION / 1e6, 6),
                 "seconds": round(time.time() - started, 2)})
    _journal(cfg["project_root"], rows)
    missing = [k for k in built if k not in base["answers"]]
    return {**base, "status": "ok", "input_tokens": tokens, "unanswered": missing}


def ask_many(requests: list, *, workers: int = 6, **common) -> list:
    """Several small states at once: [(state, questions), ...] -> replies in the same order.

    A question answers best when its subject is the state, not an id inside a large one,
    so per-item judgments are many small requests. They are independent; send them together.
    """
    if not requests:
        return []
    cfg = common.pop("cfg", None) or settings(common.get("project_root"))
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(requests)))) as pool:
        return list(pool.map(lambda item: ask(item[0], item[1], cfg=cfg, **common), requests))


def ask_one(state, judgment_id: str, *, variables: dict | None = None, ticket=None, stage=None,
            project_root=None, cfg: dict | None = None) -> dict | None:
    """One judgment over one state: the decision dict, or None when the judge is off,
    unavailable or the question is disabled. Callers branch on `value`/`decided`."""
    reply = ask(state, {"q": {"judgment": judgment_id, "vars": variables or {}}},
                ticket=ticket, stage=stage, project_root=project_root, cfg=cfg)
    if reply["status"] != "ok":
        return None
    answer = reply["answers"].get("q")
    return dict(answer, advisory=reply["advisory"]) if answer else None


def judged_refusal(refusal_id: str, judgment_id: str, state, *, variables: dict | None = None,
                   ticket=None, stage=None, project_root=None, cfg: dict | None = None) -> dict:
    """A refusal of FORM or DIAGNOSIS asks the judge before it fires.

    The rule the code holds is binary; the thing in front of it deviates in a way the rule's
    author did not foresee (an id spelled by a plugin, a reason worded differently, a digest
    with one extra line). Before refusing, the caller puts the item and the rule's intent to
    the judge as a registered question whose `true` means "this satisfies the intent".

    Returns {"passed": bool, "mode": ..., "decision": ..., "note": str}. `passed` is True only
    in `mode: on` with a decided `true`; shadow journals what would have passed and returns
    False, so nothing changes until the question is calibrated. A pass is journalled as
    kind `pass` under the refusal id, and `passes()` lists them for the gate brief - the
    person sees every block the judge let through. Safety refusals (writes into the
    application, secrets, external writes, gates) never call this.
    """
    cfg = cfg or settings(project_root)
    decision = ask_one(state, judgment_id, variables=variables, ticket=ticket, stage=stage,
                       project_root=project_root, cfg=cfg)
    out = {"passed": False, "mode": cfg["mode"], "decision": decision, "refusal": refusal_id, "note": ""}
    if not decision:
        return out
    would = decision.get("value") is True
    if would and cfg["mode"] == "on":
        out["passed"] = True
        out["note"] = f"judge passed {refusal_id} ({judgment_id} p={decision.get('probability', decision.get('confidence'))})"
    elif would:
        out["note"] = f"judge (shadow) would pass {refusal_id}"
    _journal(cfg["project_root"], [{"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                    "kind": "pass" if out["passed"] else "would_pass" if would else "held",
                                    "ticket": ticket, "stage": stage, "refusal": refusal_id,
                                    "judgment": judgment_id, "mode": cfg["mode"],
                                    "probability": decision.get("probability"),
                                    "confidence": decision.get("confidence")}])
    return out


def passes(project_root, ticket=None) -> list:
    """Every block the judge let through for this story, for the gate brief and the retro."""
    path = journal_path(project_root)
    rows = []
    if not path or not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("kind") == "pass" and (not ticket or row.get("ticket") == ticket):
            rows.append(row)
    return rows


def summary(project_root, ticket=None) -> dict:
    path = journal_path(project_root)
    out = {"questions": 0, "decided": 0, "requests": 0, "input_tokens": 0, "cost_usd": 0.0,
           "errors": 0, "by_judgment": {}}
    if not path or not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if ticket and row.get("ticket") != ticket:
            continue
        if row.get("kind") == "answer":
            out["questions"] += 1
            out["decided"] += bool(row.get("decided"))
            per = out["by_judgment"].setdefault(row["judgment"], {"asked": 0, "decided": 0})
            per["asked"] += 1
            per["decided"] += bool(row.get("decided"))
        elif row.get("kind") == "request":
            out["requests"] += row.get("requests", 0)
            out["input_tokens"] += row.get("input_tokens", 0)
            out["cost_usd"] = round(out["cost_usd"] + row.get("cost_usd", 0), 6)
        elif row.get("kind") == "error":
            out["errors"] += 1
        elif row.get("kind") == "pass":
            out["passes"] = out.get("passes", 0) + 1
    return out


def status(project_root=None, probe: bool = False) -> dict:
    cfg = settings(project_root)
    out = {"provider": cfg["provider"], "mode": cfg["mode"], "model": cfg["model"],
           "api_key_env": cfg["api_key_env"],
           "api_key_present": bool(_api_key(cfg["api_key_env"])),
           "problems": cfg["problems"],
           "registry_errors": registry_errors()}
    if probe and cfg["provider"] != "none":
        reply = ask("The build finished and every test passed.",
                    {"probe": {"judgment": "judge_probe"}}, cfg={**cfg, "project_root": None})
        out["probe"] = {"status": reply["status"], "reason": reply.get("reason"),
                        "answer": reply["answers"].get("probe")}
    return out


def _selftest() -> int:
    failures = []
    errors = registry_errors()
    if errors:
        failures += errors
    registry = load_registry()
    off = ask({"x": 1}, {"a": {"judgment": "judge_probe"}},
              cfg={"provider": "none", "mode": "on", "model": DEFAULT_MODEL, "disabled": [],
                   "api_key_env": DEFAULT_KEY_ENV, "thresholds": {}, "project_root": None})
    if off["status"] != "off" or off["answers"]:
        failures.append("provider none must send nothing and answer nothing")
    nokey = ask({"x": 1}, {"a": {"judgment": "judge_probe"}},
                cfg={"provider": "typesafe", "mode": "on", "model": DEFAULT_MODEL, "disabled": [],
                     "api_key_env": "QA_FACTORY_NO_SUCH_KEY", "thresholds": {}, "project_root": None})
    if nokey["status"] != "unavailable":
        failures.append("a missing key must be `unavailable`, never an exception")
    noul = next(i for i in registry.values() if i["type"] == "noul")
    hi, lo = noul["thresholds"]["true_at"], noul["thresholds"]["false_at"]
    if decide(noul, {"noul": hi})["value"] is not True or decide(noul, {"noul": lo})["value"] is not False \
            or decide(noul, {"noul": 0.5})["decided"]:
        failures.append("noul thresholds do not decide as registered")
    choice = next(i for i in registry.values() if i["type"] == "choice")
    first = next(iter(choice["criteria"]))
    if decide(choice, {"choice": first, "confidence": 0.2})["decided"]:
        failures.append("a low-confidence choice must stay undecided")
    if build_question({"type": "noul", "instructions": "about {id}"}, {"id": "R1"})["instructions"] != "about R1":
        failures.append("variables are not substituted")
    for failure in failures:
        print("FAIL", failure)
    print(f"judge selftest: {len(registry)} judgments, {len(failures)} failures")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("command", nargs="?", choices=["status", "ask", "summary"])
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--project-root")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--judgments")
    parser.add_argument("--state")
    parser.add_argument("--vars")
    parser.add_argument("--ticket")
    parser.add_argument("--stage")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.command == "status":
        print(json.dumps(status(args.project_root, args.probe), indent=2))
        return 0
    if args.command == "summary":
        root = _project_root(args.project_root)
        print(json.dumps(summary(root, args.ticket), indent=2))
        return 0
    if args.command == "ask":
        if not args.judgments or not args.state:
            parser.error("ask needs --judgments and --state")
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        variables = json.loads(Path(args.vars).read_text(encoding="utf-8")) if args.vars else {}
        questions = {jid: {"judgment": jid, "vars": variables} for jid in args.judgments.split(",")}
        reply = ask(state, questions, ticket=args.ticket, stage=args.stage,
                    project_root=args.project_root)
        print(json.dumps(reply, indent=2, ensure_ascii=False))
        return 0 if reply["status"] in ("ok", "off") else 3
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
