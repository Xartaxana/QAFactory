#!/usr/bin/env python3
"""X2-5 (t-1765, E-B11): a stage with an acceptor (`acceptance_by`) does not close without an `accept` record for its author's last dispatch.

The gate sits in `controller.validate` (accept branch, after the S3 completion gate). `acceptance_by` is data of `stages.json` that B4 sets;
until then the shipped table has none, so the two worlds are tested: the REAL table (no stage has the key: nothing new is refused) and a
table patched to give S2 an acceptor. The writer (`stage_done.py --acceptance`) is driven end to end into the gate.
"""
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance as A  # noqa: E402
import contract  # noqa: E402
import hooklib  # noqa: E402
import stage_done  # noqa: E402
import waiver  # noqa: E402
from controller import Controller  # noqa: E402
from event_store import StateConflict  # noqa: E402

import test_controller_state as BASE  # noqa: E402  (accept_stage fixture)

AUTHOR, CRITIC = "qa-requirements-tester", "qa-case-critic"
S2_DEF = {"id": "S2", "roles": [AUTHOR, CRITIC], "acceptance_by": CRITIC}
FORM = ("inputs_read:\n  - path: work/handoffs/{reviewed}.yaml\n    version: abc\n"
        "header:\n  role: qa-case-critic\n  stage: S2\n  window_or_scope: S2\n  verdict: {word}\n"
        "stage_acceptance:\n  failure_class: {failure}\n  quote: \"work/requirements-register.md#R-7 is silent on the limit\"\n"
        "  witness_paths: [work/requirements-register.md]\n")


class Patched:
    """The world after B4: S2 has the critic as its last role and `acceptance_by`; every other stage is as shipped."""

    def __init__(self, defs=None):
        self.defs = defs or {"S2": S2_DEF}

    def __enter__(self):
        self.stage_def, self.roles = A.stage_def_of, contract.stage_roles
        real_def, real_roles, defs = self.stage_def, self.roles, self.defs
        A.stage_def_of = lambda stage, table=None: dict(defs[stage]) if stage in defs else real_def(stage, table)
        contract.stage_roles = lambda stage: list(defs[stage]["roles"]) if stage in defs else real_roles(stage)

    def __exit__(self, *exc):
        A.stage_def_of, contract.stage_roles = self.stage_def, self.roles


def story():
    root = temp_project()
    task = root / "qa-factory" / "artifacts" / "QA-1"
    task.mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}), encoding="utf-8")
    c = Controller(task)
    c.apply("initialize", {"scope": ["TC-1"], "source_revision": "src", "known_paths": {"root": str(task)}, "idempotency_key": "init"})
    for stage in ("S0", "S1"):
        BASE.accept_stage(c, task, stage)
    return root, task, c


def dispatch(c, task, did, role, stage="S2"):
    c.apply("dispatch", {"id": did, "stage": stage, "role": role, "scope": ["TC-1"], "input_hash": did, "budget": {},
                         "known_paths": {}, "idempotency_key": "d-" + did})
    path = task / (did + ".txt")
    path.write_text(did, encoding="utf-8")
    return {"id": did, "status": "accepted", "evidence_refs": [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
            "idempotency_key": "a-" + did}


def accept(c, receipt, complete):
    return c.apply("accept", dict(receipt, stage_complete=complete))


def refused(c, receipt, complete=True):
    try:
        accept(c, receipt, complete)
    except StateConflict as exc:
        return str(exc)
    return ""


def write_pipeline(task, **keys):
    path = task / "pipeline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(keys)
    path.write_text(json.dumps(data), encoding="utf-8")


def record(dispatch_id, verdict="accept", **over):
    base = {"stage": "S2", "role": AUTHOR, "acceptor": CRITIC, "reviewed_dispatch": dispatch_id, "verdict": verdict,
            "failure_class": None if verdict == "accept" else "spec", "quote": "R-7", "witness_paths": [], "at": "2026-11-04T10:00:00"}
    return dict(base, **over)


def quiet(call, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = call(*args, **kwargs)
    return code, out.getvalue() + err.getvalue()


def run() -> None:
    old = hooklib._PROJECT_ROOT_CACHE
    # --- the world BEFORE B4: the shipped table gives no stage an acceptor -> nothing new is refused (E-X2-T5), and nothing is switched on
    check_eq("the shipped stages.json gives S2, S3 and S4 the critic as acceptor, S6 and S7 their consumers (X7-6, X7-6b), and no other stage one",
             [bool(A.stage_def_of(s).get("acceptance_by")) for s in ("S2", "S3", "S4", "S5", "S6", "S7", "S8")], [True] * 3 + [False, True, True, False])
    root, task, c = story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with Patched({"S2": {"id": "S2", "roles": [AUTHOR, CRITIC]}}):       # a table with no acceptor: the world before X2-7
            receipt = dispatch(c, task, "dA", AUTHOR)
            check_eq("no acceptor in the table: a closing accept with no acceptance record is taken as it was", refused(c, receipt, True), "")
            check_eq("... and the stage is completed", c.state()["stages"]["S2"]["status"], "completed")
    finally:
        cleanup(root)

    # --- the world AFTER B4: S2 has an acceptor
    root, task, c = story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with Patched():
            author = dispatch(c, task, "dA", AUTHOR)
            check_eq("the author's accept with stage_complete false is not touched by the gate", refused(c, author, False), "")
            critic = dispatch(c, task, "dC", CRITIC)
            text = refused(c, critic)
            check_in("no record -> refused with the stage, the dispatch and the door (dispatch the stage critic)", "Dispatch the stage critic", text)
            check_in("... naming the author's dispatch", "S2 has no stage acceptance for dA", text)
            check_in("... and the person's door with its block phrase", "--block \"stage acceptance\"", text)
            check_eq("... and the stage is not completed", c.state()["stages"]["S2"]["status"], "running")

            write_pipeline(task, acceptance={"S2": [record("dA", "reject")]})
            check_in("verdict reject -> refused with the critic's quote", "the stage critic rejected it: R-7", refused(c, critic))

            write_pipeline(task, acceptance={"S2": [record("dOLD", "accept")]})
            check_in("an accept for another dispatch of the author -> refused", "a record given for other bytes does not count", refused(c, critic))

            write_pipeline(task, acceptance={"S2": [record("dA", "accept", quote="")]} )
            check_eq("an accept for the author's last dispatch (quote empty is legal on accept) -> taken", refused(c, critic), "")
            check_eq("... and the stage is completed", c.state()["stages"]["S2"]["status"], "completed")
    finally:
        cleanup(root)

    # --- the next transition keeps the record (the preserved-keys tuple), and a person's word passes the gate
    root, task, c = story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with Patched():
            author = dispatch(c, task, "dA", AUTHOR)
            refused(c, author, False)
            critic = dispatch(c, task, "dC", CRITIC)
            (task / "work" / "handoffs").mkdir(parents=True)
            (task / "work" / "handoffs" / "dC.yaml").write_text(FORM.format(reviewed="dA", word="approve", failure="null"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("the writer records the critic's form (exit 0)", code, 0)
            pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
            last = A.stage_acceptance(pipeline, "S2")
            check_eq("... one round, verdict accept by the critic for dA", (last["verdict"], last["acceptor"], last["reviewed_dispatch"], last["failure_class"]),
                     ("accept", CRITIC, "dA", None))
            code, said = quiet(stage_done.run, "QA-1", "S2", "running", AUTHOR, "after the record", True)
            check_eq("a later stage transition runs", code, 0)
            kept = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
            check_eq("... and the record is still on disk (on disk wins: the key is in the tuple)", A.stage_acceptance(kept, "S2"), last)
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_in("the same form again writes nothing", "already recorded", said)
            check_eq("... one round only", len(json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["acceptance"]["S2"]), 1)

            (task / "work" / "handoffs" / "dC.yaml").write_text(FORM.format(reviewed="dA", word="rejected", failure="spec"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("a verdict word outside the table -> exit 2, no record", code, 2)
            check_in("... the refusal names the words", "approve|approve_with_fixes|concerns|review", said)
            (task / "work" / "handoffs" / "dC.yaml").write_text(FORM.format(reviewed="dA", word="concerns", failure="opinion"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("a reject with failure_class `opinion` -> exit 2", code, 2)
            check_in("... the refusal lists the four classes", "spec, capability, data, tooling", said)
            check_eq("... nothing new was written", len(json.loads((task / "pipeline.json").read_text(encoding="utf-8"))["acceptance"]["S2"]), 1)
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml", "driver", "reject", "x")
            check_eq("the driver records an accept only", code, 2)
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml", "driver", "accept", "the critic's last round is spent; gap: no limit stated")
            check_eq("the driver's accept with the gap in words is recorded", code, 0)
            last = A.stage_acceptance(json.loads((task / "pipeline.json").read_text(encoding="utf-8")), "S2")
            check_eq("... the last round is the driver's", (last["acceptor"], last["verdict"], last["reviewed_dispatch"]), ("driver", "accept", "dA"))
            check_eq("the critic's close with the driver's accept on record is taken", refused(c, critic), "")
    finally:
        cleanup(root)

    root, task, c = story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with Patched():
            author = dispatch(c, task, "dA", AUTHOR)
            refused(c, author, False)
            critic = dispatch(c, task, "dC", CRITIC)
            check("a refusal first", bool(refused(c, critic)))
            pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
            waiver.apply_stage_override(pipeline, "S2", "no stage acceptance", "the person closes S2 without the critic", waiver.now_iso())
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            check_eq("a person's recorded word passes the gate", refused(c, critic), "")
            passed = (task / "state" / "passed-by-person.jsonl")
            check("... and the pass is recorded", passed.is_file() and '"stage": "S2"' in passed.read_text(encoding="utf-8"))
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)

    # --- t-1815 F4: the record is bound to the dispatch the critic REVIEWED, so an old `ok` never closes a stage over newer work
    root, task, c = story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with Patched():
            refused(c, dispatch(c, task, "dA", AUTHOR), False)
            refused(c, dispatch(c, task, "dB", AUTHOR), False)        # the author reworked: dB is now the last accepted dispatch
            critic = dispatch(c, task, "dC", CRITIC)
            handoffs = task / "work" / "handoffs"
            handoffs.mkdir(parents=True, exist_ok=True)
            (handoffs / "dC.yaml").write_text(FORM.format(reviewed="dA", word="approve", failure="null"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("an `ok` that reviewed dA, given after the author reworked to dB: not recorded (exit 2)", code, 2)
            check_in("... the refusal says the record is for other bytes and names both dispatches", "it is for 'dA', the last dispatch of the author is 'dB'", said)
            check_in("... and the critic dispatch stays refused at the gate", "S2 has no stage acceptance for dB", refused(c, critic))
            (handoffs / "dC.yaml").write_text(FORM.format(reviewed="dA", word="approve", failure="null").replace(
                "inputs_read:\n  - path: work/handoffs/dA.yaml\n    version: abc\n", ""), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("a form that names no reviewed dispatch: refused (exit 2)", code, 2)
            check_in("... the refusal names the field `inputs_read` as the door", "inputs_read", said)
            check_in("test_refusal_names_author_path_no_sha256: ... and the concrete expected row, the author's last accepted dispatch",
                     "path: work/handoffs/dB.yaml", said)
            check("test_refusal_names_author_path_no_sha256: ... and no sha256 (the check never reads it)", "sha256" not in said, said)
            (handoffs / "dC.yaml").write_text(FORM.format(reviewed="dC", word="approve", failure="null"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("a form that names only a dispatch that is not the author's: refused (exit 2)", code, 2)
            check_eq("... nothing was written by any refusal", "acceptance" in json.loads((task / "pipeline.json").read_text(encoding="utf-8")), False)
            (handoffs / "dC.yaml").write_text(FORM.format(reviewed="dB", word="approve", failure="null"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("the `ok` that reviewed the newer dB is recorded for dB, and closes the stage", (code, refused(c, critic)), (0, ""))
    finally:
        cleanup(root)

    # --- t-1936 F1 (c): no accepted dispatch of the author yet -> the refusal says so, and names no path to list
    root, task, c = story()
    hooklib._PROJECT_ROOT_CACHE = root
    try:
        with Patched():
            dispatch(c, task, "dC", CRITIC)
            handoffs = task / "work" / "handoffs"
            handoffs.mkdir(parents=True, exist_ok=True)
            (handoffs / "dC.yaml").write_text(FORM.format(reviewed="dX", word="approve", failure="null"), encoding="utf-8")
            code, said = quiet(stage_done.record_acceptance, "QA-1", "S2", "work/handoffs/dC.yaml")
            check_eq("test_refusal_when_no_author_yet: exit 2", code, 2)
            check_in("test_refusal_when_no_author_yet: ... says no accepted dispatch of the author exists at S2 yet",
                     f"no accepted dispatch of {AUTHOR} exists at S2 yet, so no review can be recorded", said)
            check("test_refusal_when_no_author_yet: ... and names no row to list", "work/handoffs/.yaml" not in said and "sha256" not in said, said)
    finally:
        cleanup(root)

    # --- S3 (E-X2-5f): the author of a stage with an acceptor is no longer the closing role, and his exit window is still judged on the plan
    S3_ROLES = {"id": "S3", "roles": ["qa-test-strategist", CRITIC]}
    for label, definition, expected in (("with an acceptor", dict(S3_ROLES, acceptance_by=CRITIC), "S3 structured test plan invalid"),
                                        ("without one (as shipped)", S3_ROLES, "")):
        root, task, c = story()
        hooklib._PROJECT_ROOT_CACHE = root
        try:
            BASE.accept_stage(c, task, "S2")
            (task / "work").mkdir(exist_ok=True)
            (task / "work" / "test-plan.json").write_text(json.dumps([{"id": "TS-1"}]), encoding="utf-8")
            with Patched({"S3": definition}):
                author = dispatch(c, task, "dP", "qa-test-strategist", "S3")
                text = refused(c, author, False)
                check(f"S3 author's exit (stage_complete false) with a broken plan, {label}: " + (f"refused ({expected})" if expected else "taken, as before"),
                      (expected in text) if expected else text == "", text[:200])
        finally:
            cleanup(root)

    # --- positional invariant: a stage with no acceptor (S5..S8, or S2 as shipped) and a dispatch that does not close are not asked
    with Patched():
        check_eq("S5 closing accept: no refusal", A.stage_acceptance_refusal({}, {"stage": "S5", "role": "qa-code-critic", "id": "x"}, {}, lambda s, e: (e, []))[0], "")
        check_eq("S3 has an acceptor as shipped -> the author's exit is owed a plan check by X2-5", A.author_exit_owes_plan({"stage": "S3", "role": "qa-test-strategist"}), True)
        check_eq("an unknown stage gives no definition", A.stage_def_of("S99"), {})
    check_eq("S2 author's exit: an author-of-an-acceptor stage as shipped", A.author_exit_owes_plan({"stage": "S2", "role": AUTHOR}), True)
    check_eq("... the critic is not the author", A.author_exit_owes_plan({"stage": "S2", "role": CRITIC}), False)
    table = Path(SCRIPTS).parent / "references" / "stages.json"
    check("author_exit_owes_plan reads the table it is given", A.author_exit_owes_plan({"stage": "S3", "role": "qa-test-strategist"}, table) is True)


if __name__ == "__main__":
    run()
    finish("test_controller_stage_acceptance")
