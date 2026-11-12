"""onboard_apply.py - the one apply path of an installation: plan, listing, retirement, manifest
(spec t-232 sections 1, 4, 5 headless, 6; Lead decisions F2, F5, G1, G2, C2, C9, E1, E2, E4, K1, K2,
K8, K10, K12, K13), and the FR-7 memory of config_contract (a question answered is not asked again).

t-272 (fix wave after critic t-268): item 2 (the undetermined file is set aside), item 3 (git is read, the lines are
printed, nothing is written), item 6 (locks by class and kind; a listing cannot make a carried-row lock removable),
item 8 (one line for a row with many hits; nothing_to_do is false while two copies of a record stand).

Mutations this file kills (each by this file alone):
  retire before regenerate | per-path sha recheck off | live lock not refused | a newer manifest
  retires | the memory of answers off | an unrecognised file left where it is | a lock under a carried row
  removed | the removal not intersected with what the table calls removable | nothing_to_do ignores a
  duplicate | the dev-factory rows listed one by one
t-288 (the onboarding runs inside a session whose hooks hold locks): the listing/--out refuse on a held lock |
  this session's own writer refuses the apply | ANY writer ignored whatever the session id | the apply does not
  look again before it refuses (or waits for a lease) | a 0-byte free lock refuses | the phase text keeps "stop"

Run: python -B scripts/tests/test_install_retire.py
"""
import contextlib
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import FIXTURES, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir, temp_project, use_project  # noqa: E402

use_project(temp_project("qa-install-retire-audit-"))  # config_contract pulls audit_factory, which reads the hook layer

import config_contract as C  # noqa: E402
import install_paths as I  # noqa: E402
import onboard_apply as OA  # noqa: E402
import session_identity as SI  # noqa: E402

TEMPLATE = C.canonical_template()
KEYS = C.config_keys()
VERSION = C.package_version()
DATE = "2026-10-01"
CTX = {"package_fingerprint": "fingerprint-of-the-installed-package"}
GEN1 = "qa-factory/artifacts/*/work/evidence/"
DISCARDED = ["qa-factory/state/jira-probe-01a0.json", "qa-factory/state/doctor-install-smoke-old.json",
             "qa-factory/strategy/product-passport.md",
             "qa-factory/readiness.json"]       # the old place of the readiness report: it lives in state/ now (t-232 F8)
# The carried records of the old layout (state/) and where the install moves them (records/).
OLD_RECORDS = ["qa-factory/state/journal.jsonl", "qa-factory/state/estimation-ledger.jsonl", "qa-factory/state/coverage-map.md",
               "qa-factory/state/project-decisions.json"]
NEW_RECORDS = [p.replace("/state/", "/records/") for p in OLD_RECORDS]
SUPERPOWERS = "docs/superpowers/qa-tasks/2026-09-04-qa-1"
NOTES = "qa-factory/my-notes.md"


def put(root: Path, rel: str, text: str = "x") -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def sha(root: Path, rel: str) -> str:
    """sha256 of a file, or 'missing': a check that asks about a file that is not there FAILS with that word, it does not stop the run."""
    path = root.joinpath(*rel.split("/"))
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except PermissionError:     # a byte range another handle holds locked (a running writer's lock file)
        return "locked"


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): _digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def old_project() -> Path:
    """An old-generation project (spec section 5, case B, shortened): a live-shaped config with
    deprecated keys, the carried records, a pile of machine-local state, the strategy documents
    with the old product passport, one team dev-factory folder, one file nobody recognises."""
    root = temp_dir("qa-install-retire-")
    cfg = json.loads((FIXTURES / "config-live-shape.json").read_text(encoding="utf-8"))
    cfg["audit_cadence_days"] = 30
    put(root, "qa-factory/config.json", json.dumps(cfg, indent=2))
    put(root, ".gitignore", f"node_modules/\n.env\n{GEN1}\n")
    for name in ("test-strategy", "project-profile", "aspect-profile", "faq", "framework-rules", "product-passport"):
        put(root, f"qa-factory/strategy/{name}.md", f"# {name}\nwritten by a person or an earlier run\n")
    put(root, "qa-factory/obligations.md", "# Obligations\n")
    put(root, "qa-factory/factory-backlog.md", "# Backlog\n")
    put(root, "qa-factory/bugs/BUG-1.md", "# BUG-1\n")
    put(root, "qa-factory/artifacts/QA-1/work/test-cases/a/TC-001.md", "# TC-001\n")
    for name in ("journal.jsonl", "estimation-ledger.jsonl", "coverage-map.md", "project-decisions.json"):
        put(root, f"qa-factory/state/{name}", f"carried {name}\n")
    put(root, "qa-factory/readiness.json", json.dumps({"runtime_paths": {"package_version": "0.7.4", "plugin_root": "C:/old/0.7.4"}}))
    for n in (1, 2, 3):
        put(root, f"qa-factory/state/host-receipts/r{n}.json", "{}")
    put(root, "qa-factory/state/turns/t1.json", "{}")
    put(root, "qa-factory/state/doctor-install-smoke-old.json", json.dumps({"package_fingerprint": "an-older-package"}))
    put(root, "qa-factory/state/jira-probe-01a0.json", '{"probe": true}\n')
    # t-363 B6: `state/events.lock` is hook-written now (a running session's hooks make it again), so the lock this
    # project leaves for the install to REMOVE is one no hook makes: a stale lock of some other writer
    put(root, "qa-factory/state/other-writer/state/events.lock", "0")
    put(root, "qa-factory/state/pre-0.7.0-recovery/metrics.json", "{}")
    put(root, f"{SUPERPOWERS}/.state.json", '{"flow": "stlc-feature"}')
    put(root, NOTES, "my own notes\n")
    return root


# t-298: `environment.access` is asked until answered (config-keys.json `asked_until_answered`); the live-shaped config
# records none, so every plan over it opens that pointer and the apply refuses until it is answered. The cases below are
# about retirement, not about the question, so they pass the person's answer like a headless caller does (--answers).
ACCESS_PTR = "/environment/access"
ACCESS = {"kind": "oidc_password", "command": "", "url": "https://sso.example.test/login", "client_id_key": "OIDC_CLIENT",
          "realm_key": "OIDC_REALM", "user_key": "STAND_USER", "secret_key": "STAND_SECRET", "user_field": "", "secret_field": "", "token_key": "",
          "unauth_status": [302], "login_probe": {}}


def migration(root: Path, **kw) -> dict:
    # the live-shaped config carries an old price table: the person's answer is part of the input
    kw.setdefault("price_table_answer", "builtin")
    answers = dict(kw.pop("answers", None) or {})
    if kw.pop("access_answer", True):        # False: the memory of an earlier approval must answer by itself (K-B4b)
        answers.setdefault(ACCESS_PTR, copy.deepcopy(ACCESS))
    return C.migration_plan(C.read_config_file(root), root=root, answers=answers, **kw)


class Runner:
    """Stands in for readiness.py / factory_dashboard.py: records what existed when each ran and
    writes the output the real one writes, so a second plan sees a finished install."""

    def __init__(self, probe):
        self.calls, self.probe = [], probe

    def __call__(self, root, script, args=()):
        self.calls.append((script, {rel: os.path.exists(root.joinpath(*rel.split("/"))) for rel in self.probe}))
        if script == "readiness.py":
            put(Path(root), OA.READINESS_REL, json.dumps({"runtime_paths": {"package_version": VERSION}}))
        elif script == "factory_dashboard.py":
            put(Path(root), OA.DASHBOARD_REL, "<html></html>")
        return {"step": script, "ok": True, "rc": 0, "note": ""}


def approve(root: Path, made: dict, ref: str = "onboarding:t1") -> str:
    C.record_approval(root, made["proposal"], ref, "test:evidence")
    return ref


@contextlib.contextmanager
def held(path: Path):
    """What a running writer does: the OS lock on byte 0 of its lock file (event_store.lock)."""
    handle = open(path, "a+b")
    handle.seek(0, 2)
    if not handle.tell():
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


class Writer:
    """A running writer that can let go IN THE MIDDLE of a test (held() lets go only at the end of its block):
    the OS lock on byte 0 of its lock file, as event_store.lock takes it."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(path, "a+b")
        self.handle.seek(0, 2)
        if not self.handle.tell():
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


@contextlib.contextmanager
def session_env(value):
    """CLAUDE_SESSION_ID as the SessionStart hook leaves it for a command the role runs; None = absent (an old host, a shell run).
    B-410 (E26): every name the session-identity rules read is cleared first (a builder's own CLAUDE_CODE_SESSION_ID must not leak
    in), the home is redirected to a throwaway folder (a child process finds no receipt of the real spool), and the spool root of
    this process is patched to it."""
    names = list(SI.load_rules()["env_vars"]) + ["HOME", "USERPROFILE"]
    saved, saved_spool, home = {k: os.environ.get(k) for k in names}, SI.spool_root, temp_dir("qa-install-retire-home-")
    for name in names:
        os.environ.pop(name, None)
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
    SI.spool_root = lambda: home / ".qa-factory" / "spool"
    if value is not None:
        os.environ["CLAUDE_SESSION_ID"] = value
    try:
        yield
    finally:
        SI.spool_root = saved_spool
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        cleanup(home)


def refusal(call) -> str:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - the text is what is asserted
        return f"{type(exc).__name__}: {exc}"
    return ""


# --- the plan: shape, K1, K2, F5, G2 -------------------------------------------------------------

def plan_shape_and_lists() -> None:
    root = old_project()
    try:
        before = snapshot(root)
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("FR-45: plan() writes nothing into the project", snapshot(root), before)
        check_eq("FR-14: the plan's keys", sorted(made), sorted(
            ["write", "regenerate", "retire", "changed_since_install", "not_ours_kept", "locks", "live_locks", "unknown", "refused", "date",
             "retire_blocked", "set_aside", "blocked", "needs_answers", "manifest", "install_exists", "nothing_to_do", "proposal", "tracking",
             "profile_problems"]))
        check_eq("FR-14: a retire item's keys", sorted(made["retire"][0]),
                 sorted(["rel_path", "class", "retire_mode", "sha256", "summary", "source", "generation", "requires"]))
        check_eq("FR-14: its summary's keys", sorted(made["retire"][0]["summary"]), ["bytes", "first_line", "mtime"])
        check_eq("FR-14: a lock item's keys", sorted(made["locks"][0]), sorted(["rel_path", "state", "kind", "class", "age_hours", "action", "holder"]))
        check_eq("FR-14: the tracking's keys", sorted(made["tracking"]), sorted(["checked", "line", "tracked_in_state", "tracked_ignored", "tracked_changes", "git_rm"]))
        check_eq("K1: the retire list is exactly the discarded files (the old readiness report among them, NO record) and the ONE undetermined "
                 "file, which is set aside (t-272 item 2)",
                 [r["rel_path"] for r in made["retire"]], sorted(DISCARDED + [NOTES]))
        check_eq("K1: each item carries the sha256 of its bytes", [r["sha256"] for r in made["retire"]], [sha(root, r["rel_path"]) for r in made["retire"]])
        check_eq("F2: the factory's own technical data is deleted; what no row names is MOVED (the class rule, from the table)",
                 {r["rel_path"]: r["retire_mode"] for r in made["retire"]}, {**{p: "delete" for p in DISCARDED}, NOTES: "move"})
        check_eq("FR-13 / item 1: the scripts the apply runs are exactly the scripts the table declares outputs for (one list, two places: they cannot drift)",
                 sorted(OA.REGENERATE_SCRIPTS), sorted(s["script"] for s in I.load_table()["regenerate_step"]))
        check_eq("item 1: the plan keeps what those scripts rebuild (not in retire), whatever the tree holds of it",
                 [r["rel_path"] for r in made["retire"] if r["rel_path"] in I.regenerate_outputs(I.load_table(), OA.REGENERATE_SCRIPTS)], [])
        check_eq("item 2: the undetermined item says why it is listed and has class unrecognised",
                 [(r["class"], r["source"]) for r in made["retire"] if r["rel_path"] == NOTES], [("unrecognised", "no row of the factory names it")])
        passport = next(r for r in made["retire"] if r["rel_path"].endswith("product-passport.md"))
        check_eq("C9: the passport item says it needs the fold receipt", passport["requires"], ["fold_receipt"])
        probe = next(r for r in made["retire"] if r["rel_path"] == DISCARDED[0])
        check_eq("summary: first line is recognisable, bytes are the file's", (probe["summary"]["first_line"], probe["summary"]["bytes"]),
                 ('{"probe": true}', len('{"probe": true}\n')))
        kept = {n["rel_path"]: n for n in made["not_ours_kept"]}
        check_eq("K2 (t-272): not ours, kept: ONLY the team's dev-factory folder (its not_ours row); the unknown file is set aside, not kept",
                 sorted(kept), [SUPERPOWERS])
        check_eq("F5: the dev factory is not an earlier generation: reason as the table says, no generation",
                 (kept[SUPERPOWERS]["reason"], kept[SUPERPOWERS]["generation"]), ("the project's dev factory (superpowers)", None))
        check_eq("F5: it is never in a retire list", [r["rel_path"] for r in made["retire"] if "superpowers" in r["rel_path"]], [])
        check("carried data is nowhere in the retire list (config, records, receipts, price evidence, recovery)",
              not any(r["rel_path"].startswith(("qa-factory/bugs", "qa-factory/artifacts", "qa-factory/state/host-receipts", "qa-factory/state/turns",
                                                "qa-factory/state/pre-0.7.0-recovery", "qa-factory/state/journal"))
                      or r["rel_path"] == OA.CONFIG_REL for r in made["retire"]))
        check_eq("a stale lock is listed under regenerate as removed",
                 [(r["rel_path"], r["action"]) for r in made["regenerate"] if r["action"] == "remove"], [("qa-factory/state/other-writer/state/events.lock", "remove")])
        check_eq("the stale lock is not a blocker", made["blocked"], None)
        check_eq("no manifest: status absent", made["manifest"]["status"], "absent")
        check_eq("an install exists (config, and table hits)", made["install_exists"], True)
        check_eq("E4: config.json is never reported as changed since install", [c["rel_path"] for c in made["changed_since_install"]], [])
        check_eq("the config is migrated, the template copies exist already, the gitignore block, the four records to move and the manifest are to be written",
                 [(w["rel_path"], w["action"]) for w in made["write"]],
                 [(OA.CONFIG_REL, "update"), (OA.GITIGNORE_REL, "rewrite")] + [(p, "move") for p in NEW_RECORDS] + [(OA.MANIFEST_REL, "create")])
        check_eq("F8: a move names its old place as `source`, and carries no sha (a record grows)",
                 [(w["source"], "sha256" in w) for w in made["write"] if w["action"] == "move"], [(p, False) for p in OLD_RECORDS])
        sealed = made["proposal"]
        check_eq("the listing joins the proposal; retire items there carry sha256 and no summary",
                 sorted(sealed["listing"]["retire"][0]), sorted(["rel_path", "class", "retire_mode", "sha256", "source", "generation", "requires"]))
        check_eq("the listing carries no date (a run's day never invalidates an approval)",
                 "2026-10-01" in json.dumps(sealed["listing"]), False)
        again = OA.plan(root, migration(root), context=CTX, date="2031-01-01")
        check_eq("...so the same tree on another day seals to the same hash", again["proposal"]["proposal_hash"], sealed["proposal_hash"])
        check_eq("the seal is the proposal_hash of the proposal WITH its listing", sealed["proposal_hash"], C.proposal_hash(sealed))
        cut = copy.deepcopy(sealed)
        cut["listing"]["retire"].pop()
        check("an approval of the sealed proposal does not cover a listing with an item deleted", C.proposal_hash(cut) != sealed["proposal_hash"])
        approve(root, made)
        check("the person's yes is recorded against the sealed hash", C.is_approved(root, sealed))
        check("...and not against the proposal without its listing", not C.is_approved(root, {k: v for k, v in sealed.items() if k != "listing"}))
        check_eq("G2: no manifest: the listing says the word is the only authority",
                 "the word you give is the only authority" in OA.render(made), True)
        text = OA.render(made)
        check_not_in("F5: the listing never calls the dev factory a generation or an earlier version", "earlier version", text.split("Kept, not touched:")[1].split(SUPERPOWERS)[0] if SUPERPOWERS in text else text)
        check_in("F5: it names it as the table does", "the project's dev factory (superpowers)", text)
    finally:
        cleanup(root)


# --- K13: the whole listing (t-232 pinned a cap of 20 and a count; t-868 / F-5 overturns it) --------------------

def listing_whole() -> None:
    root = old_project()
    try:
        for n in range(2, 22):
            put(root, f"qa-factory/state/jira-probe-x{n:02d}.json", f"{{\"n\": {n}}}\n")
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        deleted = [r for r in made["retire"] if r["retire_mode"] == "delete"]
        check_eq("K13: the plan holds every item (24 = 21 probes + smoke + passport + the old readiness report)", len(deleted), 24)
        text = OA.render(made)
        group = text.split("Will be deleted")[1].split("\n\n")[0].splitlines()[1:]
        shown = [l for l in group if l.startswith("  - ")]
        check_eq("K13: all 24 are shown, one line each (the listing has no cap)", len(shown), 24)
        check("K13: and no count of what is left out appears anywhere (NEGATIVE control, any number)",
              re.search(r"\+\d+ more", text) is None, text[-200:])
        runner = Runner(DISCARDED)
        OA._run_script = runner
        ref = approve(root, made)
        done = OA.apply(root, made, ref, date=DATE)
        if not check("K13: a retire record was written", bool(done["record"])):
            return
        record = json.loads(root.joinpath(*done["record"].split("/")).read_text(encoding="utf-8"))
        check_eq("K13: the retire record holds all of them (24 to delete + the one set aside), with their sha256 and result",
                 (len(record["retired"]), {r["result"] for r in record["retired"]}), (25, {"deleted", "waits for the fold", "moved"}))
        check_eq("K13: the record keeps the approval and the proposal it came from",
                 (record["approval_ref"], record["proposal_hash"]), (ref, made["proposal"]["proposal_hash"]))
        check_eq("FR-40: the record lives under the table's move target for this day", done["record"].startswith(f"qa-factory/state/retired/{DATE}/"), True)
    finally:
        cleanup(root)


# --- apply: order, modes, the passport, K8, the manifest -------------------------------------------

def apply_path() -> None:
    root = old_project()
    try:
        runner = Runner(DISCARDED + NEW_RECORDS + OLD_RECORDS)
        OA._run_script = runner
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        ref = approve(root, made)
        config_before = (root / "qa-factory" / "config.json").read_bytes()
        records_before = {p: sha(root, p) for p in OLD_RECORDS}
        steps = []
        done = OA.apply(root, made, ref, date=DATE, checkpoint=steps.append)
        check_eq("order: config, new-shape files, gitignore, move records, regenerate, retire, manifest LAST", steps,
                 ["config", "new-shape files", "gitignore", "move records", "regenerate", "retire", "manifest"])
        check_eq("order: when readiness and the dashboard were rebuilt the old files were still there (nothing retired before its replacement)",
                 [(script, present[DISCARDED[0]] and present[DISCARDED[1]]) for script, present in runner.calls],
                 [("readiness.py", True), ("factory_dashboard.py", True), ("check_coverage.py", True)])
        check_eq("order: the records were already in their new place, and gone from the old, when the first script ran (moved BEFORE anything else)",
                 [(all(present[p] for p in NEW_RECORDS), any(present[p] for p in OLD_RECORDS)) for _, present in runner.calls],
                 [(True, False)] * 3)
        check_eq("F8: the records are in records/ byte for byte, and state/ holds none of them",
                 ({p.replace("/state/", "/records/"): sha(root, p.replace("/state/", "/records/")) for p in OLD_RECORDS},
                  [os.path.exists(root / p) for p in OLD_RECORDS]),
                 ({p.replace("/state/", "/records/"): s for p, s in records_before.items()}, [False] * 4))
        check_eq("F8: the readiness report is rebuilt in state/, and the old one beside the config is deleted",
                 (os.path.exists(root / OA.READINESS_REL), os.path.exists(root / "qa-factory/readiness.json")), (True, False))
        check("the config was migrated: canonical order, deprecated key gone",
              "audit_cadence_days" not in json.loads((root / "qa-factory/config.json").read_text(encoding="utf-8"))
              and (root / "qa-factory/config.json").read_bytes() != config_before)
        check_eq("F2: the technical data is deleted (probe, stale smoke)", [os.path.exists(root / p) for p in DISCARDED[:2]], [False, False])
        check_eq("C9: no fold receipt: the passport waits, is kept, and is reported so",
                 (os.path.exists(root / DISCARDED[2]), [r["result"] for r in done["retired"] if r["rel_path"] == DISCARDED[2]]), (True, ["waits for the fold"]))
        set_aside = f"qa-factory/state/retired/{DATE}/{NOTES}"
        check_eq("item 2: the undetermined file is MOVED to retired/<day>/<same relative path>, gone from where it was, bytes unchanged "
                 "(sha256 before == after)", (os.path.exists(root / NOTES), sha(root, set_aside)), (False, hashlib.sha256(b"my own notes\n").hexdigest()))
        check_eq("K2: the team's dev factory keeps its file and its bytes", os.path.exists(root / SUPERPOWERS / ".state.json"), True)
        check_eq("the stale lock was removed", os.path.exists(root / "qa-factory/state/other-writer/state/events.lock"), False)
        gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        check_eq("K4: the project's own two gitignore lines stay, the stray line is back once, in the block", (gi[:2], gi.count(GEN1)), (["node_modules/", ".env"], 1))
        manifest = I.read_manifest(root)
        check_eq("K9: the manifest is written and current", (manifest["status"], manifest["package_version"], manifest["newer"]), ("ok", VERSION, False))
        check("K9: every manifest sha256 matches the disk", I.verify_manifest(root)["ok"], str(I.verify_manifest(root)))
        names = {e["rel_path"] for e in manifest["entries"]}
        check("the manifest names the documents the install wrote, and not what was retired or the project's own files",
              {OA.CONFIG_REL, "qa-factory/strategy/test-strategy.md"} <= names and not names & set(DISCARDED[:2]) and NOTES not in names and SUPERPOWERS not in " ".join(names))
        check("E3: machine-local entries carry no sha", all("sha256" not in e for e in manifest["entries"] if e["machine_local"]))
        # the passport: the profile alone is no receipt; another run's receipt is none; THIS run's is
        second = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("the second plan lists only the passport to retire", [r["rel_path"] for r in second["retire"]], [DISCARDED[2]])
        ref2 = approve(root, second, "onboarding:t2")
        OA.apply(root, second, ref2, phase="final", date=DATE)
        check_eq("C9: project-profile.md exists, still no receipt: the passport stays", os.path.exists(root / DISCARDED[2]), True)
        with open(root / OA.APPROVALS_REL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"fold": OA.FOLD_TOKEN, "for_approval": "onboarding:another-run"}) + "\n")
        OA.apply(root, second, ref2, phase="final", date=DATE)
        check_eq("C9: a receipt of another run does not release it", os.path.exists(root / DISCARDED[2]), True)
        with open(root / OA.APPROVALS_REL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"fold": OA.FOLD_TOKEN, "for_approval": ref2}) + "\n")
        released = OA.apply(root, second, ref2, phase="final", date=DATE)
        check_eq("C9: THIS run's fold receipt releases it: deleted", (os.path.exists(root / DISCARDED[2]),
                 [r["result"] for r in released["retired"]]), (False, ["deleted"]))
        # K8: a plan over the applied tree has nothing to approve and apply writes nothing
        third = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("K8: a second plan over the applied tree: retire [], write [], regenerate [], nothing to ask",
                 ([third[k] for k in ("retire", "write", "regenerate", "needs_answers")], third["nothing_to_do"]), ([[], [], [], []], True))
        check_eq("K8: json.dumps(proposed) equals the config on disk, order-sensitive",
                 json.dumps(C._canonical_order(third["proposal"]["proposed_config"], TEMPLATE, "/", [])),
                 json.dumps(json.loads((root / "qa-factory/config.json").read_text(encoding="utf-8"))))
        check_in("K8: the listing says there is nothing to do", "Nothing to do", OA.render(third))
        snap = snapshot(root)
        nothing = OA.apply(root, third, "", date=DATE)
        check_eq("K8: apply with nothing to do needs no approval and writes nothing", (nothing["applied"], nothing["nothing_to_do"], snapshot(root)), (False, True, snap))
    finally:
        cleanup(root)


# --- C2: the project changed since the summary ------------------------------------------------------

def stale_summary() -> None:
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        ref = approve(root, made)
        put(root, DISCARDED[0], '{"probe": "somebody edited it after the summary"}\n')
        before = snapshot(root)
        problem = refusal(lambda: OA.apply(root, made, ref, date=DATE))
        check("C2: a listed file that changed since the summary refuses the apply",
              problem.startswith("ApplyRefused: the project changed since the summary: " + DISCARDED[0]) and "make the summary again" in problem, problem)
        check_eq("C2: ...and nothing was written (config, gitignore, files, manifest)", snapshot(root), before)
        check("C2: the refusal names no script and no plugin path", ".py" not in problem and "scripts/" not in problem)
        # a path that is gone is not a change; a path that became a folder is
        os.unlink(root / DISCARDED[0])
        gone = OA.apply(root, made, ref, date=DATE)
        check_eq("a listed file that is gone already is not a change: the apply goes on", gone["applied"], True)
    finally:
        cleanup(root)
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        ref = approve(root, made)
        os.unlink(root / DISCARDED[1])
        os.mkdir(root / DISCARDED[1])
        check_in("C2: a listed file that became a folder is refused too", "the project changed since the summary: " + DISCARDED[1],
                 refusal(lambda: OA.apply(root, made, ref, date=DATE)))
    finally:
        cleanup(root)
    # an approval of another proposal, a sealed proposal that was edited, an unrecorded word
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_in("an unrecorded yes cannot apply", "has to be recorded first", refusal(lambda: OA.apply(root, made, "typed-yes-not-recorded", date=DATE)))
        ref = approve(root, made)
        forged = copy.deepcopy(made)
        forged["proposal"]["listing"]["retire"].append({"rel_path": NOTES, "class": "unrecognised", "retire_mode": "delete",
                                                        "sha256": sha(root, NOTES), "source": "x", "generation": None, "requires": []})
        check_in("a listing edited after the seal is refused", "changed after it was sealed", refusal(lambda: OA.apply(root, forged, ref, date=DATE)))
        check_eq("...and the file it named is untouched", os.path.exists(root / NOTES), True)
    finally:
        cleanup(root)


# --- E1: writers --------------------------------------------------------------------------------------

def writers() -> None:
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        lock = root / STALE_LOCK     # t-363 B6: state/events.lock is hook-written now; the held one is a lock no hook makes
        with held(lock):
            made = OA.plan(root, migration(root), context=CTX, date=DATE)
            check_eq("E1: a held lock is live in the plan", [(l["rel_path"], l["state"]) for l in made["locks"]], [(STALE_LOCK, "live")])
            check_eq("E1 (t-288): a held lock does NOT block the plan: it is reported as live_locks, the plan is not blocked",
                     (made["blocked"], made["live_locks"]), (None, [{"rel_path": STALE_LOCK, "kind": "os", "holder": "unknown"}]))
            check_eq("E1: the stale-lock removal is not offered for a live lock", [r for r in made["regenerate"] if r["action"] == "remove"], [])
            ref = approve(root, made)
            before = snapshot(root)
            problem = refusal(lambda: OA.apply(root, made, ref, date=DATE))
            check("E1: apply refuses, naming the lock, its holder and the move, and no retirement at all",
                  problem.startswith("ApplyRefused: A factory session is running") and f"{STALE_LOCK} (holder unknown)" in problem
                  and "finish the session or run that is writing there" in problem, problem)
            check_not_in("E1: no 'release the lease' wording where no command releases a lease", "release the lease", problem)
            check_eq("E1: nothing was written", snapshot(root), before)
        stale = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("E1: once the writer is gone the same lock is stale, listed to be removed, and not blocking",
                 ([l["state"] for l in stale["locks"]], stale["blocked"], stale["live_locks"]), (["stale"], None, []))
        # a lease whose process is alive is reported and refuses the apply at once (no waiting for a run); a gone one does not
        put(root, "qa-factory/state/stand-lease.json", json.dumps({"leases": {"default": {"holders": [{"job": "j", "pid": os.getpid(), "mode": "exclusive"}]}}}))
        alive = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("E1: a lease held by a live process is a live lock, with its pid, and is not a plan block",
                 ([(l["rel_path"], l["kind"], l["holder"]) for l in alive["live_locks"]], alive["blocked"]),
                 ([("qa-factory/state/stand-lease.json", "lease", f"pid {os.getpid()}")], None))
        sleeps = []
        saved_sleep = OA._sleep
        OA._sleep = sleeps.append
        try:
            problem = refusal(lambda: OA.apply(root, alive, approve(root, alive, "onboarding:lease"), date=DATE))
        finally:
            OA._sleep = saved_sleep
        check("E1: the lease refuses the apply at once (no waiting), and names the command that releases a stand",
              sleeps == [] and f"stand-lease.json (holder pid {os.getpid()})" in problem and "stand_lease.py --release --env <stand name>" in problem, (sleeps, problem))
        put(root, "qa-factory/state/stand-lease.json", json.dumps({"leases": {"default": {"holders": [{"job": "j", "pid": 0, "mode": "exclusive"}]}}}))
        gone = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("E1: a lease whose holder is gone does not", (gone["blocked"], gone["live_locks"]), (None, []))
        # t-2070 F5: the scheduler's execution-leases.json carries `process_started_at`; a recycled pid is not a lock
        put(root, "qa-factory/state/stand-lease.json", json.dumps({"leases": {}}))
        put(root, "qa-factory/state/execution-leases.json", json.dumps(
            {"leases": [{"job_id": "x", "pid": os.getpid(), "process_started_at": "winfiletime:1"}]}))
        recycled = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("E1 (t-2070 F5): an execution lease whose pid was recycled (birth differs) is no lock",
                 (recycled["blocked"], recycled["live_locks"]), (None, []))
        (root / "qa-factory/state/execution-leases.json").unlink()
        # t-2070 F6: a person's --release leaves a note that is not a holder, and the stand then reads free
        import stand_lease as SL
        put(root, "qa-factory/state/stand-lease.json", json.dumps({"leases": {"default": {"holders": [
            {"job": "j", "pid": os.getpid(), "started": SL._identity(os.getpid()), "mode": "exclusive"}]}}}))
        before_release = OA.plan(root, migration(root), context=CTX, date=DATE)
        answer = SL.release_by_person(root, "default", "the walker hung")
        after_release = OA.plan(root, migration(root), context=CTX, date=DATE)
        again = SL.release_by_person(root, "default", "the walker hung")
        check_eq("E1 (t-2070 F6): live before the release, no lock after it, and a second release answers not_held",
                 (len(before_release["live_locks"]), answer["status"], after_release["live_locks"], again["status"]),
                 (1, "released", [], "not_held"))
    finally:
        cleanup(root)


# --- E2, K10, K12: what may never be retired -----------------------------------------------------------

def newer_and_named() -> None:
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        # E2: a manifest of a newer factory
        manifest = {"schema_version": 1, "package_version": "99.0.0",
                    "entries": [{"rel_path": "qa-factory/obligations.md", "class": "carried", "package_version": "99.0.0",
                                 "input_hash": "", "sha256": sha(root, "qa-factory/obligations.md")}]}
        put(root, OA.MANIFEST_REL, json.dumps(manifest, indent=2))
        raw = (root / OA.MANIFEST_REL).read_bytes()
        made = OA.plan(root, migration(root), named=[NOTES], context=CTX, date=DATE)
        check_eq("E2: a newer manifest: nothing is offered for retirement, not even by name", (made["retire"], made["retire_blocked"]), ([], "newer_manifest"))
        check_in("E2: the listing says so in the words of the spec", "a newer factory wrote this project; update the plugin", OA.render(made))
        ref = approve(root, made)
        done = OA.apply(root, made, ref, date=DATE)
        check_eq("E2: apply retires nothing and leaves the newer manifest as it was",
                 (done["retired"], (root / OA.MANIFEST_REL).read_bytes() == raw, done["manifest"]["written"]), ([], True, False))
        check_eq("E2: the classes are honoured: the probe, the passport, the old readiness report and the kept files are all still there",
                 [os.path.exists(root / p) for p in DISCARDED + [NOTES]], [True] * 5)
    finally:
        cleanup(root)
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        # K10: an unreadable manifest retires nothing on its word and says so
        put(root, OA.MANIFEST_REL, "{ not json")
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("K10: an unreadable manifest is reported unreadable", made["manifest"]["status"], "unreadable")
        check_in("K10: ...in the listing, with the door", "cannot be read", OA.render(made))
        check_eq("K10: the table's names still retire the factory's own data (and the unrecognised file is set aside by the table's silence); "
                 "the manifest's word is not used",
                 sorted(r["source"] for r in made["retire"]), sorted(["table"] * len(DISCARDED) + ["no row of the factory names it"]))
    finally:
        cleanup(root)
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        # the manifest's word: a path it lists, whose bytes are still the ones it recorded, is the
        # factory's and may be offered (here a file the table does not name, written by a past run)
        I.write_manifest(root, [{"rel_path": NOTES, "class": "discarded"}])
        listed = OA.plan(root, migration(root), context=CTX, date=DATE)
        item = next((r for r in listed["retire"] if r["rel_path"] == NOTES), {})
        check_eq("manifest source: an untouched path the manifest lists is offered, with its source and the class mode (delete)",
                 (item.get("source"), item.get("retire_mode")), ("manifest", "delete"))
        # K10: bytes the factory did not write: an entry whose sha256 differs is changed, never retired
        put(root, NOTES, "a person edited this\n")
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("K10: an edited path is listed as changed since install", [c["rel_path"] for c in made["changed_since_install"]], [NOTES])
        check_eq("K10: ...and is not in the retire list", NOTES in [r["rel_path"] for r in made["retire"]], False)
        check_in("K10: ...and the listing says it is kept and how to have it set aside", NOTES, OA.render(made).split("changed since the factory wrote them")[1])
        # F2: naming it is the person's word, and what is undetermined is MOVED, not deleted
        named = OA.plan(root, migration(root), named=[NOTES, "qa-factory/state/not-a-file.json"], context=CTX, date=DATE)
        moves = {r["rel_path"]: r for r in named["retire"] if r["retire_mode"] == "move"}
        check_eq("F2: what the person names that changed since the factory wrote it is set aside, not deleted", sorted(moves), [NOTES])
        check_eq("F2: ...its class is its own, never 'carried'", moves[NOTES]["class"] in ("unrecognised", "discarded", "regenerated"), True)
        check_eq("a name that is no file is not retired, and the person is told so",
                 ([r["rel_path"] for r in named["retire"] if "not-a-file" in r["rel_path"]],
                  [r["reason"] for r in named["refused"] if "not-a-file" in r["rel_path"]]), ([], ["there is no such file"]))
        ref = approve(root, named)
        OA.apply(root, named, ref, date=DATE)
        target = f"qa-factory/state/retired/{DATE}/"
        check_eq("F2: it is under retired/<day>/, gone from where it was, and the discarded ones were deleted not moved",
                 (os.path.exists(root / (target + NOTES)), os.path.exists(root / NOTES), os.path.exists(root / (target + DISCARDED[0]))),
                 (True, False, False))
        check_eq("F2: the moved bytes are the very bytes that were listed", sha(root, target + NOTES), moves[NOTES]["sha256"])
        after = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("FR-40: earlier set-asides are reported once, with a size, and not as unknown files (the file and the record)",
                 ((after["set_aside"] or {}).get("files"), any("retired" in n["rel_path"] for n in after["not_ours_kept"])), (2, False))
        text = OA.render(after)
        check_in("FR-40: the person is told what stays until they empty the folder", "they stay until you empty that folder", text)
    finally:
        cleanup(root)
    root = old_project()
    sentinel = temp_dir("qa-install-sentinel-")
    try:
        OA._run_script = Runner(DISCARDED)
        outside = put(sentinel, "outside.txt", "outside the project\n")
        outside_sha = hashlib.sha256(outside.read_bytes()).hexdigest()
        bad = ["../outside.txt", str(outside), "/etc/passwd", "C:\\Windows\\system.ini", "qa-factory/../../outside.txt",
               OA.CONFIG_REL, "qa-factory/state/journal.jsonl", "qa-factory/state/host-receipts/r1.json", "qa-factory/state/events.lock",
               "qa-factory/strategy"]
        made = OA.plan(root, migration(root), named=bad, context=CTX, date=DATE)
        check_eq("K12: adversarial and carried names are refused, none reaches the retire list (only the discarded files and the one undetermined file are in it)",
                 [r["rel_path"] for r in made["retire"]], sorted(DISCARDED + [NOTES]))
        refused = " ".join(r["rel_path"] + " " + r["reason"] for r in made["refused"])
        check("K12: each refusal is listed with its reason (outside root, carried data, a lock)",
              "outside the project root" in refused or "absolute" in refused, refused[:300])
        check("K12: carried data is refused with its own words", "carried data is never retired" in refused)
        check("K12: a folder is refused as a folder", "a folder is never retired as a whole" in refused or "qa-factory/strategy" in refused)
        ref = approve(root, made)
        OA.apply(root, made, ref, date=DATE)
        check_eq("K12: the sentinel outside the project keeps its sha256", hashlib.sha256(outside.read_bytes()).hexdigest(), outside_sha)
        check_eq("K12: the carried files named are all still there (the journal is where the install moved it: records/)",
                 [os.path.exists(root / p) for p in (bad[5], "qa-factory/records/journal.jsonl", bad[7])], [True] * 3)
    finally:
        cleanup(root)
        cleanup(sentinel)


# --- a crash half-way: the old manifest stands, the next plan recomputes -----------------------------

def crash_midway() -> None:
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        ref = approve(root, made)

        def boom(step):
            if step == "retire":
                raise RuntimeError("power cut after the retirement, before the manifest")
        check("a crash after retire is the crash we injected", "power cut" in refusal(lambda: OA.apply(root, made, ref, date=DATE, checkpoint=boom)))
        check_eq("the manifest was never written: none exists", I.read_manifest(root), None)
        check_eq("what was retired stays retired", [os.path.exists(root / p) for p in DISCARDED[:2]], [False, False])
        replan = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("the next plan recomputes: only what is left is listed (the passport)", [r["rel_path"] for r in replan["retire"]], [DISCARDED[2]])
        check_eq("...the manifest is still to be written, so there is something to approve", ([w["rel_path"] for w in replan["write"]], replan["nothing_to_do"]),
                 ([OA.MANIFEST_REL], False))
        ref2 = approve(root, replan, "onboarding:t2")
        done = OA.apply(root, replan, ref2, date=DATE)
        check_eq("...and applying it ends with the manifest, consistently", (done["manifest"]["written"], I.read_manifest(root)["status"]), (True, "ok"))
    finally:
        cleanup(root)


# --- the command line: the headless entry, FR-45, p0's preflight ------------------------------------------

def command_line() -> None:
    root = temp_dir("qa-install-fresh-")
    try:
        (root / ".git").mkdir()
        before = snapshot(root)
        pre = json.loads(run_script("onboard_apply.py", "--root", root, "--preflight").stdout)
        check_eq("p0: a clean directory has no install", (pre["install_exists"], pre["config_present"], pre["table_hits"], pre["manifest"]["status"]),
                 (False, False, [], "absent"))
        proposal = root.parent / (root.name + "-proposal.json")
        config = copy.deepcopy(TEMPLATE)
        config["dod"] = "Done means reviewed and green"
        config["app_root"] = "."
        proposal.write_text(json.dumps({"proposed_config": config}), encoding="utf-8")
        planned = run_script("onboard_apply.py", "--root", root, "--proposal", proposal)
        out = json.loads(planned.stdout)
        check_eq("FR-14: stdout of the plan is one JSON document (nothing else)", planned.returncode, 0)
        check_eq("FR-45: without --apply nothing is written", snapshot(root), before)
        check_eq("a fresh project is the empty input: config to create, template copies, block, manifest",
                 [(w["rel_path"], w["action"]) for w in out["write"]],
                 [(OA.CONFIG_REL, "create"), ("qa-factory/obligations.md", "create"), ("qa-factory/factory-backlog.md", "create"),
                  (OA.GITIGNORE_REL, "rewrite"), (OA.MANIFEST_REL, "create")])
        check_eq("...with nothing to retire", (out["retire"], out["install_exists"]), ([], False))
        done = run_script("onboard_apply.py", "--root", root, "--proposal", proposal, "--apply")
        check("the headless entry applies: exit 0", done.returncode == 0, done.stderr[-400:])
        result = json.loads(done.stdout)
        check_eq("headless: every step ran, in order", [s["step"] for s in result["steps"]],
                 ["config", "new-shape files", "gitignore", "move records", "regenerate", "retire", "manifest"])
        check("headless: the config, the template copies, the block, the readiness report and the dashboard exist",
              all((root / p).is_file() for p in (OA.CONFIG_REL, "qa-factory/obligations.md", "qa-factory/factory-backlog.md", OA.GITIGNORE_REL, OA.READINESS_REL, OA.DASHBOARD_REL)),
              str([p for p in (OA.CONFIG_REL, OA.READINESS_REL, OA.DASHBOARD_REL) if not (root / p).is_file()]) + str(result["steps"][3:5]))
        check_eq("headless: a fresh install leaves no backup and no config-migrations folder", (root / "qa-factory/records/config-migrations").exists(), False)
        check_eq("F8: a fresh install makes records/ (the approval is in it) and no carried file in state/",
                 ((root / "qa-factory/records/onboarding-approvals.jsonl").is_file(), (root / "qa-factory/state/onboarding-approvals.jsonl").exists()),
                 (True, False))
        check("headless: the person's word (the command line) is on record", "headless" in (root / OA.APPROVALS_REL).read_text(encoding="utf-8"))
        check_eq("headless: the manifest is current", I.verify_manifest(root)["ok"], True)
        again = json.loads(run_script("onboard_apply.py", "--root", root, "--proposal", proposal).stdout)
        check_eq("K8 through the command line: a second plan has nothing to do", (again["nothing_to_do"], again["write"], again["retire"]), (True, [], []))
        listing = run_script("onboard_apply.py", "--root", root, "--proposal", proposal, "--listing")
        check_eq("--listing prints the text, not JSON", (listing.returncode, listing.stdout.startswith("Nothing to do")), (0, True))
        # a project with traces and no config is not clean (p0 step 5)
        traces = temp_dir("qa-install-traces-")
        try:
            put(traces, "qa-factory/state/jira-probe-01a0.json", "{}")
            hit = json.loads(run_script("onboard_apply.py", "--root", traces, "--preflight").stdout)
            check_eq("p0: old traces and no config: an install exists", (hit["install_exists"], hit["config_present"], hit["table_hits"]),
                     (True, False, ["qa-factory/state/jira-probe-01a0.json"]))
            stray = temp_dir("qa-install-stray-")
            try:
                put(stray, ".gitignore", f"node_modules/\n{GEN1}\n")
                hit = json.loads(run_script("onboard_apply.py", "--root", stray, "--preflight").stdout)
                check_eq("p0: the stray first-generation .gitignore line alone is a trace", (hit["install_exists"], hit["table_hits"]), (True, [".gitignore"]))
            finally:
                cleanup(stray)
            manifest_only = temp_dir("qa-install-manifest-only-")
            try:
                put(manifest_only, OA.MANIFEST_REL, "{ broken")
                check_eq("p0: a manifest alone (even an unreadable one) is an install", json.loads(run_script("onboard_apply.py", "--root", manifest_only, "--preflight").stdout)["install_exists"], True)
                dev = temp_dir("qa-install-dev-factory-")
                try:
                    put(dev, f"{SUPERPOWERS}/.state.json", "{}")
                    check_eq("p0: the team's dev factory is not a trace of ours", json.loads(run_script("onboard_apply.py", "--root", dev, "--preflight").stdout)["install_exists"], False)
                finally:
                    cleanup(dev)
            finally:
                cleanup(manifest_only)
        finally:
            cleanup(traces)
        # a sealed proposal applied after the tree changed is refused by the command line too
        bad = run_script("onboard_apply.py", "--root", root, "--proposal", root / "no-such-file.json")
        check("a proposal file that cannot be read is refused with what is expected, no traceback",
              bad.returncode == 1 and "cannot be read as JSON" in bad.stderr and "Traceback" not in bad.stderr, bad.stderr[-300:])
    finally:
        cleanup(root)
        with contextlib.suppress(OSError):
            os.unlink(root.parent / (root.name + "-proposal.json"))


# --- FR-7: a question answered is not asked again ------------------------------------------------------

def memory() -> None:
    old = copy.deepcopy(TEMPLATE)
    old["environment"]["access"] = copy.deepcopy(ACCESS)      # t-298: a config that records its access, so only /dod is the question here
    del old["dod"]
    root = temp_dir("qa-install-memory-")
    try:
        put(root, "qa-factory/config.json", json.dumps(old, indent=2))
        asked = C.migration_plan(old, root=root)
        check_eq("FR-7: first time, a required key the config lacks waits for an answer", C.unanswered_pointers(asked), ["/dod"])
        answered = C.migration_plan(old, answers={"/dod": "Done means green in CI"}, root=root)
        C.record_approval(root, answered, "onboarding:m1", "t:m1")
        line = json.loads((root / OA.APPROVALS_REL).read_text(encoding="utf-8").splitlines()[-1])
        check_eq("FR-7: the approval stores the answers beside the hash, and the default each was given against",
                 (line["answers"], line["answer_defaults"]), ({"/dod": "Done means green in CI"}, {"/dod": TEMPLATE["dod"]}))
        again = C.migration_plan(old, root=root)
        check_eq("FR-7: the same key missing again (answers None): not asked again, the answer is written",
                 (C.unanswered_pointers(again), again["proposed_config"]["dod"], [k for k in again["kept"] if k["path"] == "/dod"]),
                 ([], "Done means green in CI", [{"path": "/dod", "reason": "answered earlier, not asked again"}]))
        check_eq("FR-7: ...and the row left added[]", [r["path"] for r in again["added"] if r["path"] == "/dod"], [])
        check_eq("FR-7: without a project to read from there is no memory (the call stays pure)", C.unanswered_pointers(C.migration_plan(old)), ["/dod"])
        check_eq("FR-7: an explicit answers (even empty) no longer switches the memory off: it MERGES, so {} asks nothing the memory knows",
                 C.unanswered_pointers(C.migration_plan(old, answers={}, root=root)), [])
        moved = {**TEMPLATE, "dod": TEMPLATE["dod"] + " (new default)"}
        changed = C.migration_plan(old, root=root, template=moved)
        check_eq("FR-7: the template default of the key changed since: it is a new question, asked again", C.unanswered_pointers(changed), ["/dod"])
        # never for a key nobody asked: a recorded answer for an ordinary key is not pre-loaded
        ordinary = next(k for k, m in KEYS["keys"].items() if m.get("absent_means") == "default" and k in TEMPLATE and not k.endswith("_note"))
        with open(root / OA.APPROVALS_REL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"status": "approved", "approval_ref": "x", "answers": {f"/{ordinary}": "elsewhere"},
                                     "answer_defaults": {f"/{ordinary}": TEMPLATE[ordinary]}}) + "\n")
        lacking = copy.deepcopy(TEMPLATE)
        del lacking[ordinary]
        plan = C.migration_plan(lacking, root=root)
        check_eq("FR-7: memory is for required and re-asked rows ONLY: another key keeps the template default and shows no 'not asked' row",
                 (plan["proposed_config"][ordinary], [k for k in plan["kept"] if k["path"] == f"/{ordinary}"]), (TEMPLATE[ordinary], []))
        # the latest answer of a pointer wins; an unreadable line is skipped
        with open(root / OA.APPROVALS_REL, "a", encoding="utf-8") as handle:
            handle.write("{ this line is not json\n")
            handle.write(json.dumps({"status": "approved", "approval_ref": "m2", "answers": {"/dod": "The newer answer"},
                                     "answer_defaults": {"/dod": TEMPLATE["dod"]}}) + "\n")
        check_eq("FR-7: the latest record of a pointer wins, an unreadable line costs nothing",
                 C.migration_plan(old, root=root)["proposed_config"]["dod"], "The newer answer")
        # a not-approved record is no memory
        with open(root / OA.APPROVALS_REL, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"status": "declined", "approval_ref": "m3", "answers": {"/dod": "declined text"},
                                     "answer_defaults": {"/dod": TEMPLATE["dod"]}}) + "\n")
        check_eq("FR-7: a record that is not an approval is no memory", C.migration_plan(old, root=root)["proposed_config"]["dod"], "The newer answer")
    finally:
        cleanup(root)
    # the loop FR-7 closes: a re-asked key answered with a non-default value is asked again next plan
    table = copy.deepcopy(KEYS)
    table["reasked"] = {"cases_root": {"question": "Where do this project's cases live now?"}}
    with_access = copy.deepcopy(TEMPLATE)
    with_access["environment"]["access"] = copy.deepcopy(ACCESS)      # t-298: the access is recorded, so only /cases_root is the question
    moved_config = {**copy.deepcopy(with_access), "cases_root": "tests/cases"}
    root = temp_dir("qa-install-memory-reasked-")
    try:
        put(root, "qa-factory/config.json", json.dumps(moved_config, indent=2))
        first = C.migration_plan(moved_config, keys=table, answers={"/cases_root": "docs/cases"}, root=root)
        C.record_approval(root, first, "onboarding:r1", "t:r1")
        written = {**copy.deepcopy(with_access), "cases_root": "docs/cases"}
        put(root, "qa-factory/config.json", json.dumps(written, indent=2))
        check_eq("FR-7 reasked: with no memory (no project to read it from) the same question comes back after the answer was written (the bug)",
                 C.unanswered_pointers(C.migration_plan(written, keys=table)), ["/cases_root"])
        later = C.migration_plan(written, keys=table, root=root)
        check_eq("FR-7 reasked: with the memory it does not, and the person's value stands",
                 (C.unanswered_pointers(later), later["proposed_config"]["cases_root"], later["reasked"]), ([], "docs/cases", []))
    finally:
        cleanup(root)


# --- F-VERSION at SessionStart: session_env.py prints the version line, never breaks the hook ----------

def session_start_line() -> None:
    import hashlib as _hashlib
    import io
    import subprocess
    import tempfile
    import hooklib
    import session_env
    running = hooklib.version_carriers(None)["running"]["version"]
    top = temp_dir("qa-session-env-")
    session = "t232-" + uuid_hex()
    flag = Path(tempfile.gettempdir()) / ("qa-factory-version-" + _hashlib.sha1(session.encode("utf-8")).hexdigest()[:16])
    try:
        home, market = top / "claude", top / "market"

        def machine(source_version: str) -> None:
            put(home, "settings.json", json.dumps({"extraKnownMarketplaces": {hooklib.VERSION_MARKETPLACE: {"source": {"source": "directory", "path": str(market)}}}}))
            put(market, ".claude-plugin/marketplace.json", json.dumps({"name": hooklib.VERSION_MARKETPLACE, "plugins": [{"name": "qa-factory", "source": "./ai-packages/qa-factory"}]}))
            put(market, "ai-packages/qa-factory/.claude-plugin/plugin.json", json.dumps({"name": "qa-factory", "version": source_version}))

        def hook(payload: str, **env_more):
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_ENV_FILE"}
            env.update({"CLAUDE_CONFIG_DIR": str(home), "PYTHONDONTWRITEBYTECODE": "1", **env_more})
            return subprocess.run([sys.executable, "-B", str(HERE / "session_env.py")], input=payload, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=env, cwd=str(top), timeout=120)
        machine("99.0.0")
        started = hook(json.dumps({"session_id": session, "cwd": str(top)}))
        check_eq("session_env: carriers differ (the marketplace has 99.0.0) and the host supplies NO CLAUDE_ENV_FILE (the line goes before the "
                 "early return): exit 0, ONE line on stdout, nothing on stderr",
                 (started.returncode, len(started.stdout.strip().splitlines()), started.stderr.strip()), (0, 1, ""))
        check("...it is the version line, naming what runs and what the marketplace has",
              started.stdout.startswith("QA Factory versions differ: ") and "the marketplace has 99.0.0" in started.stdout, started.stdout[:300])
        again = hook(json.dumps({"session_id": session, "cwd": str(top)}))
        check_eq("session_env: the same session is told once (startup, resume, clear and compact all fire the hook)", (again.returncode, again.stdout), (0, ""))
        flag.unlink(missing_ok=True)
        # the carriers agree: nothing is printed
        machine(running)
        quiet = hook(json.dumps({"session_id": session + "-b", "cwd": str(top)}))
        check_eq("session_env: the carriers agree: nothing on stdout, exit 0", (quiet.returncode, quiet.stdout, quiet.stderr.strip()), (0, "", ""))
        # a payload that is not JSON, or has no session: no crash, and the line still comes when the carriers differ
        machine("99.0.0")
        for label, payload in (("not JSON", "{ not json"), ("empty", ""), ("a list", "[1, 2]")):
            got = hook(payload)
            check_eq(f"session_env: a payload that is {label}: exit 0 and no traceback", (got.returncode, "Traceback" in got.stderr), (0, False))
        # an exception inside the version call never breaks the hook: the session id is still written for the host
        env_file = top / "env.txt"
        saved_stdin, saved_stdout, saved_env = sys.stdin, sys.stdout, os.environ.get("CLAUDE_ENV_FILE")
        original = hooklib.session_start_version_line

        def boom(*_a, **_k):
            raise RuntimeError("the version note crashed")
        hooklib.session_start_version_line = boom
        sys.stdin, sys.stdout = io.StringIO(json.dumps({"session_id": "s-crash"})), io.StringIO()
        os.environ["CLAUDE_ENV_FILE"] = str(env_file)
        try:
            error = ""
            try:
                session_env.main()
            except Exception as exc:  # noqa: BLE001 - what is asserted is that none escapes
                error = repr(exc)
            printed = sys.stdout.getvalue()
        finally:
            hooklib.session_start_version_line = original
            sys.stdin, sys.stdout = saved_stdin, saved_stdout
            if saved_env is None:
                os.environ.pop("CLAUDE_ENV_FILE", None)
            else:
                os.environ["CLAUDE_ENV_FILE"] = saved_env
        check_eq("session_env: an exception in the version call: none escapes, nothing is printed, and the session id is still written",
                 (error, printed, env_file.read_text(encoding="utf-8") if env_file.exists() else None), ("", "", "CLAUDE_SESSION_ID=s-crash\n"))
    finally:
        flag.unlink(missing_ok=True)
        cleanup(top)


def uuid_hex() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


HERE = Path(__file__).resolve().parents[1]


# --- t-272 item 6: locks by class and kind --------------------------------------------------------------

ARTIFACT_LOCK = "qa-factory/artifacts/QA-1/.case-versions.lock"
CARRIED_LOCK = "qa-factory/state/cost/.writers/s1/state/events.lock"
EXIT_LOCK = "qa-factory/state/.exit_gate_blocks.json.lock"
FOLDER_LOCK = "qa-factory/state/.project-decisions.lock"
STALE_LOCK = "qa-factory/state/other-writer/state/events.lock"      # a stale lock no hook makes (t-363 B6: state/events.lock is hook-written)


def age(root: Path, rel: str, hours: float) -> None:
    stamp = time.time() - hours * 3600
    os.utime(root / rel, (stamp, stamp))


def locks_by_class() -> None:
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        put(root, ARTIFACT_LOCK, "0")
        put(root, CARRIED_LOCK, "0")
        put(root, EXIT_LOCK, "")
        (root / FOLDER_LOCK).mkdir()
        limit = OA.OLD_LOCK_HOURS
        for hours in (limit + 0.02, limit - 0.2):     # just BEYOND the limit, and just inside it
            age(root, EXIT_LOCK, hours)
            age(root, FOLDER_LOCK, hours)
            made = OA.plan(root, migration(root), context=CTX, date=DATE)
            by = {l["rel_path"]: l for l in made["locks"]}
            listed = sorted(r for r, l in by.items() if l["action"] == "listed")
            if hours > limit:
                check_eq(f"item 6: an old-generation folder lock older than {limit} h (here {hours:.2f}) is LISTED, with the carried-row locks, by name; "
                         "the hook-written exit gate OS lock is neither listed nor removed; the stale OS lock under state/ is the one to remove",
                         (listed, [r for r, l in by.items() if l["action"] == "remove"]),
                         (sorted([ARTIFACT_LOCK, CARRIED_LOCK, FOLDER_LOCK]), [STALE_LOCK]))
                check_eq("item 6: kinds and classes come from the table",
                         {r: (by[r]["kind"], by[r]["class"]) for r in by},
                         {ARTIFACT_LOCK: ("os", "carried"), CARRIED_LOCK: ("os", "carried"), EXIT_LOCK: ("os", "regenerated"),
                          FOLDER_LOCK: ("folder", "regenerated"), STALE_LOCK: ("os", "regenerated")})
                text = OA.render(made)
                check_eq("item 6: every listed lock is named in the text, none is only counted", [r in text for r in listed], [True] * 3)
                check_in("item 6: ...and the text says they are not removed", "never removed here", text)
            else:
                check_eq(f"item 6: AT/under the limit ({hours:.2f} h) the existence and folder locks are neither listed nor blocking nor removed (they may be held now)",
                         (sorted(r for r, l in by.items() if l["action"] == "listed"), made["blocked"], by[EXIT_LOCK]["action"], by[FOLDER_LOCK]["state"]),
                         (sorted([ARTIFACT_LOCK, CARRIED_LOCK]), None, "none", "recent"))
        age(root, EXIT_LOCK, limit + 5)
        age(root, FOLDER_LOCK, limit + 5)
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        ref = approve(root, made)
        C.record_fold(root, made["proposal"], ref)         # this run's fold receipt: the passport goes too, so nothing is left to do after
        before = {p: sha(root, p) for p in (ARTIFACT_LOCK, CARRIED_LOCK, EXIT_LOCK)}
        done = OA.apply(root, made, ref, date=DATE)
        regen = next(s for s in done["steps"] if s["step"] == "regenerate")["detail"]
        check_eq("item 6: apply removes ONLY the stale OS lock of a regenerated row (state/events.lock)", regen["locks"], {STALE_LOCK: "removed"})
        check_eq("item 6: the carried-row locks, the existence lock and the folder lock are all still there, bytes unchanged",
                 ([os.path.exists(root / p) for p in (ARTIFACT_LOCK, CARRIED_LOCK, EXIT_LOCK, FOLDER_LOCK)], {p: sha(root, p) for p in before}),
                 ([True] * 4, before))
        check_eq("item 6: the removed lock's empty folder is not left behind (a fresh install has none)", os.path.exists(root / STALE_LOCK), False)
        again = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("item 6 / K8: the listed locks stay listed (they are never removed) but are nothing to approve: nothing_to_do holds",
                 (again["nothing_to_do"], sorted(l["rel_path"] for l in again["locks"] if l["action"] == "listed")),
                 (True, sorted([ARTIFACT_LOCK, CARRIED_LOCK, FOLDER_LOCK])))
        # a lock under a carried row that a running writer holds still refuses the apply
        with held(root / ARTIFACT_LOCK):
            blocked = OA.plan(root, migration(root), context=CTX, date=DATE)
            check_eq("item 6: a HELD lock under a carried row is live and reported (t-288: the plan no longer stops; the apply refuses, see live_session_locks)",
                     ([l["rel_path"] for l in blocked["live_locks"]], [l["state"] for l in blocked["locks"] if l["rel_path"] == ARTIFACT_LOCK]),
                     ([ARTIFACT_LOCK], ["live"]))
    finally:
        cleanup(root)
    # a sealed listing cannot be made to remove a lock that is not removable (defence in depth: the table is asked at apply time)
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        put(root, ARTIFACT_LOCK, "0")
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        forged = copy.deepcopy(made)
        forged["proposal"]["listing"]["regenerate"].append({"rel_path": ARTIFACT_LOCK, "action": "remove", "by": "onboarding", "reason": "forged"})
        forged["proposal"]["proposal_hash"] = C.proposal_hash(forged["proposal"])      # re-sealed: the hash check passes, the table must still say no
        ref2 = approve(root, forged, "onboarding:forged")
        done = OA.apply(root, forged, ref2, date=DATE)
        check_eq("item 6: even a re-sealed listing that NAMES a carried-row lock does not remove it (the stale state/ lock still goes)",
                 (os.path.exists(root / ARTIFACT_LOCK), next(s for s in done["steps"] if s["step"] == "regenerate")["detail"]["locks"]),
                 (True, {STALE_LOCK: "removed"}))
    finally:
        cleanup(root)


# --- t-288: the onboarding runs INSIDE a session whose hooks hold locks --------------------------------------
# A live reinstall (headless onboarding session 34f8d442): `--listing` refused with "a factory session is
# running (.dashboard-writer/..., cost/.writers/34f8d442-.../...)": the first lock was the dashboard writer
# the session's own hook had started, the second the session's OWN activity capture. A ban with no door.

OWN_ID = "34f8d442-aaaa"
OWN_LOCK = f"qa-factory/state/cost/.writers/{OWN_ID}/state/events.lock"
OTHER_LOCK = "qa-factory/state/cost/.writers/9c0de111-bbbb/state/events.lock"
DASH_LOCK = "qa-factory/state/.dashboard-writer/state/events.lock"
SECTION = "Held right now by a running session (the apply waits for these, then refuses if still held):"


def ready(root: Path):
    """A plan of the old project and the person's recorded yes for it."""
    OA._run_script = Runner(DISCARDED)
    made = OA.plan(root, migration(root), context=CTX, date=DATE)
    return made, approve(root, made)


def live_session_locks() -> None:
    check_eq("K-RETRY: the window is 10 looks, 1 s apart (the spec's numbers, named here so a change is a decision)", (OA.LIVE_TRIES, OA.LIVE_WAIT_S), (10, 1.0))
    # --- K-LIST: the listing and the sealed proposal only READ: a held lock is a section and a field, never a refusal
    root = old_project()
    writers_open = []
    out = root.parent / (root.name + "-sealed.json")
    try:
        writers_open += [Writer(root / OWN_LOCK), Writer(root / OTHER_LOCK), Writer(root / DASH_LOCK)]
        put(root, "qa-factory/state/cost/.writers/9c0de111-bbbb/state/capture.owner", json.dumps({"pid": os.getpid(), "at": 1, "token": "t"}))
        before = snapshot(root)
        with session_env(OWN_ID):
            listing = run_script("onboard_apply.py", "--root", root, "--price-table-answer", "builtin", "--out", out, "--listing")
            plan_json = run_script("onboard_apply.py", "--root", root, "--price-table-answer", "builtin")
        check_eq("K-LIST: --listing with three held locks exits 0 and prints the plan (not a refusal)",
                 (listing.returncode, listing.stdout.startswith("What the factory will do after your"), listing.stderr.strip()), (0, True, ""))
        check_in("K-LIST: ...and the section that names what is held", SECTION, listing.stdout)
        tail = listing.stdout.split(SECTION)[1].split("\n\n")[0].splitlines()[1:]
        check_eq("K-LIST: one line per held lock: the dashboard writer (unknown holder), this session, the other session by the pid its record names",
                 tail, [f"  - {DASH_LOCK} - holder unknown",
                        f"  - {OWN_LOCK} - holder this session (the session this runs in: the apply does not wait for it)",
                        f"  - {OTHER_LOCK} - holder pid {os.getpid()}"])
        check_eq("K-LIST: --out wrote the sealed proposal although locks are held", (out.is_file(), "proposal_hash" in json.loads(out.read_text(encoding="utf-8"))), (True, True))
        check_eq("K-LIST: the listing, --out and the plan wrote nothing into the project", snapshot(root), before)
        made = json.loads(plan_json.stdout)
        check_eq("K-LIST: the plan JSON carries live_locks and is not blocked",
                 (plan_json.returncode, made["blocked"], [(l["rel_path"], l["holder"]) for l in made["live_locks"]]),
                 (0, None, [(DASH_LOCK, "unknown"), (OWN_LOCK, "this session"), (OTHER_LOCK, f"pid {os.getpid()}")]))
        with session_env(None):
            nobody = run_script("onboard_apply.py", "--root", root, "--price-table-answer", "builtin", "--listing")
        check_eq("K-LIST: with no CLAUDE_SESSION_ID the own writer is just one more unknown holder, and the listing still does not refuse",
                 (nobody.returncode, f"  - {OWN_LOCK} - holder unknown" in nobody.stdout), (0, True))
    finally:
        for w in writers_open:
            w.release()
        out.unlink(missing_ok=True)
        cleanup(root)
    # --- K-OWN: the apply ignores THIS session's writer and nobody else's
    root = old_project()
    try:
        w_own = Writer(root / OWN_LOCK)
        made, ref = ready(root)
        before = snapshot(root)
        with session_env(None):
            problem = refusal(lambda: OA.apply(root, made, ref, date=DATE))
        check("K-OWN: with no session id found nothing is taken for the caller's own: the apply refuses, naming the lock, the holder, the door and why the "
              "session could not be told apart", problem.startswith("ApplyRefused: A factory session is running")
              and f"{OWN_LOCK} (holder unknown): finish that session (its id is the folder name {OWN_ID})" in problem
              and "could not tell which session it runs in" in problem, problem)
        check_eq("K-OWN: ...and nothing was written", snapshot(root), before)
        with session_env("another-session-id"):
            problem = refusal(lambda: OA.apply(root, made, ref, date=DATE))
        check("K-OWN: another session's id is not this one: refused, and no 'not set' note (the id IS known)",
              f"{OWN_LOCK} (holder unknown): finish that session (its id is the folder name {OWN_ID})" in problem and "not set" not in problem, problem)
        with session_env(OWN_ID):
            done = OA.apply(root, made, ref, date=DATE)
        check_eq("K-OWN: with CLAUDE_SESSION_ID equal to the writer's folder the apply goes through", done["applied"], True)
        check_eq("K-OWN: ...and does not touch the held lock (still there)", (root / OWN_LOCK).is_file(), True)
        w_own.release()
    finally:
        cleanup(root)
    # the own writer is ignored, but a DIFFERENT live writer in the same project still refuses, even with the own id set
    root = old_project()
    writers_open = []
    try:
        writers_open += [Writer(root / OWN_LOCK), Writer(root / OTHER_LOCK)]
        made, ref = ready(root)
        with session_env(OWN_ID):
            problem = refusal(lambda: OA.apply(root, made, ref, date=DATE))
        check("K-OWN: the own writer is ignored and the other session's refuses: its path and its folder-name id are named, the own is not",
              f"{OTHER_LOCK} (holder unknown): finish that session (its id is the folder name 9c0de111-bbbb)" in problem and OWN_LOCK not in problem, problem)
    finally:
        for w in writers_open:
            w.release()
        cleanup(root)
    # --- K-RETRY: the dashboard writer lets go in seconds; the apply looks again before it refuses
    saved_sleep = OA._sleep
    try:
        for let_go_after, expect_applied in ((2, True), (OA.LIVE_TRIES - 1, True), (OA.LIVE_TRIES, False)):
            root = old_project()
            try:
                dash = Writer(root / DASH_LOCK)
                made, ref = ready(root)
                sleeps = []

                def fake_sleep(seconds, sleeps=sleeps, dash=dash, let_go_after=let_go_after):
                    sleeps.append(seconds)
                    if len(sleeps) == let_go_after:
                        dash.release()

                OA._sleep = fake_sleep
                before = snapshot(root)
                with session_env(OWN_ID):
                    if expect_applied:
                        done = OA.apply(root, made, ref, date=DATE)
                        problem = ""
                    else:
                        done, problem = None, refusal(lambda: OA.apply(root, made, ref, date=DATE))
                if expect_applied:
                    check_eq(f"K-RETRY: released after {let_go_after} wait(s) (look {let_go_after + 1} of {OA.LIVE_TRIES}) -> the apply proceeds; "
                             "it slept 1 s between looks and no longer", (done["applied"], sleeps), (True, [1.0] * let_go_after))
                else:
                    check_eq(f"K-RETRY: held through all {OA.LIVE_TRIES} looks -> 9 sleeps of 1 s, then a refusal", sleeps, [1.0] * (OA.LIVE_TRIES - 1))
                    check("K-RETRY: ...the refusal names the path, the holder and the door of the dashboard writer, and the number of looks",
                          f"{DASH_LOCK} (holder unknown): wait a moment and run the apply again" in problem
                          and "after 10 look(s), 1 s apart" in problem and "Nothing was changed" in problem, problem)
                    check_not_in("K-RETRY: ...with no 'release the lease' wording", "release the lease", problem)
                    check_eq("K-RETRY: ...and nothing was written", snapshot(root), before)
                dash.release()
            finally:
                cleanup(root)
    finally:
        OA._sleep = saved_sleep
    # --- K-STALE: a free lock of 0 bytes (the leftover shape: 106 writer folders, locks of 0-1 B) and an empty .writers/ folder are listed, never a refusal
    root = old_project()
    try:
        put(root, "qa-factory/state/cost/.writers/gone-1/state/events.lock", "")
        put(root, "qa-factory/state/cost/.writers/gone-2/state/events.lock", "0")
        (root / "qa-factory/state/cost/.writers/gone-3").mkdir(parents=True)
        for env_value in (None, OWN_ID):
            with session_env(env_value):
                made = OA.plan(root, migration(root), context=CTX, date=DATE)
            by = {l["rel_path"]: l for l in made["locks"]}
            zero = by["qa-factory/state/cost/.writers/gone-1/state/events.lock"]
            check_eq(f"K-STALE (env {env_value!r}): a 0-byte lock nobody holds is stale and LISTED (a carried row: never removed), with no holder",
                     (zero["state"], zero["action"], zero["holder"], zero["class"]), ("stale", "listed", "", "carried"))
            check_eq("K-STALE: ...nothing is live and the plan is not blocked", (made["live_locks"], made["blocked"]), ([], None))
            check_in("K-STALE: ...the text lists it among the locks left alone", "qa-factory/state/cost/.writers/gone-1/state/events.lock", OA.render(made))
        made, ref = ready(root)
        sleeps = []
        OA._sleep = sleeps.append
        try:
            with session_env(None):
                done = OA.apply(root, made, ref, date=DATE)
        finally:
            OA._sleep = saved_sleep
        check_eq("K-STALE: the apply goes through with no waiting, the 0-byte locks and the empty folder are left as they were",
                 (done["applied"], sleeps, (root / "qa-factory/state/cost/.writers/gone-1/state/events.lock").stat().st_size,
                  (root / "qa-factory/state/cost/.writers/gone-3").is_dir()), (True, [], 0, True))
    finally:
        cleanup(root)
    # --- K-TEXT: the phase text tells the role what to do with each stop
    phase = " ".join((HERE.parent / "skills" / "qa-onboarding" / "phases" / "p3-summary-gate.md").read_text(encoding="utf-8").split())
    check_in("K-TEXT: the listing's held-lock section is part of the text, not a stop (the listing never refuses)",
             'A section "Held right now by a running session" is part of the text, not a stop: show it with the rest (the listing never refuses;', phase)
    check_in("K-TEXT: only the apply refuses, and then the role shows its message and stops",
             "Only the apply refuses on a lock still held after it waited, and then you show its message (path, holder, the move) and stop.", phase)
    check_not_in("K-TEXT: the old sentence (the listing says a session is running: stop; release its lease) is gone", "or releases its lease", phase)


# --- t-272 items 2 and 8: undetermined files, the listing's noise, FR-10 ----------------------------------

def applied_project() -> Path:
    root = old_project()
    OA._run_script = Runner(DISCARDED + NEW_RECORDS + OLD_RECORDS)
    made = OA.plan(root, migration(root), context=CTX, date=DATE)
    ref = approve(root, made)
    C.record_fold(root, made["proposal"], ref)
    OA.apply(root, made, ref, date=DATE)
    return root


def undetermined_and_listing() -> None:
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        put(root, "qa-factory/state/odd-folder/deep/file.bin", "binary-ish")
        put(root, "qa-factory/state/doctor-install-smoke-broken.json", "{ not json")
        for n in range(58):
            put(root, f"docs/superpowers/qa-tasks/2026-09-{n % 28 + 1:02d}-task-{n}/.state.json", "{}")
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        moved = sorted(r["rel_path"] for r in made["retire"] if r["retire_mode"] == "move")
        check_eq("item 2: a file in a folder no row names is its own undetermined item (the folder is opened; none is moved whole)",
                 moved, sorted([NOTES, "qa-factory/state/odd-folder/deep/file.bin"]))
        check_eq("item 2: an unreadable item is listed as unknown, never moved", ([u["rel_path"] for u in made["unknown"]],
                 "qa-factory/state/doctor-install-smoke-broken.json" in [r["rel_path"] for r in made["retire"]]),
                 (["qa-factory/state/doctor-install-smoke-broken.json"], False))
        text = OA.render(made)
        check_in("item 2: the listing says they are SET ASIDE, with the day", f"moved to qa-factory/state/retired/{DATE}/", text)
        check_in("item 2: ...and names the undetermined file", "qa-factory/state/odd-folder/deep/file.bin", text.split("Will be set aside")[1])
        # item 8: the team's folders are ONE line with the count and the row's name
        kept = text.split("Kept, not touched:")[1].split("\n\n")[0].splitlines()[1:]
        check("item 8: 59 dev-factory folders are ONE line with the count and the row's own name, not 59 lines",
              len(kept) == 1 and "59 paths" in kept[0] and "the project's dev factory (superpowers)" in kept[0], str(kept[:3]))
        check_eq("item 8: the plan's JSON still holds every one of them (the person's text is short, the data is whole)",
                 len([n for n in made["not_ours_kept"] if "superpowers" in n["rel_path"]]), 59)
        OA.apply(root, made, approve(root, made), date=DATE)
        check_eq("item 2: apply moved both under retired/<day>/<same relative path>, and the unreadable one is where it was",
                 ([os.path.exists(root / f"qa-factory/state/retired/{DATE}/{p}") for p in (NOTES, "qa-factory/state/odd-folder/deep/file.bin")],
                  [os.path.exists(root / p) for p in (NOTES, "qa-factory/state/odd-folder/deep/file.bin", "qa-factory/state/doctor-install-smoke-broken.json")]),
                 ([True, True], [False, False, True]))
        check_eq("item 2: the empty folder the move left in state/ is gone (a fresh install has none)", os.path.exists(root / "qa-factory/state/odd-folder"), False)
        after = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("item 2 / K8: a second plan finds nothing to set aside (the moved copies are carried, under retired/)",
                 ([r["rel_path"] for r in after["retire"] if r["retire_mode"] == "move"], [n["rel_path"] for n in after["not_ours_kept"] if "retired" in n["rel_path"]]), ([], []))
    finally:
        cleanup(root)
    # a file changed since the factory wrote it stays in place (it is a person's now) and is listed as changed, never moved
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        I.write_manifest(root, [{"rel_path": NOTES, "class": "discarded"}])
        put(root, NOTES, "a person edited this\n")
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        OA.apply(root, made, approve(root, made), date=DATE)
        check_eq("item 2: changed_since_install stays in place (carried by the person's edit), listed",
                 ([c["rel_path"] for c in made["changed_since_install"]], os.path.exists(root / NOTES), NOTES in [r["rel_path"] for r in made["retire"]]),
                 ([NOTES], True, False))
    finally:
        cleanup(root)
    # a newer manifest retires nothing: not even the undetermined
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED)
        put(root, OA.MANIFEST_REL, json.dumps({"schema_version": 1, "package_version": "99.0.0", "entries": []}))
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("item 2: a newer factory's project: nothing is set aside, the unrecognised file is only reported", ([r for r in made["retire"]], [n["rel_path"] for n in made["not_ours_kept"] if n["reason"] == "unrecognised"]),
                 ([], [NOTES]))
    finally:
        cleanup(root)
    # FR-10: while a duplicate stands, the text does not say "nothing to do"
    root = applied_project()
    try:
        OA._run_script = Runner(DISCARDED)
        quiet = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("FR-10 precondition: the applied project has nothing to do", quiet["nothing_to_do"], True)
        put(root, "qa-factory/state/journal.jsonl", "a second, different copy of the journal\n")
        twin = OA.plan(root, migration(root), context=CTX, date=DATE)
        text = OA.render(twin)
        check_eq("FR-10: with a record in two different copies nothing_to_do is False and the listing prints the twin",
                 (twin["nothing_to_do"], [c.get("duplicate_of") for c in twin["changed_since_install"]] != [], text.startswith("Nothing to do"), "two different copies" in text),
                 (False, True, False, True))
    finally:
        cleanup(root)


# --- t-298 A: hook-written files are not retired, not hashed, not printed (B-250) -------------------------------

HOOK_FILES = ["qa-factory/state/dashboard-dirty.json", "qa-factory/state/dashboard-refresh.json"]
DASH_LOCK_REL = "qa-factory/state/.dashboard-writer/state/events.lock"


def cli(*args) -> tuple:
    """`onboard_apply.main(argv)` as the command line runs it: (exit code, stdout, stderr). In-process, so the regenerate scripts stay stubbed."""
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = OA.main([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


def hook_project(side: Path) -> tuple:
    """An old project with both hook files, the dashboard writer's stale lock, and the sealed proposal made through the command line
    (the `--out sealed --listing` of the summary). -> (root, sealed path, the listing text)."""
    root = old_project()
    OA._run_script = Runner(DISCARDED + NEW_RECORDS + OLD_RECORDS)
    for rel in HOOK_FILES:
        put(root, rel, "first bytes of " + rel)
    put(root, DASH_LOCK_REL, "0")
    answers = side / "answers.json"
    answers.write_text(json.dumps({ACCESS_PTR: ACCESS}), encoding="utf-8")
    sealed = side / "sealed.json"
    code, text, err = cli("--root", root, "--price-table-answer", "builtin", "--answers", answers, "--out", sealed, "--listing")
    check_eq("hook project: the summary (--out --listing) exits 0 and writes the sealed proposal", (code, err, sealed.is_file()), (0, "", True))
    return root, sealed, text


def hook_written_files() -> None:
    side = temp_dir("qa-hook-side-")
    try:
        # K-A4 (the Lead's key, K-RACE): a hook rewrites the two files between the summary and the apply; the apply neither refuses nor deletes
        root, sealed, text = hook_project(side)
        try:
            check_eq("K-A4: the summary's text names neither hook file, nor the dashboard writer's lock", [p in text for p in HOOK_FILES + [DASH_LOCK_REL]], [False] * 3)
            listing = json.loads(sealed.read_text(encoding="utf-8"))["listing"]
            check_eq("K-A4: ...and the sealed listing holds none of them (no sha of a file a running session rewrites)",
                     [p for p in HOOK_FILES if p in json.dumps(listing)], [])
            for rel in HOOK_FILES:
                put(root, rel, "NEW bytes written by a hook after the summary: " + rel)
            new_bytes = {rel: sha(root, rel) for rel in HOOK_FILES}
            proposal = json.loads(sealed.read_text(encoding="utf-8"))
            C.record_approval(root, proposal, "r", "t:r")
            C.record_fold(root, proposal, "r")
            code, out, err = cli("--root", root, "--proposal", sealed, "--apply", "--approval-ref", "r")
            result = json.loads(out) if out.strip().startswith("{") else {}
            check_eq("K-A4: --proposal sealed --apply --approval-ref r: exit 0, applied true", (code, result.get("applied"), err), (0, True, ""))
            check_eq("K-A4: both hook files still exist with the NEW bytes (not deleted, not set aside, not refused on)",
                     {rel: sha(root, rel) for rel in HOOK_FILES}, new_bytes)
            check_eq("K-A4: the stale lock of the dashboard writer is still there (neither removed nor counted)", os.path.exists(root / DASH_LOCK_REL), True)
            check_eq("K-A4: the stale lock of a row no hook rewrites WAS removed (only the flagged row's is left)", os.path.exists(root / STALE_LOCK), False)
            put(root, HOOK_FILES[1], "bytes of a hook that fired AFTER the apply")
            code, text2, err = cli("--root", root, "--listing")
            check_eq("K-A4: a second --listing starts with 'Nothing to do'", (code, text2.startswith("Nothing to do")), (0, True))
            code, out2, err = cli("--root", root)
            again = json.loads(out2) if out2.strip().startswith("{") else {}
            check_eq("K-A4: the second plan JSON: retire, write and regenerate are empty, nothing_to_do is true",
                     ([again.get(k) for k in ("retire", "write", "regenerate")], again.get("nothing_to_do")), ([[], [], []], True))
            check_eq("K-A4: ...while the lock is still reported as a lock, with action none", [(l["rel_path"], l["action"]) for l in again.get("locks", []) if "dashboard-writer" in l["rel_path"]],
                     [(DASH_LOCK_REL, "none")])
        finally:
            cleanup(root)
        # K-A5 (negative control, C2 kept): any OTHER listed file that changes between the summary and the apply still refuses, nothing written
        side2 = temp_dir("qa-hook-side2-")
        root, sealed, text = hook_project(side2)
        try:
            check_in("K-A5 setup: the discarded probe is in the summary (so the control is a real one)", DISCARDED[0], text)
            put(root, DISCARDED[0], '{"probe": "changed after the summary"}\n')
            proposal = json.loads(sealed.read_text(encoding="utf-8"))
            C.record_approval(root, proposal, "r", "t:r")
            C.record_fold(root, proposal, "r")
            snap = snapshot(root)
            code, out, err = cli("--root", root, "--proposal", sealed, "--apply", "--approval-ref", "r")
            check("K-A5: exit 1 and the refusal names the file that changed", code == 1 and
                  ("the project changed since the summary: " + DISCARDED[0]) in err, f"{code} {err[-300:]}")
            check_eq("K-A5: ...and nothing was written (every file byte for byte as it was)", snapshot(root), snap)
        finally:
            cleanup(root)
            cleanup(side2)
        # K-A6 (temporal): a proposal sealed by an OLDER package that lists a hook file with its sha, applied after the file changed
        for how in ("the apply() call", "the command line"):
            root = old_project()
            side3 = temp_dir("qa-hook-side3-")
            try:
                OA._run_script = Runner(DISCARDED + NEW_RECORDS + OLD_RECORDS)
                put(root, HOOK_FILES[0], "bytes the old listing saw")
                made = OA.plan(root, migration(root), context=CTX, date=DATE)
                old_sealed = copy.deepcopy(made["proposal"])
                old_sealed["listing"]["retire"].append({"rel_path": HOOK_FILES[0], "class": "regenerated", "retire_mode": "delete", "sha256": sha(root, HOOK_FILES[0]),
                                                        "source": "table", "generation": None, "requires": []})
                old_sealed["proposal_hash"] = C.proposal_hash(old_sealed)
                made["proposal"] = old_sealed
                ref = approve(root, made)
                C.record_fold(root, old_sealed, ref)
                put(root, HOOK_FILES[0], "bytes a hook wrote after the listing was sealed")
                changed = sha(root, HOOK_FILES[0])
                if how == "the apply() call":
                    done = OA.apply(root, made, ref, date=DATE)
                    rows = [r["result"] for r in done["retired"] if r["rel_path"] == HOOK_FILES[0]]
                    ok = done["applied"]
                else:
                    file = side3 / "old-sealed.json"
                    file.write_text(json.dumps(old_sealed), encoding="utf-8")
                    code, out, err = cli("--root", root, "--proposal", file, "--apply", "--approval-ref", ref)
                    result = json.loads(out) if out.strip().startswith("{") else {}
                    rows = [r["result"] for r in result.get("retired", []) if r["rel_path"] == HOOK_FILES[0]]
                    ok = bool(result.get("applied")) and code == 0
                check_eq(f"K-A6 ({how}): an older sealed listing that names a hook file with its old sha: the apply is NOT refused, the row says "
                         "'kept: rewritten by a running session'", (ok, rows), (True, ["kept: rewritten by a running session"]))
                check_eq(f"K-A6 ({how}): ...and the file is still there with the bytes the hook wrote", sha(root, HOOK_FILES[0]), changed)
            finally:
                cleanup(root)
                cleanup(side3)
        # K-A7 / K-A10: a hook file made AFTER the apply, and a stale writer lock: the next plan has nothing to do and writes nothing
        root = applied_project()
        try:
            OA._run_script = Runner(DISCARDED)
            quiet = OA.plan(root, migration(root), context=CTX, date=DATE)
            check_eq("K-A10 precondition: the applied project has nothing to do", quiet["nothing_to_do"], True)
            for rel in HOOK_FILES:
                put(root, rel, "a hook file made after the apply: " + rel)
            put(root, DASH_LOCK_REL, "0")
            after = OA.plan(root, migration(root), context=CTX, date=DATE)
            check_eq("K-A7: a hook file created after the apply: the next plan's `write` holds no manifest row (and nothing else)", after["write"], [])
            check_eq("K-A10: adding only hook files and a stale `.dashboard-writer` lock: nothing_to_do is true, no retire, no regenerate, no question",
                     (after["nothing_to_do"], after["retire"], after["regenerate"], after["needs_answers"]), (True, [], [], []))
            check_in("K-A10: the listing says so", "Nothing to do", OA.render(after))
            snap = snapshot(root)
            nothing = OA.apply(root, after, "", date=DATE)
            check_eq("K-A10: apply returns applied False with no approval and writes nothing (the snapshot is equal)",
                     (nothing["applied"], nothing["nothing_to_do"], snapshot(root) == snap), (False, True, True))
            # the proposal hash is never "of nothing": it covers the proposal, whatever the listing holds
            check_eq("K-A10: the hash still covers the proposal (the listing is empty but sealed)",
                     (after["proposal"]["proposal_hash"] == C.proposal_hash(after["proposal"]), after["proposal"]["listing"]),
                     (True, {"retire": [], "write": [], "regenerate": []}))
        finally:
            cleanup(root)
        # E(a): a lock held by a live foreign session is not a stale hook lock - it is waited for and refuses, whatever row it sits under
        root = applied_project()
        try:
            OA._run_script = Runner(DISCARDED)
            put(root, DASH_LOCK_REL, "0")
            with held(root / DASH_LOCK_REL):
                locks = {l["rel_path"]: l for l in OA.find_locks(root)}
                check_eq("E(a): a HELD hook-row lock stays live, with a holder (the flag only silences a STALE lock)",
                         (locks[DASH_LOCK_REL]["state"], locks[DASH_LOCK_REL]["action"], locks[DASH_LOCK_REL]["holder"] != ""), ("live", "none", True))
                made = OA.plan(root, migration(root), context=CTX, date=DATE)
                check_eq("E(a): ...the plan reports it under 'Held right now' and does not refuse; nothing_to_do can be True beside it",
                         (made["live_locks"] != [], made["nothing_to_do"], "Held right now" in OA.render(made)), (True, True, True))
        finally:
            cleanup(root)
        # K-B4b: "not now" answered once: the next plan asks nothing and there is nothing to do
        root = old_project()
        try:
            OA._run_script = Runner(DISCARDED + NEW_RECORDS + OLD_RECORDS)
            default = copy.deepcopy(TEMPLATE["environment"]["access"])
            made = OA.plan(root, migration(root, answers={ACCESS_PTR: default}), context=CTX, date=DATE)
            check_eq("K-B4b setup: 'not now' (the default, explicitly) closes the question", made["needs_answers"], [])
            ref = approve(root, made, "onboarding:b4b")
            C.record_fold(root, made["proposal"], ref)
            done = OA.apply(root, made, ref, date=DATE)
            again = migration(root, access_answer=False)
            check_eq("K-B4b: after the apply, the next plan with NO answers asks nothing (the memory answers) and says why",
                     (C.unanswered_pointers(again), [(k["path"], k["reason"]) for k in again["kept"] if k["path"] == ACCESS_PTR]),
                     ([], [(ACCESS_PTR, "answered earlier, not asked again")]))
            check_eq("K-B4b: ...and the install has nothing to do",
                     OA.plan(root, again, context=CTX, date=DATE)["nothing_to_do"], True)
            check_eq("K-B4b control: without the recorded approval's memory (a project that never answered) the same plan asks",
                     C.unanswered_pointers(C.migration_plan(C.read_config_file(root))), [ACCESS_PTR])
        finally:
            cleanup(root)
    finally:
        cleanup(side)
    # K-B5t: what the phase text tells the role about the keys the plan waits on (the sentences were registered before the run)
    phase = " ".join((HERE.parent / "skills" / "qa-onboarding" / "phases" / "p3-summary-gate.md").read_text(encoding="utf-8").split())
    for sentence in ("The keys the plan waits on are asked with the question text the plan gives each, and only those keys.",
                     "\"Keep everything as before\" does not answer them: a key with no earlier value has nothing to keep.",
                     "The answer is the whole value at the pointer the plan lists, given in `--answers`.",
                     "\"Not now\" is recorded as the key's current empty value, given in `--answers` like any answer, and is not asked again.",
                     "An answer that is not valid is refused before anything is written: correct it, seal again and ask \"yes\" again for the corrected summary."):
        check_in(f"K-B5t: p3 says: {sentence[:60]}...", sentence, phase)
    p2 = " ".join((HERE.parent / "skills" / "qa-onboarding" / "phases" / "p2-interview.md").read_text(encoding="utf-8").split())
    check_in("K-B6: p2 re-asks the access for a config with no `access`, or an empty `kind` and no recorded answer",
             "has no `access`, or one with an empty `kind` and no recorded answer", p2)


# --- t-363 B6 (B-250 remainder): the second listing after the apply and the session that just finished ------------

def second_listing_and_the_finished_session() -> None:
    """B-250 remainder: after `--apply` the second `--listing` must read "Nothing to do" although the session that ran
    the apply left a stale lock behind, while a lock of ANOTHER session still counts. MEASURED at step 0 (the lock files
    of a live project, the fixture and the apply's own journal): a lock is one byte `0` - there is no session id and no
    pid INSIDE it; the only identity is the folder name of a writer lock, `state/cost/.writers/<session id>/...`.
    That shape is a carried row, so a stale lock of this session there is LISTED, never removed and never counted:
    the listing already reads "Nothing to do" with it (pinned below, with the control that the same probe sees a lock
    that DOES count). The locks that DID break "Nothing to do" - `state/events.lock`, `state/.journal-writer/...` - carry
    no session id at all; they are HOOK-WRITTEN (hooklib journals from a running session's hooks), the class t-298
    settled for `.dashboard-writer`, so the table marks both rows `hook_written` (the Lead's decision): neither is
    removed, listed or counted. A stray lock of any other name has no such row and stays counted (edge 6, fail closed)."""
    root = applied_project()
    try:
        OA._run_script = Runner(DISCARDED)
        quiet = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("B6 precondition: the applied project has nothing to do", quiet["nothing_to_do"], True)
        put(root, OWN_LOCK, "0")
        check_eq("B6 shape: a session's lock file is ONE byte, `0`: no session id and no pid inside it",
                 (root / OWN_LOCK).read_bytes(), b"0")
        with session_env(OWN_ID):
            own = OA.plan(root, migration(root), context=CTX, date=DATE)
        row = next(l for l in own["locks"] if l["rel_path"] == OWN_LOCK)
        check_eq("B6: this session's own stale writer lock is listed and holds nothing back: nothing_to_do, no regenerate step",
                 (row["state"], row["action"], row["holder"], own["nothing_to_do"], own["regenerate"]), ("stale", "listed", "", True, []))
        check("B6: ...and the second listing starts with `Nothing to do`", OA.render(own).startswith("Nothing to do"), OA.render(own)[:80])
        put(root, OTHER_LOCK, "0")
        with session_env(OWN_ID):
            both = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("B6: ANOTHER session's stale lock is listed too, by name (it is nobody's to remove)",
                 sorted(l["rel_path"] for l in both["locks"] if l["action"] == "listed"), sorted([OWN_LOCK, OTHER_LOCK]))
        check_in("B6: ...and the text names it", OTHER_LOCK, OA.render(both))
        # another session's lock that is HELD right now still counts: it is live, and it is not this session's
        with held(root / OTHER_LOCK), held(root / OWN_LOCK):
            with session_env(OWN_ID):
                live = OA.plan(root, migration(root), context=CTX, date=DATE)["live_locks"]
                refusing = [l["rel_path"] for l in OA._live(OA.find_locks(root))]
        check_eq("B6: a lock of another session held right now is reported live, with its holder; this session's own is live too",
                 sorted(l["rel_path"] for l in live), sorted([OWN_LOCK, OTHER_LOCK]))
        check_eq("B6: ...but only the OTHER session's refuses the apply (this session's own is ignored by the apply)", refusing, [OTHER_LOCK])
        # the decision: the two hook-written locks and this session's own writer folder together -> "Nothing to do"
        events, journal = "qa-factory/state/events.lock", "qa-factory/state/.journal-writer/state/events.lock"
        put(root, events, "0")
        put(root, journal, "0")
        with session_env(OWN_ID):
            second = OA.plan(root, migration(root), context=CTX, date=DATE)
        rows = {l["rel_path"]: l for l in second["locks"]}
        check_eq("B6: with both hook-written locks and the own writer folder present, the second plan has nothing to do and removes nothing",
                 (second["nothing_to_do"], second["regenerate"], second["retire"], second["write"]), (True, [], [], []))
        check_eq("B6: ...the hook-written locks are reported as locks with action none (never removed, listed or counted)",
                 [(rows[p]["state"], rows[p]["action"]) for p in (events, journal)], [("stale", "none")] * 2)
        check("B6: ...and the second --listing starts with `Nothing to do`", OA.render(second).startswith("Nothing to do"), OA.render(second)[:80])
        # edge 6, fail closed: a stray lock the table names no hook-written row for stays COUNTED
        put(root, "qa-factory/state/stray-writer.lock", "0")
        with session_env(OWN_ID):
            stray = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("B6 control (edge 6): a stray *.lock with no hook-written row is counted and offered for removal",
                 (stray["nothing_to_do"], [r["rel_path"] for r in stray["regenerate"]]), (False, ["qa-factory/state/stray-writer.lock"]))
        # a held hook-written lock is still live: the flag silences a STALE lock only
        (root / "qa-factory/state/stray-writer.lock").unlink()
        with held(root / events):
            live_events = [l["rel_path"] for l in OA.find_locks(root) if l["state"] == "live"]
        check_eq("B6: a HELD hook-written lock is still live (it is waited for, then refuses)", live_events, [events])
    finally:
        cleanup(root)


# --- t-272 item 3: what git tracks, read only -----------------------------------------------------------------

def git(root: Path, *args) -> "subprocess.CompletedProcess":
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def git_tracking() -> None:
    root = old_project()
    saved = os.environ.get("GIT_CEILING_DIRECTORIES")
    try:
        OA._run_script = Runner(DISCARDED)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(root.parent)       # so a repository ABOVE the temp folder is not found
        plain = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("item 3: no git: ONE line, nothing checked, no lines",
                 (plain["tracking"]["line"], plain["tracking"]["checked"], plain["tracking"]["git_rm"]),
                 ("not a git repository: tracking not checked", False, []))
        check_in("item 3: ...and the listing prints that line", "not a git repository: tracking not checked", OA.render(plain))
        check_eq("item 3: no git: nothing_to_do is not held back by it", plain["nothing_to_do"], False)     # (there is plenty else to do here)
        os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        init = git(root, "init", "-q")
        check_eq("precondition: git init works here", init.returncode, 0)
        git(root, "add", "-A")
        git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "old install")
        index_before = (root / ".git" / "index").read_bytes()
        made = OA.plan(root, migration(root), context=CTX, date=DATE)
        t = made["tracking"]
        tracked_state = sorted(p for p in git(root, "ls-files", "--", "qa-factory/state").stdout.splitlines())
        check_eq("item 3: every tracked path under qa-factory/state/ is named, with its exact `git rm --cached` line",
                 (t["checked"], t["tracked_in_state"], [l for l in t["git_rm"] if "/state/" in l]),
                 (True, tracked_state, [f"git rm --cached {p}" for p in tracked_state]))
        changes = {(c["rel_path"], c["what"]) for c in t["tracked_changes"]}
        wanted = {("qa-factory/readiness.json", "deleted"), ("qa-factory/strategy/product-passport.md", "deleted"), (NOTES, "set aside"),
                  ("qa-factory/state/jira-probe-01a0.json", "deleted"), (STALE_LOCK, "deleted")}
        check_eq("item 3: a tracked deletion and a tracked set-aside are named (the old readiness report, the passport, the probe, a stale lock, the notes file)",
                 sorted(wanted - changes), [])
        check_eq("item 3: ...and the tracked records the install MOVES are named with where they go (a move of a tracked path)",
                 sorted((rel, what) for rel, what in changes if what.startswith("moved to")),
                 sorted((p, "moved to " + p.replace("/state/", "/records/")) for p in OLD_RECORDS))
        check_eq("item 3: every line of the plan is the line of a tracked path (nothing untracked is ever listed)",
                 sorted(t["git_rm"]), sorted(f"git rm --cached {p}" for p in set(t["tracked_in_state"]) | set(t["tracked_ignored"])
                                                                         | {c["rel_path"] for c in t["tracked_changes"]}))
        text = OA.render(made)
        check_in("item 3: the text says tracked inside the ignored folder", "Tracked inside the ignored folder", text)
        check_in("item 3: ...and a tracked deletion or move", "A tracked deletion or move", text)
        check_in("item 3: ...with the exact line", "git rm --cached qa-factory/state/journal.jsonl", text)
        check_not_in("FR-6: the text a person reads names no field of the plan (git_rm, tracking.git_rm)", "git_rm", text)
        check_not_in("FR-6: ...nor a script or plugin path", ".py", text)
        check_eq("item 3: the plan did not touch git: the index is byte-for-byte what it was, no lock left, nothing staged",
                 ((root / ".git" / "index").read_bytes() == index_before, (root / ".git" / "index.lock").exists(), git(root, "status", "--porcelain").stdout.strip()), (True, False, ""))
        check_eq("item 3: git rm lines exist, so there IS something to approve even for a project that is otherwise done", made["nothing_to_do"], False)
        done = OA.apply(root, made, approve(root, made), date=DATE)
        check_eq("item 3: apply does not run git either: the lines are the ROLE's (the index is unchanged by apply too)",
                 ((root / ".git" / "index").read_bytes() == index_before, (root / ".git" / "index.lock").exists()), (True, False))
        check_eq("item 3: the apply result carries the lines for what was ACTUALLY done (and the record keeps them)",
                 ("git_rm" in json.loads((root / done["record"]).read_text(encoding="utf-8")), done["tracking"]["checked"]), (True, True))
        # a project with a tracked, untouched record outside state/ is not nagged
        quiet_root = temp_dir("qa-git-quiet-")
        try:
            put(quiet_root, "qa-factory/strategy/test-strategy.md", "# s\n")
            git(quiet_root, "init", "-q")
            git(quiet_root, "add", "-A")
            q = OA.tracking(quiet_root, [])
            check_eq("item 3: tracked and untouched (strategy, outside state/): no line", (q["checked"], q["tracked_in_state"], q["git_rm"]), (True, [], []))
            q = OA.tracking(quiet_root, [("qa-factory/strategy/test-strategy.md", "deleted")])
            check_eq("item 3: the same file deleted by this run: one line", q["git_rm"], ["git rm --cached qa-factory/strategy/test-strategy.md"])
            put(quiet_root, "qa-factory/state/with space.json", "{}")
            git(quiet_root, "add", "-A")
            check_eq("item 3: a path with a space is quoted so the role can run the line as it stands",
                     OA.tracking(quiet_root, [])["git_rm"], ['git rm --cached "qa-factory/state/with space.json"'])
        finally:
            cleanup(quiet_root)
    finally:
        if saved is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = saved
        cleanup(root)


def hook_files_named_for_retirement() -> None:
    """K5 (t-319, critic t-312 F6): `--also-retire <a hook-written file>` was ACCEPTED - listed with a sha as a retirement - and
    then `_retire` kept it ("kept: rewritten by a running session"): the listing promised what the apply does not do. Now it
    is refused by name, with the reason, in the plan; a path OUTSIDE the table is still accepted (today's behaviour, control)."""
    root = old_project()
    try:
        OA._run_script = Runner(DISCARDED + NEW_RECORDS + OLD_RECORDS)
        for rel in HOOK_FILES:
            put(root, rel, "bytes of " + rel)
        put(root, DASH_LOCK_REL, "0")
        put(root, NOTES, "a person's own notes\n")
        made = OA.plan(root, migration(root), named=HOOK_FILES + [DASH_LOCK_REL, NOTES], context=CTX, date=DATE)
        listed = [r["rel_path"] for r in made["retire"]]
        check_eq("K5: no hook-written file is in the retire list, however it was named",
                 [rel for rel in HOOK_FILES + [DASH_LOCK_REL] if rel in listed], [])
        refusals = {r["rel_path"]: r["reason"] for r in made["refused"]}
        for rel in HOOK_FILES + [DASH_LOCK_REL]:
            check_in(f"K5: {rel} is refused by name, with the reason (a running session's hooks rebuild it)",
                     "hooks write this file", refusals.get(rel, ""))
        check_in("K5: ...and the reason says nothing was listed for removal", "nothing was listed for removal",
                 refusals.get(HOOK_FILES[0], ""))
        check_eq("K5 control: a path outside the table (an unrecognised notes file) named in the same call is still accepted",
                 (NOTES in listed, NOTES in refusals), (True, False))
        check_in("K5: the listing the person reads carries the refusal", "hooks write this file", OA.render(made))
        # through the command line, as the role runs it (the JSON plan)
        code, out, err = cli("--root", root, "--also-retire", HOOK_FILES[1])
        plan = json.loads(out) if out.strip().startswith("{") else {}
        check_eq("K5 CLI: `--also-retire <hook file>` exits 0 and refuses it in the plan, never lists it",
                 (code, [r["rel_path"] for r in plan.get("refused", []) if r["rel_path"] == HOOK_FILES[1]],
                  [r["rel_path"] for r in plan.get("retire", []) if r["rel_path"] == HOOK_FILES[1]]),
                 (0, [HOOK_FILES[1]], []))
        # a hook file that is NOT named is still never listed (the t-298 behaviour stays)
        quiet = OA.plan(root, migration(root), context=CTX, date=DATE)
        check_eq("K5: unnamed, the hook files are still not retire candidates",
                 [r["rel_path"] for r in quiet["retire"] if r["rel_path"] in HOOK_FILES], [])
    finally:
        cleanup(root)


def onboarding_notes_are_not_a_trace() -> None:
    """B-411 I1, I1b, I2: the onboarding run's own notes (qa-factory/state/onboarding/, a `before_install` row) are written before any
    install exists. They are never an install trace (p0 would say "traces of an earlier installation" on a project that never had one),
    never listed for retirement, and a run that was set aside or closed (retired/, done/) is under the same row. Every OTHER hit still counts."""
    notes_script = "onboarding_notes.py"

    def run(root, *args):
        return run_script(notes_script, "--root", root, *args)

    def preflight(root) -> dict:
        return json.loads(run_script("onboard_apply.py", "--root", root, "--preflight").stdout)

    def plan(root, *extra):
        """The plan as JSON, or (with `--listing`) the text a person reads."""
        proposal = root.parent / (root.name + "-proposal.json")
        config = copy.deepcopy(TEMPLATE)
        config["dod"] = "Done means reviewed and green"
        config["app_root"] = "."
        proposal.write_text(json.dumps({"proposed_config": config}), encoding="utf-8")
        try:
            done = run_script("onboard_apply.py", "--root", root, "--proposal", proposal, *extra)
            return done.stdout if extra else json.loads(done.stdout)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(proposal)

    root = temp_dir("qa-install-notes-")
    try:
        check_eq("I1 start: the run is opened by the real command", run(root, "start", "--tree", "clean").returncode, 0)
        q = root.parent / (root.name + "-q.json")
        q.write_text(json.dumps([{"topic": "t1", "text": "one?"}]), encoding="utf-8")
        run(root, "ask", "--batch", "b1", "--questions-file", q)
        words = root / "qa-factory" / "state" / "onboarding" / "words"
        words.mkdir(exist_ok=True)
        (words / "batch-b1-1.txt").write_text("their words", encoding="utf-8")
        run(root, "answer", "--batch", "b1", "--words-file", words / "batch-b1-1.txt", "--answered", "t1")
        check_eq("I1: the notes are on disk", (root / "qa-factory/state/onboarding/interview.yaml").is_file(), True)
        pre = preflight(root)
        check_eq("I1: a fresh project whose only content is the notes has no install", (pre["install_exists"], pre["config_present"], pre["table_hits"]), (False, False, []))
        out = plan(root)
        check_eq("I1: the plan agrees (install_exists false)", out["install_exists"], False)
        listed = [r["rel_path"] for r in out["retire"]]
        check_eq("I2: the plan lists none of the notes for retirement or set-aside", [p for p in listed if "state/onboarding" in p], [])
        check_eq("I2: ...nor as an unknown path or a refusal", [p for p in list(out["unknown"]) + list(out["refused"]) if "state/onboarding" in str(p)], [])
        check_not_in("I2: --listing (the text a person reads) does not name the notes", "state/onboarding", plan(root, "--listing"))
        # control: an old-generation file next to the notes still makes an install
        put(root, "qa-factory/state/jira-probe-01a0.json", "{}")
        pre = preflight(root)
        check_eq("I1 control: plus one old-generation file the install IS evidenced", (pre["install_exists"], pre["table_hits"]), (True, ["qa-factory/state/jira-probe-01a0.json"]))
        os.unlink(root / "qa-factory/state/jira-probe-01a0.json")
        # control: an unknown file next to the notes is listed for set-aside, the notes are not
        put(root, "qa-factory/state/mystery.bin", "?")
        out = plan(root)
        listed = [r["rel_path"] for r in out["retire"]]
        check("I2 control: an unknown file next to the notes IS listed, and still no note is", "qa-factory/state/mystery.bin" in listed
              and not [p for p in listed if "state/onboarding" in p], str(listed))
        text = plan(root, "--listing")
        check("I2 control: --listing names the unknown file and still not the notes", "mystery.bin" in text and "state/onboarding" not in text, text[:400])
        os.unlink(root / "qa-factory/state/mystery.bin")
        # the words row (F7): the person's words of a project decision are carried too, never set aside by a reinstall
        put(root, "qa-factory/state/words/topic-20261006-100000.txt", "their words")
        out = plan(root)
        check_eq("F7: a file in state/words/ is not listed for retirement either", [p for p in [r["rel_path"] for r in out["retire"]] if "state/words" in p], [])
        pre = preflight(root)
        check("F7: ...and a words file is a carried path of the factory: it IS a trace (it is not before_install)", pre["table_hits"] == ["qa-factory/state/words/topic-20261006-100000.txt"], str(pre["table_hits"]))
        os.unlink(root / "qa-factory/state/words/topic-20261006-100000.txt")

        # I1b: a run that was set aside is under the same row
        check_eq("I1b: set-aside", run(root, "set-aside").returncode, 0)
        check_eq("I1b: the run is under onboarding/retired/", sorted(os.listdir(root / "qa-factory/state/onboarding")), [".gitignore", "retired"])
        pre = preflight(root)
        check_eq("I1b: after start and set-aside on a fresh project, preflight gives install_exists false", (pre["install_exists"], pre["table_hits"]), (False, []))
        # ...and a closed run (done/) the same
        run(root, "start", "--tree", "clean")
        cfg_dir = root / "qa-factory" / "records"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "onboarding-approvals.jsonl").write_text(json.dumps({"approval_ref": "r1", "status": "approved"}) + "\n", encoding="utf-8")
        run(root, "phase", "--set", "p4", "--approval-ref", "r1")
        # OH3-29: `close` reads the live config; a healthy profile stands in it for the close only (the project has no install)
        config_file = root / "qa-factory" / "config.json"
        config_file.write_text(json.dumps({"schema_version": 1, "profiles": [
            {"profile_id": "api", "commands": {"one_test": {"argv": ["pytest", "<test-file>"]}}}]}), encoding="utf-8")
        check_eq("I1b: close", run(root, "close", "--approval-ref", "r1").returncode, 0)
        os.unlink(config_file)
        os.unlink(cfg_dir / "onboarding-approvals.jsonl")
        os.rmdir(cfg_dir)
        pre = preflight(root)
        check_eq("I1b: a closed run (done/) is not an install trace either", (pre["install_exists"], pre["table_hits"]), (False, []))
    finally:
        cleanup(root)
        with contextlib.suppress(OSError):
            os.unlink(root.parent / (root.name + "-q.json"))


def test_lock_state_of_a_vanished_file_is_unknown_and_creates_nothing() -> None:
    """TR4-2 part B (C9): `_lock_state` is the package's `file_lock_state`: a lock file that vanished since the scan is
    'unknown' and is NOT made again (it used to open `a+b` and create it); a free file is 'free' and stays 0 bytes."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qa-lock-state-") as td:
        gone = Path(td) / "vanished.lock"
        assert OA._lock_state(gone) == "unknown"
        assert not gone.exists(), "the probe created the file"
        free = Path(td) / "free.lock"
        free.write_bytes(b"")
        assert OA._lock_state(free) == "free"
        assert free.stat().st_size == 0, "the probe wrote into a 0-byte lock file"
        with held(free):                                    # a raw foreign holder (the test's own msvcrt / flock simulator)
            assert OA._lock_state(free) == "held"
        assert OA._lock_state(free) == "free"
        assert OA._lock_state(Path(td)) == "unknown", "a folder is not a lock file"


def main() -> None:
    test_lock_state_of_a_vanished_file_is_unknown_and_creates_nothing()
    saved = OA._run_script
    saved_sleep = OA._sleep
    OA._sleep = lambda seconds: None       # an apply that meets a held lock looks 10 times, 1 s apart: no test waits for it
    try:
        plan_shape_and_lists()
        listing_whole()
        apply_path()
        stale_summary()
        writers()
        newer_and_named()
        crash_midway()
        command_line()
        memory()
        session_start_line()
        locks_by_class()
        live_session_locks()
        undetermined_and_listing()
        hook_written_files()
        second_listing_and_the_finished_session()
        hook_files_named_for_retirement()
        git_tracking()
        onboarding_notes_are_not_a_trace()
    finally:
        OA._run_script = saved
        OA._sleep = saved_sleep
    finish("test_install_retire")


if __name__ == "__main__":
    main()
