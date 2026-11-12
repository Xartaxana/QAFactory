"""The fixture helper of the probe's model entries (t-2064 P3; no `test_` function: a helper, never collected).

`write_invert_entries` writes `work/probe-models/<dispatch>.json` with one `invert` entry per check, so a test that runs the probe
over a stub or a fixture takes the inversion road through the SAME loader a critic's file goes through. It is the one place a
wrapper flips: a call to this helper, never an environment variable and never a flag in product code (no test door exists in the tool).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402

DEFAULT_REASON = "fixture: the inverted form is what this test reads"


def plan_keys(plan_args: list, root=None, env=None) -> list:
    """The key of every check `probe_by_code.py --plan --json <plan_args>` lists, in order (`plan_args`: `--task T --instance I --test
    <file>::<function>` and whatever else the call needs; `--plan` and `--json` are added here). Runs the plan in this process, unless
    `root` (the project the call runs in) is given: then it is the same script as a process with that cwd and `env` (default: this
    environment plus `CLAUDE_PROJECT_DIR=root`), the way a wrapper that launches the probe launches it. A refusal is a RuntimeError."""
    if root is not None:
        import os
        import subprocess
        launch_env = dict(os.environ if env is None else env)
        launch_env.setdefault("CLAUDE_PROJECT_DIR", str(root))
        proc = subprocess.run([sys.executable, "-B", str(Path(PBC.__file__).resolve()), "--plan", "--json"] + list(plan_args),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root), env=launch_env,
                              timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"--plan refused (exit {proc.returncode}): {(proc.stdout + proc.stderr)[:300]}")
        return [check["key"] for check in json.loads(proc.stdout)["checks"]]
    args = PBC._build_parser().parse_args(["--plan", "--json"] + list(plan_args))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            PBC._plan_cli(args)
        except SystemExit as stop:
            if stop.code not in (0, None):
                raise RuntimeError(f"--plan refused (exit {stop.code}): {out.getvalue()[:300]}") from None
    return [check["key"] for check in json.loads(out.getvalue())["checks"]]


def write_invert_entries(task_root, dispatch: str, keys=None, reason: str = DEFAULT_REASON, *, plan_args=None, root=None,
                         env=None) -> Path:
    """Write `<task_root>/work/probe-models/<dispatch>.json`: one `{"check": key, "invert": reason}` per key. `keys` None takes every key
    of `--plan --json` for `plan_args` (a list of the call's own arguments; without them there is nothing to ask and it is a ValueError;
    `root` / `env` as in `plan_keys`: ask the plan as the project's own process). Returns the path."""
    if keys is None:
        if not plan_args:
            raise ValueError("keys=None takes the keys of `--plan --json`: pass plan_args (--task, --instance, --test ...)")
        keys = plan_keys(plan_args, root=root, env=env)
    path = Path(task_root) / "work" / "probe-models" / f"{dispatch}.json"
    wanted = json.dumps({"models": [{"check": key, "invert": reason} for key in keys]})
    # t-2064 P4b: a file already holding these bytes is left alone - a refusal test takes its tree snapshot (bytes AND mtime) around the
    # call that writes the entries, and a rewrite of the same bytes would move the mtime that snapshot compares
    if path.is_file() and path.read_text(encoding="utf-8") == wanted:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(wanted, encoding="utf-8")
    return path
