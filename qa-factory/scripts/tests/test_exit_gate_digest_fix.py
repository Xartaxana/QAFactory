#!/usr/bin/env python3
"""SC1-14 part B3: the exit gate files every digest it passed, mends the form defects code can mend, and
`story_step finish --digest -` reads the file.

The shapes are those of project run 14857 (21 of 26 gate blocks were the digest form): prose before the header, a
missing path, a reason of 81+ characters, an absolute path. The direction of error is "not mended": whatever code
cannot mend keeps today's single refusal, and a digest nobody can file under ITS dispatch (none or two live) is
neither mended nor filed.
"""
import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import exit_gate as gate  # noqa: E402
import story_step  # noqa: E402

TICKET = "QA-D1"
LIVE = "S5-qa-automator-1"
GOOD = "\n".join(["qa-automator S5 window 1 · ok",
                  "TC-001#1 · green · fresh witness",
                  "TC-014#1 · red · asserts the Then",
                  "work/automation-manifest.json"])
SCOPE = ["TC-001", "TC-014"]


def _record(ident: str, status: str = "running", **extra) -> dict:
    return {"id": ident, "stage": "S5", "role": "qa-automator", "status": status, "scope": SCOPE, **extra}


class Env:
    """A throwaway story with a controller.json holding `dispatches`; the gate reads artifacts from it."""

    def __init__(self, dispatches: dict, manifest: bool = True):
        self.root = temp_project("qa-digest-fix-")
        use_project(self.root)
        self.task = self.root / "qa-factory" / "artifacts" / TICKET
        (self.task / "state").mkdir(parents=True)
        (self.task / "work").mkdir(parents=True)
        (self.task / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
        if manifest:
            (self.task / "work" / "automation-manifest.json").write_text("{}", encoding="utf-8")
        self.saved = gate.artifact_root
        gate.artifact_root = lambda: self.root / "qa-factory" / "artifacts"

    def filed(self, name: str = LIVE) -> str | None:
        path = self.task / "work" / "digests" / f"{name}.txt"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def listing(self) -> list:
        folder = self.task / "work" / "digests"
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def close(self) -> None:
        gate.artifact_root = self.saved
        cleanup(self.root)


def one_digest_errors(env: Env, digest: str) -> tuple:
    """(errors, what the gate said on stderr)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        errors = gate.digest_errors("qa-automator", TICKET, digest)
    return errors, err.getvalue()


def every_passed_digest_is_filed() -> None:
    env = Env({LIVE: _record(LIVE), "S5-qa-automator-0": _record("S5-qa-automator-0", "completed")})
    try:
        errors, said = one_digest_errors(env, GOOD)
        check_eq("a digest in the form is no error", errors, [])
        check_eq("every passed digest is written: the file is the digest, under the live dispatch's id", env.filed(), GOOD)
        check_eq("and only that file (the finished dispatch has none)", env.listing(), [LIVE + ".txt"])
        check_eq("and nothing is said", said, "")
        errors, _ = one_digest_errors(env, "qa-automator S5 window 1 · halt\nwork/automation-manifest.json")
        check_eq("a halt in the form is passed and filed too", (errors, env.filed().splitlines()[0]),
                 ([], "qa-automator S5 window 1 · halt"))
    finally:
        env.close()


def a_mended_digest_is_filed_with_the_original_beside_it() -> None:
    env = Env({LIVE: _record(LIVE)})
    try:
        original = "Finished the window, all green.\n\n" + GOOD.replace("fresh witness", "w" * 81)
        errors, said = one_digest_errors(env, original)
        check_eq("prose before the header and a reason of 81: no error (mended)", errors, [])
        mended = env.filed()
        check("the file is the mended text, in the form", mended is not None and gate.RD.check(mended, SCOPE) == [])
        check_eq("its header and ids are the original's", [l.split(" · ")[0] for l in mended.splitlines()],
                 ["qa-automator S5 window 1", "TC-001#1", "TC-014#1", "work/automation-manifest.json"])
        check_eq("the role's own text is kept as <id>.original.txt",
                 (env.task / "work" / "digests" / f"{LIVE}.original.txt").read_text(encoding="utf-8"), original)
        # path from the witness, absolute path under the root
        env2_digest = "\n".join(GOOD.splitlines()[:-1])
        errors, _ = one_digest_errors(env, env2_digest)
        check_eq("a missing path is the stage's witness artifact (it exists): mended", errors, [])
        check_eq("and the file ends with it", env.filed().splitlines()[-1], "work/automation-manifest.json")
        absolute = "\n".join(GOOD.splitlines()[:-1] + [str(env.task / "work" / "automation-manifest.json")])
        errors, _ = one_digest_errors(env, absolute)
        check_eq("an absolute path under the task root is mended", errors, [])
        check_eq("to the task-relative one", env.filed().splitlines()[-1], "work/automation-manifest.json")
    finally:
        env.close()


def the_unmendable_keeps_todays_single_refusal_and_no_file() -> None:
    env = Env({LIVE: _record(LIVE)})
    try:
        cases = {
            "a halt under prose": "I could not finish.\nqa-automator S5 window 1 · halt\nthe stand is down",
            "two headers": "x\n" + GOOD + "\n" + GOOD.splitlines()[0],
            "a row missing for a scoped id": "\n".join([GOOD.splitlines()[0], GOOD.splitlines()[1], GOOD.splitlines()[3]]),
            "a path outside the root": "\n".join(GOOD.splitlines()[:-1] + ["C:\\other\\x.md"]),
            "pure prose": "All done, everything works, here is the long story.\nIt took a while.",
        }
        for label, digest in cases.items():
            errors, _ = one_digest_errors(env, digest)
            check_eq(f"{label}: exactly one refusal carrying the form", (len(errors), "<state>" in errors[0] if errors else None),
                     (1, True))
            check_eq(f"{label}: no file is written", env.listing(), [])
        no_witness = Env({LIVE: _record(LIVE)}, manifest=False)
        try:
            errors, _ = one_digest_errors(no_witness, "\n".join(GOOD.splitlines()[:-1]))
            check_eq("a missing path whose witness file does not exist stays a refusal, no file",
                     (len(errors), no_witness.listing()), (1, []))
        finally:
            no_witness.close()
    finally:
        env.close()


def a_later_refused_stop_leaves_no_earlier_digest() -> None:
    """SC1-14 fix X, F-4. KILLS: drop `_unfile_digest` (stop 2's refusal leaves stop 1's file, which `finish --digest -` would read);
    drop the leftover `.original.txt` removal in `_write_digest`. Killing file: this one."""
    env = Env({LIVE: _record(LIVE)})
    try:
        aside = env.task / "work" / "digests" / f"{LIVE}.original.txt"
        mended_text = "Finished.\n\n" + GOOD
        one_digest_errors(env, mended_text)
        check_eq("F-4 setup: stop 1 (mended) filed the digest and the original", (env.filed() is not None, aside.is_file()), (True, True))
        errors, _ = one_digest_errors(env, GOOD)
        check_eq("F-4: a later clean stop files its own text and removes the leftover original", (errors, env.filed(), aside.is_file()),
                 ([], GOOD, False))
        errors, _ = one_digest_errors(env, "All done, everything works, here is the long story.")
        check_eq("F-4: stop 2 is refused", len(errors), 1)
        check_eq("F-4: ... and stop 1's digest is not left for `finish --digest -`", env.listing(), [])
        one_digest_errors(env, mended_text)
        one_digest_errors(env, "I could not finish.\nqa-automator S5 window 1 · halt\nthe stand is down")
        check_eq("F-4: a refused stop removes the original beside it as well", env.listing(), [])
    finally:
        env.close()
    two = Env({LIVE: _record(LIVE), "S5-qa-automator-2": _record("S5-qa-automator-2")})
    try:
        digests = two.task / "work" / "digests"
        digests.mkdir()
        (digests / f"{LIVE}.txt").write_text("someone's", encoding="utf-8")
        one_digest_errors(two, "All done, everything works, here is the long story.")
        check_eq("F-4 (edge): with two live dispatches nobody can say whose file it is, so nothing is removed", two.listing(), [LIVE + ".txt"])
    finally:
        two.close()


def the_boundary_of_the_reason_cap() -> None:
    env = Env({LIVE: _record(LIVE)})
    try:
        errors, _ = one_digest_errors(env, GOOD.replace("fresh witness", "r" * 80))
        check_eq("a reason of exactly 80 passes as it is", (errors, "r" * 80 in env.filed()), ([], True))
        check_eq("and is filed untouched, no .original", env.listing(), [LIVE + ".txt"])
        errors, _ = one_digest_errors(env, GOOD.replace("fresh witness", "r" * 81))
        check_eq("81 is cut (79 + the ellipsis) and passes", errors, [])
        check_in("the filed row carries the cut reason", "r" * 79 + "…", env.filed())
    finally:
        env.close()


def a_digest_nobody_can_file_under_its_dispatch_is_not_filed() -> None:
    """E36: two live dispatches of the role, or none: no file, no mending, the verdict is today's, the note is on stderr."""
    prose_digest = "Done.\n" + GOOD
    for label, dispatches in (
            ("two live dispatches", {LIVE: _record(LIVE), "S5-qa-automator-2": _record("S5-qa-automator-2")}),
            ("no live dispatch", {"S5-qa-automator-0": _record("S5-qa-automator-0", "completed")})):
        env = Env(dispatches)
        try:
            errors, said = one_digest_errors(env, GOOD)
            check_eq(f"{label}: a digest in the form still passes (as before)", errors, [])
            check_eq(f"{label}: no file is written (a digest of one dispatch never lies under another's name)",
                     env.listing(), [])
            check_in(f"{label}: the gate says so on stderr", "not filed", said)
            errors, said = one_digest_errors(env, prose_digest)
            check_eq(f"{label}: a mendable digest is not mended - today's one refusal", len(errors), 1)
            check_eq(f"{label}: and no file", env.listing(), [])
        finally:
            env.close()
    env = Env({LIVE: _record(LIVE)})
    try:
        check_eq("the one live dispatch is the one `dispatch_scope` reads",
                 (gate._live_dispatch("qa-automator", TICKET)["id"], gate.dispatch_scope("qa-automator", TICKET)),
                 (LIVE, SCOPE))
        check_eq("a foreign role has no live dispatch of this stage", gate._live_dispatch("qa-runner", TICKET), None)
    finally:
        env.close()


def edges_that_write_nothing() -> None:
    env = Env({LIVE: _record(LIVE)})
    try:
        check_eq("an empty digest (a host without a transcript): no error", one_digest_errors(env, "")[0], [])
        check_eq("and no file", env.listing(), [])
        check_eq("a foreign agent owes the gate nothing and gets no file",
                 (gate.digest_errors("some-other-agent", TICKET, "prose"), env.listing()), ([], []))
    finally:
        env.close()
    bad = "../../escape"
    env = Env({bad: _record(bad)})
    try:
        errors, said = one_digest_errors(env, GOOD)
        check_eq("an id that is not a plain file name is not a path: passes, no file anywhere",
                 (errors, env.listing(), (env.task / "escape.txt").exists(), (env.root / "escape.txt").exists()),
                 ([], [], False, False))
        check_in("and says why", "not filed", said)
    finally:
        env.close()


def a_plan_dispatch_gets_no_guessed_witness_path() -> None:
    plan = _record("S5-qa-automator-3", request_binding={"purpose": "s5_plan"})
    env = Env({"S5-qa-automator-3": plan})
    try:
        errors, _ = one_digest_errors(env, "\n".join(GOOD.splitlines()[:-1]))
        check_eq("a plan dispatch's missing path is NOT the windows' manifest (the file exists, the plan is not it)",
                 (len(errors), env.listing()), (1, []))
    finally:
        env.close()


def a_word_outside_the_list_is_advice_in_the_file() -> None:
    """X2-3: no judge reads the digest any more; a row state outside the form's list is advice for the stage critic."""
    env = Env({LIVE: _record(LIVE)})
    try:
        check("the judge-mapping function is gone", not hasattr(gate, "_judged_digest_errors"))
        errors, _ = one_digest_errors(env, "talk\n" + GOOD)
        check_eq("a mendable digest is mended as before (no error, filed)", (errors, env.filed() == GOOD), ([], True))
        errors, _ = one_digest_errors(env, GOOD.replace("· green ·", "· rejected-ish ·"))
        check_eq("a state outside the list is not a refusal", errors, [])
        advice = gate._STASH.get(("qa-automator", TICKET, "digest"))
        check_eq("... it is advice waiting for the file, naming the word", (len(advice) > 0, any("rejected-ish" in a for a in advice)),
                 (True, True))
    finally:
        env.close()


def finish_reads_the_filed_digest() -> None:
    """`story_step finish --digest -`: the filed text, or a refusal that names the door; a given digest is as before."""
    env = Env({LIVE: _record(LIVE)})
    seen = []

    class Stand:
        def __init__(self, _root, wait_seconds=0.0):
            pass

        def state(self):
            return {"dispatches": {LIVE: _record(LIVE)}}

    names = ("Controller", "_task_root", "_open_window_refusal")
    saved = {name: getattr(story_step, name) for name in names}
    story_step.Controller = Stand
    story_step._task_root = lambda _task: env.task
    story_step._open_window_refusal = lambda args, *_a: seen.append(args.digest) or "STOP-HERE"

    def run(digest: str, dispatch: str = LIVE) -> tuple:
        args = argparse.Namespace(task=TICKET, dispatch_id=dispatch, digest=digest, output=None, not_complete=False,
                                  complete=False, ignore_handoff=False, window=None, unresolved=None, reason=None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = story_step.finish(args)
        return code, out.getvalue()

    try:
        code, out = run("-")
        check_eq("no file: refused", code, 2)
        check_in("with the door", 'pass the role\'s digest line: --digest "<', out)
        check_in("naming the dispatch", LIVE, out)
        check_eq("and nothing went past the refusal", seen, [])
        (env.task / "work" / "digests").mkdir(parents=True)
        (env.task / "work" / "digests" / f"{LIVE}.txt").write_text(GOOD + "\n", encoding="utf-8")
        code, out = run("-")
        check_eq("a filed digest is the digest `finish` goes on with", (code, seen), (2, [GOOD]))
        check_in("(the stand-in refusal after it)", "STOP-HERE", out)
        seen.clear()
        run("qa-automator S5 window 1 · ok\nTC-001#1 · green · x\nwork/a.json")
        check_eq("a given digest is used as it is", seen, ["qa-automator S5 window 1 · ok\nTC-001#1 · green · x\nwork/a.json"])
        (env.task / "work" / "digests" / f"{LIVE}.txt").write_text("  \n", encoding="utf-8")
        seen.clear()
        check_eq("an empty file is no digest", (run("-")[0], seen), (2, []))
        check_eq("one dispatch's digest is never read for another's id",
                 (story_step._digest_of(env.task, "S5-qa-automator-9"), story_step._digest_of(env.task, "../x")), ("", ""))
    finally:
        for name, value in saved.items():
            setattr(story_step, name, value)
        env.close()


def main() -> None:
    every_passed_digest_is_filed()
    a_mended_digest_is_filed_with_the_original_beside_it()
    the_unmendable_keeps_todays_single_refusal_and_no_file()
    a_later_refused_stop_leaves_no_earlier_digest()
    the_boundary_of_the_reason_cap()
    a_digest_nobody_can_file_under_its_dispatch_is_not_filed()
    edges_that_write_nothing()
    a_plan_dispatch_gets_no_guessed_witness_path()
    a_word_outside_the_list_is_advice_in_the_file()
    finish_reads_the_filed_digest()
    finish("test_exit_gate_digest_fix")


if __name__ == "__main__":
    main()
