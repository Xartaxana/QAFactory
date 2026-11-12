#!/usr/bin/env python3
"""B-012: an infrastructure failure of `claude -p` is not a role's result.

On TP1-13877 a login error, a usage limit and a Cloudflare page each came back from `claude -p`
as the "final message" of a role; the driver resumed the role on them, called the conductor with
them and put them to the person as the conductor's question (5 conductor sessions and 4 resumes,
`state/driver-runs.jsonl` rows 1-4, 7, 17). Nothing here reaches a network or a model: `claude` is
the stub of `story_run_common.py` behind a PRELUDE that pops `control["infra_queue"]` (one entry per
call: a JSON result or raw text, its stderr, its exit code, and the files the cut-off role had
already written) and only when the queue is empty runs the ordinary stub. Every call, queued or
not, is logged with its argv, its prompt and the environment names the control asks about.

What is proved (K = the acceptance keys of the spec):
  K1  the classifier on the three wire forms, and where it must say nothing;
  K2  auth stops the driver with exit 5 - no question file, no conductor, no saved result;
  K3  limit: the reset is quoted, or its absence is said; the session that worked is kept;
  K4  transient then success: one retry after 5 s that resumes the failed session;
  K5  transient x3: exactly three calls (AT the limit) and never a fourth (BEYOND it);
  K6  which session a retry or a rerun continues, at the num_turns boundary;
  K7  a rerun continues the interrupted dispatch, by resume or fresh with a note;
  K8  a result saved by the driver before this change (the 13877 S3 file) is classified too;
  K9  the conductor's own call is covered; K10 the S0 tracker read (t-267: REST, a lost login is
      the adapter's exit 5, not a tracker-agent call); K11 unclassified is
      today's path; K12 the child environment; K13 UTF-8 children; K14 the texts obey the human
      text rules; K15 a retry does not count as a conductor call.
"""
# Shared helpers of test_infra_failure.py, split by tools/test_split.py (TD-11c).
import json
import os
import sys
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check  # noqa: E402
sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402


TASK = "QA-9"


START_CWD = os.getcwd()


# The texts of TP1-13877, VERBATIM (state/conductor.jsonl rows 2 and 5; state/driver-runs/
# S3-qa-test-strategist-1.json). The dots and the dash are written as code points so that the
# file stays plain ASCII.
AUTH = "Not logged in " + chr(0xB7) + " Please run /login"


LIMIT = "You've hit your weekly limit " + chr(0xB7) + " resets 2am (Europe/Madrid)"


LIMIT_NO_RESET = "You've hit your limit"


MALFORMED = ("API Error: API returned an empty or malformed response (HTTP 200) \u2014 check for a proxy or "
             "gateway intercepting the request. Response: content-type html, body is an HTML page, 16066 "
             "bytes, request-id absent, server cloudflare, intermediary headers cf-cache-status cf-ray "
             "content-encoding transfer-encoding. This was the non-streaming retry of streaming request "
             "(no Anthropic request-id), which failed with: no_events, StreamNoEventsError; 0 stream "
             "events received.")


S3_SAVED = {"session_id": "531ae422-15be-43a9-bbef-2bcb38cb8e2d", "result": MALFORMED, "num_turns": 29,
            "total_cost_usd": 2.0212816, "duration_ms": 1048688, "is_error": True, "exit_code": 1, "stderr": ""}


PRELUDE = r'''
import io, json, os, re, sys
from pathlib import Path
_data = sys.stdin.buffer.read()
sys.stdin = io.TextIOWrapper(io.BytesIO(_data), encoding="utf-8")
_control = json.loads(Path(os.environ["STUB_CONTROL"]).read_text(encoding="utf-8"))
_dir = Path(os.environ["STUB_LOG"]).parent
_count = _dir / "infra-count.txt"
_n = int(_count.read_text()) if _count.exists() else 0
_queue = _control.get("infra_queue") or []
_prompt = _data.decode("utf-8")
with (_dir / "infra-log.jsonl").open("a", encoding="utf-8") as _h:
    _h.write(json.dumps({"n": _n, "queued": _n < len(_queue), "argv": sys.argv[1:], "prompt": _prompt,
                         "env": {k: os.environ.get(k) for k in _control.get("log_env") or []}}) + "\n")
if _n < len(_queue):
    _count.write_text(str(_n + 1))
    _e = _queue[_n]
    _m = re.search(r"Artifacts dir: (\S+)", _prompt)
    if _m:
        for _rel, _c in (_e.get("files") or {}).items():
            _p = Path(_m.group(1)) / _rel
            _p.parent.mkdir(parents=True, exist_ok=True)
            _p.write_text(_c, encoding="utf-8")
    if "json" in _e and not _e["json"].get("is_error"):
        write_receipt(_e["json"].get("session_id"))     # a queued SUCCESS is a session whose hooks reported (B-014)
    if "raw" in _e:
        sys.stdout.buffer.write(_e["raw"].encode("utf-8"))
    else:
        sys.stdout.buffer.write(json.dumps(_e["json"]).encode("utf-8"))
    sys.stderr.write(_e.get("stderr", ""))
    sys.stderr.flush()
    sys.stdout.flush()
    sys.exit(int(_e.get("exit", 1)))
'''


LOG_ENV = ["ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK",
           "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", "CLAUDE_CODE_HOST_AUTH_ENV_VAR", "MY_TOK", "FOO",
           "PYTHONUTF8", "PYTHONIOENCODING"]


FILES = {"work/context-manifest.json": json.dumps(T.GOOD_MANIFEST).replace("{task}", TASK),
         "work/context-bundle.json": "{}"}


DIGEST = T.SCOUT_DIGEST.replace("{task}", TASK)


def entry(text, *, turns=1, session="sess-infra", cost=0, files=None, exit_code=1, stderr="", subtype="success"):
    return {"json": {"type": "result", "subtype": subtype, "is_error": True, "session_id": session,
                     "num_turns": turns, "total_cost_usd": cost, "duration_ms": 10, "result": text},
            "exit": exit_code, "files": files or {}, "stderr": stderr}


def control(queue=None, **more):
    base = {"roles": {"qa-scout": {"files": FILES, "result": DIGEST}}, "resume": {"result": DIGEST},
            "conductor": {"action": "continue", "did": "nothing"}, "log_env": LOG_ENV,
            "infra_queue": queue or []}
    base.update(more)
    return base


def install(root, ctl):
    (root / "fake_claude.py").write_text(T.RECEIPT + PRELUDE + T.STUB, encoding="utf-8")
    T.set_control(root, ctl)


def calls(root):
    """Every claude call the stub saw. The prompt arrives with the platform's newlines (subprocess text
    mode writes CRLF on Windows): normalised here, because the tests compare words, not line ends."""
    rows = T.jsonl(root / "infra-log.jsonl")
    for row in rows:
        row["prompt"] = row["prompt"].replace("\r\n", "\n")
    return rows


def prompt_for(task_root, dispatch="S1-qa-scout-1"):
    return f"You are qa-scout. Dispatch: {dispatch}.\nArtifacts dir: {task_root}\nDo the work."


def project_of(ctl=None, task=TASK, **over):
    """A seeded project whose `claude` is the queue stub, and an in-process Driver over it whose
    sleeps are recorded, never taken."""
    root, task_root, env = T.seed(task)
    install(root, ctl or control())
    driver = T.driver_for(root, env, task, **over)
    delays = []
    driver.sleep = delays.append
    return root, task_root, env, driver, delays


def done(root):
    os.chdir(START_CWD)
    harness.cleanup(root)


def scenario(fn):
    try:
        fn()
    except Exception:  # a scenario that cannot even run is a red result, not a crash of the others
        check(f"{fn.__name__} ran to its end", False, traceback.format_exc()[-1500:])
        os.chdir(START_CWD)


def state_of(task_root):
    return T.s0_state(task_root)


def infra_of(exc_or_none):
    return getattr(exc_or_none, "kind", None)


def raised(driver, *args, **kwargs):
    """(InfraStop or None, result or None) of one run_claude call."""
    import story_run
    try:
        return None, driver.run_claude(*args, **kwargs)
    except story_run.InfraStop as stop:
        return stop, None
