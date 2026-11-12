"""A reinstall over an old-generation project ends with the tree a fresh install makes (spec t-232
section 5, keys K1-K14, owner's words 01.10 12:35). The judging file of `onboard_apply.compare_trees`.

Case B is the OLD installation: the fixture `fixtures/old-generation-project/` (a tree of files, never
written to; copied into a temp directory) put through the one apply path with the person's one "yes" and
this run's fold receipt. Case A is a FRESH project (empty but `git init`) given the same answers and the
carried files O had, in the places the new layout keeps them. `compare_trees(A, B, EXTRAS)` must find
nothing. The test builds both with the REAL readiness.py, factory_dashboard.py and check_coverage.py.

t-272 (the fix wave after critic t-268), each judged here: K1/K2 (the retire list now holds every regenerated file this
install does not rebuild, and the undetermined file is MOVED), K5 (the extras are DERIVED from the table and printed),
K-regen (state/ after the apply is exactly the rebuilt set; the retire record names the rest), K-lock (locks by class and
kind), K-git (`git init` + `git add` on a copy: the ignore block, the printed `git rm --cached` lines, the commit),
K-answer (the newer answer wins), K-normaliser (one path normaliser for the migration and the writer).

Mutations this file kills (each by this file alone):
  compare_trees ignores a differing byte | the extras list widened silently | the F2 value migration
  touches a person's own path | the tracker-write row back to carried (moved to records/) |
  compare_trees looks in one direction only | a regenerated file left in state/ | the undetermined file kept in
  place | a stale lock under a carried row removed | the git lines not printed | the receipt outranks a newer
  log answer | the normaliser not shared

Run: python -B scripts/tests/test_reinstall_equals_fresh.py        (the K-lines)
     python -B scripts/tests/test_reinstall_equals_fresh.py --smoke  (one line: what install_smoke prints)
"""
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import FIXTURES, RESULTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

use_project(temp_project("qa-reinstall-equals-fresh-audit-"))  # config_contract pulls audit_factory, which reads the hook layer

import config_contract as C  # noqa: E402
import install_paths as I  # noqa: E402
import onboard_apply as OA  # noqa: E402
import project_gitignore as G  # noqa: E402
import runtime_paths as RP  # noqa: E402
import tracker_write as TW  # noqa: E402

FIX = FIXTURES / "old-generation-project"
TEMPLATE = C.canonical_template()
VERSION = C.package_version()
DATE = "2026-10-01"
CONFIG = "qa-factory/config.json"
MANIFEST = OA.MANIFEST_REL
GEN1 = "qa-factory/artifacts/*/work/evidence/"
NOTES = "qa-factory/my-notes.md"
SUPERPOWERS = "docs/superpowers/qa-tasks/2026-09-04-qa-1"
PASSPORT = "qa-factory/strategy/product-passport.md"
SMOKE = "qa-factory/state/doctor-install-smoke-old.json"
SMOKE_NOFP = "qa-factory/state/doctor-install-smoke-nofp.json"       # a smoke report with NO package_fingerprint: foreign (t-272 item 1)
OLD_READINESS = "qa-factory/readiness.json"
SET_ASIDE_DIR = f"qa-factory/state/retired/{DATE}"
# t-272 item 1: the REGENERATED files O has that this install's regenerate step does NOT rebuild (a LITERAL list, one per
# regenerated row of the table the fixture can hold): each is a leftover nothing will use, deleted after the one "yes".
# NOT the two files a running session's hooks rewrite (dashboard-dirty.json, dashboard-refresh.json): the table flags them
# `hook_written` (t-298), so they are never retired and stay (HOOK_WRITTEN_KEPT below)
REGEN_UNBUILT = [f"qa-factory/state/{n}" for n in (
    "host-probe.json", "integrations/jira-direct-probe.json", "stand-lease.json", "execution-leases.json",
    ".exit_gate_blocks.json", "coverage-map.receipt.json", "scheduler-requests/r.json", "native-context/n.json")]
# t-298: the hook-written files O has: kept where they are, never listed, hashed or deleted; and the stale lock of the dashboard writer,
# which the install neither removes nor counts (its folder stays with it)
HOOK_WRITTEN_KEPT = [f"qa-factory/state/{n}" for n in ("dashboard-dirty.json", "dashboard-refresh.json")]
DASH_LOCK = "qa-factory/state/.dashboard-writer/state/events.lock"
# t-363 B6 / t-370: the event store's lock and the journal writer's lock are hook-written too (a running session's hooks make them again
# at each tool call): the install leaves them exactly as it leaves DASH_LOCK - not removed, not listed, not counted, their folder stays
HOOK_LOCKS = [f"qa-factory/state/{n}" for n in ("events.lock", ".journal-writer/state/events.lock")]
# the positive control: a stale OS lock of a regenerated row that NO hook makes (the generic state/**/*.lock row alone), which the install
# REMOVES as stale, never listed as retired. The fixture holds none (its two stubs are hook-written now), so build_b / k_lock put it in a
# copy before the apply - without it the removable set would be empty and the key would prove nothing.
CONTROL_LOCK = "qa-factory/state/other-writer/state/events.lock"
STALE_LOCKS = [CONTROL_LOCK]
# what the install deletes by name, and what it sets aside
DELETED = sorted([OLD_READINESS, SMOKE, SMOKE_NOFP, PASSPORT] + REGEN_UNBUILT)
SET_ASIDE = [NOTES]

# K6 / C3: the CARRIED set of O, a LITERAL list that does not ask classify() (that is the thing under
# test): (where O has it, where the new layout keeps it). Case A is seeded from this list.
CARRIED = [
    ("qa-factory/strategy/test-strategy.md", "qa-factory/strategy/test-strategy.md"),
    ("qa-factory/strategy/project-profile.md", "qa-factory/strategy/project-profile.md"),
    ("qa-factory/strategy/aspect-profile.md", "qa-factory/strategy/aspect-profile.md"),
    ("qa-factory/strategy/faq.md", "qa-factory/strategy/faq.md"),
    ("qa-factory/strategy/framework-rules.md", "qa-factory/strategy/framework-rules.md"),
    ("qa-factory/obligations.md", "qa-factory/obligations.md"),
    ("qa-factory/factory-backlog.md", "qa-factory/factory-backlog.md"),
    ("qa-factory/bugs/BUG-1.md", "qa-factory/bugs/BUG-1.md"),
    ("qa-factory/artifacts/QA-1/work/test-cases/a/TC-001.md", "qa-factory/artifacts/QA-1/work/test-cases/a/TC-001.md"),
    ("qa-factory/state/journal.jsonl", "qa-factory/records/journal.jsonl"),
    ("qa-factory/state/estimation-ledger.jsonl", "qa-factory/records/estimation-ledger.jsonl"),
    ("qa-factory/state/coverage-map.md", "qa-factory/records/coverage-map.md"),
    ("qa-factory/state/project-decisions.json", "qa-factory/records/project-decisions.json"),
    # K29 (t-300): the stand registry (the person's words about which build a stand runs) is carried byte for byte:
    # it already lives where the layout keeps it, so nothing moves - and a reinstall must neither retire nor rewrite it
    ("qa-factory/records/stand-identity.json", "qa-factory/records/stand-identity.json"),
]
# machine-local files O has that the install KEEPS where they are (price evidence, recovered metrics, a stand's history:
# CARRIED rows, one of which - stand-health.json - sits under the regenerated `stand-*.json` glob: precedence keeps it)
MACHINE_LOCAL_KEPT = ["qa-factory/state/host-receipts/r1.json", "qa-factory/state/host-receipts/r2.json",
                      "qa-factory/state/host-receipts/r3.json", "qa-factory/state/turns/t1.json",
                      "qa-factory/state/pre-0.7.0-recovery/metrics.json", "qa-factory/state/stand-health.json"]
# What the install REBUILDS in state/ (the regenerate step's outputs, the table's `regenerate_step`) - the carried history files
# the dashboard run also writes (metrics-history.json, metric-signals.json) are in the set: a fresh install makes them too.
REBUILT = [f"qa-factory/state/{n}" for n in ("readiness.json", "factory-dashboard.html", "integrations/tracker-write.json",
                                             "metrics.json", "metrics-history.json", "metric-signals.json")]
NOT_OURS = [SUPERPOWERS + "/.state.json"]


def derived_extras() -> list:
    """K5 (t-272 item 1): what tree B legitimately has and tree A has not, DERIVED from the install table - the carried
    machine-local rows (price evidence, history, what an earlier reinstall set aside) and the not_ours rows (the team's
    dev factory) - plus the two carried files this very run writes (its approval and the config backup). No hand list:
    a row added to the table is covered, and a file nobody declared is a difference."""
    rules = I.load_table()["rules"]
    return ([r["glob"] for r in rules if r["class"] == "carried" and r.get("machine_local")]
            + [r["glob"] for r in rules if r["class"] == "not_ours"]
            + [r["glob"] for r in rules if r.get("hook_written")]       # t-298: rewritten by a running session's hooks, kept by the reinstall
            + ["qa-factory/records/onboarding-approvals.jsonl", "qa-factory/records/config-migrations/**"])


EXTRAS = derived_extras()
# The manifest records, per file, the input hash of the run that wrote it; a fresh install ran from NO
# configuration and the reinstall from O's, so that one field differs by construction (everything else
# in the manifest - paths, classes, sha256 of every file, the version - must be equal).
#
# The tracker-write receipt is a PROBE CACHE (tracker_write.py): the readiness step of the very install
# asks again and rewrites it, in A and in B alike. It is machine-local, stays in state/ and is compared by
# NAME only (no field is excused for it); the one thing a reinstall carries of it is the person's own
# `answered` evidence, which lives in the approvals log (asserted under F1 below).
RECEIPT = "qa-factory/state/integrations/tracker-write.json"
IGNORED_FIELDS = {MANIFEST: ["input_hash"]}

# O's answers, as the person gave them (case A's proposal is the template with these)
PERSON_NOTE = ("Root of the test repository, relative to the project root (never absolute - audit A20) - set when tests live in a repo "
               "separate from the application code (qa-scout treats app repo and test repo as distinct inputs). Here the browser tests "
               "live in the e2e/ folder of this repository.")
PORTABLE_PROBE = {"argv": ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--probe"], "cwd": ".", "timeout_s": 60}
ANSWERS = {"dod": "Done means the change is reviewed and the suite is green in CI.", "tests_root": "tests",
           "protected_app_paths": ["src"]}
SEVEN_KEYS = ["requirements_sources", "strategy_documents", "records_policy", "format_changed", "format_all", "metrics"]


def put(root: Path, rel: str, text: str = "x") -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)      # the smoke does the same; no git is no reason to fail


def copy_fixture(into: Path, fix: Path = FIX) -> Path:
    shutil.copytree(fix, into)
    return into


def old_config() -> dict:
    return json.loads((FIX / CONFIG).read_text(encoding="utf-8"))


def fresh_config() -> dict:
    """What the role would propose for O's project from discovery: the template and O's answers (the
    person's own wording of a note, and a portable probe, are answers too)."""
    cfg = copy.deepcopy(TEMPLATE)
    cfg.update(copy.deepcopy(ANSWERS))
    cfg["execution"]["runtime_probes"] = {"api": copy.deepcopy(PORTABLE_PROBE)}
    cfg["answers_legacy"] = {"tests_root_note": PERSON_NOTE}
    return cfg


def approve_and_apply(root: Path, made: dict, ref: str, fold: bool = False) -> dict:
    C.record_approval(root, made["proposal"], ref, "test:evidence")
    if fold:
        C.record_fold(root, made["proposal"], ref)         # the role's fold step: this run's receipt for the passport
    return OA.apply(root, made, ref, date=DATE)


def build_a(tmp: Path, fix: Path = FIX) -> Path:
    """Case A: a fresh project: `git init`, the project's own .gitignore lines, O's carried files in the
    places the layout keeps them, the role's proposal for O's answers. `fix` is the old project (the fixture, or a
    copy of it in another line-ending form: B-409)."""
    root = tmp / "a"
    root.mkdir()
    git_init(root)
    for old, new in CARRIED:
        target = root.joinpath(*new.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fix.joinpath(*old.split("/")), target)
    # B-409: the project's own .gitignore keeps ITS line endings in tree A as it does in tree B (read as bytes, never through
    # universal newlines, and `keepends` keeps each line's terminator). A fresh install on the SAME project meets the same
    # bytes as the reinstall; with a text-mode read tree A was always LF and a CRLF checkout of the fixture turned K5 red
    # on a difference the writer had not made - or, worse, hid one it had.
    own = "".join(line for line in (fix / ".gitignore").read_bytes().decode("utf-8").splitlines(keepends=True) if line.strip() != GEN1)
    (root / ".gitignore").write_text(own, encoding="utf-8", newline="")
    made = OA.plan(root, {"proposed_config": fresh_config()}, date=DATE)
    approve_and_apply(root, made, "onboarding:a1")
    return root


NOT_NOW = {"/environment/access": copy.deepcopy(TEMPLATE["environment"]["access"])}


def migrate(root: Path, answer: bool = True) -> dict:
    """The migration plan of a copy of the old installation. t-298: `environment.access` is asked until answered and the old config
    records none, so the plan opens that pointer; these cases are about the tree, not the question, so the person answers "not now"
    (the template default, given explicitly) - the config a fresh install writes, which is what K3 compares. `answer=False` gives no
    answers: the memory of the first approval must then answer by itself (K8)."""
    return C.migration_plan(C.read_config_file(root), root=root, answers=copy.deepcopy(NOT_NOW) if answer else None)


def build_b(tmp: Path, named=(), fix: Path = FIX) -> tuple:
    """Case B: the old installation, reinstalled. -> (root, plan, apply result)."""
    root = copy_fixture(tmp / "b", fix)
    put(root, CONTROL_LOCK, "0")            # the positive control of the lock keys (see CONTROL_LOCK)
    git_init(root)
    proposal = migrate(root)
    made = OA.plan(root, proposal, named=list(named), date=DATE)
    done = approve_and_apply(root, made, "onboarding:b1", fold=True)
    return root, made, done


def compare(a: Path, b: Path) -> dict:
    return OA.compare_trees(a, b, EXTRAS, ignore_json_fields=IGNORED_FIELDS)


def summary(result: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in result.items() if v) or "equal"


# --- the main comparison: K1..K10 ---------------------------------------------------------------------

def the_comparison(tmp: Path) -> tuple:
    sentinel = tmp / "outside.txt"
    sentinel.write_text("outside the project\n", encoding="utf-8")
    sentinel_sha = sha(sentinel)
    adversarial = ["../outside.txt", str(sentinel), "/etc/passwd", "C:\\Windows\\system.ini", "qa-factory/../../outside.txt",
                   CONFIG, "qa-factory/state/host-receipts/r1.json", "qa-factory/strategy"]
    recorded = json.loads((FIX / "qa-factory/state/integrations/tracker-write.json").read_text(encoding="utf-8"))["answered"]["fingerprint"]
    check_eq("fixture precondition: the fingerprint inside the fixture's tracker-write `answered` is the one of the channel settings "
             "the migrated configuration has (else the probe rightly drops it; set the fixture's value to this one)",
             TW.fingerprint(fresh_config()), recorded)
    started = time.time()
    a = build_a(tmp)
    b, made, done = build_b(tmp, named=adversarial)
    took = time.time() - started

    # K1
    check_eq("K1: the retire list of case B is exactly the old readiness report, the stale smokes (a foreign fingerprint and NO fingerprint), the passport, "
             "the eight regenerated files this install does not rebuild, and the one undetermined file set aside "
             "(price evidence, records, receipts, history and recovery are carried: none is in it; neither are the two hook-written files, t-298)",
             [r["rel_path"] for r in made["retire"]], sorted(DELETED + SET_ASIDE))
    check_eq("K1 (t-298): the two hook-written files are in NO list of the plan: not retired, not listed, not in the sealed listing, not in the text",
             ([p for p in HOOK_WRITTEN_KEPT if p in {r["rel_path"] for r in made["retire"]}],
              [p for p in HOOK_WRITTEN_KEPT if p in json.dumps(made["proposal"]["listing"])], [p for p in HOOK_WRITTEN_KEPT if p in OA.render(made)]), ([], [], []))
    check_eq("K1: the 12 are DELETED by the apply (the passport on THIS run's fold receipt), the undetermined one is MOVED",
             sorted((r["rel_path"], r["result"]) for r in done["retired"]), sorted([(p, "deleted") for p in DELETED] + [(NOTES, "moved")]))
    # K2
    check_eq("K2 (t-272): not ours, kept: exactly the team's dev-factory folder (its not_ours row); qa-factory/my-notes.md is no longer kept, it is MOVED",
             sorted(n["rel_path"] for n in made["not_ours_kept"]), [SUPERPOWERS])
    check_eq("K2: the notes file is under retired/<day>/<same relative path>, gone from where it was, sha256 before == after; the dev factory is untouched",
             ([sha(b / p) == sha(FIX / p) for p in NOT_OURS], os.path.exists(b / NOTES), sha(b / SET_ASIDE_DIR / NOTES) == sha(FIX / NOTES)),
             ([True], False, True))
    # K3
    cfg_a, cfg_b = json.loads((a / CONFIG).read_text(encoding="utf-8")), json.loads((b / CONFIG).read_text(encoding="utf-8"))
    check_eq("K3: the configuration of case B equals case A, byte for byte", (b / CONFIG).read_bytes() == (a / CONFIG).read_bytes(), True)
    check("K3: deprecated keys are gone (audit_cadence_days, adapters.test_management.adapter) and the six whole keys and "
          "environment.access are present with the values a fresh install writes",
          "audit_cadence_days" not in cfg_b and "adapter" not in cfg_b["adapters"]["test_management"]
          and all(cfg_b[k] == TEMPLATE[k] for k in SEVEN_KEYS) and cfg_b["environment"]["access"] == TEMPLATE["environment"]["access"], str(list(cfg_b)[:8]))
    check_eq("K3: runtime_probes, by the rule the code AS BUILT applies to BOTH cases (an absolute argv is dropped to be derived again on "
             "this machine, the portable {python}/{plugin_root} form is kept)",
             (cfg_a["execution"]["runtime_probes"], cfg_b["execution"]["runtime_probes"]),
             ({"api": PORTABLE_PROBE}, {"api": PORTABLE_PROBE}))
    check_eq("K3: the person's wording of the note moved whole to answers_legacy, the note is the template's text again",
             (cfg_b["answers_legacy"], cfg_b["tests_root_note"]), ({"tests_root_note": PERSON_NOTE}, TEMPLATE["tests_root_note"]))
    check_eq("K3 / F2: journal_path still held the old default exactly: it names the new place, in both cases, and the plan said so",
             (cfg_a["journal_path"], cfg_b["journal_path"], {"path": "/journal_path", "reason": "changed: default path renamed"} in made["proposal"]["kept"]),
             ("qa-factory/records/journal.jsonl", "qa-factory/records/journal.jsonl", True))
    check_in("F2 / item 5: the listing a person reads says it, in the factory's words", "changed: default path renamed", OA.render(made))
    check_not_in("F2 / item 5: ...and the value DOES change, so the old word is not there", "kept: default path renamed", OA.render(made))
    # K4
    gi = (b / ".gitignore").read_text(encoding="utf-8").splitlines()
    block = list(G.GITIGNORE_BLOCK)
    start = gi.index(block[0]) if block and block[0] in gi else -1
    check_eq("K4: .gitignore: the project's own two lines stay first and unchanged", gi[:2], ["node_modules/", ".env"])
    check_eq("K4: ...the block (taken from project_gitignore.GITIGNORE_BLOCK at test time) is ONE contiguous piece", gi[start:start + len(block)], block)
    check_eq("K4: ...the first-generation line stands exactly once, nothing else of the old kinds, one line for state/ and none for records/",
             (gi.count(GEN1), gi.count("qa-factory/state/"), [l for l in gi if "records" in l]), (1, 1, []))
    check_eq("K4: the two-folder block is the derived one: state/ is ignored whole, records/ is not named", "qa-factory/state/" in block and not any("records" in l for l in block), True)
    # K5
    result = compare(a, b)
    in_b = set(OA._tree_files(b))
    covered = sorted(r for r in in_b if OA._is_extra(r, EXTRAS))
    expected_covered = sorted(set(MACHINE_LOCAL_KEPT + NOT_OURS + HOOK_WRITTEN_KEPT + HOOK_LOCKS + [DASH_LOCK, f"{SET_ASIDE_DIR}/retire-record.json", f"{SET_ASIDE_DIR}/{NOTES}",
                                                                  "qa-factory/state/metrics-history.json", "qa-factory/state/metric-signals.json",
                                                                  "qa-factory/records/onboarding-approvals.jsonl"])
                              | {r for r in in_b if r.startswith("qa-factory/records/config-migrations/")})
    print(f"INFO: K5 extras, DERIVED from the table ({len(EXTRAS)}): {EXTRAS}")
    for described in OA.difference_lines(a, b, result, ignore_json_fields=IGNORED_FIELDS):      # B-409: a red K5 says HOW the file differs
        print(f"INFO: K5 difference: {described}")
    check_eq("K5: (tree B) - (declared extras) == (tree A): nothing missing either way, nothing differing "
             f"[extras = the table's carried machine-local rows + not_ours rows + the approval log + the config backup; manifest field ignored: {IGNORED_FIELDS}]",
             result, {"missing_in_a": [], "missing_in_b": [], "differing": []})
    check_eq("K5: the extras hide exactly what they are declared for in B (no widening: every file they cover is a kept machine-local file, a history file "
             "the dashboard run writes, a not-ours file, what was set aside and its record, the approval log or the config backup, or - derived from the "
             "table's `hook_written` rows - the two hook-written files and the three hook-written stale locks the install leaves: the dashboard writer's, the "
             "journal writer's and the event store's)", covered, expected_covered)
    check_eq("K5: and a config backup of O exists (the extra is not dead)", len([r for r in covered if "config-migrations" in r]), 1)
    # K-regen (t-272 item 1): state/ holds exactly the rebuilt set (and the kept carried files); the retire record names the rest
    in_state = sorted(r for r in in_b if r.startswith("qa-factory/state/") and not r.startswith("qa-factory/state/retired/"))
    print(f"INFO: K-regen, state/ after the reinstall ({len(in_state)}): {in_state}")
    check_eq("K-regen: after the apply state/ holds EXACTLY the rebuilt set (readiness, dashboard, metrics projection and history, the probe cache), "
             "the carried machine-local files O had, the two hook-written files (kept, t-298) and the three hook-written stale locks (the dashboard "
             "writer's, the journal writer's and the event store's: neither removed nor counted, t-363 B6) - no other leftover of a regenerated row, "
             "no other lock (the control lock of a row no hook rewrites is GONE), no smoke",
             in_state, sorted(REBUILT + MACHINE_LOCAL_KEPT + HOOK_WRITTEN_KEPT + [DASH_LOCK] + HOOK_LOCKS))
    check_eq("K-regen (t-298): the hook-written files are byte-equal to O's (the install did not touch them)",
             [sha(b / p) == sha(FIX / p) for p in HOOK_WRITTEN_KEPT], [True, True])
    check_eq("K-regen: ...metrics.json is REBUILT (the fixture's old bytes are gone), not kept as it was",
             sha(b / "qa-factory/state/metrics.json") != sha(FIX / "qa-factory/state/metrics.json"), True)
    record = json.loads((b / done["record"]).read_text(encoding="utf-8"))
    check_eq("K-regen: the retire record names the rest: every deleted file with its sha256, the one set aside, and the one stale lock removed "
             "(the control lock of a row no hook rewrites; the dashboard writer's, the journal writer's and the event store's are not named: a hook-written "
             "row's stale lock is left, t-298 / t-363 B6)",
             (sorted(r["rel_path"] for r in record["retired"] if r["result"] == "deleted"), [r["rel_path"] for r in record["retired"] if r["result"] == "moved"],
              sorted(k for k, v in record["locks"].items() if v == "removed"), all(len(r.get("sha256", "")) == 64 for r in record["retired"]),
              [p in record["locks"] for p in HOOK_LOCKS + [DASH_LOCK]]),
             (DELETED, SET_ASIDE, sorted(STALE_LOCKS), True, [False, False, False]))
    check_eq("K-regen: the folders the removed files left behind are gone too (a fresh install has none) - except `.dashboard-writer` and `.journal-writer`, "
             "which stay with their (hook-written) locks, the locks themselves present, and the control lock's folder `other-writer`, which is gone",
             ([os.path.exists(b / "qa-factory/state" / d) for d in ("scheduler-requests", "native-context", ".dashboard-writer", ".journal-writer", "other-writer")],
              [os.path.isfile(b / p) for p in HOOK_LOCKS + [DASH_LOCK]]),
             ([False, False, True, True, False], [True, True, True]))
    check_eq("item 1 invariant: nothing carried was retired: stand-health.json (carried, under the regenerated `stand-*.json` glob) is byte-equal to O's",
             (sha(b / "qa-factory/state/stand-health.json") == sha(FIX / "qa-factory/state/stand-health.json"),
              "qa-factory/state/stand-health.json" in [r["rel_path"] for r in made["retire"]]), (True, False))
    # K6
    check_eq("K6: every carried file of case B is byte-equal to O's (read from the fixture, in the place the layout keeps it)",
             [(new, sha(b.joinpath(*new.split("/"))) == sha(FIX.joinpath(*old.split("/")))) for old, new in CARRIED],
             [(new, True) for _, new in CARRIED])
    check_eq("K6: ...the machine-local files O kept are where they were, byte for byte; and nothing carried is left in the old place",
             ([sha(b / p) == sha(FIX / p) for p in MACHINE_LOCAL_KEPT], [os.path.exists(b / old) for old, new in CARRIED if old != new]),
             ([True] * len(MACHINE_LOCAL_KEPT), [False] * len([1 for o, n in CARRIED if o != n])))
    # F1
    old_receipt = json.loads((FIX / RECEIPT).read_text(encoding="utf-8"))
    new_receipt = json.loads((b / RECEIPT).read_text(encoding="utf-8")) if (b / RECEIPT).is_file() else {"checked_at": old_receipt["checked_at"]}
    check_eq("F1: the tracker-write receipt is a probe cache: it STAYS in state/ (never moved to records/), in both cases, and the code reads it there",
             (os.path.exists(b / RECEIPT), os.path.exists(b / "qa-factory/records/tracker-write.json"), os.path.exists(a / RECEIPT),
              os.path.exists(a / "qa-factory/records/tracker-write.json"), TW.receipt_path(b) == b / RECEIPT),
             (True, False, True, False, True))
    check_eq("F1: an OLD receipt that carries `answered` and has no approvals line (the world before this decision) keeps working: the install's own "
             "probe read it in place, kept the person's `answered` whole and rewrote the clock",
             (new_receipt.get("answered"), new_receipt["checked_at"] != old_receipt["checked_at"]), (old_receipt["answered"], True))
    # the person's answer outlives the cache: --record also appends it to the carried approvals log, and a probe that finds no
    # `answered` in the receipt (a fresh clone has no state/) reads the latest such line
    survivor = tmp / "b-answer"
    shutil.copytree(b, survivor)
    approvals = C.approvals_path(survivor)
    lines_before = approvals.read_text(encoding="utf-8")
    approval_before = C._approval_record(survivor, "onboarding:b1", made["proposal"])
    said = TW.record(fresh_config(), survivor, TW.CONFIRMED, "the assistant answered: it can create issues")
    appended = approvals.read_text(encoding="utf-8")[len(lines_before):]
    line = json.loads(appended) if appended.strip() else {}
    check_eq("F1: --record appends ONE line to the carried approvals log (records/, the file config_contract reads), after the lines already there, "
             "of kind tracker_write_answer with the channel, the answer and the time",
             (appended.endswith("\n") and appended.count("\n") == 1, sorted(line), line.get("kind"), line.get("answered") == said["answered"],
              approvals == survivor / "qa-factory/records/onboarding-approvals.jsonl", approvals.read_text(encoding="utf-8").startswith(lines_before)),
             (True, sorted(["answered", "at", "channel", "kind"]), "tracker_write_answer", True, True, True))
    check_eq("F1: ...and config_contract still reads its own approvals around the new line (the approval of this run resolves to the same record)",
             C._approval_record(survivor, "onboarding:b1", made["proposal"]), approval_before)
    os.unlink(survivor / RECEIPT)
    carried = TW.probe(fresh_config(), survivor, where="doctor")
    check_eq("F1: the receipt gone (a clone: state/ is ignored), the next probe still has the person's `answered`, from the approvals line",
             (carried.get("answered"), TW.receipt_path(survivor).is_file()), (said["answered"], True))
    # K-answer (t-272 item 4): receipt and log are ONE pool of answers about this setup; the NEWER `at` wins
    # a channel whose own probe is UNVERIFIED (an assistant nobody asked): the person's answer is what decides the status. (O's fixture
    # config keeps its bugs in markdown, where the probe's own answer is `no`, so it cannot show which answer wins.)
    agent_cfg = {"external_writes": {"bugs": "jira", "channels": {"jira": {"method": "agent", "invoke": "jira-rw-assistant-cli", "writes": True}}},
                 "adapters": {"ticket": {"project_keys": ["TP2"]}}}
    fp = TW.fingerprint(agent_cfg)
    other = TW.fingerprint({**agent_cfg, "adapters": {"ticket": {"project_keys": ["ELSEWHERE"]}}})
    check("K-answer precondition: a changed channel setting is another fingerprint", other != fp, f"{fp} {other}")
    check_eq("K-answer precondition: with no answer at all this probe is `unverified`, so the answer decides",
             TW.probe(agent_cfg, tmp / "b-no-answer-at-all", where="doctor", save=False)["status"], "unverified")

    def said_at(status, at, fingerprint=fp):
        return {"status": status, "at": at, "fingerprint": fingerprint, "reason": f"the assistant answered {status} at {at}"}

    def pool(receipt, log, where="doctor", checked_at="2026-10-01T09:00:00+00:00"):
        root = tmp / f"b-pool-{abs(hash(json.dumps([receipt, log, where])))}"
        shutil.copytree(b, root)
        path = TW.receipt_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": receipt["status"], "channel": "jira", "checked_at": checked_at, "fingerprint": fp, "answered": receipt}), encoding="utf-8")
        C.approvals_path(root).write_text("".join(json.dumps({"kind": "tracker_write_answer", "channel": "jira", "answered": a, "at": a["at"]}) + "\n" for a in log), encoding="utf-8")
        got = TW.probe(agent_cfg, root, where=where, save=False)
        return got["status"], (got.get("answered") or {}).get("at")
    check_eq("K-answer: the critic's example - receipt `confirmed` 09-23, log `no` 10-01, same fingerprint - is NO (the newer), not the receipt's",
             pool(said_at("confirmed", "2026-09-23T10:00:00+00:00"), [said_at("no", "2026-10-01T10:00:00+00:00")]), ("no", "2026-10-01T10:00:00+00:00"))
    check_eq("K-answer: the other way round - receipt `no` 09-23, log `confirmed` 10-01 - is confirmed",
             pool(said_at("no", "2026-09-23T10:00:00+00:00"), [said_at("confirmed", "2026-10-01T10:00:00+00:00")]), ("confirmed", "2026-10-01T10:00:00+00:00"))
    check_eq("K-answer: EQUAL `at` goes to the receipt (the answer that was written beside the cache it caches)",
             pool(said_at("confirmed", "2026-10-01T10:00:00+00:00"), [said_at("no", "2026-10-01T10:00:00+00:00")]), ("confirmed", "2026-10-01T10:00:00+00:00"))
    check_eq("K-answer: a NEWER answer about another fingerprint never counts (it is not evidence about this setup)",
             pool(said_at("confirmed", "2026-09-23T10:00:00+00:00"), [said_at("no", "2026-10-01T10:00:00+00:00", other)]), ("confirmed", "2026-09-23T10:00:00+00:00"))
    check_eq("K-answer: the newest of several log lines wins, and a line whose `at` cannot be read is the oldest there is",
             pool(said_at("confirmed", "2026-09-23T10:00:00+00:00"), [said_at("no", "2026-09-30T10:00:00+00:00"), said_at("confirmed", "2026-10-02T10:00:00+00:00"),
                                                                     said_at("no", "not a date")]), ("confirmed", "2026-10-02T10:00:00+00:00"))
    check_eq("K-answer: a story-time probe does not believe a FRESH receipt over a newer log line either (the cache is not a second authority)",
             pool(said_at("confirmed", "2026-10-01T08:00:00+00:00"), [said_at("no", "2026-10-01T09:00:00+00:00")], where="story",
                  checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds")),
             ("no", "2026-10-01T09:00:00+00:00"))
    # K8
    second = OA.plan(b, migrate(b, answer=False), date=DATE)
    check_eq("K8: a second plan over case B (no answers given: the memory of the first approval answers the access question): "
             "retire [], write [], regenerate [], 0 questions, nothing to do",
             ([second[k] for k in ("retire", "write", "regenerate", "needs_answers")], second["nothing_to_do"]), ([[], [], [], []], True))
    # K9
    check_eq("K9: every manifest sha256 matches the disk in both cases, and package_version is plugin.json's",
             [(I.verify_manifest(r)["ok"], I.read_manifest(r)["package_version"]) for r in (a, b)], [(True, VERSION)] * 2)
    # K12
    refused = " | ".join(f"{r['rel_path']} {r['reason']}" for r in made["refused"])
    check_eq("K12: adversarial and carried names are refused, none reaches the retire list; the sentinel outside the root keeps its sha256",
             (len(made["retire"]), sha(sentinel) == sentinel_sha, all(os.path.exists(b / p) for p in (CONFIG, "qa-factory/records/journal.jsonl"))),
             (len(DELETED) + len(SET_ASIDE), True, True))
    check("K12: each refusal is in the listing with its reason (outside the project, carried, a folder)",
          "outside the project root" in refused or "absolute" in refused, refused[:300])
    check("K12: ...and carried data is refused in its own words", "carried data is never retired" in refused, refused[:300])
    return a, b, took


# --- K7 and the negative controls: compare_trees must FAIL when the trees are not equal ----------------------

def negative_controls(tmp: Path, a: Path, b: Path) -> None:
    wrong = tmp / "b-passport"
    shutil.copytree(b, wrong)
    shutil.copyfile(FIX / PASSPORT, put(wrong, PASSPORT, "").resolve())
    got = compare(a, wrong)
    check_eq("K7: the passport retirement suppressed: compare_trees FAILS and names qa-factory/strategy/product-passport.md "
             f"(output: {summary(got)})", got, {"missing_in_a": [PASSPORT], "missing_in_b": [], "differing": []})
    wrong2 = tmp / "b-smoke"
    shutil.copytree(b, wrong2)
    shutil.copyfile(FIX / SMOKE, put(wrong2, SMOKE, "").resolve())
    got = compare(a, wrong2)
    check_eq("C3: the stale doctor smoke under state/ NOT retired: compare_trees FAILS and names it "
             f"(output: {summary(got)})", got, {"missing_in_a": [SMOKE], "missing_in_b": [], "differing": []})
    wrong3 = tmp / "b-byte"
    shutil.copytree(b, wrong3)
    victim = wrong3 / "qa-factory/strategy/test-strategy.md"
    victim.write_bytes(victim.read_bytes() + b" ")
    got = compare(a, wrong3)
    check_eq(f"compare_trees: ONE differing byte in a carried file is named (output: {summary(got)})", got,
             {"missing_in_a": [], "missing_in_b": [], "differing": ["qa-factory/strategy/test-strategy.md"]})
    wrong4 = tmp / "b-missing"
    shutil.copytree(b, wrong4)
    os.unlink(wrong4 / "qa-factory/records/journal.jsonl")
    got = compare(a, wrong4)
    check_eq(f"compare_trees: a file the fresh install makes and the reinstall did not is named, the other direction (output: {summary(got)})", got,
             {"missing_in_a": [], "missing_in_b": ["qa-factory/records/journal.jsonl"], "differing": []})
    # a config that differs (the one-key difference a half-done migration leaves)
    wrong5 = tmp / "b-config"
    shutil.copytree(b, wrong5)
    cfg = json.loads((wrong5 / CONFIG).read_text(encoding="utf-8"))
    cfg["audit_cadence_days"] = 30
    (wrong5 / CONFIG).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    check_eq("compare_trees: a deprecated key left in the config shows as a differing config.json", compare(a, wrong5)["differing"], [CONFIG])
    # the manifest: only input_hash is excused
    wrong6 = tmp / "b-manifest"
    shutil.copytree(b, wrong6)
    manifest = json.loads((wrong6 / MANIFEST).read_text(encoding="utf-8"))
    manifest["entries"].pop()
    (wrong6 / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    check_eq("compare_trees: the manifest field that is excused is only input_hash: a lost entry still differs", compare(a, wrong6)["differing"], [MANIFEST])
    # machine-local files are compared by NAME: a missing one is named, different bytes are not
    wrong7 = tmp / "b-local"
    shutil.copytree(b, wrong7)
    local = wrong7 / "qa-factory/state/readiness.json"
    local.write_text("{}\n", encoding="utf-8")
    check_eq("compare_trees: a machine-local file is compared by name only: other bytes are no difference...", compare(a, wrong7), {"missing_in_a": [], "missing_in_b": [], "differing": []})
    os.unlink(local)
    check_eq("...and its absence is named", compare(a, wrong7)["missing_in_b"], ["qa-factory/state/readiness.json"])
    # the positive control: equal trees come back with three empty lists, an empty tree equals an empty tree, mtimes are never looked at
    same = tmp / "a-copy"
    shutil.copytree(a, same)
    old = time.time() - 86400 * 400
    for path in OA._tree_files(same).values():
        os.utime(path, (old, old))
    check_eq("positive control: a copy of A with every mtime moved a year back is equal to A (bytes and names, never mtimes)", compare(a, same),
             {"missing_in_a": [], "missing_in_b": [], "differing": []})
    empty_a, empty_b = tmp / "e1", tmp / "e2"
    empty_a.mkdir()
    empty_b.mkdir()
    git_init(empty_a)
    check_eq("positive control: a project with no qa-factory/ at all is a fresh install: two of them are equal (the .git folder is not part of it)",
             OA.compare_trees(empty_a, empty_b), {"missing_in_a": [], "missing_in_b": [], "differing": []})
    check_eq("...and it is no install yet: p0 finds none, and the plan over it retires nothing",
             (OA.preflight(empty_a)["install_exists"], OA.plan(empty_a, {"proposed_config": fresh_config()}, date=DATE)["retire"]), (False, []))
    # the extras are literal: an exact path hides that path only, `folder/**` hides what is under it and no sibling
    probe_a, probe_b = tmp / "x1", tmp / "x2"
    for root in (probe_a, probe_b):
        root.mkdir()
    put(probe_b, "kept/one.txt", "1")
    put(probe_b, "kept/one.txt.bak", "1")
    put(probe_b, "folder/deep/two.txt", "2")
    put(probe_b, "folder-not/three.txt", "3")
    got = OA.compare_trees(probe_a, probe_b, ["kept/one.txt", "folder/**"])
    check_eq("extras: an exact path hides that path only (its .bak sibling is named), `folder/**` hides what is below and not `folder-not/`",
             got["missing_in_a"], ["folder-not/three.txt", "kept/one.txt.bak"])
    check_eq("extras: a name in neither tree is no difference, and a file in A that B lacks is named under the same extras",
             OA.compare_trees(probe_b, probe_a, ["kept/one.txt", "folder/**"])["missing_in_b"], ["folder-not/three.txt", "kept/one.txt.bak"])


# --- K10, K12 (manifest), K13: on copies of the fixture, plan only -----------------------------------------------

def plans_on_copies(tmp: Path, b: Path) -> None:
    # K10: a path the manifest lists whose bytes are no longer the recorded ones is changed, never retired
    edited = tmp / "b-edited"
    shutil.copytree(b, edited)
    shutil.copyfile(FIX / NOTES, put(edited, NOTES, "").resolve())      # the notes file was set aside by the reinstall: put O's back
    I.write_manifest(edited, [{"rel_path": NOTES, "class": "discarded"}])
    (edited / NOTES).write_text("a person edited this\n", encoding="utf-8")
    made = OA.plan(edited, migrate(edited), date=DATE)
    check_eq("K10: an edited path is listed as changed since install and is NOT in the retire list",
             ([c["rel_path"] for c in made["changed_since_install"]], NOTES in [r["rel_path"] for r in made["retire"]]), ([NOTES], False))
    # K10: an unreadable manifest retires nothing on its word (and says so)
    broken = copy_fixture(tmp / "u-broken")
    put(broken, MANIFEST, "{ not json")
    made = OA.plan(broken, migrate(broken), date=DATE)
    check_eq("K10: an unreadable manifest is reported unreadable, and every item the plan retires is by the table's name (or its silence, for the undetermined "
             "file), none by the manifest's word",
             (made["manifest"]["status"], sorted({r["source"] for r in made["retire"]})), ("unreadable", ["no row of the factory names it", "table"]))
    check_in("K10: ...and the listing says it cannot be read", "cannot be read", OA.render(made))
    # K12: the manifest refuses adversarial entries and never reads them
    sentinel = temp_dir("qa-reinstall-sentinel-")
    try:
        outside = put(sentinel, "outside.txt", "outside the project\n")
        before = sha(outside)
        res = I.write_manifest(copy_fixture(tmp / "u-adv"), ["../outside.txt", str(outside), "/etc/passwd", "C:\\x\\y.txt", "qa-factory/obligations.md"])
        check_eq("K12: the manifest refuses ../x, an absolute path, /etc/x and C:\\x, and lists the one real file; the sentinel keeps its sha256",
                 (res["written"], len(res["refused"]), sha(outside) == before), (["qa-factory/obligations.md"], 4, True))
    finally:
        cleanup(sentinel)
    # K13: no group of the listing is cut (448a9a20, FR-8/FR-9: a count with no place for the rest is a decision on a slice). The old
    # 20-line cap is gone from the code (test_whole_list_sites pins that); these totals are the old boundary (AT it, one BEYOND it) and
    # one far beyond it: every path is a line, and no "+N more" stands in for the rest.
    base = len(DELETED)         # the fixture itself already has this many files to delete
    totals = (20, 21, 60)
    for total in totals:
        count = total - base
        root = copy_fixture(tmp / f"u-cap{count}")
        for n in range(count):
            put(root, f"qa-factory/state/jira-probe-x{n:02d}.json", f"{{\"n\": {n}}}\n")
        made = OA.plan(root, migrate(root), date=DATE)
        text = OA.render(made)
        group = text.split("Will be deleted")[1].split("\n\n")[0]
        lines = [l for l in group.splitlines()[1:] if l.startswith("  - ")]
        check_eq(f"K13: {total} paths to delete: all {total} shown in full, no count stands in for the rest",
                 (len([r for r in made["retire"] if r["retire_mode"] == "delete"]), len(lines), "more" in group),
                 (total, total, False))
    saved = OA._run_script
    OA._run_script = lambda *a, **k: {"step": "stub", "ok": True, "rc": 0, "note": ""}      # only the retire record is asked here
    try:
        made = OA.plan(root, migrate(root), date=DATE)
        done = approve_and_apply(root, made, "onboarding:k13")
        record = json.loads((root / done["record"]).read_text(encoding="utf-8"))
        check_eq(f"K13: the retire record holds all {totals[-1]} paths to delete (and the one set aside) with their sha256, the approval and the proposal they came from",
                 (len(record["retired"]), all("sha256" in r for r in record["retired"]), record["approval_ref"], record["proposal_hash"]),
                 (totals[-1] + len(SET_ASIDE), True, "onboarding:k13", made["proposal"]["proposal_hash"]))
    finally:
        OA._run_script = saved


# --- K-lock and K-git on copies of the fixture (t-272 items 6 and 3) ---------------------------------------------------

ARTIFACT_LOCK = "qa-factory/artifacts/QA-1/.case-versions.lock"
CARRIED_LOCK = "qa-factory/state/cost/.writers/s1/state/events.lock"
EXIT_LOCK = "qa-factory/state/.exit_gate_blocks.json.lock"
FOLDER_LOCK = "qa-factory/state/.project-decisions.lock"


def stubbed_scripts():
    """Stands in for the regenerate scripts (these keys are about locks and git, not about the scripts): it writes the two files whose
    absence would keep the old readiness report (a replacement that was not built), and nothing else."""
    saved = OA._run_script

    def stub(root, script, args=()):
        if script == "readiness.py":
            put(Path(root), OA.READINESS_REL, json.dumps({"runtime_paths": {"package_version": VERSION}}))
        elif script == "factory_dashboard.py":
            put(Path(root), OA.DASHBOARD_REL, "<html></html>")
        return {"step": script, "ok": True, "rc": 0, "note": ""}
    OA._run_script = stub
    return saved


def k_lock(tmp: Path) -> None:
    root = copy_fixture(tmp / "k-lock")
    put(root, ARTIFACT_LOCK, "0")
    put(root, CARRIED_LOCK, "0")
    put(root, EXIT_LOCK, "")
    put(root, CONTROL_LOCK, "0")            # the positive control: the one stale OS lock of a regenerated row that no hook rewrites
    (root / FOLDER_LOCK).mkdir()
    for rel in (EXIT_LOCK, FOLDER_LOCK):        # three days old: older than the day after which an old-generation folder lock is listed
        stamp = time.time() - 3 * 86400
        os.utime(root / rel, (stamp, stamp))
    listed_before = {rel: (sha(root / rel) if (root / rel).is_file() else None) for rel in (ARTIFACT_LOCK, CARRIED_LOCK, FOLDER_LOCK)}
    kept_before = {**listed_before, EXIT_LOCK: sha(root / EXIT_LOCK)}      # the exit gate's OS lock is hook-written: kept, never listed
    saved = stubbed_scripts()
    try:
        made = OA.plan(root, migrate(root), date=DATE)
        by = {l["rel_path"]: l for l in made["locks"]}
        check_eq("K-lock: the removable locks are exactly the OS locks nobody holds under state/ that the table calls regenerated and not hook-written "
                 "- here the one control lock, not the event store's or the journal writer's (listed under regenerate)",
                 (sorted(r for r, l in by.items() if l["action"] == "remove"), sorted(r["rel_path"] for r in made["regenerate"] if r["action"] == "remove")),
                 (sorted(STALE_LOCKS), sorted(STALE_LOCKS)))
        check_eq("K-lock (t-298 / t-363 B6 / TR4-2 D): the stale locks of the four hook-written rows (dashboard writer, journal writer, event store, "
                 "exit gate state) are state 'stale' and action 'none': not removed, not listed, not counted",
                 [(by[p]["state"], by[p]["action"], p in OA.render(made)) for p in [DASH_LOCK, EXIT_LOCK] + HOOK_LOCKS], [("stale", "none", False)] * 4)
        check_eq("K-lock: the locks under carried rows (artifacts/, cost/.writers/) and an old-generation folder lock "
                 "(project_decisions) are LISTED by name - none removable, none only counted",
                 sorted(r for r, l in by.items() if l["action"] == "listed"), sorted(listed_before))
        text = OA.render(made)
        check_eq("K-lock: ...and the text the person reads names every one of them", [rel in text for rel in listed_before], [True] * 3)
        check_eq("K-lock: the three listed locks are not blocking (nobody holds them), and the plan is not blocked", made["blocked"], None)
        done = approve_and_apply(root, made, "onboarding:lock", fold=True)
        regen = next(s for s in done["steps"] if s["step"] == "regenerate")["detail"]["locks"]
        check_eq("K-lock: apply removed exactly the stale OS lock of a regenerated row that no running session's hooks rewrite (the control lock); "
                 "the event store's and the journal writer's are not even in its record",
                 (sorted(k for k, v in regen.items() if v == "removed"), [p in regen for p in HOOK_LOCKS]), (sorted(STALE_LOCKS), [False, False]))
        check_eq("K-lock: ...and never touched the other four (still there, bytes unchanged)",
                 {rel: (sha(root / rel) if (root / rel).is_file() else None) for rel in kept_before if (root / rel).exists()}, kept_before)
        check_eq("K-lock: the folder the removed control lock sat in is gone; the dashboard writer's and the journal writer's folders stay with their "
                 "(hook-written) locks, the lock files themselves present and byte-unchanged; the folder lock is still a folder",
                 ([os.path.exists(root / "qa-factory/state" / d) for d in (".dashboard-writer", ".journal-writer", "other-writer")],
                  [(sha(root / p) == sha(FIX / p)) if (root / p).is_file() else None for p in [DASH_LOCK] + HOOK_LOCKS], (root / FOLDER_LOCK).is_dir()),
                 ([True, True, False], [True, True, True], True))
    finally:
        OA._run_script = saved


def run_git(root: Path, *args) -> subprocess.CompletedProcess:
    hooks = temp_dir("qa-reinstall-nohooks-")
    try:
        return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                               "-c", f"core.hooksPath={hooks}", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        cleanup(hooks)


def k_git(tmp: Path) -> None:
    root = copy_fixture(tmp / "k-git")
    check_eq("K-git precondition: git init + add + commit works on the temp copy (the fixture's state/ is tracked, as a project that committed it would have)",
             [run_git(root, *a).returncode for a in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "old installation"))], [0, 0, 0])
    check("K-git precondition: the old tree tracks files inside state/ (the 22.09 block ignored only some of them)",
          run_git(root, "ls-files", "--", "qa-factory/state").stdout.strip() != "")
    saved = stubbed_scripts()
    try:
        proposal = migrate(root)
        made = OA.plan(root, proposal, date=DATE)
        planned = made["tracking"]["git_rm"]
        check_in("K-git: the listing says which tracked paths sit inside the ignored folder", "Tracked inside the ignored folder", OA.render(made))
        done = approve_and_apply(root, made, "onboarding:git", fold=True)
        check_eq("K-git: after the reinstall git says state/ is ignored (exit 0) and records/ is not (exit 1)",
                 [run_git(root, "check-ignore", "-q", "qa-factory/state/readiness.json").returncode,
                  run_git(root, "check-ignore", "-q", "qa-factory/records/journal.jsonl").returncode], [0, 1])
        still = run_git(root, "ls-files", "--", "qa-factory/state").stdout.split()
        check("K-git NEGATIVE: without the printed lines `git ls-files` still lists the old tracked file(s) inside the ignored folder",
              "qa-factory/state/host-receipts/r1.json" in still and "qa-factory/state/journal.jsonl" in still, str(still[:5]))
        lines = done["tracking"]["git_rm"]
        check_eq("K-git: the plan's lines and the apply's lines are the same lines (the ones the person's yes covered are the ones the role runs)",
                 sorted(planned), sorted(lines))
        codes = [subprocess.run(line, shell=True, cwd=root, capture_output=True).returncode for line in lines]
        check_eq(f"K-git: the {len(lines)} printed `git rm --cached` lines run as they stand (no file is deleted by them)", set(codes), {0})
        check_eq("K-git: after the lines `git ls-files -- qa-factory/state` is EMPTY", run_git(root, "ls-files", "--", "qa-factory/state").stdout.strip(), "")
        check_eq("K-git: the role's commit - .gitignore together with qa-factory/ - leaves a clean tree, with the records tracked and state/ not",
                 (run_git(root, "add", ".gitignore", "qa-factory").returncode, run_git(root, "commit", "-q", "-m", "reinstall").returncode,
                  run_git(root, "status", "--porcelain").stdout.strip(),
                  run_git(root, "ls-files", "--", "qa-factory/records/journal.jsonl", ".gitignore").stdout.split(),
                  run_git(root, "ls-files", "--", "qa-factory/state").stdout.strip()),
                 (0, 0, "", [".gitignore", "qa-factory/records/journal.jsonl"], ""))
        again = OA.plan(root, migrate(root), date=DATE)
        check_eq("K-git: a second plan after the commit has no line to run", (again["tracking"]["checked"], again["tracking"]["git_rm"]), (True, []))
    finally:
        OA._run_script = saved


# --- K11, K14, F1, F2 on the table and the migration ---------------------------------------------------------------

def tables_and_migration() -> None:
    table = I.load_table()
    check_eq("K11: the shipped table is consistent (validate_table ok)", I.validate_table()["ok"], True)
    overlap = copy.deepcopy(table)
    overlap["rules"].append({"glob": "qa-factory/strategy/test-strategy.md", "class": "discarded", "reader": "none", "retire_mode": "delete"})
    errors = [e for e in I.validate_table(table=overlap)["errors"] if e["code"] == "class_overlap"]
    check("K11: validate_table refuses a carried glob that is also discarded and names both classes",
          len(errors) == 1 and "carried" in errors[0]["message"] and "discarded" in errors[0]["message"], str(errors))
    # F1 (Lead's decision after t-260): the receipt is a probe cache the doctor rewrites on every run: regenerated, machine-local, in the
    # ignored folder, never moved. The guard of a row in that folder is folder_mismatch: a record that is not machine-local would never be committed.
    receipt_glob = "qa-factory/state/integrations/tracker-write.json"
    carried_again = copy.deepcopy(table)
    for row in carried_again["rules"]:
        if row["glob"] == receipt_glob:
            row["class"] = "carried"
            row.pop("machine_local", None)
    codes = [e["code"] for e in I.validate_table(table=carried_again)["errors"]]
    check_eq("F1: the receipt row back to CARRIED (task data in the ignored folder, no move): folder_mismatch (git would never see it)", "folder_mismatch" in codes, True)
    row = I.classify(receipt_glob)
    check_eq("F1: the receipt is REGENERATED and machine-local (the table, not a list in code), read by tracker_write.py",
             (row["class"], row["machine_local"], row["reader"]), ("regenerated", True, "tracker_write.py"))
    check_eq("F1: no row carries it to records/ and the reinstall moves nothing of it",
             ([r["glob"] for r in table["rules"] if r["glob"].endswith("tracker-write.json")], [m for m in I.moves() if m["from"].endswith("tracker-write.json")]),
             ([receipt_glob], []))
    judgments = I.classify("qa-factory/state/judgments.jsonl")
    check_eq("G5: the judge's journal is price evidence: CARRIED, machine-local, read by judge.py, kept in place and never retired",
             (judgments["class"], judgments["machine_local"], judgments["reader"], judgments["retire_mode"] if "retire_mode" in judgments else None),
             ("carried", True, "judge.py", None))
    # K14
    bad = ["C:\\Py\\python.exe", "c:/x", "\\\\srv\\s", "/usr/bin/python", "~/x", "%TEMP%\\x", "$HOME/x", "C:foo"]
    good = ["../testproject1", "./run.sh", "poetry"]
    check_eq("K14: all 8 machine-local inputs classify machine-local", [C._machine_local_value([[p], "."]) for p in bad], [True] * 8)
    check_eq("K14: the 3 portable values are not", [C._machine_local_value([[p], "."]) for p in good], [False] * 3)
    cfg = old_config()
    cfg["execution"]["runtime_probes"] = {f"p{n}": {"argv": [p], "cwd": ".", "timeout_s": 5} for n, p in enumerate(bad + good)}
    kept = C.migration_plan(cfg)["proposed_config"]["execution"]["runtime_probes"]
    check_eq("K14: through the migration the 8 are dropped and the 3 portable ones kept", sorted(kept), sorted(f"p{n}" for n in range(8, 11)))
    # F2: only the EXACT old default moves; a person's own path is never touched
    old_default = "qa-factory/state/journal.jsonl"
    new_default = TEMPLATE["journal_path"]
    check_eq("F2: the template carries the records/ spelling", new_default, "qa-factory/records/journal.jsonl")
    mine = ["qa-factory/state/journal.jsonl.bak", "qa-factory/state/Journal.jsonl", "my-logs/journal.jsonl", "state/journal.jsonl",
            "qa-factory/records/journal.jsonl", "", "/qa-factory/state/journal.jsonl", "C:/logs/qa-factory/state/journal.jsonl",
            "../qa-factory/state/journal.jsonl", "qa-factory/state/sub/journal.jsonl"]
    # K-normaliser (t-272 item 5): the SAME normaliser (runtime_paths.normalise_project_path) decides in the migration and in the writer, so every
    # spelling the writer already resolves to the old default is renamed, and the label says what happened to the value
    spellings = [old_default, "qa-factory\\state\\journal.jsonl", "./qa-factory/state/journal.jsonl", ".\\qa-factory\\state\\journal.jsonl",
                 "qa-factory/state/journal.jsonl/", " qa-factory/state/journal.jsonl ", ".//qa-factory/state/journal.jsonl"]
    results = []
    for value in mine + spellings:
        cfg = old_config()
        cfg["journal_path"] = value
        plan = C.migration_plan(cfg)
        results.append((plan["proposed_config"]["journal_path"], [k for k in plan["kept"] if k["reason"] == "changed: default path renamed"] != []))
    check_eq(f"F2: {len(mine)} values that are a person's own (another case, extension, folder or depth, an absolute path, `..`, the new spelling, empty) are NEVER touched and not listed",
             results[:len(mine)], [(v, False) for v in mine])
    check_eq("K-normaliser: the old default in ALL its spellings (the critic's three - the backslash form, `./`, the plain default - and a trailing slash, blanks, `.\\`) "
             "migrates to the records/ place, and each is listed as 'changed: default path renamed'",
             results[len(mine):], [(new_default, True)] * len(spellings))
    proj = temp_dir("qa-normaliser-")
    try:
        check_eq("K-normaliser: the writer resolves every one of those spellings AND the migrated value to the SAME file (records/), never the old state/",
                 {str(RP.configured(proj, v, "journal.jsonl")) for v in spellings + [new_default]}, {str(proj / "qa-factory/records/journal.jsonl")})
        theirs = [v for v in mine if v and not v.startswith(("/", "C:")) and v != "qa-factory/records/journal.jsonl"]
        check_eq("K-normaliser: a person's OWN relative path (the ones the migration leaves alone) is resolved as theirs by the writer, under the project",
                 [RP.configured(proj, v, "journal.jsonl") for v in theirs], [proj / v for v in theirs])
    finally:
        cleanup(proj)
    check_eq("K-normaliser: the normaliser itself: strip `./`, forward slashes, no trailing slash, case KEPT, an absolute path stays absolute",
             [RP.normalise_project_path(v) for v in ("./a/b", ".\\a\\b", "a/b/", "  a/b ", "A/B", "/a/b", ".//a", ".", "", None, "./")],
             ["a/b", "a/b", "a/b", "a/b", "A/B", "/a/b", "a", "", "", "", ""])
    absent = old_config()
    del absent["journal_path"]
    check_eq("F2: a config with no journal_path gets the template's (the fresh install's) value", C.migration_plan(absent)["proposed_config"]["journal_path"], new_default)


# --- B-409: the same comparison over a fixture checked out with CRLF, and the negative control ----------------------

def crlf_copy(into: Path) -> Path:
    """A copy of the fixture with every text file CRLF (what a Windows checkout with core.autocrlf=true wrote before the package
    pinned its line endings). A file with a NUL byte is left alone, an empty file stays empty."""
    shutil.copytree(FIX, into)
    for path in OA._tree_files(into).values():
        if path.is_symlink():
            continue
        data = path.read_bytes()
        if data and b"\0" not in data:
            path.write_bytes(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return into


def crlf_comparison(tmp: Path) -> None:
    """K5-CRLF / K4-CRLF: a project whose own files are CRLF reinstalls to the tree a fresh install on that same project makes, and
    the project's .gitignore stays CRLF (project_gitignore: the project's line endings are the project's). Then the negative control:
    tree A with its .gitignore made LF is NOT equal, and the description names the line endings. A difference in K5-CRLF is a
    WRITER finding (some step writes LF or CRLF where the project's own files are the other): report it, never smooth it."""
    started = time.time()
    fix = crlf_copy(tmp / "crlf-fixture")
    work = tmp / "crlf"
    work.mkdir()
    a = build_a(work, fix)
    b, _, _ = build_b(work, fix=fix)
    result = compare(a, b)
    for described in OA.difference_lines(a, b, result, ignore_json_fields=IGNORED_FIELDS):
        print(f"INFO: K5-CRLF difference: {described}")
    check_eq("K5-CRLF: over a CRLF fixture too, (tree B) - (declared extras) == (tree A): nothing missing either way, nothing differing",
             result, {"missing_in_a": [], "missing_in_b": [], "differing": []})
    raw = (b / ".gitignore").read_bytes()
    check("K4-CRLF: the project's CRLF .gitignore stays CRLF after the reinstall: it has CRLF and no bare LF",
          b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), repr(raw[:80]))
    # the negative control: the same A with its .gitignore LF is a different tree, and the line says how
    wrong = work / "a-lf-gitignore"
    shutil.copytree(a, wrong)
    gi = wrong / ".gitignore"
    gi.write_bytes(gi.read_bytes().replace(b"\r\n", b"\n"))
    got = compare(wrong, b)
    check_in("K5-CRLF negative control: .gitignore made LF in tree A is named as differing (the manifest may differ too)", ".gitignore", got["differing"])
    described = [line for line in OA.difference_lines(wrong, b, got, ignore_json_fields=IGNORED_FIELDS) if line.startswith(".gitignore:")]
    for line in described:
        print(f"INFO: K5-CRLF negative control difference: {line}")
    text = described[0] if described else ""
    check("K5-CRLF negative control: its description says only the line endings differ, A: LF and B: CRLF",
          "only the line endings differ" in text and "A: LF" in text and "B: CRLF" in text, text or "no description")
    print(f"INFO: K5-CRLF (CRLF fixture, both trees, negative control) took {time.time() - started:.1f} s")


def main() -> None:
    smoke = "--smoke" in sys.argv[1:]
    tmp = temp_dir("qa-reinstall-equals-fresh-")
    try:
        a, b, took = the_comparison(tmp)
        if smoke:
            result = compare(a, b)
            equal = not any(result.values()) and all(ok for ok, _ in RESULTS)
            if not equal:       # B-409: install_smoke shows the LAST line, so the lines that say how the files differ come first
                for described in OA.difference_lines(a, b, result, ignore_json_fields=IGNORED_FIELDS):
                    print(f"INFO: K5 difference: {described}")
            print(("PASS " if equal else "FAIL ") + ("reinstall over the old-generation fixture equals a fresh install"
                  if equal else f"the reinstalled tree differs from a fresh one: {result}; failed: {[n for ok, n in RESULTS if not ok][:3]}")
                  + f" (compare_trees, {took:.0f} s)")
            sys.exit(0 if equal else 1)
        negative_controls(tmp, a, b)
        crlf_comparison(tmp)
        plans_on_copies(tmp, b)
        k_lock(tmp)
        k_git(tmp)
        tables_and_migration()
        print(f"INFO: both installs (case A and case B, real readiness/dashboard/coverage scripts) took {took:.1f} s")
    finally:
        cleanup(tmp)
    finish("test_reinstall_equals_fresh")


if __name__ == "__main__":
    main()
