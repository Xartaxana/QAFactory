"""Shared scaffolding of the story_step tests: the fake controller, the project and story builders, and the helpers
every `test_story_step_<command>.py` file uses (and the other test files that open a story the way these do).

This is not a test itself (selftest runs `test_*.py`). `test_story_step.py` re-exports every name here, so a test that says
`import test_story_step as STEP` keeps working. Split off test_story_step.py (TQ1-10).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_step  # noqa: E402

# r0107 t-439: no key of the story_step tests reads the dashboard, and every `Controller.apply` renders it after its commit
# (`refresh_derived` -> `dashboard_refresh.refresh_project`: ~2.5 s of the ~2.7 s a commit took here on t-439's box,
# measured by cProfile on `s5_window_story`, 15 commits per story, a dozen stories). The existing switch of `refresh_project`
# (test_controller_paths.py sets it the same way) is set for this process and, through the `env` copies of `os.environ`,
# for every `story_step.py` child.
os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"


class FakeController:
    """Only what `_next` reads. The real controller is exercised in test_judge.py."""

    def __init__(self, action):
        self.action = action

    def next_action(self):
        return dict(self.action)

    def state(self):
        return {}

    def _next_action_for_state(self, _state):
        return dict(self.action)


def set_pipeline_block(root: Path, value) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.pop("pipeline", None)
    if value is not None:
        cfg["pipeline"] = {"stop_after": value}
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    import hooklib
    hooklib._PROJECT_ROOT_CACHE = None


def seed(root: Path, ticket: str) -> Path:
    task = root / "qa-factory/artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": ticket, "size": "S", "environment": "local",
         "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    return task


CONFIG_FIELD = "config_sha256_at_start"  # the dispatch record's field: a contract, so spelled out here


def sha256_of(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_story(root: Path, env: dict, ticket: str) -> Path:
    """A story past S0 with the S1 evidence files present, ready for `start` / `finish`."""
    from controller import Controller
    task = seed(root, ticket)
    harness.run_script("stage_done.py", "--task", ticket, "--stage", "S0", "--status", "done",
                       "--digest", "preflight green", cwd=root, env=env)
    Controller(task).apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                          "known_paths": {"root": str(task), "project_root": str(root)},
                                          "idempotency_key": "init"})
    for name in ("context-manifest.json", "context-bundle.json"):
        (task / "work" / name).write_text("{}", encoding="utf-8")
    return task


def dispatch_record(task: Path, dispatch_id: str) -> dict:
    from controller import Controller
    return Controller(task).state()["dispatches"][dispatch_id]


def change_config(root: Path, value: int) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["b193_boundary_probe"] = value
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def finish_s1(root: Path, env: dict, ticket: str):
    return harness.run_script("story_step.py", "finish", "--task", ticket, "--dispatch-id",
                              "S1-qa-scout-1", "--digest", "qa-scout S1 done - ok",
                              "--ignore-handoff", cwd=root, env=env)


def s5_window_story(root: Path, ticket: str, handed: bool):
    """A coverage-v2 story at S5 through a REAL controller (the F1 fixture of test_fixes_13797.py: the
    author accepted, the critic's dispatch `s5-critic` running, TC-2 with no instance), plus the files
    `story_step finish` reads: pipeline.json from the fixture, the window record, the manifest."""
    import shutil
    import test_fixes_13797 as FIX
    art = root / "qa-factory/artifacts" / ticket
    art.mkdir(parents=True)
    controller, window = FIX.v2_story_at_s5(art)
    # the fixture's `known_paths` name the task root as the project: the controller looks for the
    # project's config there
    (art / "qa-factory").mkdir()
    shutil.copy(root / "qa-factory/config.json", art / "qa-factory/config.json")
    FIX.manifest_with(art, "handed_to_person" if handed else "impossible")
    if handed:   # an instance the person runs: the controller's own handed road
        window["instances"] = [dict(window["instances"][0], outcome="handed_to_person")]
        # EP1-4 (t-626 FR-4/AR-28; t-740 diagnosis): the claim counts only as far as the manifest confirms it, and every case
        # of i-1 (TC-1) must be handed (`handed_instances` rule 4) - so TC-1 gets its row beside the TC-2 row the doors use
        manifest = manifest_of(art)
        manifest["unresolved"].append({"case": "TC-1", "reason": "handed_to_person",
                                       "detail": "web: npx playwright test tests/test_one.py"})
        (art / "work/automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return art, window


def finish_s5(root: Path, env: dict, ticket: str, *more):
    return harness.run_script("story_step.py", "finish", "--task", ticket, "--dispatch-id", "s5-critic",
                              "--digest", "qa-code-critic S5 done", "--ignore-handoff", "--output", "run.txt",
                              "--output", "critic-findings.md", *more, cwd=root, env=env)


DECIDE_WORDS = "I run it myself on the device.\r\nSecond line 00e9"


def run_decide(root: Path, env: dict, ticket: str, words, *more, text: str = DECIDE_WORDS, dispatch: str = "s5-critic"):
    """`story_step.py decide` as a child process; the words go in a file OUTSIDE the story folder, written as bytes
    (a text-mode write would turn \\r\\n into \\r\\r\\n on Windows)."""
    path = root / f"words-{ticket}.txt"
    path.write_bytes(text.encode("utf-8"))
    return harness.run_script("story_step.py", "decide", "--task", ticket, "--dispatch-id", dispatch,
                              "--words-file", str(path), *words, *more, cwd=root, env=env)


def manifest_of(art: Path) -> dict:
    return json.loads((art / "work/automation-manifest.json").read_text(encoding="utf-8"))


def set_rows(art: Path, rows: list) -> None:
    data = manifest_of(art)
    data["unresolved"] = rows
    (art / "work/automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")


def s4_story(root: Path, ticket: str, role: str = "qa-case-critic", did: str = "s4-critic",
             valid_case: bool = False) -> Path:
    """A story through S0..S3 with the S4 case critic's dispatch `s4-critic` running (the closing role of S4); `role` and
    `did` name another S4 role's dispatch instead (t-827 FX-5: a role that does not close the stage). The case file is
    the text "the case" - INVALID for S4's exit gate on purpose (GW1-8 fix round F1: the person's decision is carried
    through `finish` whatever the case files hold); `valid_case=True` writes one the gate accepts."""
    import shutil
    import test_controller_state as BASE
    from controller import Controller
    art = seed(root, ticket)
    (art / "qa-factory").mkdir()
    shutil.copy(root / "qa-factory/config.json", art / "qa-factory/config.json")
    controller = Controller(art)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1", "known_paths": {"root": str(art)},
                                    "idempotency_key": "init"})
    # G1-5: `seed` records no implementation source (off_diff:absent): S3 on a diff without a table would be refused
    for number in range(4):
        BASE.accept_stage(controller, art, f"S{number}")
    # E-B11: `finish` closes S4 over the acceptor's record; the critic dispatch is the only S4 dispatch, so no author dispatch is reviewed
    BASE.record_stage_acceptance(art, "S4", "")
    controller.apply("dispatch", {"id": did, "stage": "S4", "role": role, "scope": ["TC-1"],
                                  "input_hash": "cases-1", "budget": {}, "known_paths": {}, "idempotency_key": "d-s4"})
    (art / "work/test-cases").mkdir(parents=True)
    (art / "work/test-cases/TC-1.md").write_text(
        f"---\nid: TC-1\ntitle: t\narea: api\npriority: P2\nstatus: Draft\nchannel: auto\nreuse_decision: new\n"
        f"updated: 2026-09-01\ntask: {ticket}\ncovers: [R-1]\n---\nthe case\n" if valid_case else "the case",
        encoding="utf-8")
    (art / "work/case-critic-findings.md").write_text("findings", encoding="utf-8")
    return art


def finish_s4(root: Path, env: dict, ticket: str, *more):
    return harness.run_script("story_step.py", "finish", "--task", ticket, "--dispatch-id", "s4-critic",
                              "--digest", "qa-case-critic S4 done", "--ignore-handoff", *more, cwd=root, env=env)


class _StopAtAuthor(Exception):
    pass


def author_story(root: Path, ticket: str, *, run_witness: bool = True) -> Path:
    """A coverage-v2 story at S5 through a REAL controller with the automator's dispatch `s5-author` RUNNING (the F1
    fixture of test_fixes_13797.py, stopped at the author's accept by wrapping `Controller.apply` - no copy of it), the
    manifest with ONE instance (`i-1`) and no run block, and a run witness so the manifest itself is whole: the one
    thing the real `s5_precheck` then finds is `run_mapping` - no run block carries a result row."""
    import shutil
    import test_fixes_13797 as FIX
    from controller import Controller
    art = root / "qa-factory/artifacts" / ticket
    art.mkdir(parents=True)
    real = Controller.apply

    def stop_at_author_accept(self, operation, request, *rest, **kw):
        if operation == "accept" and request.get("id") == "s5-author":
            raise _StopAtAuthor()
        return real(self, operation, request, *rest, **kw)
    Controller.apply = stop_at_author_accept
    try:
        FIX.v2_story_at_s5(art)
    except _StopAtAuthor:
        pass
    finally:
        Controller.apply = real
    (art / "qa-factory").mkdir()
    shutil.copy(root / "qa-factory/config.json", art / "qa-factory/config.json")
    FIX.manifest_with(art, "impossible")
    data = manifest_of(art)
    data["tests"][0]["file"] = "tests/test_one.py"
    if run_witness:
        data["run_witness"] = "evidence/run-20261021-120000.json exit 0, 1 passed in 0.10s"
    (art / "work/automation-manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return art


def author_picture(art: Path) -> tuple:
    """What a refusal must leave alone: the controller's revision and the dispatch's status."""
    from controller import Controller
    state = Controller(art).state()
    return state["revision"], state["dispatches"]["s5-author"]["status"]


def finish_here(ticket: str, *, dispatch: str = "s5-author", **flags):
    """`story_step.finish` in this process (its stdout captured): `(exit code, stdout)`. The flags are the CLI's, as the
    namespace spells them."""
    import argparse
    import contextlib
    import io
    ns = argparse.Namespace(task=ticket, dispatch_id=dispatch, digest="x", output=["author.txt"], not_complete=False,
                            complete=False, ignore_handoff=False, window=None, unresolved=None, reason=None)
    vars(ns).update(flags)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        return story_step.finish(ns), out.getvalue()


def author_picture_of(art: Path, dispatch: str) -> tuple:
    from controller import Controller
    state = Controller(art).state()
    return state["revision"], state["dispatches"][dispatch]["status"]
