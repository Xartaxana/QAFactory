"""The story runner's loop, second part: the waiver and the journal shapes, the question flag, the paths a role is
given, the observed stand job, the window counters, and the halt texts. Moved out of test_story_run.py unchanged;
the shared scaffolding is `story_run_common`. Continues test_story_run_loop.py (t-104).
"""
# Shared helpers of test_story_run_loop_b.py, split by tools/test_split.py (TD-11c).
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_run_common import driver_for


# --- the question threshold: the stop and the resume (t-113 B2: R15, R16, R17, Q8) ---------------------------
# TP1-13797 (cmp1): five open questions went to gate A and the person saw six cards of eleven. A stop
# by code asks the WHOLE batch and the person's words reach the same role without a conductor. The
# driver's half is under test here: the role, `claude -p`, the handoff, `stage_done` and `story_step`
# are stubbed (nothing reaches a model); the register, the thresholds, the batch text, `question_register`
# and the answer files are the real ones.
ROLE_OF = {"S2": "qa-requirements-tester", "S3": "qa-test-strategist", "S4": "qa-case-designer"}


Q_TASK = "QA-9"


class QStub:
    """One in-process driver whose role, `claude -p`, handoff, `stage_done` and `story_step` are recorded."""

    def __init__(self, root, env, stage: str = "S2", digest: str | None = None):
        self.stage, self.role = stage, ROLE_OF[stage]
        self.dispatch = f"{stage}-{self.role}-1"
        self.digest = digest or f"{self.role} {stage} {Q_TASK} · ok\n{Q_TASK} · ok · the work is written\n"
        self.py_calls, self.claude_calls, self.conductor_calls, self.role_calls = [], [], [], []
        self.claude_result = {"result": "done", "session_id": "sess-1", "stderr": "", "total_cost_usd": 0.0,
                              "is_error": False}
        d = self.driver = driver_for(root, env, Q_TASK)
        d.step = lambda *a, **k: (f"dispatched {self.dispatch} (revision 4)\n--- Agent prompt, verbatim ---\n"
                                  f"You are {self.role}.\n--- the moment the Agent call returns ---\n")
        d.system_file = lambda *a, **k: ""

        def run_claude(kind, prompt, **kw):
            self.claude_calls.append({"kind": kind, "prompt": prompt, "resume": kw.get("resume", "")})
            result = dict(self.claude_result)
            if kw.get("dispatch") and result.get("session_id") and not result.get("is_error"):
                d.state["sessions"][kw["dispatch"]] = result["session_id"]   # what the real `run_claude` stores
            return result
        d.run_claude = run_claude
        d.handoff = lambda role, stage, dispatch, result: self.digest
        real_py = d.py

        def py(script, *args, **kwargs):
            self.py_calls.append((script, args))
            if script in ("stage_done.py", "story_step.py"):
                return 0, ""
            return real_py(script, *args, **kwargs)
        d.py = py
        d.conductor = lambda *a, **k: self.conductor_calls.append(a) or {"action": "continue", "did": "stub"}
        d.controller_state = lambda: {"dispatches": {self.dispatch: {"stage": stage, "role": self.role, "scope": []}}}

    def statuses(self) -> list:
        return [args[args.index("--status") + 1] for script, args in self.py_calls
                if script == "stage_done.py" and "--status" in args]

    def finishes(self) -> list:
        return [args for script, args in self.py_calls if script == "story_step.py" and args and args[0] == "finish"]

    def run_role(self):
        try:
            self.driver.run_role(self.stage, self.role)
            return None
        except Exception as raised:  # noqa: BLE001 - a Person or a Refusal is the subject, not a crash
            return raised

    def answer(self, root: Path, words: str, quiet: bool = True) -> str:
        """The person's answer as a file, taken by the driver; the driver's own printing is returned."""
        import contextlib
        import io
        path = root / "answer.md"
        path.write_bytes(words.encode("utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.driver.take_answer(path)
        return out.getvalue()


def q_load(task_root: Path) -> dict:
    import question_register as QR
    return {q["id"]: q for q in QR.load(task_root)["questions"]}
