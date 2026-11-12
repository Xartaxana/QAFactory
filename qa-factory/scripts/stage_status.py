"""ONE sentence for the person, built from receipts — never composed by the orchestrator.

The owner's rule of 21.09.2026: "the critic found something, it went to the author for repair
— why does the person have to read all of that? One sentence is enough: *Handed the critic's
findings to the author. Round 2 is the last one.*"

TP1-15045 is the run that earned it. The person was handed all eight of the code critic's
findings verbatim — every one of them addressed to the author, none of them a decision anybody
was asking the person to make — plus a paragraph about `git update-index --no-skip-worktree`
and an account of the author deleting duplicate helpers by hand. The four real questions of
that run (the toolchain, the non-owner account, the contradiction in TC-009's text, the status
of R-12) were asked correctly; everything else was noise around them.

So a message to the person is one of exactly two things: a QUESTION they decide, with options,
or ONE LINE of status. This module builds the second kind. A role's remarks to another role,
a guard's refusal the factory walks around itself and a state repair the factory performed are
files, not messages; the line points at the path only when the person might want to open it.

  stage_status.py --task TP1-15045 --event critic_returned
  stage_status.py --task TP1-15045 --event role_halt --fact role=qa-automator \
      --fact reason="the test toolchain is not installed" --fact need="install it, or say run without it"

Read-only. Every fact is read off disk (`pipeline.json`, the manifest, the controller's
dispatch receipts) or passed in by the caller; a fact that can be neither read nor was given
is left out of the sentence rather than guessed — a status line that invents a number is worse
than a shorter one.
"""
import argparse
import functools
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)

# One line on one screen. Longer than this and it stops being a status line and starts being
# the wall of text the rule exists to stop.
MAX_CHARS = 240
NOTHING = "Nothing is needed from you."
EVENTS = ("critic_returned", "author_repair", "role_halt", "window_done", "state_repaired")
# `repair_cycles` in runtime_policy.DEFAULT_LIMITS. Read from there when it is importable, so
# one number stays in one place; the literal is the fallback for a build that lacks it.
FALLBACK_ROUND_CAP = 2


# The package's one JSON reader. This module's direction: whatever goes wrong while reading is `default`, None unless passed.
_read_json = functools.partial(hooklib.read_json, errors=Exception)


def _clean(value, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip(" .,;:") if len(text) > limit else text.rstrip()


def _int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def round_cap(task_root: Path, role: str = "") -> int:
    """The number of repair rounds this factory allows before the rest is carried as debt."""
    try:
        from runtime_policy import DEFAULT_LIMITS
        key = "design_repair_cycles" if "case" in str(role) else "repair_cycles"
        return int(DEFAULT_LIMITS.get(key) or FALLBACK_ROUND_CAP)
    except Exception:
        return FALLBACK_ROUND_CAP


# A dispatch receipt that spends nobody's round: `superseded`/`stale` was replaced,
# `never_started` reached no agent, `released` was let go. controller.DISCOUNTED, repeated
# here so one status line costs no import of the controller.
DISCOUNTED = {"superseded", "stale", "never_started", "released"}


def _is_repair_round(dispatch: dict) -> bool:
    """A round is work sent BACK over the same window: the controller marks it
    `purpose: repair_verify`, or `rework_of` when the prior dispatch was already accepted.

    What it is not: the window's own first dispatch; a `parent_retry`, which "resumes the
    same work from its checkpoint and is not another round" (controller.repair_rounds); and
    the `s5_precheck` author repair, which s5.md runs deliberately without a critic round.
    Counting every dispatch told the person "Round 5 of 2 is the last one" on TP1-15045,
    a number the controller's own cap disagreed with."""
    if dispatch.get("parent_retry") or str(dispatch.get("status") or "") in DISCOUNTED:
        return False
    # Only a round about the test spends the cap (controller.repair_rounds): a mechanical fix,
    # a stand failure or a reviewer's own mistake is sent back too, and is nobody's round.
    if str(dispatch.get("repair_cause") or "test_defect") != "test_defect":
        return False
    return bool(dispatch.get("rework_of")) or str(dispatch.get("purpose") or "") == "repair_verify"


def rounds_spent(task_root: Path, stage: str = "", role: str = "") -> int | None:
    """Repair rounds already spent on this stage's window, counted from dispatch receipts.

    The controller counts them the same way and is the owner of the rule; this only reads its
    projection, and answers None when there is none to read (a story on an older build, a host
    that records no dispatches). None means the sentence simply carries no round number.

    Scoped to the CURRENT window the way `controller.budget_scope` is: S5 runs several
    windows of one stage and role on purpose, and window three is not round three."""
    state = _read_json(task_root / "state" / "controller.json")
    dispatches = (state or {}).get("dispatches")
    if not isinstance(dispatches, dict) or not dispatches:
        return None
    rows = [d for d in dispatches.values() if isinstance(d, dict)
            and (not stage or str(d.get("stage") or "") == stage)
            and (not role or str(d.get("role") or "") == role)]
    if not rows:
        return None
    if stage == "S5":
        # SC1-14 B1a (E33): the S5 PLAN dispatch has every case for its scope, which with one window is the window's own, so a
        # narrow rework of the plan was read as a round of the window. Records of the plan are not rows of a window; when the
        # role's LAST record is the plan, the question is about the plan and only plan records are counted. The kind is
        # `controller.s5_part_of`'s, imported here only for S5 (a status line of any other stage costs no controller import).
        from controller import s5_part_of
        want_plan = s5_part_of(rows[-1]) == "plan"
        rows = [d for d in rows if (s5_part_of(d) == "plan") == want_plan]
    window = sorted(str(case) for case in (rows[-1].get("scope") or []))
    same = [d for d in rows if sorted(str(c) for c in (d.get("scope") or [])) == window]
    return len([d for d in same if _is_repair_round(d)]) or None


def findings_count(task_root: Path, stage: str = "", dispatch: str = "") -> int | None:
    """How many findings the critic returned — from its own file, never from its prose.

    The review receipt the manifest names is the machine-readable form; a markdown findings
    file is the fallback, counted by its numbered items. The file is the returning critic's own, read through
    `findings_path` (t-2106 X3, AR-13): S4 the case critic's files, any other stage the file of `dispatch` (else the old
    single file of a one-window story) - never "the first findings file under work/", which at S5 was the S4 file."""
    manifest = _read_json(task_root / "work" / "automation-manifest.json", {}) or {}
    ref = str(manifest.get("review_receipt_ref") or "").strip()
    if ref:
        receipt = _read_json(task_root / ref)
        for key in ("findings", "rejected", "unresolved"):
            rows = (receipt or {}).get(key)
            if isinstance(rows, list) and rows:
                return len(rows)
    import findings_path
    if stage == "S4":
        files = findings_path.s4_files(task_root)
    else:
        own = findings_path.resolve(task_root, dispatch)
        files = [task_root / own] if own else []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        items = re.findall(r"^\s*\d+\.\s+\S", text, re.MULTILINE)
        if items:
            return len(items)
    return None


# S7 hands the automator failing tests, not review findings. `qa-automator is repairing 8
# findings` at S7 would be the code critic's S5 count read off the review receipt — a number
# from another stage, which is exactly the "status line that invents a number" this module
# refuses. At S7 the count comes from triage.json, or the sentence carries none.
REPAIRABLE_VERDICTS = ("TEST_BUG", "TEST_BUG:collection", "FLAKY")


def repairs_count(task_root: Path) -> int | None:
    """How many failures the triage hands back to the automator — from `triage.json` itself."""
    rows = (_read_json(task_root / "triage.json") or {}).get("triage")
    if not isinstance(rows, list):
        return None
    return len([r for r in rows if isinstance(r, dict)
                and str(r.get("verdict") or "").strip() in REPAIRABLE_VERDICTS]) or None


# The manifest's own reason for "the test asserts the approved case's Then and the
# implementation does something else" (contract.UNRESOLVED_REASONS). After gate A the approved
# case is the oracle, so that red is the factory's PRODUCT: S7 decides what it is (a bug draft is one outcome).
RED_ON_PURPOSE = "contradicts_requirement"


def reds_on_purpose(task_root: Path) -> int:
    """How many tests are red on purpose — counted from `unresolved[]`, never from prose."""
    rows = (_read_json(task_root / "work" / "automation-manifest.json", {}) or {}).get("unresolved")
    if not isinstance(rows, list):
        return 0
    return len([r for r in rows if isinstance(r, dict)
                and str(r.get("reason") or "").strip() == RED_ON_PURPOSE])


def red_on_purpose_phrase(count: int) -> str:
    """The words the person hears about those tests.

    Never "unresolved" and never "concerns": on TP1-15045 two of these were reported as
    designer conflicts and the story stood still on findings that were its own deliverable."""
    if not count:
        return ""
    return (f" {count} test{'s' if count != 1 else ''} red on purpose — the implementation "
            "differs from the approved cases; S7 decides what each one is.")


def _cap_sentence(text: str) -> str:
    """One line, within the cap, and still ending in a full stop."""
    line = " ".join(str(text).split())
    if len(line) <= MAX_CHARS:
        return line
    cut = line[:MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(" .,;:")
    return cut + "."


def line(task_root, event: str, **facts) -> str:
    """The sentence. `facts` always win over what is on disk: the caller saw the event."""
    task_root = Path(task_root)
    event = str(event or "").strip()
    if event not in EVENTS:
        raise ValueError("event must be one of: " + ", ".join(EVENTS))
    role = _clean(facts.get("role") or "", 40)
    stage = _clean(facts.get("stage") or "", 8)
    if facts.get("findings") is not None:
        count = _int(facts.get("findings"))
    elif stage == "S7":
        count = repairs_count(task_root)
    else:
        count = findings_count(task_root, stage, _clean(facts.get("dispatch") or "", 80))
    spent = _int(facts.get("round")) if facts.get("round") is not None \
        else rounds_spent(task_root, stage, role or "qa-automator")
    cap = _int(facts.get("cap")) or round_cap(task_root, role)

    def round_phrase() -> str:
        if not spent:
            return ""
        if spent >= cap:
            return f" Round {spent} of {cap} is the last one."
        return f" Round {spent} of {cap}."

    if event == "critic_returned":
        what = f"the critic's {count} findings" if count else "the critic's findings"
        return _cap_sentence(f"Handed {what} to the author.{round_phrase()} {NOTHING}")

    if event == "author_repair":
        if stage == "S7":
            what = f"{count} failing test" + ("s" if count != 1 else "") if count else "the failing tests"
        else:
            what = f"{count} findings" if count else "the review findings"
        who = role or "the author"
        return _cap_sentence(f"{who} is repairing {what}.{round_phrase()} {NOTHING}")

    if event == "role_halt":
        who = role or "a role"
        where = f" at {stage}" if stage else ""
        reason = _clean(facts.get("reason") or "", 100)
        need = _clean(facts.get("need") or "", 100)
        head = f"{who} stopped{where}" + (f": {reason}." if reason else ".")
        # The one event that may need the person — and then it says exactly what, once.
        tail = f" I need one thing from you: {need}." if need else f" {NOTHING} I am clearing it."
        return _cap_sentence(head + tail)

    if event == "window_done":
        done, left = _int(facts.get("done")), _int(facts.get("left"))
        where = stage or "the stage"
        progress = (f": {done} of {done + left} cases done" if done is not None and left is not None
                    else f": {done} cases done" if done is not None else "")
        reds = _int(facts.get("reds")) if facts.get("reds") is not None else reds_on_purpose(task_root)
        tail = (" Continuing in a new window." if left else " The stage is finished.")
        return _cap_sentence(f"The {where} window closed{progress}."
                             + red_on_purpose_phrase(reds or 0) + f"{tail} {NOTHING}")

    # state_repaired — a repair the factory performed on its own state. It is reported so the
    # person is never surprised by a changed file, and never as something they must act on.
    what = _clean(facts.get("what") or "its own story state", 100)
    how = _clean(facts.get("how") or "", 80)
    return _cap_sentence(f"Repaired {what}" + (f" ({how})" if how else "")
                         + f"; no work was lost. {NOTHING}")


def selftest() -> int:
    import tempfile
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    with tempfile.TemporaryDirectory(prefix="qa-stage-status-") as td:
        root = Path(td)
        text = line(root, "critic_returned", findings=8, round=2, cap=2)
        case("the critic's findings are counted, not quoted", "8 findings" in text, True)
        case("the last round is named as the last", "Round 2 of 2 is the last one." in text, True)
        case("and the person is told they are not needed", text.endswith(NOTHING), True)
        case("it is one line", "\n" in text, False)
        case("a halt names what is wanted",
             "I need one thing from you: install it" in
             line(root, "role_halt", role="qa-automator", stage="S5",
                  reason="the test toolchain is not installed",
                  need="install it, or say run without it"), True)
        long_line = line(root, "role_halt", role="qa-automator", stage="S5",
                         reason="x" * 400, need="y" * 400)
        case("even a long reason stays one short line", len(long_line) <= MAX_CHARS, True)
        case("a window that ends the stage says so",
             "The stage is finished." in line(root, "window_done", stage="S5", done=14, left=0), True)

        # A test left red on purpose is the factory's product, not an open item: the sentence
        # says so in those words, and never as "unresolved" or "concerns".
        (root / "work").mkdir(parents=True, exist_ok=True)
        (root / "work" / "automation-manifest.json").write_text(json.dumps({"unresolved": [
            {"case": "TC-009", "reason": RED_ON_PURPOSE, "requirement": "R-13"},
            {"case": "TC-014", "reason": RED_ON_PURPOSE, "requirement": "R-12"},
            {"case": "TC-012", "reason": "blocked_by_env"}]}), encoding="utf-8")
        case("the reds on purpose are counted from the manifest", reds_on_purpose(root), 2)
        red = line(root, "window_done", stage="S5", done=12, left=2)
        case("and the person hears what they are",
             "2 tests red on purpose — the implementation differs from the approved cases; "
             "S7 decides what each one is." in red, True)
        case("and no bug draft is promised", "bug draft" in red, False)
        case("never as unresolved", "unresolved" in red, False)
        case("never as a concern", "concern" in red, False)
        case("and the line is still one short line", len(red) <= MAX_CHARS and "\n" not in red, True)
        case("one such test reads as one test",
             "1 test red on purpose" in line(root, "window_done", stage="S5", reds=1), True)
        (root / "work" / "automation-manifest.json").unlink()
        case("a state repair is reported, never asked about",
             line(root, "state_repaired", what="the dispatch left open by a crashed window")
             .endswith(NOTHING), True)
        try:
            line(root, "everything_is_fine")
            case("an unknown event is refused", False, True)
        except ValueError:
            case("an unknown event is refused", True, True)

        # The round number is the critic's rounds, not every dispatch of the window: the
        # first one, a resumed one and the s5_precheck author repair are not rounds.
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "state" / "controller.json").write_text(json.dumps({"dispatches": {
            "S5-qa-automator-1": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                  "status": "never_started"},
            "S5-qa-automator-2": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                  "status": "superseded"},
            "S5-qa-automator-3": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                  "status": "accepted", "parent_retry": "S5-qa-automator-2"},
            "S5-qa-automator-4": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                  "status": "accepted", "purpose": "repair_verify"},
        }}), encoding="utf-8")
        case("one critic round is one round", rounds_spent(root, "S5", "qa-automator"), 1)
        case("and the sentence stops promising a round past the cap",
             "Round 1 of 2." in line(root, "critic_returned", stage="S5", findings=3), True)
        (root / "state" / "controller.json").write_text(json.dumps({"dispatches": {
            "S5-qa-automator-1": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"],
                                  "status": "accepted"},
            "S5-qa-automator-2": {"stage": "S5", "role": "qa-automator", "scope": ["TC-9"],
                                  "status": "accepted"},
        }}), encoding="utf-8")
        case("a second window is not a second round",
             rounds_spent(root, "S5", "qa-automator"), None)

        # S7 repairs test defects, not review findings, and its rounds are counted the same way.
        (root / "state" / "controller.json").write_text(json.dumps({"dispatches": {
            "S7-qa-automator-1": {"stage": "S7", "role": "qa-automator", "scope": ["TC-4"],
                                  "status": "accepted"},
            "S7-qa-automator-2": {"stage": "S7", "role": "qa-automator", "scope": ["TC-4"],
                                  "status": "accepted", "purpose": "repair_verify",
                                  "rework_of": "S7-qa-automator-1"},
        }}), encoding="utf-8")
        (root / "triage.json").write_text(json.dumps({"triage": [
            {"test": "t1", "verdict": "TEST_BUG"}, {"test": "t2", "verdict": "FLAKY"},
            {"test": "t3", "verdict": "APP_BUG"}]}), encoding="utf-8")
        s7 = line(root, "author_repair", stage="S7")
        case("an S7 repair counts the tests handed back, not the critic's findings",
             "2 failing tests" in s7, True)
        case("and it carries the S7 round", "Round 1 of 2." in s7, True)
        case("one test reads as one test",
             "1 failing test." in line(root, "author_repair", stage="S7", findings=1), True)
        (root / "triage.json").write_text(json.dumps({"triage": [
            {"test": "t3", "verdict": "APP_BUG"}]}), encoding="utf-8")
        case("nothing repairable means no invented number",
             "the failing tests" in line(root, "author_repair", stage="S7"), True)
        case("an S7 halt still names the stage",
             "stopped at S7" in line(root, "role_halt", stage="S7", role="qa-automator",
                                     reason="the fixture is gone"), True)
    if failures:
        print("STAGE_STATUS SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("STAGE_STATUS SELFTEST: no violations (one line, counted not quoted, cap, need)")
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--task", default=None)
    ap.add_argument("--task-root", dest="task_root", default=None)
    ap.add_argument("--event", default="", choices=("",) + EVENTS)
    ap.add_argument("--fact", action="append", default=[], metavar="k=v",
                    help="a fact the caller already knows (role, stage, findings, round, cap, "
                         "reason, need, done, left, reds, what, how)")
    ap.add_argument("--selftest", action="store_true")
    args = hooklib.exact_options(ap).parse_args()
    if args.selftest:
        return selftest()
    if args.task is None and args.task_root is None:
        print("stage_status.py: --task or --task-root is required", file=sys.stderr)
        return 2
    # The story first (CX1-18): one existing folder named by the pair, or a refusal (exit 2) - never a line about a phantom.
    task_root = hooklib.story_cli("stage_status.py", key=args.task, root=args.task_root)
    if not args.event:
        print("stage_status.py: --event is required", file=sys.stderr)
        return 2
    facts = {}
    for item in args.fact:
        key, _, value = str(item).partition("=")
        if key.strip():
            facts[key.strip()] = value
    print(line(task_root, args.event, **facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
