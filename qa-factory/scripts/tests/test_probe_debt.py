"""probe_debt.py: a live probe passed and its receipt was never published (t-134, P6-A).

cmp1 (TP1-13797), critic window 1: sixteen probes said `intended_failure`, none published a receipt,
because each measured a file whose bytes the manifest did not bind - "Proven" fell from 24 to 8 on the
factory's own bookkeeping. `find` names that state (read-only); `--settle` clears what code may clear by a
rebind (`manifest_from_tests.py`) and a FRESH probe (`probe_by_code.py`). Both tools are subprocesses the
settle calls, and here they are stubs: the real ones are never launched. The two real functions the settle
leans on - `execution_request.build_mine_request` through `probe_by_code.build_request` - ARE called, in a temp
project, for the two facts the spec left unverified (R13, NV).
"""
import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, run_script, temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import execution_request as ER  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import probe_debt as D  # noqa: E402
import proof_level as PL  # noqa: E402

TASK = "PD-1"
AUTHOR = "S5-qa-automator-1"
CRITIC = "S5-qa-code-critic-2"
TEST_REL = "tests/test_x.py"
HELPER_REL = "tests/helpers.py"
TEST_SRC = "def test_a():\n    assert 1 + 1 == 2\n\n\ndef test_b():\n    assert 2 == 2\n"
HELPER_SRC = "def expect(a, b):\n    assert a == b\n"
OLD = "22e8b568" + "0" * 56          # what the critic's probe measured (cmp1 shape)
STALE = "cdb5" + "0" * 60            # what the manifest bound before the rebind
PUBLISHED = (0, {"verdict": "intended_failure", "restore": {"verified": True}, "notes": [],
                 "publish": {"published": True}, "receipt": {"path": "work/sensitivity-receipts/r.json"}})
NODE_DEFAULT = object()


def write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=1), encoding="utf-8")
    return path


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


class World:
    pass


def world(scope=("TC-1", "TC-2", "TC-3")) -> World:
    w = World()
    w.project = temp_dir("qa-probe-debt-")
    write(w.project / "qa-factory" / "config.json", {"tests_root": "tests"})
    write(w.project / TEST_REL, TEST_SRC)
    write(w.project / HELPER_REL, HELPER_SRC)
    w.task_root = w.project / "qa-factory" / "artifacts" / TASK
    w.sha = sha((w.project / TEST_REL).read_bytes())
    w.scope = list(scope)
    w.controller = {"dispatches": {
        AUTHOR: {"id": AUTHOR, "stage": "S5", "role": "qa-automator", "status": "accepted", "scope": w.scope},
        CRITIC: {"id": CRITIC, "stage": "S5", "role": "qa-code-critic", "status": "running", "scope": w.scope}}}
    write(w.task_root / "state" / "controller.json", w.controller)
    use_project(w.project)
    return w


def row(w, iid, bound=None, case="TC-1", required=True, **extra) -> dict:
    r = {"instance_id": iid, "case": case, "covers": [case], "file": TEST_REL,
         "case_version_links": [{"case_id": case, "version": "cv_x"}],
         "trace_binding": {"test_content_sha": w.sha if bound is None else bound}}
    if required:
        r["sensitivity_proof_required"] = True
    r.update(extra)
    return r


def put_manifest(w, rows, **extra) -> dict:
    w.manifest = {"tests": rows, **extra}
    write(w.task_root / "work" / "automation-manifest.json", w.manifest)
    return w.manifest


def stored_checks(w, node) -> list:
    """t-2064 P4c: the `checks[]` rows an aggregate of `node` on the test file AS IT STANDS holds - one per check, with its `statement_sha`
    and an `invert` entry whole (a stored model: a replay under S5 joins it, so the settle probes instead of leaving the item as "model
    owed"). [] when the node is not a Python test that lists a check: such a record is an old one, and old records are owed (`record(...,
    checks=[])` says it by hand)."""
    try:
        spec = PBC.parse_node(node, w.project)
        data = (w.project / spec["file"]).read_bytes()
        listed = PBC.checks_of(data, spec, PBC._reader_entry(spec), [], [], [])
    except Exception:
        return []
    return [{"key": c["key"], "statement_sha": c["statement_sha"], "verdict": "intended_failure", "probe_kind": "invert",
             "entry": {"check": c["key"], "instance": "", "alternative": "", "kind": "invert", "supposes": "",
                       "invert": "the stored model of the fixture"}} for c in listed]


def record(w, iid, *, verdict="intended_failure", measured=None, node=NODE_DEFAULT, mutation="invert",
           detail=None, moved=None, at="2026-09-30T05:02:39+00:00", published=False, **extra) -> Path:
    function = iid.split("[")[0].split("::")[-1]
    rec = {"schema_version": 1, "instance_id": iid, "case": "TC-1",
           "test_node": f"{TEST_REL}::{function}" if node is NODE_DEFAULT else node,
           "verdict": verdict, "mutation": mutation,
           "mutation_detail": detail if detail is not None else {"line": 2, "mutation": mutation},
           "test_file_sha256": measured or OLD, "recorded_at": at, "publish": {"published": published}}
    if moved:
        rec["mutated_file"] = {"path": moved, "sha256": "x"}
    rows = stored_checks(w, rec["test_node"]) if isinstance(rec["test_node"], str) and "::" in rec["test_node"] else []
    if rows:        # a walk of the plan stores its models (`extra` may overrule: `checks=[]` is an old record)
        rec["checks"] = rows
    rec.update(extra)
    return write(PL.probe_record_path(w.task_root, iid), rec)


def by_id(items) -> dict:
    return {i["instance_id"]: i for i in items}


class Stub:
    """Both subprocesses, in one callable: `runner(argv, cwd=, timeout=) -> (rc, stdout, stderr)`."""

    def __init__(self, w):
        self.w, self.calls, self.now, self.step = w, [], 0.0, 0.0
        self.timeouts = []   # the process timeout each probe was started with (manifest calls are not listed)
        self.manifest_step = 0.0   # seconds the clock moves on each manifest_from_tests call (a slow rebind)
        self.manifest_timeouts = []   # (kind, process timeout) of each manifest_from_tests call
        self.manifest_raise = {}      # "dry" / "write" -> an exception that call raises (a timeout)
        self.dry_ids, self.dry_rc, self.dry_out, self.write_rc, self.binds = None, 0, None, 0, True
        self.probe, self.default = {}, PUBLISHED

    def clock(self):
        return self.now

    def kinds(self) -> list:
        out = []
        for script, args in self.calls:
            if script == "manifest_from_tests.py":
                out.append("dry" if "--dry-run" in args else "write")
            else:
                out.append("probe:" + args[args.index("--instance") + 1])
        return out

    def __call__(self, argv, cwd=None, timeout=None):
        script, args = Path(argv[2]).name, list(argv[3:])
        self.calls.append((script, args))
        if script == "manifest_from_tests.py":
            self.now += self.manifest_step
            kind = "dry" if "--dry-run" in args else "write"
            self.manifest_timeouts.append((kind, timeout))
            if kind in self.manifest_raise:
                raise self.manifest_raise[kind]
            return self._manifest(args)
        self.now += self.step
        self.timeouts.append(timeout)
        got = self.probe.get(args[args.index("--instance") + 1], self.default)
        if isinstance(got, BaseException):
            raise got
        rc, body = got
        return rc, (body if isinstance(body, str) else json.dumps(body)), ""

    def _manifest(self, args):
        rows = C.manifest_tests(json.loads((self.w.task_root / "work" / "automation-manifest.json")
                                           .read_text(encoding="utf-8")))
        if "--dry-run" in args:
            if self.dry_out is not None:
                return self.dry_rc, self.dry_out, ""
            ids = self.dry_ids if self.dry_ids is not None else [C.test_instance_id(r) for r in rows]
            return 0, json.dumps({"ok": True, "dry_run": True,
                                  "fragment": {"tests": [{"instance_id": i} for i in ids]}}), ""
        if self.write_rc:
            return self.write_rc, "", "manifest_put refused the merge"
        if self.binds:
            for r in rows:
                r["trace_binding"] = {"test_content_sha": self.w.sha}
            write(self.w.task_root / "work" / "automation-manifest.json", {"tests": rows})
        return 0, json.dumps({"ok": True, "dry_run": False}), ""


def settle(w, stub, **kw) -> dict:
    kw.setdefault("stand", lambda: (False, ""))
    return D.settle(TASK, w.task_root, w.project, CRITIC, dispatch_record=w.controller["dispatches"][CRITIC],
                    runner=stub, clock=stub.clock, **kw)


def fresh_settle(w, stub, **kw) -> dict:
    """A settle with no memory: these tests change what the stubs answer between settles of the SAME bytes, which is
    exactly what the refused-rebind memory (P2-2) would now skip; the memory itself is judged by the settle_* tests."""
    (w.task_root / D.MEMORY_REL).unlink(missing_ok=True)
    return settle(w, stub, **kw)


# --- R11: the detector ---------------------------------------------------------------------------------

def find_names_the_unpublished_probe():
    w = world()
    try:
        check_eq("no manifest at all: the empty result", D.find(w.task_root, {}, w.project), {"items": [], "info": []})
        put_manifest(w, [row(w, "test_a")])
        check_eq("no records at all (edge i): the empty result, and exactly these two keys",
                 D.find(w.task_root, w.manifest, w.project), {"items": [], "info": []})
        for bad in (None, [], "x", 7):
            check_eq(f"a manifest that is {bad!r} (edge iii): the empty result, no exception",
                     D.find(w.task_root, bad, w.project), {"items": [], "info": []})
        # the cmp1 shape: bound to the old bytes, measured on the old bytes, the file has moved on
        put_manifest(w, [row(w, "test_a", bound=STALE)])
        record(w, "test_a", measured=STALE)
        got = D.find(w.task_root, w.manifest, w.project, CRITIC)
        item = got["items"][0] if got["items"] else {}
        check_eq("one required row with an intended_failure record is one item", len(got["items"]), 1)
        check_eq("item: instance_id, case", (item.get("instance_id"), item.get("case")), ("test_a", "TC-1"))
        check_eq("item: the record is named task-relative", item.get("record"), "work/probes/test_a.json")
        check_eq("item: recorded_at", item.get("recorded_at"), "2026-09-30T05:02:39+00:00")
        check_eq("item: measured / bound / current sha",
                 (item.get("measured_sha"), item.get("bound_sha"), item.get("current_sha")),
                 (STALE, STALE, w.sha))
        check_eq("bound != current is rebind_and_reprobe", item.get("action"), D.REBIND_AND_REPROBE)
        check_in("item: why says which bytes", STALE[:12], item.get("why", ""))
        check_eq("item: the exact probe_by_code line", item.get("command"),
                 f"probe_by_code.py --task {TASK} --dispatch {CRITIC} --test {TEST_REL}::test_a "
                 "--instance test_a --mutation invert --json")
        check("item: no private handle leaks into the public shape", not [k for k in item if k.startswith("_")])
        check_eq("item: exactly the named fields", sorted(item), sorted(
            ["instance_id", "case", "record", "recorded_at", "measured_sha", "bound_sha", "current_sha",
             "action", "why", "command"]))
        check_in("without a dispatch the command carries a placeholder",
                 "<the open S5 qa-code-critic dispatch id>",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["command"])
        # bound == current, measured on other bytes: reprobe (F-4: always re-probe)
        put_manifest(w, [row(w, "test_a")])
        record(w, "test_a", measured=OLD)
        check_eq("bound == current: reprobe", D.find(w.task_root, w.manifest, w.project)["items"][0]["action"],
                 D.REPROBE)
        # F-8: published, but on bytes the test no longer has - debt as well
        record(w, "test_a", measured=OLD, published=True)
        check_eq("F-8: a published record whose receipt is not valid for the current bytes is debt too",
                 [i["instance_id"] for i in D.find(w.task_root, w.manifest, w.project)["items"]], ["test_a"])
        # measured == bound == current but no valid receipt anywhere: still one fresh probe
        record(w, "test_a", measured=w.sha)
        check_eq("measured == bound == current, no receipt: reprobe (F-4)",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["action"], D.REPROBE)
        # a valid receipt reaches a level: settled, neither item nor info
        receipt = write(w.task_root / "work" / "sensitivity-receipts" / "a-live.json", {
            "instance_id": "test_a", "case_version": "cv_x", "test_content_hash": w.sha, "source_revision": "src",
            "build_id": "b", "mutation": "invert", "expected_assertion_failure": "x", "actual_failure": "x",
            "assertion_location": "t.py:2", "restoration_evidence": "ok", "failure_kind": "assertion",
            "immutable": True, "receipt_hash": "h-a", "proof_level": "live", "probe_tool": "probe_by_code.py",
            "mutation_kind": "assertion"})
        ref = {"path": receipt.relative_to(w.task_root).as_posix(), "sha256": sha(receipt.read_bytes())}
        put_manifest(w, [row(w, "test_a", sensitivity_proof={"receipt_ref": ref})])
        check_eq("a row that reached a level is not debt", D.find(w.task_root, w.manifest, w.project),
                 {"items": [], "info": []})
    finally:
        cleanup(w.project)


def find_info_and_edges():
    w = world()
    try:
        # (b) a legacy row: its probe passed, but no live check is owed - info, never an item
        put_manifest(w, [row(w, "test_a", bound=STALE, required=False)])
        record(w, "test_a", measured=STALE)
        got = D.find(w.task_root, w.manifest, w.project)
        check_eq("a record of a NOT-required row is no item", got["items"], [])
        check_eq("...it is one info row, with no action", [i["instance_id"] for i in got["info"]], ["test_a"])
        check_in("...that says no live check is owed and no action is taken", "no action", got["info"][0]["why"])
        check("...and carries no `action`", "action" not in got["info"][0])
        # only intended_failure is debt
        put_manifest(w, [row(w, "test_a"), row(w, "test_b")])
        record(w, "test_a", verdict="no_failure")
        record(w, "test_b", verdict="not_executed")
        check_eq("no_failure / not_executed records are not debt", D.find(w.task_root, w.manifest, w.project),
                 {"items": [], "info": []})
        # a corrupt record: info, unreadable (P1)
        put_manifest(w, [row(w, "test_a"), row(w, "test_b")])
        (w.task_root / "work" / "probes" / "test_a.json").write_text("{not json", encoding="utf-8")
        write(w.task_root / "work" / "probes" / "test_b.json", ["a", "list"])
        got = D.find(w.task_root, w.manifest, w.project)
        check_eq("a corrupt or non-object record is info, not an item, no exception",
                 (got["items"], [i["instance_id"] for i in got["info"]]), ([], ["test_a", "test_b"]))
        check_in("...named 'unreadable'", "unreadable", got["info"][0]["why"])
        # (ii) a record whose row is gone from the manifest
        put_manifest(w, [row(w, "test_b")])
        for name in ("test_a", "test_b"):
            (w.task_root / "work" / "probes" / f"{name}.json").unlink()
        record(w, "test_gone")
        got = D.find(w.task_root, w.manifest, w.project)
        check_eq("(ii) a record with no manifest row is info 'row gone'",
                 (got["items"], [(i["instance_id"], "row gone" in i["why"]) for i in got["info"]]),
                 ([], [("test_gone", True)]))
        # (v) the same instance twice under aliases: one item
        put_manifest(w, [row(w, "test_a"), row(w, "TC-1::test_a")])
        record(w, "test_a")
        check_eq("(v) one instance under two spellings is one item",
                 [i["instance_id"] for i in D.find(w.task_root, w.manifest, w.project)["items"]], ["test_a"])
        # the record under the ALIAS' file name is found (the probe was asked for the prefixed spelling)
        (w.task_root / "work" / "probes" / "test_a.json").unlink()
        put_manifest(w, [row(w, "test_a")])
        record(w, "TC-1::test_a")
        check_eq("a record named by an alias of the row's id is found",
                 [i["instance_id"] for i in D.find(w.task_root, w.manifest, w.project)["items"]], ["test_a"])
    finally:
        cleanup(w.project)


def leave_to_critic_and_the_oracle():
    w = world()
    try:
        put_manifest(w, [row(w, "test_a")])
        # V6: a record with an oracle function whose function is still there is REPLAYED, file-qualified
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "expect",
                                    "file": HELPER_REL}, moved=HELPER_REL)
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("V6: an oracle function still in its file is replayed, not handed over", item["action"], D.REPROBE)
        check_in("V6: and the command passes --oracle <file>::<function>", f"--oracle {HELPER_REL}::expect",
                 item["command"])
        # the oracle in the TEST's own file (a helper defined beside the tests)
        write(w.project / TEST_REL, TEST_SRC + "\n\ndef local_expect(a):\n    assert a\n")
        put_manifest(w, [row(w, "test_a", bound=sha((w.project / TEST_REL).read_bytes()))])
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "local_expect"},
               moved=TEST_REL)
        check_in("an oracle inside the test file is replayed with the test file named",
                 f"--oracle {TEST_REL}::local_expect", D.find(w.task_root, w.manifest, w.project)["items"][0]["command"])
        write(w.project / TEST_REL, TEST_SRC)
        put_manifest(w, [row(w, "test_a")])
        # (e) the function is gone: the critic's, with the reason, and the command has no --oracle
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "vanished",
                                    "file": HELPER_REL}, moved=HELPER_REL)
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("(e) an oracle function that is gone from its file goes to the critic", item["action"],
                 D.LEAVE_TO_CRITIC)
        check_in("(e) ...and says which function and file", "vanished", item["why"])
        check_not_in("(e) ...and the command names no oracle that cannot be replayed", "--oracle", item["command"])
        # the file is gone altogether
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "expect",
                                    "file": "tests/nowhere.py"}, moved="tests/nowhere.py")
        check_eq("an oracle whose FILE is gone goes to the critic",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["action"], D.LEAVE_TO_CRITIC)
        # a function defined twice: the probe itself would refuse it
        write(w.project / HELPER_REL, HELPER_SRC + "\n\ndef expect(a, b):\n    assert a != b\n")
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "expect",
                                    "file": HELPER_REL}, moved=HELPER_REL)
        check_eq("an oracle function defined twice goes to the critic (the probe refuses it)",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["action"], D.LEAVE_TO_CRITIC)
        write(w.project / HELPER_REL, "def broken(:\n")
        check_eq("an oracle file that does not parse goes to the critic",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["action"], D.LEAVE_TO_CRITIC)
        write(w.project / HELPER_REL, HELPER_SRC)
        # a mutation this tool does not make
        record(w, "test_a", mutation="swap_operands")
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("a mutation outside MUTATIONS goes to the critic", item["action"], D.LEAVE_TO_CRITIC)
        check_in("...naming the mutation", "swap_operands", item["why"])
        # the probe mutated another file and the record names no function for it
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "file": "app/service.py"})
        check_eq("mutation_detail.file naming another file, with no function to replay, goes to the critic",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["action"], D.LEAVE_TO_CRITIC)
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "file": TEST_REL})
        check_eq("mutation_detail.file naming the TEST itself is an ordinary replay",
                 D.find(w.task_root, w.manifest, w.project)["items"][0]["action"], D.REPROBE)
        # no test node: code does not guess
        record(w, "test_a", node="")
        item = D.find(w.task_root, w.manifest, w.project)["items"][0]
        check_eq("a record with no test_node goes to the critic, with no command", (item["action"], item["command"]),
                 (D.LEAVE_TO_CRITIC, ""))
        # the test file cannot be found: nothing to probe
        put_manifest(w, [row(w, "test_a", file="tests/test_gone.py")])
        record(w, "test_a")
        item = D.find(w.task_root, w.manifest, w.project)["items"][0]
        check_eq("a test file that cannot be found goes to the critic", item["action"], D.LEAVE_TO_CRITIC)
        check_eq("...with no current sha", item["current_sha"], "")
    finally:
        cleanup(w.project)


def commands_survive_hard_ids():
    w = world()
    try:
        ids = ["test_a[P-x]", "test_a[malformed-$[?(unterminated-True]", "test_a[\u0438\u043c\u044f-\u00e9]",
               "test_a[a b]"]
        put_manifest(w, [row(w, i) for i in ids])
        for i in ids:
            record(w, i, node=f"{TEST_REL}::{i}")
        got = by_id(D.find(w.task_root, w.manifest, w.project, CRITIC)["items"])
        check_eq("hard ids (brackets, `$`, non-ASCII, a space): one item each", sorted(got), sorted(ids))
        check_in("an id with [P-x] is quoted", '--instance "test_a[P-x]"', got["test_a[P-x]"]["command"])
        dollar = got["test_a[malformed-$[?(unterminated-True]"]["command"]
        check_in("an id with `$` is single-quoted, so no shell expands it",
                 "--instance 'test_a[malformed-$[?(unterminated-True]'", dollar)
        check_in("a non-ASCII id is carried as is", "test_a[\u0438\u043c\u044f-\u00e9]",
                 got["test_a[\u0438\u043c\u044f-\u00e9]"]["command"])
        check_eq("quote: a plain word stays bare", D._quote("test_a"), "test_a")
        check_eq("quote: a quote-free special word is double-quoted", D._quote("a[b]"), '"a[b]"')
        check_eq("quote: `$` without an apostrophe is single-quoted", D._quote("a$b"), "'a$b'")
        check_eq("quote: `$` with an apostrophe is escaped in double quotes", D._quote("a$b'c"), '"a\\$b\'c"')
    finally:
        cleanup(w.project)


def find_writes_nothing():
    w = world()
    try:
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b", required=False), row(w, "test_c"),
                         row(w, "test_d")])
        record(w, "test_a", measured=STALE)
        record(w, "test_b")
        record(w, "test_gone")
        (w.task_root / "work" / "probes" / "test_c.json").write_text("{broken", encoding="utf-8")
        record(w, "test_d", detail={"line": 2, "mutation": "invert", "oracle_function": "expect",
                                    "file": HELPER_REL}, moved=HELPER_REL)
        before = tree(w.project)
        got = D.find(w.task_root, w.manifest, w.project, CRITIC)
        check("the world holds an item, info rows and a corrupt record", len(got["items"]) == 2 and len(got["info"]) == 3)
        check_eq("FR-45 / R11: `find` writes nothing - not a receipt, not a manifest field, not the debt file",
                 tree(w.project), before)
        check("...and no receipt directory exists", not (w.task_root / "work" / "sensitivity-receipts").exists())
        check("...nor the debt file", not (w.task_root / D.debt_rel(CRITIC)).exists())
        proc = run_script("probe_debt.py", "--task", TASK, "--json", cwd=w.project,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(w.project)))
        check_eq("the read-only CLI exits 0 and prints one JSON document (FR-14)",
                 (proc.returncode, sorted(json.loads(proc.stdout))), (0, ["info", "items"]))
        check_eq("...and the CLI wrote nothing either", tree(w.project), before)
    finally:
        cleanup(w.project)


# --- R12: the settle -----------------------------------------------------------------------------------

def settle_sequence():
    w = world()
    try:
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b")])
        record(w, "test_a", measured=STALE)
        record(w, "test_b", measured=OLD, detail={"line": 2, "mutation": "expected", "oracle_function": "expect",
                                                 "file": HELPER_REL}, moved=HELPER_REL, mutation="expected")
        stub = Stub(w)
        doc = settle(w, stub)
        check_eq("the order: rebind (dry run, write), probe, then the next item's probe",
                 stub.kinds(), ["dry", "write", "probe:test_a", "probe:test_b"])
        dry, write_call = stub.calls[0][1], stub.calls[1][1]
        check_eq("the dry run: task, the latest accepted automator dispatch, the test file, --dry-run --json",
                 dry, ["--task", TASK, "--dispatch", AUTHOR, "--file", TEST_REL, "--dry-run", "--json"])
        check_eq("the write is the same call without --dry-run", write_call,
                 ["--task", TASK, "--dispatch", AUTHOR, "--file", TEST_REL])
        check_eq("the first probe: the record's own test, mutation, on the critic's dispatch, and the time left as its own timeout",
                 stub.calls[2][1], ["--task", TASK, "--dispatch", CRITIC, "--test", f"{TEST_REL}::test_a",
                                    "--instance", "test_a", "--mutation", "invert", "--json",
                                    "--timeout", str(D.SETTLE_BUDGET_S)])
        check_eq("the second probe replays the oracle of ITS record (V6), and its stored `expected` as `invert` (N7)",
                 stub.calls[3][1], ["--task", TASK, "--dispatch", CRITIC, "--test", f"{TEST_REL}::test_b",
                                    "--instance", "test_b", "--mutation", "invert", "--oracle",
                                    f"{HELPER_REL}::expect", "--json", "--timeout", str(D.SETTLE_BUDGET_S)])
        check_eq("both published: nothing is left", doc["left"], [])
        check_eq("every step is an outcome line", [(o["instance_id"], o["step"], o["result"]) for o in doc["outcomes"]],
                 [("test_a", "rebind", "rebound"), ("test_a", "probe", "published"), ("test_b", "probe", "published")])
        check_in("the outcome of a probe names the receipt", "work/sensitivity-receipts/r.json",
                 doc["outcomes"][1]["words"])
        debt = json.loads((w.task_root / D.debt_rel(CRITIC)).read_text(encoding="utf-8"))
        check_eq("R12.3: the outcomes are recorded in work/probe-debt.json", debt["outcomes"], doc["outcomes"])
        check_eq("...with the budget it ran under", (debt["budget"]["budget_s"], debt["budget"]["limit"],
                                                      debt["budget"]["probes_started"]), (D.SETTLE_BUDGET_S, 25, 2))
        # generated_from: the files the row was generated from, else its own test file
        put_manifest(w, [row(w, "test_a", bound=STALE, generated_from=["tests/data_a.py", TEST_REL])])
        write(w.project / "tests/data_a.py", "DATA = 1\n")
        stub = Stub(w)
        settle(w, stub)
        check_eq("every generated_from path is a --file of the rebind", [a for a in stub.calls[0][1] if a.startswith("tests/")],
                 ["tests/data_a.py", TEST_REL])
        # a reprobe-only item makes no manifest_from_tests call at all
        put_manifest(w, [row(w, "test_a")])
        stub = Stub(w)
        settle(w, stub)
        check_eq("an item whose binding is current is not rebound: one probe only", stub.kinds(), ["probe:test_a"])
        # two items of ONE file: the second finds the row already bound by the first write
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b", bound=STALE)])
        record(w, "test_b", measured=STALE)
        stub = Stub(w)
        settle(w, stub)
        check_eq("one file, two stale rows: one dry run, one write, two probes",
                 stub.kinds(), ["dry", "write", "probe:test_a", "probe:test_b"])
    finally:
        cleanup(w.project)


def rebind_writes_only_known_ids():
    w = world()
    try:
        put_manifest(w, [row(w, "TC-1::test_a", bound=STALE)])
        record(w, "TC-1::test_a", measured=STALE)
        # (c) a source-spelled id the manifest does not hold would be a ghost row beside the collected ones
        stub = Stub(w)
        stub.dry_ids = ["TC-1::test_a", "test_a[chromium]"]
        doc = fresh_settle(w, stub)
        check_eq("(c) the dry run would write an unknown id: no write, no probe", stub.kinds(), ["dry"])
        check_eq("...the item stays, with the rebind reason", [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("TC-1::test_a", "rebind")])
        check_in("...and the words name the author's door", D.REBIND_LEFT, doc["left"][0]["reason_words"])
        check_in("...and the unknown id", "test_a[chromium]", doc["left"][0]["reason_words"])
        check_eq("...and the manifest was not touched", json.loads(
            (w.task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8")), w.manifest)
        # the same row under ANOTHER alias is the row: the write goes ahead
        stub = Stub(w)
        stub.dry_ids = ["test_a"]
        doc = fresh_settle(w, stub)
        check_eq("a dry-run id that is an alias of a held row is known: write, then probe",
                 stub.kinds(), ["dry", "write", "probe:TC-1::test_a"])
        # a retracted row is not held
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b")], retracted_instances=["test_b"])
        record(w, "test_a", measured=STALE)
        stub = Stub(w)
        stub.dry_ids = ["test_a", "test_b"]
        doc = fresh_settle(w, stub)
        check_eq("an id the manifest retracted does not count as held: no write", stub.kinds(), ["dry"])
        # a dry run that would not write this very instance rebinds nothing
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b")])
        stub = Stub(w)
        stub.dry_ids = ["test_b"]
        doc = fresh_settle(w, stub)
        check_eq("a dry run that does not name the item's instance: no write, no probe", stub.kinds(), ["dry"])
        # no ids at all
        stub = Stub(w)
        stub.dry_ids = []
        fresh_settle(w, stub)
        check_eq("a dry run that would write nothing: no write, no probe", stub.kinds(), ["dry"])
    finally:
        cleanup(w.project)


def a_failed_rebind_means_no_probe():
    w = world()
    try:
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b")])
        record(w, "test_a", measured=STALE)
        record(w, "test_b")
        for label, configure in (
                ("(iv) the dry run exits non-zero", lambda s: setattr(s, "dry_rc", 2) or setattr(
                    s, "dry_out", json.dumps({"ok": False, "refusal": "no marker in tests/test_x.py"}))),
                ("(iv) the dry run prints no JSON", lambda s: setattr(s, "dry_out", "Traceback ...")),
                ("the write is refused (exit 3)", lambda s: setattr(s, "write_rc", 3)),
                ("the write 'succeeds' but the row is still bound to other bytes", lambda s: setattr(s, "binds", False))):
            stub = Stub(w)
            configure(stub)
            doc = fresh_settle(w, stub)
            kinds = stub.kinds()
            check(f"{label}: no probe of the rebind item (bound != current would receipt other bytes)",
                  "probe:test_a" not in kinds, str(kinds))
            check_eq(f"{label}: the item is left with reason rebind",
                     [(i["instance_id"], i["reason"]) for i in doc["left"]], [("test_a", "rebind")])
            check_in(f"{label}: the words name the door", D.REBIND_LEFT, doc["left"][0]["reason_words"])
            check_eq(f"{label}: the reprobe item after it is still probed", "probe:test_b" in kinds, True)
        check_in("(iv) the dry run's own refusal words reach the item", "no marker in tests/test_x.py",
                 fresh_settle(w, _with(Stub(w), dry_rc=2, dry_out=json.dumps({"ok": False, "refusal": "no marker in tests/test_x.py"})))
                 ["left"][0]["reason_words"])
        # no accepted automator dispatch to attribute the rebind to
        w.controller["dispatches"][AUTHOR]["status"] = "running"
        write(w.task_root / "state" / "controller.json", w.controller)
        stub = Stub(w)
        doc = fresh_settle(w, stub)
        check_eq("no accepted S5 qa-automator dispatch: no rebind call, no probe of that item",
                 [k for k in stub.kinds() if k != "probe:test_b"], [])
        check_in("...and the words say so", "no accepted S5 qa-automator dispatch", doc["left"][0]["reason_words"])
        # the stub that raises on the dry run
        w.controller["dispatches"][AUTHOR]["status"] = "accepted"
        write(w.task_root / "state" / "controller.json", w.controller)

        class Boom(Stub):
            def _manifest(self, args):
                raise OSError("no such interpreter")
        doc = fresh_settle(w, Boom(w))
        check_eq("an OSError on the rebind is an outcome line, not a traceback",
                 [(o["instance_id"], o["step"], o["result"]) for o in doc["outcomes"]][:1], [("test_a", "rebind", "kept")])
    finally:
        cleanup(w.project)


def _with(stub, **attrs):
    for key, value in attrs.items():
        setattr(stub, key, value)
    return stub


def probe_outcomes():
    w = world()
    try:
        ids = ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]
        put_manifest(w, [row(w, i) for i in ids])
        for i in ids:
            record(w, i)
        stub = Stub(w)
        stub.probe["t1"] = (0, {"verdict": "intended_failure", "restore": {"verified": True},
                                 "publish": {"published": False}, "receipt": None,
                                 "receipt_missing": ["test_content_hash"], "notes": ["stale trace_binding"]})
        stub.probe["t2"] = (0, {"verdict": "no_failure", "restore": {"verified": True}, "notes": []})
        stub.probe["t3"] = (2, {"status": "refused", "error": "no test function test_zzz in this file"})
        stub.probe["t4"] = (1, "Traceback (most recent call last): boom")
        stub.probe["t5"] = OSError("the interpreter vanished")
        stub.probe["t6"] = (0, {"verdict": "already_probed", "by": "receipt", "words": "holds a receipt"})
        doc = settle(w, stub)
        got = {o["instance_id"]: o for o in doc["outcomes"]}
        left = {i["instance_id"]: i for i in doc["left"]}
        check_eq("every item's probe was attempted, in order (none of the failures stopped the settle)",
                 stub.kinds(), [f"probe:{i}" for i in ids])
        check_eq("a probe that passed but published nothing is unpublished, and its receipt_missing is told",
                 (got["t1"]["result"], "test_content_hash" in got["t1"]["words"]), ("unpublished", True))
        check_eq("no_failure is the critic's: left with that verdict", (got["t2"]["result"], left["t2"]["reason"]),
                 ("no_failure", "no_failure"))
        check_eq("a refusal (exit 2) is an outcome and the item stays", (got["t3"]["result"], "t3" in left),
                 ("refused", True))
        check_in("...with the tool's own words", "no test function test_zzz", got["t3"]["words"])
        check_eq("output that is not JSON is an error outcome", (got["t4"]["result"], "t4" in left), ("error", True))
        check_eq("(viii) an OSError is an outcome line, and the next item went on",
                 (got["t5"]["result"], "probe:t6" in stub.kinds()), ("exception", True))
        check_in("...naming the exception", "OSError", got["t5"]["words"])
        check_eq("already_probed by a receipt is settled: not left", ("t6" in left, got["t6"]["result"]),
                 (False, "already_probed"))
        check_eq("a published probe is settled: not left", ("t7" in left, got["t7"]["result"]), (False, "published"))
        check_eq("(f) an exception in one probe did not stop the settle: the rest ran and were recorded",
                 [o["result"] for o in doc["outcomes"]],
                 ["unpublished", "no_failure", "refused", "error", "exception", "already_probed", "published"])
        check_eq("the left list carries every item's command and reason words",
                 all(i["command"] and i["reason_words"] for i in doc["left"]), True)
        # V1: the first not_executed stops the settle
        stub = Stub(w)
        stub.probe["t2"] = (1, {"verdict": "not_executed", "restore": {"verified": True},
                                 "notes": ["run_suite printed no summary (exit 3)"]})
        doc = settle(w, stub)
        check_eq("V1: the first not_executed stops the settle: t1, t2 probed, nothing after",
                 stub.kinds(), ["probe:t1", "probe:t2"])
        check_eq("...the rest are left with the reason 'stopped'",
                 [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("t2", "not_executed")] + [(i, "stopped") for i in ids[2:]])
        check_in("...and the stopped words name the probe that ended it", "t2", doc["left"][1]["reason_words"])
        # an unverified restore stops it too
        stub = Stub(w)
        stub.probe["t1"] = (1, {"verdict": "intended_failure", "restore": {"verified": False}, "notes": []})
        settle(w, stub)
        check_eq("a restore that could not be verified stops the settle", stub.kinds(), ["probe:t1"])
    finally:
        cleanup(w.project)


def legacy_rows_are_never_settled():
    w = world()
    try:
        put_manifest(w, [row(w, "test_a", bound=STALE, required=False), row(w, "test_b")])
        record(w, "test_a", measured=STALE)
        record(w, "test_b")
        stub = Stub(w)
        doc = settle(w, stub)
        check_eq("(b) a legacy row is neither rebound nor probed", stub.kinds(), ["probe:test_b"])
        check_eq("...it is an info row in the recorded debt", [i["instance_id"] for i in doc["info"]], ["test_a"])
    finally:
        cleanup(w.project)


def budget_stand_and_limit():
    w = world()
    try:
        ids = [f"t{n}" for n in range(1, 6)]
        put_manifest(w, [row(w, i) for i in ids])
        for i in ids:
            record(w, i)
        # V1: a wall-clock budget, checked before each item; the budget bounds the WHOLE call, so a probe
        # that would not fit is not begun (the longest probe of this settle is the estimate)
        stub = Stub(w)
        stub.step = 40.0
        doc = settle(w, stub, budget_s=90)
        check_eq("V1/(vii): probes at 0 and 40 s run (50 s left, longest 40 s); at 80 s 10 s are left: two probes",
                 stub.kinds(), ["probe:t1", "probe:t2"])
        check_eq("(vii) all items left go to the list with reason 'budget'",
                 [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("t3", "budget"), ("t4", "budget"), ("t5", "budget")])
        check_in("...and the words say the next one would not fit", "would not fit", doc["left"][0]["reason_words"])
        check_eq("the budget record", (doc["budget"]["budget_s"], doc["budget"]["probes_started"]), (90, 2))
        stub = Stub(w)
        stub.step = 45.0
        settle(w, stub, budget_s=90)
        check_eq("the budget is checked BEFORE an item: at exactly 90 s elapsed the next one does not start",
                 stub.kinds(), ["probe:t1", "probe:t2"])
        check_eq("the default budget is about 90 s", D.SETTLE_BUDGET_S, 90)
        # the stand is checked ONCE, first
        asked = []
        stub = Stub(w)
        settle(w, stub, stand=lambda: asked.append(1) or (False, ""))
        check_eq("V1: the stand is asked once for five items", len(asked), 1)
        check_eq("...and a free stand lets them all run", len(stub.kinds()), 5)
        stub = Stub(w)
        doc = settle(w, stub, stand=lambda: (True, "the stand default is held by run j1 (pid 4)"))
        check_eq("a busy stand: nothing is started", stub.kinds(), [])
        check_eq("...every item is left with reason 'stand' and the holder's words",
                 sorted({i["reason"] for i in doc["left"]}), ["stand"])
        check_in("...naming the holder", "run j1", doc["left"][0]["reason_words"])
        check_eq("...and the record says the stand was busy", doc["budget"]["stand_busy"], True)
        stub = Stub(w)
        settle(w, stub, stand=lambda: (_ for _ in ()).throw(RuntimeError("lease file broken")))
        check_eq("a stand check that itself fails is 'not busy': the first probe is the check", len(stub.kinds()), 5)
        # the stand is not even asked when nothing is for code to do
        put_manifest(w, [row(w, "t1")])
        record(w, "t1", mutation="swap_operands")
        asked.clear()
        settle(w, Stub(w), stand=lambda: asked.append(1) or (False, ""))
        check_eq("only leave_to_critic items: the stand is not asked", asked, [])
    finally:
        cleanup(w.project)


def the_budget_bounds_the_whole_call():
    """B-207, the critic's addition: `story_step start` runs the settle through a shell call that times out
    at 120 s, so the budget must bound the WHOLE call - a probe that would not fit is not begun, and one
    that has begun is given the time left as its own `--timeout` (never a kill: probe_by_code mutates the
    author's file in place and restores it in a `finally`, which a kill skips)."""
    w = world()
    try:
        ids = [f"t{n}" for n in range(1, 5)]
        put_manifest(w, [row(w, i) for i in ids])
        for i in ids:
            record(w, i)

        def timeouts(stub):
            return [a[a.index("--timeout") + 1] if "--timeout" in a else None
                    for script, a in stub.calls if script != "manifest_from_tests.py"]
        # the witness of the dispatch: a probe of 30 s, a budget of 45 s
        stub = Stub(w)
        stub.step = 30.0
        doc = settle(w, stub, budget_s=45)
        check_eq("probe 30 s, budget 45 s: ONE probe runs", stub.kinds(), ["probe:t1"])
        check_eq("...the second is left with reason 'budget', and every one after it",
                 [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("t2", "budget"), ("t3", "budget"), ("t4", "budget")])
        check_in("...its words give the time left", "15 s left", doc["left"][0]["reason_words"])
        check_in("...and the longest probe so far", "took 30 s", doc["left"][0]["reason_words"])
        check("...and the settle ends inside the budget (30 s of 45)", stub.now <= 45, str(stub.now))
        # the boundary: time left EQUAL to the longest probe fits, one tenth of a second less does not
        for budget, expected in ((60, ["probe:t1", "probe:t2"]), (59.9, ["probe:t1"]), (30, ["probe:t1"]),
                                 (89.9, ["probe:t1", "probe:t2"]), (90, ["probe:t1", "probe:t2", "probe:t3"])):
            stub = Stub(w)
            stub.step = 30.0
            settle(w, stub, budget_s=budget)
            check_eq(f"fit: budget {budget} s, probes of 30 s: {len(expected)} begin", stub.kinds(), expected)
        # the FIRST probe always runs, whatever the budget
        stub = Stub(w)
        stub.step = 500.0
        doc = settle(w, stub, budget_s=10)
        check_eq("the first probe runs even when it is expected to be longer than the whole budget",
                 stub.kinds(), ["probe:t1"])
        check_eq("...and its own timeout is the budget, not its 1860 s default", timeouts(stub), ["10"])
        # each probe's own timeout is the time LEFT; the process timeout is that plus the margin
        stub = Stub(w)
        stub.step = 30.0
        settle(w, stub, budget_s=100)
        check_eq("each probe is given the time left as its own --timeout", timeouts(stub), ["100", "70", "40"])
        check_eq("...and the process timeout (the net under a hung probe) is that plus the margin",
                 stub.timeouts, [100 + D.PROBE_PROCESS_MARGIN_S, 70 + D.PROBE_PROCESS_MARGIN_S,
                                 40 + D.PROBE_PROCESS_MARGIN_S])
        stub = Stub(w)
        settle(w, stub, budget_s=10000)
        check_eq("the process timeout never exceeds PROBE_PROCESS_TIMEOUT_S", max(stub.timeouts),
                 D.PROBE_PROCESS_TIMEOUT_S)
        stub = Stub(w)
        settle(w, stub, budget_s=0.5)
        check_eq("a fraction of a second left is at least 1 s of timeout for the probe", timeouts(stub)[0], "1")
        check("the `command` the critic copies carries no timeout of ours",
              all("--timeout" not in i["command"] for i in doc["left"]), str([i["command"] for i in doc["left"]]))
        # a slow rebind counts: the budget used up by it leaves the item, with no probe on other bytes
        put_manifest(w, [row(w, "t1", bound=STALE)])
        stub = Stub(w)
        stub.manifest_step = 50.0
        doc = settle(w, stub, budget_s=90)
        check_eq("a rebind that used the whole budget: no probe is begun", stub.kinds(), ["dry", "write"])
        check_eq("...the item is left with reason 'budget'", [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("t1", "budget")])
        check_in("...and the words name the rebind", "by the rebind", doc["left"][0]["reason_words"])

        # the rebind's own subprocesses (dry run, write) get the time LEFT as their timeout, never more
        # than MANIFEST_PROCESS_TIMEOUT_S
        def stale():   # a successful rebind binds the row, so each scenario starts from a stale one again
            put_manifest(w, [row(w, "t1", bound=STALE)])
        stale()
        stub = Stub(w)
        stub.manifest_step = 30.0
        settle(w, stub, budget_s=100)
        check_eq("rebind: dry run gets the whole 100 s, the write the 70 s left", stub.manifest_timeouts,
                 [("dry", 100), ("write", 70)])
        stale()
        stub = Stub(w)
        settle(w, stub, budget_s=500)
        check_eq("rebind: and never more than MANIFEST_PROCESS_TIMEOUT_S", stub.manifest_timeouts,
                 [("dry", D.MANIFEST_PROCESS_TIMEOUT_S), ("write", D.MANIFEST_PROCESS_TIMEOUT_S)])
        # a rebind step that times out: the item is left with reason 'budget', and nothing is probed
        for kind in ("dry", "write"):
            stale()
            stub = Stub(w)
            stub.manifest_raise[kind] = subprocess.TimeoutExpired(["manifest_from_tests.py"], 1)
            doc = settle(w, stub, budget_s=90)
            check_eq(f"rebind timeout ({kind}): no probe is begun", [k for k in stub.kinds() if k.startswith("probe")], [])
            check_eq(f"rebind timeout ({kind}): the item is left with reason 'budget'",
                     [(i["instance_id"], i["reason"]) for i in doc["left"]], [("t1", "budget")])
            check_in(f"rebind timeout ({kind}): in words that name the step", f"rebind {'dry run' if kind == 'dry' else kind} did not finish",
                     doc["left"][0]["reason_words"])
            check_eq(f"rebind timeout ({kind}): the outcome is a kept row, not an exception",
                     [(o["step"], o["result"]) for o in doc["outcomes"]], [("rebind", "kept")])
        # the budget used up by the dry run: the write is not even started
        stale()
        stub = Stub(w)
        stub.manifest_step = 100.0
        doc = settle(w, stub, budget_s=90)
        check_eq("rebind: budget gone after the dry run - the write is not started", stub.kinds(), ["dry"])
        check_in("...the words say so", "used up before the rebind write could start", doc["left"][0]["reason_words"])
        # a timeout stops the settle: the items after it are left with the same reason
        put_manifest(w, [row(w, "t1", bound=STALE), row(w, "t2")])
        record(w, "t2")
        stub = Stub(w)
        stub.manifest_raise["dry"] = subprocess.TimeoutExpired(["manifest_from_tests.py"], 1)
        doc = settle(w, stub, budget_s=90)
        check_eq("rebind timeout: the next item is left 'budget' too and nothing is probed",
                 ([(i["instance_id"], i["reason"]) for i in doc["left"]], stub.kinds()),
                 ([("t1", "budget"), ("t2", "budget")], ["dry"]))
        # any OTHER failure of the rebind is still its own reason
        put_manifest(w, [row(w, "t1", bound=STALE), row(w, "t2")])
        stub = Stub(w)
        stub.manifest_raise["dry"] = OSError("no interpreter")
        doc = settle(w, stub, budget_s=90)
        check_eq("rebind: an OSError is reason 'rebind', not 'budget'", doc["left"][0]["reason"], "rebind")
    finally:
        cleanup(w.project)


def an_item_is_not_probed_twice_on_the_same_bytes():
    """An item unchanged since a `not_executed` attempt is not re-probed at every critic start: the debt
    file remembers the bytes (`current_sha`) of the last attempt, and only a changed sha probes again."""
    w = world()
    try:
        put_manifest(w, [row(w, "t1"), row(w, "t2")])
        record(w, "t1")
        record(w, "t2")
        not_executed = (1, {"verdict": "not_executed", "restore": {"verified": True},
                            "notes": ["run_suite printed no summary (exit 3)"]})
        stub = Stub(w)
        stub.probe["t1"] = not_executed
        first = settle(w, stub)
        check_eq("first settle: t1 ends not_executed and stops it", stub.kinds(), ["probe:t1"])
        check_eq("...the debt file remembers it, with the bytes it was probed on",
                 [(a["instance_id"], a["current_sha"], a["result"]) for a in first["last_attempts"]],
                 [("t1", w.sha, "not_executed")])
        stub = Stub(w)
        second = settle(w, stub)
        check_eq("second settle, same bytes: t1 is NOT probed again, t2 is", stub.kinds(), ["probe:t2"])
        left = by_id(second["left"]).get("t1", {})
        check_eq("...t1 is left with its own reason", left.get("reason"), "same_bytes")
        check_in("...in words that say why", "same bytes as the last attempt", left.get("reason_words", ""))
        check("...and its command is still there for the critic", bool(left.get("command")))
        check_eq("...the memory is carried forward as it was",
                 second["last_attempts"], first["last_attempts"])
        check_eq("...and is on disk for the next settle",
                 json.loads((w.task_root / D.MEMORY_REL).read_text(encoding="utf-8"))["last_attempts"],
                 first["last_attempts"])
        # other verdicts are not remembered: only what ended not_executed
        stub = Stub(w)
        stub.probe["t2"] = (0, {"verdict": "no_failure", "restore": {"verified": True}, "notes": []})
        settle(w, stub)
        stub = Stub(w)
        third = settle(w, stub)
        check_eq("a no_failure is probed again at the next settle", "probe:t2" in stub.kinds(), True)
        check_eq("...and is not in the memory", [a["instance_id"] for a in third["last_attempts"]], ["t1"])
        # a changed file has a new sha: probed again, and the old memory goes
        (w.project / TEST_REL).write_text(TEST_SRC + "\n\ndef test_c():\n    assert 3 == 3\n", encoding="utf-8")
        w.sha = sha((w.project / TEST_REL).read_bytes())
        put_manifest(w, [row(w, "t1"), row(w, "t2")])
        stub = Stub(w)
        fourth = settle(w, stub)
        check_eq("a changed file (a new sha) is probed again", stub.kinds(), ["probe:t1", "probe:t2"])
        check_eq("...and nothing is left nor remembered", (fourth["left"], fourth["last_attempts"]), ([], []))
        # a memory that cannot be read is no memory: probed again (an error errs toward running)
        write(w.task_root / D.MEMORY_REL, "{not json")
        stub = Stub(w)
        settle(w, stub)
        check_eq("an unreadable debt file: both items are probed", stub.kinds(), ["probe:t1", "probe:t2"])
        # an entry that names other bytes, or no bytes, is ignored
        stub = Stub(w)
        stub.probe["t1"] = not_executed
        settle(w, stub)
        memory = json.loads((w.task_root / D.MEMORY_REL).read_text(encoding="utf-8"))
        memory["last_attempts"][0]["current_sha"] = "0" * 64
        write(w.task_root / D.MEMORY_REL, memory)
        stub = Stub(w)
        settle(w, stub)
        check_eq("an entry for other bytes is no memory of these", stub.kinds(), ["probe:t1", "probe:t2"])
    finally:
        cleanup(w.project)


NO_FAILURE = (0, {"verdict": "no_failure", "restore": {"verified": True}, "notes": []})


def _refused_world(w):
    """Two rows: `ra` binds other bytes and its dry run would write nothing (the rebind is kept); `rb` binds the
    current bytes and its probe says no_failure (left every time, so the settle never counts as 'nothing changed')."""
    put_manifest(w, [row(w, "ra", bound=STALE), row(w, "rb")])
    record(w, "ra", measured=STALE)
    record(w, "rb")


def _refused_stub(w):
    stub = Stub(w)
    stub.dry_ids = []
    stub.probe["rb"] = NO_FAILURE
    return stub


def settle_skips_refused_rebind_on_same_bytes():
    w = world()
    try:
        _refused_world(w)
        stub = _refused_stub(w)
        first = settle(w, stub)
        check_eq("first settle: the dry run of ra is made and refuses, rb is probed", stub.kinds(), ["dry", "probe:rb"])
        check_eq("...the kept rebind is remembered with its step",
                 [(a["instance_id"], a["step"], a["result"]) for a in first["last_attempts"]], [("ra", "rebind", "kept")])
        stub = _refused_stub(w)
        second = settle(w, stub)
        check_eq("second settle, same bytes: ra is NOT dry-run again, rb is probed", stub.kinds(), ["probe:rb"])
        left = by_id(second["left"])
        check_eq("...ra is left with its own word for a kept rebind", left["ra"]["reason"], "rebind_same_bytes")   # kept_rebind_has_own_word
        check_in("...and the earlier words", D.REBIND_LEFT, left["ra"]["reason_words"])
        check("...and its command is still there", bool(left["ra"]["command"]))
        check_eq("...the memory is carried forward", second["last_attempts"], first["last_attempts"])
        stub = _refused_stub(w)
        settle(w, stub)
        check_eq("third settle: still not dry-run", stub.kinds(), ["probe:rb"])
        # the memory survives a settle that stops before the item is reached (the stand is busy)
        stub = _refused_stub(w)
        busy = settle(w, stub, stand=lambda: (True, "a run is going"))
        check_eq("a busy stand starts nothing", stub.kinds(), [])
        check_eq("...and ra stays remembered", [a["instance_id"] for a in busy["last_attempts"]], ["ra"])
    finally:
        cleanup(w.project)


def settle_retries_when_bound_sha_changes():
    w = world()
    try:
        _refused_world(w)
        settle(w, _refused_stub(w))
        # the author re-ran manifest_from_tests: the row binds ANOTHER old sha, the file is the same bytes
        put_manifest(w, [row(w, "ra", bound="beef" + "0" * 60), row(w, "rb")])
        stub = _refused_stub(w)
        doc = settle(w, stub)
        check_eq("same current_sha, a changed bound_sha: the rebind is tried again", stub.kinds(), ["dry", "probe:rb"])
        check_eq("...and its new kept stamp holds the new bound sha",
                 [s["bound_sha"] for s in doc["stamps"] if s["instance_id"] == "ra"], ["beef" + "0" * 60])
        # a changed file (a new current_sha) is tried again too
        (w.project / TEST_REL).write_text(TEST_SRC + "\n\ndef test_c():\n    assert 3 == 3\n", encoding="utf-8")
        w.sha = sha((w.project / TEST_REL).read_bytes())
        put_manifest(w, [row(w, "ra", bound="beef" + "0" * 60), row(w, "rb", bound=w.sha)])
        stub = _refused_stub(w)
        settle(w, stub)
        check_eq("a new current_sha: the rebind is tried again", stub.kinds(), ["dry", "probe:rb"])
    finally:
        cleanup(w.project)


def settle_retries_when_record_mtime_changes():
    w = world()
    try:
        _refused_world(w)
        settle(w, _refused_stub(w))
        path = record(w, "ra", measured=STALE, mutation="expected",
                      detail={"line": 2, "mutation": "expected"})   # the same sha, a new mutation
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        stub = _refused_stub(w)
        settle(w, stub)
        check_eq("a record rewritten on the same shas: the rebind is tried again", stub.kinds(), ["dry", "probe:rb"])
    finally:
        cleanup(w.project)


def settle_retries_when_manifest_ids_change():
    """F8: `ra` is kept because its dry run would write an id the manifest does not hold; another window's manifest_put
    adds that id (shas and record unchanged): the same dry run may pass now, so it is made again."""
    w = world()
    try:
        _refused_world(w)
        stub = _refused_stub(w)
        stub.dry_ids = ["ghost"]
        first = settle(w, stub)
        check_eq("first: the dry run would write an unknown id, the rebind is kept and remembered",
                 [(a["instance_id"], a["step"]) for a in first["last_attempts"]], [("ra", "rebind")])
        stub = _refused_stub(w)
        stub.dry_ids = ["ghost"]
        settle(w, stub)
        check_eq("control: nothing else changed - not dry-run again", stub.kinds(), ["probe:rb"])
        put_manifest(w, [row(w, "ra", bound=STALE), row(w, "rb"), row(w, "ghost")])
        stub = _refused_stub(w)
        stub.dry_ids = ["ghost"]
        settle(w, stub)
        check_eq("the manifest now holds the id: the dry run is made again", stub.kinds(), ["dry", "probe:rb"])
        # the stamp-level fact: the manifest ids are in the stamp, and they differ
        a = D._manifest_ids({"tests": [row(w, "ra")]}, {"instance_id": "ra"})
        b = D._manifest_ids({"tests": [row(w, "ra"), row(w, "ghost")]}, {"instance_id": "ra"})
        check("the stamp's manifest_ids differ when a row is added", a and b and a != b, f"{a} {b}")
        check_eq("...and are None when the row cannot be read", D._manifest_ids({}, {"instance_id": "ra"}), None)
    finally:
        cleanup(w.project)


def settle_retries_after_a_dry_run_that_did_not_run():
    """F9: a dry run that raised, an exit with no JSON, a refused write say nothing about the bytes: not remembered,
    not 'nothing changed'. A JSON refusal is a fact about the bytes: remembered."""
    w = world()
    try:
        put_manifest(w, [row(w, "ra", bound=STALE)])
        record(w, "ra", measured=STALE)
        stub = Stub(w)
        stub.manifest_raise["dry"] = RuntimeError("the runner fell over")
        first = settle(w, stub)
        check_eq("runner raised: ra is left with reason rebind, nothing is remembered",
                 ([i["reason"] for i in first["left"]], first["last_attempts"]), (["rebind"], []))
        stub = Stub(w)
        stub.dry_ids = []
        second = settle(w, stub)
        check_eq("second settle calls the dry run again (not 'nothing changed')", stub.kinds(), ["dry"])
        check_eq("...and a dry run that would not write IS remembered", [a["instance_id"] for a in second["last_attempts"]], ["ra"])
        for label, rc, out, remembered in (("an exit with no JSON", 1, "boom", False),
                                            ("a JSON refusal", 2, json.dumps({"ok": False, "refusal": "no"}), True),
                                            ("a JSON failure with no refusal", 1, json.dumps({"ok": False}), False)):
            (w.task_root / D.MEMORY_REL).unlink(missing_ok=True)
            stub = Stub(w)
            stub.dry_rc, stub.dry_out = rc, out
            doc = settle(w, stub)
            check_eq(f"{label}: remembered={remembered}", bool(doc["last_attempts"]), remembered)
            stub = Stub(w)
            stub.dry_rc, stub.dry_out = rc, out
            settle(w, stub)
            check_eq(f"{label}: the next settle calls the dry run again={not remembered}", stub.kinds() == ["dry"], not remembered)
        (w.task_root / D.MEMORY_REL).unlink(missing_ok=True)
        stub = Stub(w)
        stub.write_rc = 1
        doc = settle(w, stub)
        check_eq("a refused write is not remembered", (stub.kinds(), doc["last_attempts"]), (["dry", "write"], []))
    finally:
        cleanup(w.project)


def settle_scope_of_a_new_dispatch_is_read_before_nothing_changed():
    """F10: an item left for `rebind` by dispatch A, and critic B's scope excludes its case: `scope`, no subprocess."""
    w = world()
    try:
        put_manifest(w, [row(w, "ra", bound=STALE)])
        record(w, "ra", measured=STALE)
        stub = Stub(w)
        stub.dry_ids = []
        settle(w, stub)
        calls = []

        def counting(argv, cwd=None, timeout=None):
            calls.append(argv)
            raise AssertionError("a subprocess was started")
        later = "S5-qa-code-critic-3"
        record_b = dict(w.controller["dispatches"][CRITIC], scope=["TC-2"])
        doc = D.settle(TASK, w.task_root, w.project, later, dispatch_record=dict(record_b, scope=["TC-1"]),
                       runner=counting, clock=Stub(w).clock, stand=lambda: (False, ""))
        check_eq("control: the case in scope - nothing changed, 0 calls", (len(calls), bool(doc.get("unchanged_since"))), (0, True))
        doc = D.settle(TASK, w.task_root, w.project, later, dispatch_record=record_b, runner=counting,
                       clock=Stub(w).clock, stand=lambda: (False, ""))
        check_eq("scope excludes the case: no subprocess", len(calls), 0)
        check_eq("...the item is left for scope, with no rebind outcome",
                 ([i["reason"] for i in doc["left"]], [o["result"] for o in doc["outcomes"]]),
                 (["scope"], ["outside_scope"]))
        check("...and it is not the 'unchanged' road", not doc.get("unchanged_since"), str(doc.get("unchanged_since")))
    finally:
        cleanup(w.project)


def settle_nothing_changed_writes_no_subprocess():
    w = world()
    try:
        put_manifest(w, [row(w, "ra", bound=STALE)])
        record(w, "ra", measured=STALE)
        stub = Stub(w)
        stub.dry_ids = []
        first = settle(w, stub)
        check_eq("first settle: the dry run refuses", (stub.kinds(), [i["reason"] for i in first["left"]]),
                 (["dry"], ["rebind"]))
        calls = []

        def counting(argv, cwd=None, timeout=None):
            calls.append(argv)
            raise AssertionError("a subprocess was started")
        stood = []
        later = "S5-qa-code-critic-3"
        doc = D.settle(TASK, w.task_root, w.project, later, runner=counting, clock=Stub(w).clock,
                       stand=lambda: stood.append(1) or (False, ""))
        check_eq("nothing changed: the injected runner counts 0 calls, the stand is not asked", (len(calls), stood), (0, []))
        check_eq("...the doc says which dispatch it stood on", doc.get("unchanged_since"), CRITIC)
        check_eq("...and is addressed to the new one, commands included", (doc["dispatch"], doc["outcomes"]), (later, []))
        left = doc["left"][0]
        check_eq("...ra is still left, for its old reason", (left["instance_id"], left["reason"]), ("ra", "rebind"))
        check_in("...with a command spelled with the new dispatch", later, left["command"])
        disk = json.loads((w.task_root / D.debt_rel(later)).read_text(encoding="utf-8"))
        check_eq("...and that is the file on disk", (disk["dispatch"], disk["unchanged_since"]), (later, CRITIC))
        again = D.settle(TASK, w.task_root, w.project, later, runner=counting, clock=Stub(w).clock)
        check_eq("...and again: still no call", (len(calls), again["unchanged_since"]), (0, later))
        # a debt file of another story is no memory
        disk["task"] = "OTHER-1"
        write(w.task_root / D.MEMORY_REL, disk)
        stub = Stub(w)
        stub.dry_ids = []
        settle(w, stub)
        check_eq("a debt file of another story is ignored: the settle runs", stub.kinds(), ["dry"])
        # an item that was left for a reason a repeat could change (a stand, a probe result) is run again
        put_manifest(w, [row(w, "rb")])
        record(w, "rb")
        stub = Stub(w)
        stub.probe["rb"] = NO_FAILURE
        settle(w, stub)
        stub = Stub(w)
        stub.probe["rb"] = NO_FAILURE
        settle(w, stub)
        check_eq("a probe result may come out differently: not skipped", stub.kinds(), ["probe:rb"])
        # no debt at all creates no file and is no 'nothing changed'
        put_manifest(w, [])
        PL.probe_record_path(w.task_root, "rb").unlink()
        PL.probe_record_path(w.task_root, "ra").unlink()
        (w.task_root / D.MEMORY_REL).unlink()
        check_eq("no item, no info: no file", (settle(w, Stub(w)).get("unchanged_since"),
                                                 (w.task_root / D.MEMORY_REL).exists()), (None, False))
    finally:
        cleanup(w.project)


def settle_unreadable_memory_runs():
    w = world()
    try:
        put_manifest(w, [row(w, "ra", bound=STALE)])
        record(w, "ra", measured=STALE)
        stub = Stub(w)
        stub.dry_ids = []
        settle(w, stub)
        for label, text in (("not JSON", "{not json"), ("a list", "[1, 2]"), ("empty", "")):
            write(w.task_root / D.MEMORY_REL, text)
            stub = Stub(w)
            stub.dry_ids = []
            settle(w, stub)
            check_eq(f"a debt file that is {label} is no memory: the dry run is made", stub.kinds(), ["dry"])
        # a stamp with a field missing never matches
        good = json.loads((w.task_root / D.MEMORY_REL).read_text(encoding="utf-8"))
        good["stamps"][0].pop("record_mtime_ns")
        for entry in good["last_attempts"]:
            entry["stamp"].pop("record_mtime_ns")
        write(w.task_root / D.MEMORY_REL, good)
        stub = Stub(w)
        stub.dry_ids = []
        settle(w, stub)
        check_eq("a stamp that lacks a field is no memory", stub.kinds(), ["dry"])
    finally:
        cleanup(w.project)


def the_count_cap_at_25_and_26():
    for count, expected_probes, expected_left in ((25, 25, 0), (26, 25, 1)):
        w = world()
        try:
            ids = [f"t{n:02d}" for n in range(count)]
            put_manifest(w, [row(w, i) for i in ids])
            for i in ids:
                record(w, i)
            stub = Stub(w)
            doc = settle(w, stub)
            check_eq(f"(d) {count} items: {expected_probes} are probed", len(stub.kinds()), expected_probes)
            check_eq(f"(d) {count} items: {expected_left} left", len(doc["left"]), expected_left)
            if expected_left:
                check_eq("(d) the one beyond the cap is the LAST item, reason 'limit'",
                         [(i["instance_id"], i["reason"]) for i in doc["left"]], [("t25", "limit")])
            check_eq(f"(d) {count} items: the record counts the probes started", doc["budget"]["probes_started"],
                     expected_probes)
        finally:
            cleanup(w.project)
    check_eq("SETTLE_LIMIT is 25", D.SETTLE_LIMIT, 25)
    w = world()
    try:
        put_manifest(w, [row(w, "a"), row(w, "b"), row(w, "c")])
        for i in "abc":
            record(w, i)
        stub = Stub(w)
        doc = settle(w, stub, limit=2)
        check_eq("the limit is a parameter of the settle (a third item is left)",
                 (len(stub.kinds()), [i["reason"] for i in doc["left"]]), (2, ["limit"]))
    finally:
        cleanup(w.project)


def an_item_outside_the_dispatch_scope_is_left():
    w = world(scope=("TC-1",))
    try:
        put_manifest(w, [row(w, "test_a"), row(w, "test_b", case="TC-9")])
        record(w, "test_a")
        record(w, "test_b")
        stub = Stub(w)
        doc = settle(w, stub)
        check_eq("a case outside the critic dispatch's scope is not probed, the other one is",
                 stub.kinds(), ["probe:test_a"])
        check_eq("...it is left with reason 'scope'", [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("test_b", "scope")])
        check_in("...with the words build_mine_request uses", "outside its scope", doc["left"][0]["reason_words"])
        check_in("...naming the scope", "TC-1", doc["left"][0]["reason_words"])
        # a person's recorded word for the scope block passes it (build_mine_request looks it up the same way)
        word = {"stage": "S5", "match": "outside its scope", "decision": "go on, I asked",
                "at": "2026-09-30T06:00:00+00:00"}
        write(w.task_root / "pipeline.json", {"stage_overrides": [word]})
        stub = Stub(w)
        doc = settle(w, stub)
        check_eq("a waiver for the scope block: the item is NOT left with 'scope', it is probed",
                 (stub.kinds(), doc["left"]), (["probe:test_a", "probe:test_b"], []))
        write(w.task_root / "pipeline.json", {"stage_overrides": [dict(word, stage="S6")]})
        check_eq("a waiver of another stage does not pass it",
                 [i["reason"] for i in settle(w, Stub(w))["left"]], ["scope"])
        write(w.task_root / "pipeline.json", {"stage_overrides": [dict(word, revoked_at="2026-09-30T07:00:00+00:00")]})
        check_eq("a revoked waiver does not pass it",
                 [i["reason"] for i in settle(w, Stub(w))["left"]], ["scope"])
        write(w.task_root / "pipeline.json", {"stage_overrides": [dict(word, match="some other block")]})
        check_eq("a waiver for another block does not pass it",
                 [i["reason"] for i in settle(w, Stub(w))["left"]], ["scope"])
    finally:
        cleanup(w.project)


def hf8_18_c_k12_a_row_of_another_spelling_passes_the_outside_scope_door():
    """C-K12 (HF8-18 N1 widens the door `_outside_scope_door` asks): the row holds a receipt of another spelling of the same test
    on other bytes - the door is "stale"; a row with no receipt - "" (no word recorded), as before."""
    import test_proof_level as TPL
    s, edit, put_receipt, row = TPL.other_spelling_world()
    try:
        bare = put_receipt("test_a", "test_a")
        s.put("tests/test_a.py", edit)
        item = {"instance_id": "test_a[p]", "case": "TC-1"}
        write(s.task / "work" / "automation-manifest.json", {"tests": [row("test_a[p]", bare)]})
        check_eq("C-K12: a receipt of another spelling of the same test on other bytes - the stale door",
                 D._outside_scope_door(s.task, {"stage": "S5"}, item, "D-1", ["TC-9"]), "stale")
        write(s.task / "work" / "automation-manifest.json", {"tests": [row("test_a[p]")]})
        check_eq("C-K12: the row with no receipt - no door, as before",
                 D._outside_scope_door(s.task, {"stage": "S5"}, item, "D-1", ["TC-9"]), "")
    finally:
        s.close()


def the_debt_file():
    w = world()
    try:
        stub = Stub(w)
        put_manifest(w, [row(w, "test_a")])
        doc = settle(w, stub)
        check_eq("(i) no record, no item, no info: no file is written (the reader looks for one)",
                 (doc["left"], doc["outcomes"], doc["info"], (w.task_root / D.debt_rel(CRITIC)).exists()), ([], [], [], False))
        put_manifest(w, [row(w, "test_a", required=False)])
        record(w, "test_a")
        settle(w, Stub(w))
        debt = json.loads((w.task_root / D.debt_rel(CRITIC)).read_text(encoding="utf-8"))
        check_eq("(i) an info row alone is enough to write it", [i["instance_id"] for i in debt["info"]], ["test_a"])
        check_eq("...the shape: schema, task, dispatch, outcomes, left, info, last_attempts, stamps, budget", sorted(debt),
                 sorted(["schema_version", "task", "dispatch", "generated_at", "outcomes", "left", "info",
                         "last_attempts", "stamps", "budget"]))
        # Q2: a file an earlier settle left is REWRITTEN, empty, when a later settle finds nothing
        (w.task_root / "work" / "probes" / "test_a.json").unlink()
        doc = settle(w, Stub(w))
        again = json.loads((w.task_root / D.debt_rel(CRITIC)).read_text(encoding="utf-8"))
        check_eq("an existing debt file is rewritten with empty lists when nothing is found",
                 (again["left"], again["outcomes"], again["info"]), ([], [], []))
        check("...and says when it was settled", bool(again.get("settled_at")), str(sorted(again)))
        (w.task_root / D.debt_rel(CRITIC)).unlink()
        (w.task_root / D.MEMORY_REL).unlink(missing_ok=True)
        settle(w, Stub(w))
        check("...while an empty find creates no file where there was none", not (w.task_root / D.debt_rel(CRITIC)).exists() and not (w.task_root / D.MEMORY_REL).exists())
        put_manifest(w, [row(w, "test_a")])
        record(w, "test_a", mutation="swap_operands")
        settle(w, Stub(w))
        debt = json.loads((w.task_root / D.debt_rel(CRITIC)).read_text(encoding="utf-8"))
        check_eq("a leave_to_critic item is in `left` with its command and reason",
                 [(i["instance_id"], i["reason"], bool(i["command"])) for i in debt["left"]], [("test_a", "critic", True)])
        # the settle itself writes no receipt and no manifest field
        before = tree(w.project)
        stub = Stub(w)
        settle(w, stub)
        after = tree(w.project)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        check_eq("the settle writes the debt file and nothing else of its own", [c for c in changed if "probe-debt" not in c], [])
        check("...no receipt directory", not (w.task_root / "work" / "sensitivity-receipts").exists())
    finally:
        cleanup(w.project)


# --- the command line ----------------------------------------------------------------------------------

def arguments():
    w = world()
    try:
        put_manifest(w, [row(w, "test_a")])
        record(w, "test_a")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(w.project))

        def cli(*args, **kw):
            return run_script("probe_debt.py", *args, cwd=w.project, env=kw.get("env", env))
        proc = cli("--task", TASK, "--settle")
        check_eq("(vi) --settle without --dispatch: exit 2", proc.returncode, 2)
        check("(vi) ...with the usage line and what was expected", "usage:" in proc.stderr and "--dispatch" in proc.stderr,
              proc.stderr)
        proc = cli("--task", TASK, "--settle", "--dispatch", "")
        check_eq("(vi) an empty --dispatch: exit 2", proc.returncode, 2)
        for label, given in (("an unknown id", "S5-qa-code-critic-9"), ("the author's accepted dispatch", AUTHOR)):
            proc = cli("--task", TASK, "--settle", "--dispatch", given)
            check_eq(f"(vi) {label} is not an open critic dispatch: exit 2", proc.returncode, 2)
            check_in(f"(vi) ...and the message names the expectation ({label})", "open S5 qa-code-critic dispatch",
                     proc.stderr)
            check_in(f"(vi) ...and names the one that IS open ({label})", CRITIC, proc.stderr)
        w.controller["dispatches"][CRITIC]["status"] = "accepted"
        write(w.task_root / "state" / "controller.json", w.controller)
        check_eq("(vi) a critic dispatch that is no longer running: exit 2",
                 cli("--task", TASK, "--settle", "--dispatch", CRITIC).returncode, 2)
        w.controller["dispatches"][CRITIC].update(status="running", stage="S6")
        write(w.task_root / "state" / "controller.json", w.controller)
        check_eq("(vi) a critic dispatch of another stage: exit 2",
                 cli("--task", TASK, "--settle", "--dispatch", CRITIC).returncode, 2)
        w.controller["dispatches"][CRITIC].update(stage="S5", role="qa-runner")
        write(w.task_root / "state" / "controller.json", w.controller)
        check_eq("(vi) an open dispatch of another role: exit 2",
                 cli("--task", TASK, "--settle", "--dispatch", CRITIC).returncode, 2)
        # --budget-s (B-207: `story_step start` passes what is left of its own budget)
        for label, given in (("zero", "0"), ("negative", "-5"), ("not a number", "soon"), ("nan", "nan"),
                             ("infinite", "inf")):
            proc = cli("--task", TASK, "--settle", "--dispatch", CRITIC, "--budget-s", given)
            check_eq(f"--budget-s {label}: exit 2", proc.returncode, 2)
        proc = cli("--task", TASK, "--settle", "--dispatch", CRITIC, "--budget-s", "0")
        check_in("--budget-s 0: the message says what is expected", "above 0", proc.stderr)
        proc = cli("--task", TASK, "--budget-s", "30")
        check_eq("--budget-s without --settle: exit 2", proc.returncode, 2)
        check_in("...and says it belongs to --settle", "--budget-s belongs to --settle", proc.stderr)
        check_eq("no story folder: exit 2", cli("--task", "NOPE-1").returncode, 2)
        check_eq("a task id that is a path: exit 2", cli("--task", "../x").returncode, 2)
        check_eq("no arguments: exit 2 (argparse)", cli().returncode, 2)
        check("none of the refusals wrote the debt file", not (w.task_root / D.debt_rel(CRITIC)).exists())
    finally:
        cleanup(w.project)


def the_command_line_end_to_end_with_stub_tools():
    w = world()
    scripts = temp_dir("qa-probe-debt-stubs-")
    try:
        put_manifest(w, [row(w, "test_a", bound=STALE), row(w, "test_b")])
        record(w, "test_a", measured=STALE)
        record(w, "test_b")
        log = scripts / "calls.log"
        probe_stub = write(scripts / "stub_probe.py", (
            "import json, os, sys\n"
            "with open(os.environ['STUB_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(['probe'] + sys.argv[1:]) + '\\n')\n"
            "print(json.dumps({'verdict': 'intended_failure', 'restore': {'verified': True}, 'notes': [],\n"
            "                  'publish': {'published': True}, 'receipt': {'path': 'work/sensitivity-receipts/r.json'}}))\n"))
        manifest_stub = write(scripts / "stub_manifest.py", (
            "import json, os, sys\n"
            "with open(os.environ['STUB_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(['manifest'] + sys.argv[1:]) + '\\n')\n"
            "path = os.environ['STUB_MANIFEST']\n"
            "data = json.load(open(path, encoding='utf-8'))\n"
            "if '--dry-run' in sys.argv:\n"
            "    print(json.dumps({'ok': True, 'fragment': {'tests': [{'instance_id': t['instance_id']} for t in data['tests']]}}))\n"
            "else:\n"
            "    for t in data['tests']:\n"
            "        t['trace_binding'] = {'test_content_sha': os.environ['STUB_SHA']}\n"
            "    json.dump(data, open(path, 'w', encoding='utf-8'))\n"
            "    print(json.dumps({'ok': True}))\n"))
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(w.project), STUB_LOG=str(log),
                   STUB_MANIFEST=str(w.task_root / "work" / "automation-manifest.json"), STUB_SHA=w.sha,
                   **{D.PROBE_SCRIPT_ENV: str(probe_stub), D.MANIFEST_SCRIPT_ENV: str(manifest_stub)})
        proc = run_script("probe_debt.py", "--task", TASK, "--settle", "--dispatch", CRITIC, "--json",
                          cwd=w.project, env=env)
        check("settle through the real command line and real subprocesses (stub tools): exit 0",
              proc.returncode == 0, proc.stdout + proc.stderr)
        try:
            doc = json.loads(proc.stdout)
        except ValueError:
            doc = {}
        check("FR-14: stdout is one JSON document and nothing else", bool(doc), proc.stdout[:300])
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        check_eq("the stubs were called in order: dry run, write, probe, probe",
                 [(c[0], "--dry-run" in c) for c in calls],
                 [("manifest", True), ("manifest", False), ("probe", False), ("probe", False)])
        check_eq("...the probes carry the critic's dispatch", [c[c.index("--dispatch") + 1] for c in calls if c[0] == "probe"],
                 [CRITIC, CRITIC])
        check_eq("both are settled: nothing left", doc.get("left"), [])
        check("work/probe-debt.json exists", (w.task_root / D.debt_rel(CRITIC)).is_file())
        proc = run_script("probe_debt.py", "--task", TASK, "--settle", "--dispatch", CRITIC, cwd=w.project, env=env)
        check_in("the human form prints the outcomes", "probe debt settle:", proc.stdout)
    finally:
        cleanup(w.project)
        cleanup(scripts)


def the_budget_on_the_command_line():
    """`--budget-s` through the real command line and real subprocesses (stub tools): a probe of ~3 s under a
    budget of 4 s begins, the second would not fit and is left with reason 'budget'. Only the DIRECTION is
    asserted - a slow machine makes the first probe longer and the second even less likely to fit, and the
    first always runs - so nothing here depends on the clock."""
    w = world()
    scripts = temp_dir("qa-probe-debt-budget-")
    try:
        put_manifest(w, [row(w, "test_a"), row(w, "test_b")])
        record(w, "test_a")
        record(w, "test_b")
        log = scripts / "calls.log"
        probe_stub = write(scripts / "stub_probe.py", (
            "import json, os, sys, time\n"
            "with open(os.environ['STUB_LOG'], 'a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "time.sleep(3)\n"
            "print(json.dumps({'verdict': 'intended_failure', 'restore': {'verified': True}, 'notes': [],\n"
            "                  'publish': {'published': True}, 'receipt': {'path': 'work/sensitivity-receipts/r.json'}}))\n"))
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(w.project), STUB_LOG=str(log),
                   **{D.PROBE_SCRIPT_ENV: str(probe_stub)})
        proc = run_script("probe_debt.py", "--task", TASK, "--settle", "--dispatch", CRITIC, "--budget-s", "4",
                          "--json", cwd=w.project, env=env)
        check_eq("--budget-s through the real command line: exit 0", proc.returncode, 0)
        doc = json.loads(proc.stdout)
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        check_eq("one probe began, the second would not fit", len(calls), 1)
        check_eq("...the second is left with reason 'budget'", [(i["instance_id"], i["reason"]) for i in doc["left"]],
                 [("test_b", "budget")])
        check_eq("...the record says which budget it ran under", doc["budget"]["budget_s"], 4.0)
        given = int(calls[0][calls[0].index("--timeout") + 1])
        check("...and the probe that began was given the time left as its own --timeout (1 to 4 s)",
              1 <= given <= 4, str(calls[0]))
    finally:
        cleanup(w.project)
        cleanup(scripts)


# --- the two unverified facts of R13 (NV) ---------------------------------------------------------------

PROVENANCE = {"profile_id": "unit", "timestamp": "2026-09-24T10:00:00Z", "environment_id": "local",
              "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
              "evidence_refs": ["probe"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact",
                             "deployed_source_revision": "source-1"}}
NV_TASK = "NV-1"
NV_TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n"


def nv_project(scope):
    """A project of test_probe_by_code's shape: one test, one profile, a critic dispatch running with `scope`
    and a request budget of 2, and the author's run in the job store (the producer of the contracts)."""
    root = temp_dir("qa-probe-debt-nv-")
    (root / "tests").mkdir()
    write(root / "tests" / "test_calc.py", NV_TEST)
    write(root / "calc.py", "def add(a, b):\n    return a + b\n")
    bin_dir = root.parent / (root.name + "-bin")
    bin_dir.mkdir()
    write(bin_dir / "pytest", "import sys; sys.exit(3)\n")
    probe_script = write(root.parent / (root.name + "-runtime-probe.py"),
                         "import json\nprint(json.dumps(" + repr(PROVENANCE) + "))\n")
    write(root / "qa-factory" / "config.json", {
        "tests_root": "tests", "app_root": ".",
        "profiles": [{"profile_id": "unit", "selected": True, "roots": {"test": "tests"},
                      "commands": {"one_test": {"argv": [sys.executable, str(bin_dir / "pytest"), "--junitxml",
                                                         "{report_path}"], "cwd": "."}},
                      "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}],
        "execution": {"runtime_probes": {"unit": {"argv": [sys.executable, str(probe_script)], "cwd": ".",
                                                   "timeout_s": 20}}}})
    task_root = root / "qa-factory" / "artifacts" / NV_TASK
    write(task_root / "pipeline.json", {"stages": {"S5": {"status": "running"}},
                                        "first_test_run_at": "2026-09-24T09:00:00+00:00"})
    write(task_root / "state" / "controller.json", {
        "schema_version": "2", "revision": "1", "source_revision": "source-1",
        "dispatches": {CRITIC: {"id": CRITIC, "stage": "S5", "role": "qa-code-critic", "status": "running",
                                "scope": list(scope), "budget": {"requests": 2}}}})
    write(task_root / "work" / "automation-manifest.json", {"tests": [
        {"case": "TC-100", "covers": ["TC-100"], "file": "tests/test_calc.py", "test": "test_add",
         "instance_id": "test_add", "selector": "test_add", "sensitivity_proof_required": True,
         "case_version_links": [{"case_id": "TC-100", "version": "cv_1"}],
         "trace_binding": {"test_content_sha": sha((root / "tests" / "test_calc.py").read_bytes())}}]})
    cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    request, _n, _r, _v = ER.build_mine_request(root, ["TC-100"], cfg=cfg, task=NV_TASK, dispatch_id=CRITIC,
                                                probe=lambda spec: PROVENANCE) \
        if "TC-100" in scope else (None, None, None, None)
    return root, cfg, task_root, request


def nv_scope_and_budget():
    # --- does build_mine_request accept a case outside the critic dispatch's scope? ------------------------
    root, cfg, task_root, _ = nv_project(scope=("TC-200",))
    try:
        use_project(root)
        spec = PBC.parse_node("tests/test_calc.py::test_add")
        try:
            PBC.build_request(root, cfg, NV_TASK, CRITIC, "TC-100", spec, "test_add", "invert", "r")
            refused = ""
        except ER.MineRefusal as exc:
            refused = str(exc)
        check_in("NV-1: a red probe of a case OUTSIDE the critic dispatch's scope is refused (MineRefusal)",
                 "TC-100 is outside its scope", refused)
        check_in("NV-1: the refusal names the dispatch and what it was given", f"{CRITIC} was given TC-200", refused)
        # what probe_by_code does with that refusal: the probe ends not_executed, and the earlier
        # intended_failure record STAYS (t-177: it was overwritten, and the debt vanished from `find`)
        standing = {"verdict": "intended_failure", "instance_id": "test_add", "case": "TC-100",
                    "test_node": "tests/test_calc.py::test_add", "mutation": "invert",
                    "test_file_sha256": OLD, "recorded_at": "2026-09-30T05:02:39+00:00"}
        write(PL.probe_record_path(task_root, "test_add"), standing)
        original = (root / "tests" / "test_calc.py").read_bytes()
        import probe_entries as PE      # the model entry the probe owes for the check, written as every probing test does
        PE.write_invert_entries(task_root, CRITIC, keys=["tests/test_calc.py:5"])
        record_out = PBC.probe(NV_TASK, CRITIC, "tests/test_calc.py::test_add", "test_add", "invert")
        check_eq("NV-1: through probe() the refusal is a `not_executed` run, with the refusal's words in its notes",
                 (record_out["verdict"], any("outside its scope" in n for n in record_out["notes"])), ("not_executed", True))
        check_eq("NV-1: the test file was restored byte for byte", (root / "tests" / "test_calc.py").read_bytes(), original)
        kept = json.loads(PL.probe_record_path(task_root, "test_add").read_text(encoding="utf-8"))
        check_eq("NV-1: the refused re-probe did NOT overwrite the intended_failure record",
                 (kept["verdict"], kept["test_file_sha256"]), ("intended_failure", OLD))
        check_in("NV-1: it says what the attempt was", "outside its scope", kept["last_attempt"]["why"])
        got = D.find(task_root, json.loads((task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8")),
                     root)
        check_eq("NV-1: so the next `find` still lists the item", [i["instance_id"] for i in got["items"]], ["test_add"])
    finally:
        cleanup(root)
    # --- does the run budget allow up to 25 red_probe jobs? ---------------------------------------------------
    root, cfg, task_root, seeded = nv_project(scope=("TC-100",))
    try:
        use_project(root)
        spec = PBC.parse_node("tests/test_calc.py::test_add")
        store = ER.JobStore(task_root / "state" / "execution-jobs")
        store.begin(seeded)
        keys, remaining, refusals, purposes = [], [], [], set()
        for n in range(26):
            try:
                request, _notes = PBC.build_request(root, cfg, NV_TASK, CRITIC, "TC-100", spec, "test_add",
                                                    "invert", f"probe {n}")
            except ER.MineRefusal as exc:
                refusals.append(str(exc))
                break
            store.begin(request)
            keys.append(request["idempotency_key"])
            remaining.append(request["remaining_budget"])
            purposes.add(request["purpose"])
        check_eq("NV-2: every request is a red_probe one", purposes, {"red_probe"})
        check_eq("NV-2: 26 red_probe requests of one dispatch (request budget 2): no refusal", refusals, [])
        check_eq("NV-2: every one got a distinct idempotency key", len(set(keys)), 26)
        check("NV-2: and `remaining_budget` never reaches 0, which is what validate_request refuses",
              min(remaining) >= 1, str(remaining))
    finally:
        cleanup(root)


def a_not_executed_settle_keeps_the_debt():
    """The whole road, in one process: settle -> the real probe() with a run_suite that prints nothing ->
    `not_executed` -> the standing intended_failure record is kept -> the next `find` still lists the item."""
    root, cfg, task_root, _ = nv_project(scope=("TC-100",))
    scripts = temp_dir("qa-probe-debt-crash-")
    saved = os.environ.get("PROBE_RUN_SUITE")
    try:
        use_project(root)
        crash = write(scripts / "crash_run_suite.py", "import sys\nprint('stub: no summary today')\nsys.exit(1)\n")
        os.environ["PROBE_RUN_SUITE"] = str(crash)
        # t-2064 P4c: a record with no `checks[]` is an old one and owes every check (the settle leaves it to the critic, nothing runs);
        # a walk's record stores its models, so the standing record carries them, and the probe owes the critic's entry for the re-run
        standing = types.SimpleNamespace(project=root)
        write(PL.probe_record_path(task_root, "test_add"), {
            "verdict": "intended_failure", "instance_id": "test_add", "case": "TC-100",
            "test_node": "tests/test_calc.py::test_add", "mutation": "invert", "test_file_sha256": OLD,
            "recorded_at": "2026-09-30T05:02:39+00:00", "checks": stored_checks(standing, "tests/test_calc.py::test_add")})
        import probe_entries as PE      # the model entry the probe owes for the check, written as every probing test does
        PE.write_invert_entries(task_root, CRITIC, keys=["tests/test_calc.py:5"])

        def in_process(argv, cwd=None, timeout=None):   # the real probe(), not a subprocess of it
            args = list(argv[3:])
            got = lambda flag: args[args.index(flag) + 1]   # noqa: E731
            return 1, json.dumps(PBC.probe(NV_TASK, got("--dispatch"), got("--test"), got("--instance"),
                                           got("--mutation"))), ""
        manifest = json.loads((task_root / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        doc = D.settle(NV_TASK, task_root, root, CRITIC, runner=in_process, stand=lambda: (False, ""),
                       dispatch_record=json.loads((task_root / "state" / "controller.json").read_text(
                           encoding="utf-8"))["dispatches"][CRITIC])
        check_eq("settle: the real probe ended not_executed and the settle stopped on it",
                 [(o["instance_id"], o["result"]) for o in doc["outcomes"]], [("test_add", "not_executed")])
        kept = json.loads(PL.probe_record_path(task_root, "test_add").read_text(encoding="utf-8"))
        check_eq("the standing record is still intended_failure on its own bytes",
                 (kept["verdict"], kept["test_file_sha256"], kept["last_attempt"]["verdict"]),
                 ("intended_failure", OLD, "not_executed"))
        check_eq("the next find still lists the item",
                 [i["instance_id"] for i in D.find(task_root, manifest, root)["items"]], ["test_add"])
    finally:
        if saved is None:
            os.environ.pop("PROBE_RUN_SUITE", None)
        else:
            os.environ["PROBE_RUN_SUITE"] = saved
        cleanup(root)
        cleanup(scripts)


def a_test_that_is_not_python_is_replayed_with_its_line():
    """B-373 c (K11, A12): a probe of a test in another language that was pointed at a line (`--at`: the
    assertion, or which of two declarations) is replayed with the SAME line - without it the replay would invert
    the first assertion again, which is not the one that probe proved; an `incomplete` answer is the generic
    branch: nothing is settled, and the settle goes on (stop only for an unverified restore).
    t-2064 P4c: `_replay_plan` still READS the anchor, but the replay is the walk of the whole plan and carries none: a record with
    stored models replays with no `--at`, an old record (no `checks[]`) is `model owed` and stays with the critic."""
    args = D._probe_args("T-1", "S5-c-1", "tests/CalcTests.cs::CalcTests.Adds", "Adds", "invert", "")
    check_not_in("no --at when the probe had none", "--at", " ".join(args))
    check_eq("an empty or missing --at appends nothing", (D._probe_args("T", "D", "n::f", "i", "invert", "", ""),
                                                           D._probe_args("T", "D", "n::f", "i", "invert", "", None)),
             (["--task", "T", "--dispatch", "D", "--test", "n::f", "--instance", "i", "--mutation", "invert", "--json"],) * 2)
    with_at = D._probe_args("T-1", "S5-c-1", "tests/CalcTests.cs::CalcTests.Adds", "Adds", "invert", "", "15")
    check_eq("--at <line> goes in before --json, as a flag and its value", with_at[-3:], ["--at", "15", "--json"])
    check_in("and the rendered command carries it", "--at 15 --json", D._command(with_at))
    both = D._probe_args("T-1", "S5-c-1", "n::f", "i", "invert", "tests/H.cs::Expect", "7")
    check_eq("--oracle and --at together: oracle first, then the line", both[-5:], ["--oracle", "tests/H.cs::Expect", "--at", "7", "--json"])
    w = world()
    try:
        put_manifest(w, [row(w, "test_a")])
        for at, wanted in ((15, "15"), (0, "0"), (None, ""), ("", ""), (True, ""), ("15", ""), ("tests/H.cs:15", "tests/H.cs:15")):
            record(w, "test_a", detail={"line": 2, "mutation": "invert", "style": "detector", "at": at})
            plan = D._replay_plan(json.loads(PL.probe_record_path(w.task_root, "test_a").read_text(encoding="utf-8")), w.project)
            check_eq(f"_replay_plan reads mutation_detail.at ({at!r}): an int or <file>:<line> is a line (t-2045 N1)", plan[3], wanted)
            item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
            # t-2064 P4c: a replay is the walk of the whole plan, so it never carries a line anchor (`_item` ignores `_replay_plan`'s `at`)
            check_eq(f"...and the replayed command has no --at, whatever the record's anchor ({at!r})",
                     ("--at" in item["command"], item["action"]), (False, D.REPROBE))
        record(w, "test_a", checks=[], detail={"line": 2, "mutation": "invert", "style": "detector", "at": 15})
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("an OLD record (no checks[]) that was aimed by --at is `model owed`: the critic's, nothing run, no command",
                 (item["action"], item["command"], item["why"].startswith("model owed: the critic writes the entry for tests/test_x.py:2")),
                 (D.LEAVE_TO_CRITIC, "", True))
        record(w, "test_a")
        check_eq("a record that has no mutation_detail.at replays with no flag",
                 "--at" in D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]["command"], False)
        # t-2045 N5 (S9): an oracle helper in another language is replayed by the probe's own reader of that language (`declared_once`: the
        # entry's `helper_declaration`), so a helper declared once replays with --oracle, with no hand-named helper
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "ExpectSum", "file": "tests/Helpers.cs",
                                    "at": 3}, moved="tests/Helpers.cs")
        write(w.project / "tests" / "Helpers.cs", "class H { static void ExpectSum() { } }\n")
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("an oracle helper in another language, declared once, is replayed", item["action"] != D.LEAVE_TO_CRITIC, True)
        check_in("...with --oracle naming its file and function", "--oracle tests/Helpers.cs::ExpectSum", item["command"])
        # ... and the critic's again when the reader cannot find it exactly once: gone, or a language with no entry (the data gap named)
        write(w.project / "tests" / "Helpers.cs", "class H { static void Other() { } }\n")
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("an oracle helper that is gone from its file goes to the critic", item["action"], D.LEAVE_TO_CRITIC)
        check_in("...saying why, by the table's own row", "no declaration of ExpectSum", item["why"])
        check_not_in("...and not a misleading parse error", "does not parse", item["why"])
        check_not_in("...and the command names no oracle it cannot replay", "--oracle", item["command"])
        record(w, "test_a", detail={"line": 2, "mutation": "invert", "oracle_function": "helper", "file": "tests/notes.kt",
                                    "at": 3}, moved="tests/notes.kt")
        write(w.project / "tests" / "notes.kt", "fun helper() {}\n")
        item = D.find(w.task_root, w.manifest, w.project, CRITIC)["items"][0]
        check_eq("an oracle helper of a language with no entry goes to the critic", item["action"], D.LEAVE_TO_CRITIC)
        check_in("...naming the data gap", "factory data gap", item["why"])
    finally:
        cleanup(w.project)
    # K11: `incomplete` is the generic branch of _classify - nothing settled, stop only when the restore is not verified
    ok = D._classify(1, json.dumps({"verdict": "incomplete", "restore": {"verified": True}, "notes": ["a", "the library's wording differs"]}), "")
    check_eq("K11: an incomplete probe is not settled and does not stop the settle", (ok["result"], ok["settled"], ok["stop"]),
             ("incomplete", False, False))
    check_in("K11: its words are the verdict and the last note", "the probe said incomplete: the library's wording differs", ok["words"])
    bad = D._classify(1, json.dumps({"verdict": "incomplete", "restore": {"verified": False}, "notes": []}), "")
    check_eq("K11: an incomplete probe whose restore was NOT verified stops (the bytes are the author's)",
             (bad["result"], bad["stop"]), ("incomplete", True))
    check_eq("K11 control: not_executed still stops, as before", D._classify(1, json.dumps(
        {"verdict": "not_executed", "restore": {"verified": True}, "notes": []}), "")["stop"], True)
    w = world()
    try:
        ids = ["t1", "t2", "t3"]
        put_manifest(w, [row(w, i) for i in ids])
        for i in ids:
            record(w, i)
        stub = Stub(w)
        stub.probe["t1"] = (1, {"verdict": "incomplete", "restore": {"verified": True}, "notes": ["frame not read"]})
        doc = settle(w, stub)
        check_eq("K11: after an incomplete probe the settle goes on to the next item", stub.kinds(), ["probe:t1", "probe:t2", "probe:t3"])
        got = {o["instance_id"]: o for o in doc["outcomes"]}
        left = {i["instance_id"]: i for i in doc["left"]}
        check_eq("K11: the incomplete item is left, with its verdict as the reason", (got["t1"]["result"], left["t1"]["reason"]),
                 ("incomplete", "incomplete"))
        check_eq("K11: the others were settled (published)", (got["t2"]["result"], got["t3"]["result"]), ("published", "published"))
    finally:
        cleanup(w.project)


def oracle_from_probe_record_not_debt_file():
    """t-2180 B: `record_files` reads the oracle file from the probe RECORD (the debt files never carry `_args`)."""
    w = world()
    try:
        r1 = row(w, "t1")
        put_manifest(w, [r1])
        record(w, "t1", detail={"line": 2, "mutation": "invert", "oracle_function": "add", "file": "src\\calc.py"})
        check_eq("test file and the oracle file (backslashes normalised, one spelling)", D.record_files(w.task_root, r1),
                 {"tests/test_x.py", "src/calc.py"})
        record(w, "t1", detail={"line": 2, "mutation": "invert", "oracle_function": "add"}, moved="src/moved.py")
        check_eq("mutated_file.path wins over the test file", D.record_files(w.task_root, r1), {"tests/test_x.py", "src/moved.py"})
        check_eq("_oracle_where is the one reader of the replay file", D._oracle_where(json.loads(
            PL.probe_record_path(w.task_root, "t1").read_text(encoding="utf-8"))), "src/moved.py")
        record(w, "t1", detail={"line": 2, "mutation": "invert", "oracle_function": ""})
        check_eq("an empty oracle_function: the test file only", D.record_files(w.task_root, r1), {"tests/test_x.py"})
        record(w, "t1", node="tests/test_y.py::A::test_b")
        check_eq("several :: -> the part before the first", D.record_files(w.task_root, r1), {"tests/test_y.py"})
        PL.probe_record_path(w.task_root, "t1").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable record adds nothing, no crash", D.record_files(w.task_root, r1), set())
        PL.probe_record_path(w.task_root, "t1").unlink()
        check_eq("an absent record adds nothing", D.record_files(w.task_root, r1), set())
        check_eq("a row with no id adds nothing", D.record_files(w.task_root, {"case": "TC-1"}), set())
        r2 = {"instance_id": "t2", "case": "TC-2"}       # no test file on the row, an oracle record
        record(w, "t2", detail={"line": 2, "mutation": "invert", "oracle_function": "f", "file": "src/o.py"})
        check_eq("a row with no test file but an oracle record", D.record_files(w.task_root, r2), {"tests/test_x.py", "src/o.py"})
    finally:
        cleanup(w.project)


def gone_oracle_still_counted():
    """t-2180 B: no `_oracle_gone` check - an oracle function that no longer exists still counts (the error direction is a wait)."""
    w = world()
    try:
        r1 = row(w, "t1")
        record(w, "t1", detail={"line": 2, "mutation": "invert", "oracle_function": "vanished", "file": "src/calc.py"})
        check("the oracle file does not even exist in the project", not (w.project / "src" / "calc.py").exists())
        check_in("a gone oracle file is still named", "src/calc.py", D.record_files(w.task_root, r1))
        node, mutation, oracle, at, why = D._replay_plan(json.loads(PL.probe_record_path(w.task_root, "t1").read_text(encoding="utf-8")), w.project)
        check("the replay itself leaves it to the critic (unchanged)", oracle == "" and "cannot be replayed" in why)
    finally:
        cleanup(w.project)


def main():
    oracle_from_probe_record_not_debt_file()
    gone_oracle_still_counted()
    a_test_that_is_not_python_is_replayed_with_its_line()
    find_names_the_unpublished_probe()
    find_info_and_edges()
    leave_to_critic_and_the_oracle()
    commands_survive_hard_ids()
    find_writes_nothing()
    settle_sequence()
    rebind_writes_only_known_ids()
    a_failed_rebind_means_no_probe()
    probe_outcomes()
    legacy_rows_are_never_settled()
    budget_stand_and_limit()
    the_budget_bounds_the_whole_call()
    an_item_is_not_probed_twice_on_the_same_bytes()
    settle_skips_refused_rebind_on_same_bytes()
    settle_retries_when_bound_sha_changes()
    settle_retries_when_record_mtime_changes()
    settle_retries_when_manifest_ids_change()
    settle_retries_after_a_dry_run_that_did_not_run()
    settle_scope_of_a_new_dispatch_is_read_before_nothing_changed()
    settle_nothing_changed_writes_no_subprocess()
    settle_unreadable_memory_runs()
    the_count_cap_at_25_and_26()
    an_item_outside_the_dispatch_scope_is_left()
    hf8_18_c_k12_a_row_of_another_spelling_passes_the_outside_scope_door()
    the_debt_file()
    arguments()
    the_command_line_end_to_end_with_stub_tools()
    the_budget_on_the_command_line()
    nv_scope_and_budget()
    a_not_executed_settle_keeps_the_debt()
    finish("probe_debt")


if __name__ == "__main__":
    main()
