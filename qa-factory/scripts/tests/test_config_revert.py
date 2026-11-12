"""HF5-6 - the stand's config.json is given back when the story ends (t-1501 section 5.6, hotfix-12586/5).

On TP1-12586 the run changed the stand's `qa-factory/config.json` by hand (the account keys of the second user, a flat
`frontend_url`) and nothing took it back. A FRESH story keeps the bytes it found (`config_contract.snapshot_config`); at S9 and at
`stop` `restore_config` gives them back, except what a recorded writer wrote in the story's window.

K1   the 12586 drift (fixture) + a runtime_probe `--suggest --write` entry, through the real `do_suggest`: the drift is reverted, the
     probe entry stays, a dispatch started with the hash of the restored file reports no change
K2   nothing recorded in the window: the file after the revert is byte for byte the copy (sha256)
K3   a story that is not fresh keeps no copy: `not_kept_copy`, never `unchanged`; a resume does not take a copy; both worlds
K4   two stories: one in flight (not only an open dispatch) or one that ran inside the window: `skipped`, the file untouched
K5   two recorded writes with a hand edit between them, and a backup whose approval row is not in the window
K6   the file before the revert is machine-local (`qa-factory/state/config-reverts/`), nothing new in records/
K7   edges: unchanged, deleted, broken, damaged copy, absent copy, the pointer limit 5/6, a second call, a note one byte off
K8   the CLI (`story_step.py config-snapshot|config-restore`) prints one JSON line; the phase files carry the commands
K9   the writer: `_write_config` writes through `_replace_bytes`, and no temp file is left
K10  the driver: the story start keeps the copy, the story end gives it back
K-9.9 (HF8-9) a stand fact recorded through `project_decisions` (`stand-account`) outlives the story: the receipt's `recorded_at` / `before`
     are a recorded write (`source: project decision`); a hand edit before it is still reverted; an old or pending receipt keeps nothing

Runnable on its own: `python -B scripts/tests/test_config_revert.py`.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (  # noqa: E402
    FIXTURES, check, check_eq, check_in, cleanup, finish, run_script, temp_project, use_project,
)

import config_contract as C  # noqa: E402

DRIFT = FIXTURES / "run-12586-config-drift"
BEFORE = (DRIFT / "config.before.json").read_bytes()
DRIFTED = (DRIFT / "config.drifted.json").read_bytes()
DRIFT_POINTERS = {"/environment/user_key", "/environment/secret_keys", "/environments"}      # a changed list is ONE pointer (F5)


def now(offset: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat(timespec="seconds")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Project:
    """A throwaway onboarded project with the stand config of the fixture and one or more story folders."""

    def __init__(self, config: bytes = BEFORE):
        self.root = temp_project("qa-config-revert-")
        use_project(self.root)
        self.config = self.root / "qa-factory" / "config.json"
        self.config.write_bytes(config)

    def task(self, name: str = "TP1-12586") -> Path:
        path = self.root / "qa-factory" / "artifacts" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def records(self) -> list:
        folder = self.root / "qa-factory" / "records"
        return sorted(str(p.relative_to(self.root)) for p in folder.rglob("*")) if folder.exists() else []

    def done(self):
        cleanup(self.root)


def config_of(project: Project) -> dict:
    return json.loads(project.config.read_text(encoding="utf-8"))


def finished_pipeline(task: Path, at: str) -> None:
    """A story that ended: S8 and S9 done, gate B decided, closed."""
    (task / "pipeline.json").write_text(json.dumps({
        "closed_at": at, "stages": {"S8": {"status": "done", "finished": at}, "S9": {"status": "done", "finished": at}},
        "gates": {"B": {"decision": "approved", "at": at}}}), encoding="utf-8")


def running_pipeline(task: Path, at: str) -> None:
    (task / "pipeline.json").write_text(json.dumps({"stages": {"S1": {"status": "running", "started": at}}}), encoding="utf-8")


def with_probe(raw: bytes, profile: str = "e2e-ui") -> bytes:
    """The drifted file with the entry the REAL `runtime_probe --suggest --write` writes (its code, a faked `suggest`)."""
    import runtime_probe
    path = Path(os.environ["CLAUDE_PROJECT_DIR"]) / "qa-factory" / "config.json"
    path.write_bytes(raw)
    import node_ids
    real = (runtime_probe.suggest, runtime_probe.rehearsal_argv, runtime_probe.resolve_argv, node_ids.run_captured)
    runtime_probe.suggest = lambda *a, **k: ({"argv": ["x"], "cwd": ".", "timeout_s": 5}, "")
    runtime_probe.rehearsal_argv, runtime_probe.resolve_argv = (lambda argv, *a, **k: list(argv)), (lambda argv: list(argv))
    node_ids.run_captured = lambda *a, **k: types.SimpleNamespace(stdout="", stderr="stub", returncode=0)   # EP1-35: the check runs through node_ids
    try:
        ns = types.SimpleNamespace(write=True, task_root=None, profile=profile, environment="", container="c", checkout="",
                                   app_root="", force=False)
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            code = runtime_probe.do_suggest(ns)
    finally:
        runtime_probe.suggest, runtime_probe.rehearsal_argv, runtime_probe.resolve_argv, node_ids.run_captured = real
    assert code == 0, code
    return path.read_bytes()


def k1_the_12586_drift_is_given_back() -> None:
    project = Project()
    try:
        task = project.task()
        snap = C.snapshot_config(project.root, task, True)
        check_eq("K1 the copy is kept at the start", snap["state"], "kept")
        with_probe(DRIFTED)
        before_revert = project.config.read_bytes()
        records_before = project.records()
        result = C.restore_config(project.root, task)
        check_eq("K1 the story's drift is reverted", (result["state"], set(result["reverted"])), ("reverted", DRIFT_POINTERS))
        cfg = config_of(project)
        check_eq("K1 the account keys are the default ones again", (cfg["environment"]["user_key"], cfg["environment"]["secret_keys"]),
                 ("AUTH_USERNAME", ["AUTH_PASSWORD"]))
        check("K1 the flat frontend_url is gone", "frontend_url" not in cfg["environments"][0])
        import runtime_probe
        check_eq("K1 the runtime_probe entry stays (its note is the constant)",
                 cfg["execution"]["runtime_probes"]["e2e-ui"]["note"], runtime_probe.SUGGEST_NOTE)
        check_eq("K1 it is named as kept", result["kept"], ["/execution/runtime_probes/e2e-ui"])
        line = C.revert_line(result)
        check_in("K1 the report line counts the reverted changes", "3 change(s) made during the story were reverted", line)
        check_in("K1 and the kept one with its writer", "1 kept (written by runtime_probe --suggest --write)", line)
        check_in("K1 and the backup path", result["backup"], line)
        check_eq("K6 the pre-revert file is kept byte for byte", (project.root / result["backup"]).read_bytes(), before_revert)
        check_eq("K6 nothing new in records/", project.records(), records_before)
        check("K6 the backup is under qa-factory/state/config-reverts/", result["backup"].startswith("qa-factory/state/config-reverts/"))
        import story_step
        restored_hash = sha(project.config.read_bytes())
        check_eq("K1 a dispatch started with the RESTORED file's hash reports no config change",
                 story_step.config_finding("S3-qa-x-1", {story_step.CONFIG_START_FIELD: restored_hash}), [])
    finally:
        project.done()


def k1b_a_note_one_character_off_is_not_the_probes() -> None:
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        raw = with_probe(DRIFTED)
        spec = json.loads(raw.decode("utf-8"))
        spec["execution"]["runtime_probes"]["e2e-ui"]["note"] += "."
        project.config.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        result = C.restore_config(project.root, task)
        check_eq("K7 a note that differs by one character is not the runtime_probe's: its entry is reverted too",
                 (result["state"], result["kept"], "/execution" in result["reverted"] or "/execution/runtime_probes/e2e-ui" in result["reverted"]
                  or "/execution/runtime_probes" in result["reverted"]), ("reverted", [], True))
        check("K7 and the entry is gone from the file", "execution" not in config_of(project))
    finally:
        project.done()


def k2_nothing_recorded_gives_the_copy_back_byte_for_byte() -> None:
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        project.config.write_bytes(DRIFTED)
        result = C.restore_config(project.root, task)
        check_eq("K2 reverted, nothing kept", (result["state"], result["kept"]), ("reverted", []))
        check_eq("K2 the file is the copy, sha256", sha(project.config.read_bytes()), sha(BEFORE))
    finally:
        project.done()


def k3_a_story_that_is_not_fresh_keeps_no_copy() -> None:
    import story_step
    project = Project()
    try:
        task = project.task()
        (task / "pipeline.json").write_text(json.dumps({"stages": {"S0": {"status": "done"}, "S1": {"status": "running"}}}), encoding="utf-8")
        fresh, why = story_step.config_story_fresh(task)
        check_eq("K3 a recorded stage is not fresh", fresh, False)
        snap = C.snapshot_config(project.root, task, fresh, why)
        check_eq("K3 the marker, not a copy", (snap["state"], (task / "state" / C.SNAPSHOT_NAME).read_text(encoding="utf-8").count("bytes_b64")),
                 ("not_kept_copy", 0))
        project.config.write_bytes(DRIFTED)
        result = C.restore_config(project.root, task)
        check_eq("K3 restore says not_kept_copy (never unchanged)", result["state"], "not_kept_copy")
        check_in("K3 and the line says the story started before the factory kept a copy",
                 "not reverted: the story started before the factory kept a copy", C.revert_line(result))
        check_eq("K3 the file is not touched", project.config.read_bytes(), DRIFTED)
        # the temporal edge: a story with NO snapshot file at all (begun on 0.10.4) is the same world
        old = project.task("TP1-OLD")
        check_eq("K3 no snapshot file at all: not_kept_copy too", C.restore_config(project.root, old)["state"], "not_kept_copy")
        # fresh readings
        new = project.task("TP1-NEW")
        check_eq("K3 no pipeline, no controller: fresh", story_step.config_story_fresh(new), (True, ""))
        (new / "pipeline.json").write_text(json.dumps({"stages": {"S0": {"status": "pending"}}}), encoding="utf-8")
        check_eq("K3 a pipeline with only pending stages is still fresh", story_step.config_story_fresh(new)[0], True)
        (new / "state").mkdir(exist_ok=True)
        (new / "state" / "controller.json").write_text(json.dumps({"dispatches": {"S1-x-1": {"stage": "S1"}}}), encoding="utf-8")
        check_eq("K3 a recorded dispatch is not fresh", story_step.config_story_fresh(new)[0], False)
        (new / "state" / "controller.json").write_text("{not json", encoding="utf-8")
        check_eq("K3 a state that cannot be read is not fresh (an unknown is not 'nothing recorded')", story_step.config_story_fresh(new)[0], False)
        # a resume: the copy is there, a second call (fresh or not) does not replace it
        resumed = project.task("TP1-RES")
        first = C.snapshot_config(project.root, resumed, True)
        kept_bytes = (resumed / "state" / C.SNAPSHOT_NAME).read_bytes()
        project.config.write_bytes(BEFORE.replace(b"AUTH_USERNAME", b"OTHER_USERNAME", 1))
        again = C.snapshot_config(project.root, resumed, True)
        check_eq("K3 the S0 stops re-enter the start: the second call keeps the first copy",
                 (first["state"], again["state"], (resumed / "state" / C.SNAPSHOT_NAME).read_bytes()), ("kept", "exists", kept_bytes))
        later = C.snapshot_config(project.root, resumed, False, "x")
        check_eq("K3 a call that says 'not fresh' on a story that has its copy changes nothing",
                 (later["state"], (resumed / "state" / C.SNAPSHOT_NAME).read_bytes()), ("exists", kept_bytes))
    finally:
        project.done()


def k4_another_story_in_flight_or_in_the_window() -> None:
    project = Project()
    try:
        a, b = project.task("TP1-A"), project.task("TP1-B")
        C.snapshot_config(project.root, a, True)
        C.snapshot_config(project.root, b, True)
        project.config.write_bytes(DRIFTED)
        stamp = now(1)
        finished_pipeline(a, stamp)
        running_pipeline(b, stamp)          # B is in flight with NO open dispatch: a stage that has begun is enough
        result = C.restore_config(project.root, a)
        check_eq("K4 A closes while B is in flight: skipped", result["state"], "skipped")
        check_in("K4 and the line names B", "TP1-B", C.revert_line(result))
        check_eq("K4 the file is untouched", project.config.read_bytes(), DRIFTED)
        finished_pipeline(b, now(2))
        result = C.restore_config(project.root, b)
        check_eq("K4 B closes after A ran inside its window: skipped", result["state"], "skipped")
        check_in("K4 and the line says another story ran inside this one's window", "another story ran inside this one's window", result["why"])
        check_in("K4 naming A", "TP1-A", result["why"])
        check_eq("K4 the file is untouched again (the conductor's edit does not come back, nor is it undone)", project.config.read_bytes(), DRIFTED)
        # a story that is only a copy (S0 not finished: no pipeline.json yet) is in flight too
        c = project.task("TP1-C")
        C.snapshot_config(project.root, c, True)
        solo = Project()
        try:
            one = solo.task("TP1-ONE")
            C.snapshot_config(solo.root, one, True)
            other = solo.task("TP1-TWO")
            C.snapshot_config(solo.root, other, True)         # no pipeline.json, a copy never restored: in flight
            solo.config.write_bytes(DRIFTED)
            verdict = C.restore_config(solo.root, one)
            check_eq("K4 a story with a copy and no pipeline yet is in flight: skipped", (verdict["state"], "TP1-TWO" in verdict["why"]), ("skipped", True))
        finally:
            solo.done()
        # an archived / old story whose last activity is before this story's start does not block
        project2 = Project()
        try:
            old, mine = project2.task("TP1-OLD"), project2.task("TP1-MINE")
            finished_pipeline(old, "2020-01-01T00:00:00+00:00")
            C.snapshot_config(project2.root, mine, True)
            project2.config.write_bytes(DRIFTED)
            check_eq("K4 a story that ended long before this one started does not block the revert",
                     C.restore_config(project2.root, mine)["state"], "reverted")
        finally:
            project2.done()
    finally:
        project.done()


def approve(project: Project, ref: str, input_hash: str, at: str) -> None:
    path = C.approvals_path(project.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"schema_version": 1, "approval_ref": ref, "status": "approved", "input_hash": input_hash,
                                 "proposal_hash": "p-" + ref, "evidence_ref": "e", "recorded_at": at}) + "\n")


def write_recorded(project: Project, ref: str, change, at: str, approved: bool = True) -> None:
    """One write by the real writer `_write_config`; `approved` False leaves its approval row out."""
    current = config_of(project)
    proposed = json.loads(json.dumps(current))
    change(proposed)
    input_hash = C._json_hash(current)
    if approved:
        approve(project, ref, input_hash, at)
    C._write_config(project.root, current, proposed, input_hash, ref)


def k5_recorded_writes_with_a_hand_edit_between() -> None:
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        # a write with a backup but no approval row in the window (a ghost), then two recorded writes with a hand edit between
        write_recorded(project, "onboarding:ghost", lambda c: c["test_data"].update(accounts_by_role="changed by the ghost"), now(1), approved=False)
        write_recorded(project, "onboarding:w1", lambda c: c["environment"].update(health_path="/v2/info"), now(2))
        hand = config_of(project)
        hand["environment"]["user_key"] = "QA_SECOND_USER_EMAIL"
        project.config.write_text(json.dumps(hand, indent=2) + "\n", encoding="utf-8")
        write_recorded(project, "onboarding:w2", lambda c: c["environments"][0].update(safe_to_break=False), now(3))
        writes = C.recorded_writes(project.root, json.loads((task / "state" / C.SNAPSHOT_NAME).read_text())["taken_at"])
        check_eq("K5 two recorded writes are in the window, oldest first", [w["ref"] for w in writes], ["onboarding:w1", "onboarding:w2"])
        result = C.restore_config(project.root, task)
        check_eq("K5 the ghost's change (a backup with no approval row) is reverted", result["reverted"], ["/test_data/accounts_by_role"])
        check_eq("K5 both writes' pointers and the hand edit between them are kept",
                 sorted(result["kept"]), ["/environment/health_path", "/environment/user_key", "/environments"])
        cfg = config_of(project)
        check_eq("K5 the file holds them", (cfg["environment"]["health_path"], cfg["environment"]["user_key"], cfg["environments"][0]["safe_to_break"],
                                            cfg["test_data"]["accounts_by_role"].startswith("Default user")), ("/v2/info", "QA_SECOND_USER_EMAIL", False, True))
        check_in("K5 the line says who wrote what was kept", "3 kept (written by onboarding approval)", C.revert_line(result))
        # the window is the record's time: an approval dated before the story started is not in it
        late = Project()
        try:
            t = late.task()
            C.snapshot_config(late.root, t, True)
            write_recorded(late, "onboarding:early", lambda c: c["environment"].update(health_path="/early"), "2020-01-01T00:00:00+00:00")
            check_eq("K5 an approval dated before the start is not a recorded write of this story", C.restore_config(late.root, t)["kept"], [])
        finally:
            late.done()
    finally:
        project.done()


def k7_edges() -> None:
    # unchanged: nothing written, no line, no backup
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        result = C.restore_config(project.root, task)
        check_eq("K7 bytes equal the copy: unchanged, no line, no backup", (result["state"], C.revert_line(result), result["backup"]), ("unchanged", "", ""))
        check("K7 and no config-reverts folder", not (project.root / "qa-factory" / "state" / C.REVERTS_NAME).exists())
        project.config.write_bytes(DRIFTED)
        check_eq("K7 a second call on a finished story reverts nothing (the copy is marked)", C.restore_config(project.root, task)["state"], "already_restored")
        check_eq("K7 and the later edit stays", project.config.read_bytes(), DRIFTED)
    finally:
        project.done()
    # deleted in the window
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        project.config.unlink()
        result = C.restore_config(project.root, task)
        check_eq("K7 deleted in the window: the copy is put back", (result["state"], sha(project.config.read_bytes()), result["backup"]), ("reverted", sha(BEFORE), ""))
    finally:
        project.done()
    # broken JSON now: whole copy, backup of the broken bytes
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        project.config.write_bytes(b"{ broken")
        result = C.restore_config(project.root, task)
        check_eq("K7 broken JSON now: the copy whole, the broken bytes in the backup",
                 (result["state"], sha(project.config.read_bytes()), (project.root / result["backup"]).read_bytes()), ("reverted", sha(BEFORE), b"{ broken"))
        check_in("K7 and the line says why", "not valid JSON", C.revert_line(result))
    finally:
        project.done()
    # a damaged / unreadable copy: skipped, the file untouched
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        path = task / "state" / C.SNAPSHOT_NAME
        held = json.loads(path.read_text())
        project.config.write_bytes(DRIFTED)
        path.write_text(json.dumps(dict(held, bytes_b64=base64.b64encode(b"other").decode())), encoding="utf-8")
        result = C.restore_config(project.root, task)
        check_eq("K7 a damaged copy (checksum): skipped, the file untouched", (result["state"], project.config.read_bytes()), ("skipped", DRIFTED))
        path.write_text("{ not json", encoding="utf-8")
        check_eq("K7 an unreadable copy: skipped", C.restore_config(project.root, task)["state"], "skipped")
    finally:
        project.done()
    # an absent copy (no file at the start): a config that appeared is never deleted
    project = Project()
    try:
        project.config.unlink()
        task = project.task()
        snap = C.snapshot_config(project.root, task, True)
        check_eq("K7 no config at the start: the copy says absent", snap["state"], "kept")
        check_eq("K7 and still none at the end: unchanged", C.restore_config(project.root, task)["state"], "unchanged")
    finally:
        project.done()
    project = Project()
    try:
        project.config.unlink()
        task = project.task()
        C.snapshot_config(project.root, task, True)
        project.config.write_bytes(DRIFTED)
        result = C.restore_config(project.root, task)
        check_eq("K7 a config that appeared when there was none is never deleted", (result["state"], project.config.read_bytes()), ("skipped", DRIFTED))
    finally:
        project.done()
    # the pointer limit: 5 shown (AT), 6 -> '+1 more' (BEYOND)
    for count, tail in ((5, False), (6, True)):
        project = Project()
        try:
            base = json.loads(BEFORE)
            base["test_data"] = {f"k{i}": "a" for i in range(count)}
            project.config.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
            task = project.task()
            C.snapshot_config(project.root, task, True)
            base["test_data"] = {f"k{i}": "b" for i in range(count)}
            project.config.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
            line = C.revert_line(C.restore_config(project.root, task))
            check_eq(f"K7 {count} reverted pointers: the 'more' tail is {'there' if tail else 'absent'}", "+1 more" in line, tail)
            check_in(f"K7 {count} pointers: the first five are named", "/test_data/k4", line)
        finally:
            project.done()
    # a killed story: the next story's start names it
    project = Project()
    try:
        killed = project.task("TP1-KILLED")
        C.snapshot_config(project.root, killed, True)
        project.config.write_bytes(DRIFTED)
        snap = C.snapshot_config(project.root, project.task("TP1-NEXT"), True)
        check_in("K7 the next story's start says the killed story did not end", "differs from the copy TP1-KILLED kept at its start, and TP1-KILLED did not end",
                 snap["notes"])
    finally:
        project.done()


def k8_the_cli_and_the_phase_files() -> None:
    project = Project()
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project.root))
        out = run_script("story_step.py", "config-snapshot", "--task", "TP1-CLI", env=env)
        check_eq("K8 config-snapshot exits 0", out.returncode, 0)
        lines = [row for row in out.stdout.splitlines() if row.strip()]
        check_eq("K8 and prints one line, a JSON object with the state", (len(lines), json.loads(lines[0])["state"]), (1, "kept"))
        project.config.write_bytes(DRIFTED)
        out = run_script("story_step.py", "config-restore", "--task", "TP1-CLI", env=env)
        lines = [row for row in out.stdout.splitlines() if row.strip()]
        answer = json.loads(lines[0])
        check_eq("K8 config-restore: one line, reverted, with the report line and its backup", (len(lines), answer["state"], answer["backup"] in answer["line"]), (1, "reverted", True))
        check_eq("K8 and the file is the copy", sha(project.config.read_bytes()), sha(BEFORE))
        out = run_script("story_step.py", "config-restore", "--task", "TP1-CLI", env=env)
        again = json.loads(out.stdout.strip().splitlines()[0])
        check_eq("K8 a second config-restore: already_restored, no line", (again["state"], "line" in again), ("already_restored", False))
    finally:
        project.done()


def k9_one_atomic_writer() -> None:
    project = Project()
    try:
        C._write_config(project.root, config_of(project), dict(config_of(project), default_environment="local-docker"), "h1", "onboarding:x")
        left = [p.name for p in (project.root / "qa-factory").iterdir() if p.name.endswith(".tmp")]
        check_eq("K9 no temp file is left beside the config", left, [])
    finally:
        project.done()


def k10_the_driver_start_and_end() -> None:
    import story_run
    import story_step
    from story_run_common import driver_for
    project = Project()
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project.root), STORY_RUN_CLAUDE=str(project.root / "none.py"), STUB_CONTROL="", STUB_LOG="")
        driver = driver_for(project.root, env, "TP1-DRV")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            story_step.keep_config_copy(driver.project, driver.task_root, driver.task)
        copy = driver.task_root / "state" / C.SNAPSHOT_NAME
        check("K10 the story start keeps the copy", copy.is_file() and json.loads(copy.read_text())["sha256"] == sha(BEFORE))
        project.config.write_bytes(DRIFTED)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            story_step.give_back_config(driver.project, driver.task_root, driver.task)
        check_eq("K10 the story end gives the file back", sha(project.config.read_bytes()), sha(BEFORE))
        check_in("K10 and prints the report line with the backup path", "qa-factory/state/config-reverts/", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            story_step.give_back_config(driver.project, driver.task_root, driver.task)
        check_eq("K10 a second end says nothing", out.getvalue(), "")
        # the closed-story end: `_act_closed` with nothing held and no retro pending gives the file back, then stops
        again = Project()
        try:
            env2 = dict(env, CLAUDE_PROJECT_DIR=str(again.root))
            second = driver_for(again.root, env2, "TP1-DRV2")
            with contextlib.redirect_stdout(io.StringIO()):
                story_step.keep_config_copy(second.project, second.task_root, second.task)
            again.config.write_bytes(DRIFTED)
            rebuilds = []
            second.rebuild_report = lambda: rebuilds.append(1)      # F4: the report is rebuilt after a revert that has a line
            stopped, out = None, io.StringIO()
            for _round in (1, 2):
                try:
                    with contextlib.redirect_stdout(out):
                        second._act_closed({"action": "closed", "held": [], "closed_at": now()})
                except story_run.Stop as stop:
                    stopped = stop.code
                if _round == 1:
                    check_eq("K10 _act_closed on a finished story stops with EXIT_DONE", stopped, story_run.EXIT_DONE)
                    check_eq("K10 and gave the file back first", sha(again.config.read_bytes()), sha(BEFORE))
                    check_eq("K10 and rebuilt the report once, after the revert", rebuilds, [1])
            check_eq("K10 a second end of the same story rebuilds nothing (no line)", rebuilds, [1])
        finally:
            again.done()
    finally:
        project.done()


def k11_fix_round_t1546() -> None:
    """The fix round of t-1542: F1 (a skip is one-shot), F2 (never raises), F4 (the line reaches the report), F5, F7."""
    import shutil
    import story_step
    # F1: A ends while the abandoned C is un-closed -> skipped; C goes; the person edits the file; the next run of A reverts NOTHING
    project = Project()
    try:
        a, c = project.task("TP1-A"), project.task("TP1-C")
        C.snapshot_config(project.root, a, True)
        running_pipeline(c, "2020-01-01T00:00:00+00:00")
        project.config.write_bytes(DRIFTED)
        finished_pipeline(a, now(1))
        first = C.restore_config(project.root, a)
        check_eq("K11 F1 the first end: skipped, the file untouched", (first["state"], project.config.read_bytes()), ("skipped", DRIFTED))
        check_in("K11 F9 and the skip line names what to do (archive the other story)", "archive_task.py", first["why"])
        shutil.rmtree(c)
        later = config_of(project)
        later["persons_later_edit"] = True
        edited = (json.dumps(later, indent=2) + "\n").encode("utf-8")
        project.config.write_bytes(edited)
        second = C.restore_config(project.root, a)
        check_eq("K11 F1 a later run on the finished story reverts nothing: already_restored", second["state"], "already_restored")
        check_in("K11 F1 and says the file was not given back at the end", "was not given back when this story ended", second["why"])
        check_eq("K11 F1 the person's later edit is byte for byte there", project.config.read_bytes(), edited)
        check_in("K11 F4 the skip's line is kept in the story's copy", "not reverted", C.stored_revert_line(a))
    finally:
        project.done()
    # F1 (the other transient skip): a config that appeared when there was none is marked the same way
    project = Project()
    try:
        project.config.unlink()
        a = project.task("TP1-A")
        C.snapshot_config(project.root, a, True)
        project.config.write_bytes(DRIFTED)
        check_eq("K11 F1 appeared config: skipped", C.restore_config(project.root, a)["state"], "skipped")
        check_eq("K11 F1 and then already_restored", C.restore_config(project.root, a)["state"], "already_restored")
    finally:
        project.done()
    # F2: a sibling whose stages.S9 is not an object is a named skip, never an exception
    project = Project()
    try:
        a, b = project.task("TP1-A"), project.task("TP1-B")
        C.snapshot_config(project.root, a, True)
        project.config.write_bytes(DRIFTED)
        (b / "pipeline.json").write_text(json.dumps({"closed_at": "2020-01-01T00:00:00+00:00", "stages": {"S9": "done"}}), encoding="utf-8")
        result = C.restore_config(project.root, a)
        check_eq("K11 F2 stages.S9 not an object: skipped, naming the sibling", (result["state"], "TP1-B" in result["why"]), ("skipped", True))
        check_eq("K11 F2 and the file is untouched", project.config.read_bytes(), DRIFTED)
        real = story_step._take_config_copy
        story_step._take_config_copy = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                story_step.keep_config_copy(project.root, a, "TP1-A")
        finally:
            story_step._take_config_copy = real
        check_in("K11 F2 keep_config_copy catches any exception and says so", "no copy was kept (RuntimeError", out.getvalue())
    finally:
        project.done()
    # F4: the revert's line reaches the report's "Where to look" block, from the story's copy
    import report_facts
    project = Project()
    try:
        task = project.task()
        C.snapshot_config(project.root, task, True)
        check_eq("K11 F4 before the end there is no line", report_facts._where(task, {})["config_revert"], "")
        project.config.write_bytes(DRIFTED)
        line = C.revert_line(C.restore_config(project.root, task))
        where = report_facts._where(task, {})
        check_eq("K11 F4 the report reads the revert's line from the copy", where["config_revert"], line)
        check_in("K11 F4 and renders it under 'Where to look'", "- " + line, report_facts._r_where({"where": where, "unknown": {}}))
        check_eq("K11 F4 a second call changes nothing in the line", where["config_revert"], report_facts._where(task, {})["config_revert"])
    finally:
        project.done()
    # F5: a list is a leaf; a pointer the file no longer has is taken out
    check_eq("K11 F5 a changed list is one pointer", C._leaf_diff({"a": [1, 2], "b": 1}, {"a": [1, 3], "b": 1}), ["/a"])
    check_eq("K11 F5 a kept deletion is taken out of the copy",
             json.loads(C._merge_kept({"a": 1, "b": {"c": 2}}, {"a": 1}, {"/b/c": "x"})), {"a": 1, "b": {}})
    check_eq("K11 F5 a drop never creates the objects on the way", C._set_pointer({"a": 1}, "/x/y", None, drop=True), False)
    check_eq("K11 F5 _moment is contract._answer_moment (a naive time is UTC, junk is None)",
             (C._moment("2026-01-01T00:00:00"), C._moment("2026-01-01T00:00:00Z"), C._moment("junk")),
             (C._moment("2026-01-01T00:00:00+00:00"),) * 2 + (None,))


def k12_a_stand_fact_recorded_at_a_gate_outlives_the_story() -> None:
    """HF8-9 K-9.9: `project_decisions.py stand-account` writes through `resolve`, whose receipt carries `recorded_at` and `before`;
    `recorded_writes` reads them, so the revert keeps `/environments` (a list is one pointer) and names the writer. A receipt without
    those fields, or one dated before the window, keeps nothing; a hand edit made BEFORE the decision is still reverted."""
    import project_decisions as PD

    def two_stands(project: Project) -> None:
        spec = json.loads(BEFORE.decode("utf-8"))
        spec["environments"].append({"name": "second", "base_url": "http://localhost:9090", "credentials_by_role": {}, "safe_to_break": True})
        project.config.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        env_file = project.root / "testproject1_test_harness" / "env.fixture"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("AUTH_USERNAME=a\nAUTH_PASSWORD=b\nQA_SECOND_USER_EMAIL=c\nQA_SECOND_USER_PASSWORD=d\n", encoding="utf-8")

    def record(project: Project, role: str = "Second user") -> dict:
        return PD.record_stand_account(project.root, stand="second", role=role, user_key="QA_SECOND_USER_EMAIL",
                                       secret_key="QA_SECOND_USER_PASSWORD", words="the second user is a plain user")

    project = Project()
    try:
        two_stands(project)
        task = project.task()
        C.snapshot_config(project.root, task, True)
        hand = config_of(project)
        hand["environment"]["health_path"] = "/by-hand"
        project.config.write_text(json.dumps(hand, indent=2) + "\n", encoding="utf-8")      # a hand edit BEFORE the decision
        written = record(project)
        check_eq("K-9.9 the record is written", written["decision"], "DD-1")
        result = C.restore_config(project.root, task)
        check_eq("K-9.9 the revert keeps /environments (a list is one pointer) and names the writer",
                 (result["state"], result["kept"], result["kept_sources"]), ("reverted", ["/environments"], ["project decision"]))
        cfg = config_of(project)
        check_eq("K-9.9 the role is on the second stand", cfg["environments"][1]["credentials_by_role"],
                 {"Second user": "QA_SECOND_USER_EMAIL / QA_SECOND_USER_PASSWORD"})
        check_eq("K-9.9 the hand edit with no receipt is reverted as before (the earlier pin)", cfg["environment"]["health_path"], "/v1/info")
        check_in("K-9.9 the report line says who wrote what was kept", "1 kept (written by project decision)", C.revert_line(result))
    finally:
        project.done()
    # a decision made BEFORE the story started is not this story's write
    project = Project()
    try:
        two_stands(project)
        record(project)
        receipt = project.root / "qa-factory" / "state" / "decision-transactions" / "DD-1.json"
        held = json.loads(receipt.read_text(encoding="utf-8"))
        held["recorded_at"] = "2020-01-01T00:00:00+00:00"
        receipt.write_text(json.dumps(held), encoding="utf-8")
        task = project.task()
        C.snapshot_config(project.root, task, True)
        check_eq("K-9.9 a receipt dated before the window is no recorded write of this story", C.recorded_writes(project.root, now(-5)), [])
    finally:
        project.done()
    # a receipt of an older version (no `before`) or one still pending keeps nothing: the safe side
    project = Project()
    try:
        two_stands(project)
        task = project.task()
        C.snapshot_config(project.root, task, True)
        record(project)
        receipt = project.root / "qa-factory" / "state" / "decision-transactions" / "DD-1.json"
        held = json.loads(receipt.read_text(encoding="utf-8"))
        for label, change in (("no `before`", {"before": None}), ("not complete", {"status": "pending"}), ("no `recorded_at`", {"recorded_at": ""})):
            receipt.write_text(json.dumps(dict(held, **change)), encoding="utf-8")
            check_eq(f"K-9.9 a receipt with {label} is no recorded write", C.recorded_writes(project.root, now(-60)), [])
        receipt.write_text(json.dumps(held), encoding="utf-8")
        check_eq("K-9.9 and the whole one is", [w["source"] for w in C.recorded_writes(project.root, now(-60))], ["project decision"])
    finally:
        project.done()


def k13_the_address_of_the_ui_recorded_at_a_gate_outlives_the_story() -> None:
    """HF8-10 K-10.6: the same as K-9.9 for `stand-frontend`: the block form (one stand) keeps `/environment/frontend`, the entry form (two
    stands) keeps `/environments`, both under the writer's name; the address is read back by `frontend_of` after the revert."""
    import env_probe
    import project_decisions as PD
    words = "the UI is on FRONTEND_URL"

    def setup(project: Project, stands: int) -> None:
        spec = json.loads(BEFORE.decode("utf-8"))
        if stands == 2:
            spec["environments"].append({"name": "second", "base_url": "http://localhost:9090", "safe_to_break": True})
        project.config.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
        env_file = project.root / "testproject1_test_harness" / "env.fixture"
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text("AUTH_USERNAME=a\nFRONTEND_URL=http://localhost:5173\n", encoding="utf-8")

    def hand_edit(project: Project) -> None:        # an edit with no receipt: reverted, so the report names who wrote what stayed
        hand = config_of(project)
        hand["environment"]["health_path"] = "/by-hand"
        project.config.write_text(json.dumps(hand, indent=2) + "\n", encoding="utf-8")

    project = Project()
    try:
        setup(project, 1)
        task = project.task()
        C.snapshot_config(project.root, task, True)
        hand_edit(project)
        written = PD.record_stand_frontend(project.root, key="FRONTEND_URL", api_path="/api/v1/config", words=words)
        check_eq("K-10.6 the block record is written", written["decision"], "DD-1")
        result = C.restore_config(project.root, task)
        check_eq("K-10.6 the revert keeps /environment/frontend and names the writer",
                 (result["state"], result["kept"], result["kept_sources"]), ("reverted", ["/environment/frontend"], ["project decision"]))
        cfg = config_of(project)
        check_eq("K-10.6 the block is on the config after the revert", cfg["environment"]["frontend"],
                 {"url_key": "FRONTEND_URL", "api_path": "/api/v1/config"})
        check_eq("K-10.6 ... and `frontend_of` reads the address back",
                 env_probe.frontend_of(cfg, "", root=project.root)["url"], "http://localhost:5173")
    finally:
        project.done()
    project = Project()
    try:
        setup(project, 2)
        task = project.task()
        C.snapshot_config(project.root, task, True)
        hand_edit(project)
        PD.record_stand_frontend(project.root, url="http://localhost:5174", stand="second", words=words)
        result = C.restore_config(project.root, task)
        check_eq("K-10.6 the entry record: the revert keeps /environments under the writer's name",
                 (result["state"], result["kept"], result["kept_sources"]), ("reverted", ["/environments"], ["project decision"]))
        check_eq("K-10.6 ... and `frontend_of` reads the named stand's address back",
                 env_probe.frontend_of(config_of(project), "second", root=project.root)["url"], "http://localhost:5174")
    finally:
        project.done()


def main() -> None:
    for scenario in (k1_the_12586_drift_is_given_back, k1b_a_note_one_character_off_is_not_the_probes,
                     k2_nothing_recorded_gives_the_copy_back_byte_for_byte, k3_a_story_that_is_not_fresh_keeps_no_copy,
                     k4_another_story_in_flight_or_in_the_window, k5_recorded_writes_with_a_hand_edit_between, k7_edges,
                     k8_the_cli_and_the_phase_files, k9_one_atomic_writer, k10_the_driver_start_and_end, k11_fix_round_t1546,
                     k12_a_stand_fact_recorded_at_a_gate_outlives_the_story,
                     k13_the_address_of_the_ui_recorded_at_a_gate_outlives_the_story):
        scenario()
    finish("test_config_revert")


if __name__ == "__main__":
    main()
