"""probe_by_code.py --alternative: a case's declared reading B walked on the ONE road (t-2064 P5), on the stub runner of `test_probe_walk`.

No real test runner starts: the World of `test_probe_walk` (Python test) and a TypeScript twin of it answer through a stub `run_request`; the
project, the story and the dispatch are those of `test_probe_every_check.flip`. What this file adds is the story's own data of a reading:
a manifest row with `then_bindings` (Then 1 -> the first check, Then 2 -> the next two), a test-case file with an `alternatives` key, and
a model file whose entries carry `alternative: TC-1:ALT-1`. Each test names the mutation of the code that kills it. Runnable alone (the
`__main__` line below) and collected by pytest; fast, no sleeps."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402
import test_probe_every_check as EC  # noqa: E402
import test_probe_walk as TW  # noqa: E402

REAL_PARSE_NODE = PBC.parse_node        # `EC.flip` replaces it by the Python World's spec; the TypeScript twin needs the real reader
TOKEN = "TC-1:ALT-1"
ALT_FILE = "i1--TC-1--ALT-1.json"
CASE_TEXT = ("---\nid: TC-1\nalternatives: [{\"id\": \"ALT-1\", \"then\": 2, \"reading\": \"the stamp is taken at completion\", \"ref\": \"R-2\"}]\n"
             "---\n# TC-1\n\n## Then\n1. the request is accepted\n2. the stamp is the trigger time\n")
TS_FILE = "tests/t.spec.ts"
TS_NODE = "tests/t.spec.ts::t"
TS_HEAD = "import { test, expect } from '@playwright/test';\ntest('t', async () => {\n  const a = 1;\n"
TS_SOFT = "  expect.soft(a, '{n}').toBe(1);\n"


class TSWorld(TW.World):
    """The World of `test_probe_walk` with a TypeScript test of three soft checks (lines 4, 5, 6) in place of the Python one."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path, "sss")
        self.path.unlink()
        self.text = TS_HEAD + "".join(TS_SOFT.format(n=f"c{n}") for n in (1, 2, 3)) + "});\n"
        self.path = self.root / TS_FILE
        self.path.write_bytes(self.text.encode())
        self.original = self.text.encode()
        spec = REAL_PARSE_NODE(TS_NODE)
        entry = dict(spec["entry"], soft_assert_patterns=[r"\bexpect\.soft\s*\("], interruption_texts=["Test timeout of 9ms exceeded"],
                     marker_read=["message", "text"])
        self.spec = dict(spec, entry=entry)
        self.checks = PBC.checks_of(self.original, self.spec, PBC._reader_entry(self.spec), [], [], [])
        self.plan = {"checks": self.checks, "runs": PBC.run_plan(self.checks)}
        self.keys = [c["key"] for c in self.checks]

    def tokens_in(self, data: bytes) -> dict:
        out = {}
        for number, line in enumerate(data.decode().splitlines(), 1):
            hit = TW.TOKEN.search(line)
            if hit:
                out[f"{TS_FILE}:{number}"] = hit.group(1)
        return out


def story(tmp_path, monkeypatch, language="python", stage="S5"):
    """A flip world of the language with the story's data of the reading: a manifest row of `i1` covering TC-1, its `then_bindings`
    (Then 1: the first check, Then 2: the second and third), and `work/test-cases/TC-1.md` declaring ALT-1 on Then 2."""
    world = EC.flip(tmp_path, monkeypatch, "sss", stage=stage)
    if language == "typescript":
        ts = TSWorld(tmp_path / "ts")
        ts.stage = stage
        ts.install(monkeypatch)
        monkeypatch.setattr(PBC, "project_root", lambda: ts.root)
        monkeypatch.setattr(PBC, "artifacts_dir", lambda task: ts.task_root)
        monkeypatch.setattr(PBC, "parse_node", lambda test, root=None: ts.spec)
        monkeypatch.setattr(PBC, "_test_path", lambda root, cfg, spec, entry=None: (ts.path, ts.root))
        monkeypatch.setattr(PBC, "_dispatch_stage", lambda root, task, dispatch, case: ts.stage)
        monkeypatch.setattr(PBC.proof_level, "binding_facts", lambda task_root, iid: {
            "case_version": "v1", "test_content_hash": hashlib.sha256(ts.original).hexdigest(), "source_revision": "rev1", "build_id": "b1"})
        # R6 (`_shape_refusals`) is on the alternative's road too since the merge of the fix rounds: this world has no execution profile and
        # these tests are about the marker form, not the request check, so the request check is stubbed out here
        monkeypatch.setattr(PBC, "run_shape_checks", lambda *a, **k: None)
        world = ts
    first =world.keys[0].rpartition(":")[0]
    file = first
    row = {"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"], "file": file, "test": "t", "selector": "t"}
    monkeypatch.setattr(PBC, "manifest_entry", lambda task_root, iid: row)
    lines = [int(k.rpartition(":")[2]) for k in world.keys]
    bindings = [{"case": "TC-1", "then": 1, "instance_id": "i1", "assertion_ref": f"{file}:{lines[0]}", "status": "covered"},
                {"case": "TC-1", "then": 2, "instance_id": "i1", "assertion_ref": f"{file}:{lines[1]}-{lines[2]}", "status": "covered"}]
    work = world.task_root / "work"
    (work / "test-cases").mkdir(parents=True, exist_ok=True)
    (work / "test-cases" / "TC-1.md").write_text(CASE_TEXT, encoding="utf-8")
    (work / "automation-manifest.json").write_text(json.dumps({"tests": [row], "then_bindings": bindings}), encoding="utf-8")
    node = "tests/t.spec.ts::t" if language == "typescript" else TW.NODE      # the report row names the test it ran
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]), test_id=node)]
    return world


def alt_entry(key, actual="3", **more):
    return {"check": key, "alternative": TOKEN, "supposes": "B", "actual": actual, **more}


def plain_entry(key, actual="2"):
    return {"check": key, "supposes": "s", "actual": actual}


def alt_call(world, **more):
    return EC.flip_call(world, mutation="model", alternative=TOKEN, **more)


def alt_record(world) -> dict:
    return json.loads((world.task_root / "work" / "probes" / "alternative" / ALT_FILE).read_text(encoding="utf-8"))


def then2(world):
    return world.keys[1:]


def test_alternative_python_keeps_token_and_path(tmp_path, monkeypatch):
    """A reading's entries on the two checks of Then 2 walk in ONE run on Python: the edit and the marker of each check are in the file the
    runner sees, the per-check records are named by the reading, and the one record stands under work/probes/alternative/ and is no
    receipt. Killed by: `_records_id` ignoring `ctx.alt` (the per-check files take the plain name), `_aggregate_record` not redirecting."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    record = alt_call(world)
    assert record["verdict"] == "intended_failure" and record["alternative"] == TOKEN and record["then"] == 2, record
    assert record["mutation"] == "alternative" and record["proof_level"] is None and record["receipt"] is None and record["proved_by"], record
    assert record["record"] == f"work/probes/alternative/{ALT_FILE}" and alt_record(world)["verdict"] == "intended_failure"
    assert len(world.runs) == 1 and sorted(world.runs[0]["tokens"]) == then2(world), "the reading's two checks, one run, a marker each"
    assert "assert (3 == 1)" in world.runs[0]["bytes"].decode(), "the reading's value stands where the check read the product"
    checks = world.task_root / "work" / "probes" / "checks"
    names = sorted(p.name for p in checks.glob("*.json"))
    assert names and all(n.startswith("i1--TC-1--ALT-1--L") for n in names), names
    assert not (world.task_root / "work" / "probes" / "i1.json").exists() and not (world.task_root / "work" / "sensitivity-receipts").exists()
    assert record["then_checks"] == then2(world) and record["unmodelled"] == [] and world.path.read_bytes() == world.original


def test_alternative_runs_on_ts(tmp_path, monkeypatch):
    """The same reading on a TypeScript test: no language question on the road, the marker rides on the TS form and the record proves.
    Killed by: an alternative branch that reads `.py` only (the old road), or a marker form of the Python AST only."""
    world = story(tmp_path, monkeypatch, "typescript")
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    record = alt_call(world)
    assert record["verdict"] == "intended_failure" and record["alternative"] == TOKEN, record
    seen = world.runs[0]["bytes"].decode()
    assert "expect.soft(3, " in seen and "'qa-probe'" in seen and sorted(world.runs[0]["tokens"]) == then2(world), seen
    assert record["record"] == f"work/probes/alternative/{ALT_FILE}" and world.path.read_bytes() == world.original


def test_alternative_request_refusal_is_before_any_write(tmp_path, monkeypatch):
    """Junction of the fix rounds (R6) and P5: an ALTERNATIVE call whose request the builder refuses (the REAL `run_shape_checks`) is refused with its own text and door (here: the world's config names no profile), and NOTHING moved - no run,
    no record, no copy, the tree and the story folder byte for byte. Killed by: `_probe_alternative` not calling `_shape_refusals` before `_walk_plan` (the walk writes)."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    real = PBC._probe_alternative       # the World's test is Python (the AST reader): only the flag that puts R6 on the road is turned on
    monkeypatch.setattr(PBC, "_probe_alternative", lambda ctx, *a, **k: real(ctx._replace(detector=True), *a, **k))
    before = EC.flip_snapshot(world.root, world.task_root)
    text = EC.flip_refusal(world, mutation="model", alternative=TOKEN)
    assert "execution profile" in text and "Nothing was changed" in text, text      # this world's config has no profile: R6's refusal of that
    assert EC.flip_snapshot(world.root, world.task_root) == before, "not a byte written"
    assert world.runs == [] and not (world.task_root / "work" / "probes").exists(), "no run, no record"


def test_plain_and_alternative_entry_never_meet(tmp_path, monkeypatch):
    """One check holds a plain entry AND a reading's: the plain walk edits with the plain value only, the alternative's with its own only,
    and a check of Then 1 (plain entry only) is never touched by the reading's call. Killed by: `_entries_for` not filtering
    `alternative`, or `_probe_alternative` selecting entries without the token."""
    world = story(tmp_path, monkeypatch)
    k0, k1, k2 = world.keys
    EC.flip_models(world, [plain_entry(k0, "2"), plain_entry(k1, "2"), plain_entry(k2, "2"), alt_entry(k1, "3"), alt_entry(k2, "3")])
    plain = EC.flip_call(world)
    plain_bytes = world.runs[0]["bytes"].decode()
    assert plain["verdict"] == "intended_failure" and "assert (2 == 1)" in plain_bytes and "(3 == 1)" not in plain_bytes, plain_bytes
    alt = alt_call(world)
    alt_bytes = world.runs[1]["bytes"].decode()
    assert alt["verdict"] == "intended_failure" and alt_bytes.count("assert (3 == 1)") == 2 and "(2 == 1)" not in alt_bytes, alt_bytes
    assert sorted(world.runs[1]["tokens"]) == [k1, k2], "Then 1's check is not in the reading's plan"


def test_alternative_flag_spelling_refused_with_door(tmp_path, monkeypatch):
    """`--mutation alternative` is refused for every language with the door `--alternative`, before a byte moves. Killed by: `_refuse_flags`
    not reading the word (the call walks as a plain one), or a refusal that names no door."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    before = EC.flip_snapshot(world.root, world.task_root)
    text = EC.flip_refusal(world, mutation="alternative")
    assert "`--alternative <case>:ALT-n`" in text and "removed" in text and "Nothing was changed" in text, text
    assert EC.flip_snapshot(world.root, world.task_root) == before and world.runs == []


def test_gap_entry_writes_gap_row(tmp_path, monkeypatch):
    """A reading whose only entry is a `gap`: a gap record by the critic's own word, no run, no byte of the test touched, no per-check
    record. Killed by: walking the gap as a value entry (a run), or refusing it."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [{"alternative": TOKEN, "gap": "the stamp is not readable in this test"}])
    record = alt_call(world)
    assert world.runs == [] and record["verdict"] == "gap" and record["cause"] == "model" and "not readable" in record["why"], record
    assert alt_record(world)["verdict"] == "gap" and world.path.read_bytes() == world.original
    assert not (world.task_root / "work" / "probes" / "checks").exists()


def test_alternative_call_leaves_the_plain_aggregate_alone(tmp_path, monkeypatch):
    """INV: an alternative record is never a live receipt and a plain walk is never fed a reading's edit. A plain call writes the
    aggregate and its receipt; an alternative call afterwards leaves both byte for byte; a plain call after it (its entry changed so that
    it runs) edits with the plain value only. Killed by: `_aggregate_record` writing the alternative to `record_path` (the aggregate bytes
    change), or calling `attach_receipt` for it (a second receipt file)."""
    world = story(tmp_path, monkeypatch)
    keys = world.keys
    EC.flip_models(world, [plain_entry(k) for k in keys] + [alt_entry(k) for k in then2(world)])
    plain = EC.flip_call(world)
    assert plain["verdict"] == "intended_failure" and plain["receipt"], plain
    aggregate = world.task_root / "work" / "probes" / "i1.json"
    receipts = world.task_root / "work" / "sensitivity-receipts"
    before = (aggregate.read_bytes(), sorted((p.name, p.read_bytes()) for p in receipts.glob("*.json")))
    record = alt_call(world)
    assert record["verdict"] == "intended_failure" and record["receipt"] is None
    after = (aggregate.read_bytes(), sorted((p.name, p.read_bytes()) for p in receipts.glob("*.json")))
    assert after == before, "the plain aggregate and its receipt are the same bytes"
    EC.flip_models(world, [{**plain_entry(k), "supposes": "changed"} for k in keys] + [alt_entry(k) for k in then2(world)])
    runs = len(world.runs)
    EC.flip_call(world)
    plain_bytes = world.runs[runs]["bytes"].decode()
    assert len(world.runs) == runs + 1 and "(3 == 1)" not in plain_bytes and plain_bytes.count("assert (2 == 1)") == 3, plain_bytes


def test_reading_on_a_red_author_never_proves(tmp_path, monkeypatch):
    """INV: a reading never proves on a red author (the test not green under the author's bytes): the record is not `intended_failure`.
    Killed by: `_walk_plan` for an alternative skipping `author_green_of`."""
    world = story(tmp_path, monkeypatch)
    world.green = False
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    record = alt_call(world)
    assert record["verdict"] != "intended_failure" and record["receipt"] is None, record
    assert {row["verdict"] for row in record["checks"]} != {"intended_failure"}, record["checks"]


def test_unmodelled_check_of_the_then_is_incomplete(tmp_path, monkeypatch):
    """An entry for one of the two checks of Then 2 only: the walk proves it, the record says `incomplete` and names the other as
    `unmodelled` (proven = ALL the Then's checks), and nothing is refused. Killed by: folding the proved rows into `intended_failure`."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [alt_entry(world.keys[1])])
    record = alt_call(world)
    assert record["verdict"] == "incomplete" and record["unmodelled"] == [world.keys[2]], record
    assert [r["verdict"] for r in record["checks"]] == ["intended_failure"] and world.keys[2] in record["why"], record


@pytest.mark.parametrize("what", ["no_file", "no_entry_of_the_token", "no_check_of_the_then", "wrong_kind", "foreign_check", "gap_and_entry"])
def test_alternative_refusals_name_the_door(tmp_path, monkeypatch, what):
    """Every way the call cannot walk is a refusal with the door and no byte written: no model file (the real model path), a file with
    no entry of the token, a Then with no check, an `invert` entry, an entry on a check outside the Then, a gap beside entries.
    Killed by: any of them reaching `_walk_plan`."""
    world = story(tmp_path, monkeypatch)
    k0, k1, k2 = world.keys
    if what == "no_check_of_the_then":
        manifest = world.task_root / "work" / "automation-manifest.json"
        doc = json.loads(manifest.read_text())
        doc["then_bindings"] = doc["then_bindings"][:1]
        manifest.write_text(json.dumps(doc), encoding="utf-8")
    if what == "no_entry_of_the_token":
        EC.flip_models(world, [plain_entry(k) for k in world.keys])
    elif what == "wrong_kind":
        EC.flip_models(world, [alt_entry(k1), {"check": k2, "alternative": TOKEN, "invert": "no value is known"}])
    elif what == "foreign_check":
        EC.flip_models(world, [alt_entry(k0), alt_entry(k1)])
    elif what == "gap_and_entry":
        EC.flip_models(world, [alt_entry(k1), {"alternative": TOKEN, "gap": "x"}])
    elif what == "no_check_of_the_then":
        EC.flip_models(world, [alt_entry(k1)])
    before = EC.flip_snapshot(world.root, world.task_root)
    text = EC.flip_refusal(world, mutation="model", alternative=TOKEN)
    assert "Nothing was changed" in text and world.runs == [] and EC.flip_snapshot(world.root, world.task_root) == before, text
    if what == "no_file":
        assert "work/probe-models/D.json" in text and "no model file" in text, text
    if what == "no_check_of_the_then":
        assert "Then 2" in text and "TC-1" in text, text
    if what == "wrong_kind":
        assert "`invert` entry" in text, text
    if what == "foreign_check":
        assert k0 in text and "not a check of that Then" in text, text


# --- step (b): the report `--alternatives` and the old shapes -----------------------------------------------------------------------------

def report_row(world) -> dict:
    rows = PBC.alternatives_report(world.task_root, world.root, "i1")
    assert len(rows) == 1 and rows[0]["alternative"] == TOKEN, rows
    return rows[0]


def test_alternatives_report_proven_all_checks(tmp_path, monkeypatch):
    """`proven` = every check of that Then proved under the entries: one of the Then's two checks modelled gives `incomplete` and the row
    is not `proven` (the flags to add stay); both modelled give `proven`; a passing run gives `not_separated`; an edit of the test after
    it makes the row `stale`. Killed by: the row reading `proven` off the proved rows alone, or off `unmodelled` not being recorded."""
    world = story(tmp_path, monkeypatch)
    assert report_row(world)["state"] == "unknown" and "never probed" in report_row(world)["why"]
    EC.flip_models(world, [alt_entry(world.keys[1])])
    alt_call(world)
    half = report_row(world)
    assert half["state"] == "unknown" and half["verdict"] == "incomplete" and half["flags"] and world.keys[2] in half["why"], half
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    alt_call(world)
    full = report_row(world)
    assert full["state"] == "proven" and full["record"] == f"work/probes/alternative/{ALT_FILE}" and not full["flags"], full
    world.scenario = lambda w, run: [TW.row("passed")]
    EC.flip_models(world, [alt_entry(k, "4") for k in then2(world)])
    alt_call(world)
    assert report_row(world)["state"] == "not_separated"
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]))]
    EC.flip_models(world, [alt_entry(k, "5") for k in then2(world)])
    alt_call(world)
    assert report_row(world)["state"] == "proven"
    changed = world.original + b"# edited\n"
    world.path.write_bytes(changed)
    assert report_row(world)["state"] == "stale", report_row(world)


def test_reading_whose_entries_all_name_another_instance_is_refused_by_name(tmp_path, monkeypatch):
    """F1 (t-2490): every entry of the reading carries `instance: i2`, the call is for i1: the refusal names the instance and the model file
    and its door (add entries for i1), not 'the record could not be written'; nothing moves. Killed by: `_probe_alternative` selecting
    `mine` by the token alone (the walk then has no entry and the false 'record could not be written' text comes out)."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [alt_entry(k, instance="i2") for k in then2(world)])
    before = EC.flip_snapshot(world.root, world.task_root)
    text = EC.flip_refusal(world, mutation="model", alternative=TOKEN)
    assert "i2" in text and "i1" in text and "work/probe-models/D.json" in text and "another instance" in text, text
    assert "could not be written" not in text and "Nothing was changed" in text, text
    assert world.runs == [] and EC.flip_snapshot(world.root, world.task_root) == before


def test_mixed_instance_file_names_the_other_instances_check_as_unmodelled(tmp_path, monkeypatch):
    """F1 (t-2490): k1 for i1 and k2 for i2 only, a call for i1: k2 is named in `unmodelled` and in the why, the verdict is `incomplete`
    (never a proof). Killed by: computing `keys` from the token's entries before the instance pick (k2 looks modelled)."""
    world = story(tmp_path, monkeypatch)
    k1, k2 = then2(world)
    EC.flip_models(world, [alt_entry(k1, instance="i1"), alt_entry(k2, instance="i2")])
    record = alt_call(world)
    assert record["verdict"] == "incomplete" and record["unmodelled"] == [k2] and k2 in record["why"], record
    assert sorted(world.runs[0]["tokens"]) == [k1]


def test_helper_edit_after_the_proof_makes_the_row_stale(tmp_path, monkeypatch):
    """F2 (t-2490): a Then bound to a body check AND a helper check edits two files, the test file first. The record keeps both in
    `mutated_files`; the helper changed after the proof: the row reads `stale`, never `proven`. An old record carrying only
    `mutated_file` reads as before; an unreadable helper reads `stale` with a note. Killed by: `alternative_fresh` comparing only the
    first `mutated_file` (`proven` stays on bytes it was not proved on)."""
    world = story(tmp_path, monkeypatch)
    EC.flip_models(world, [alt_entry(k) for k in then2(world)])
    alt_call(world)
    assert report_row(world)["state"] == "proven"
    helper = world.root / "tests" / "helper_lib.py"
    helper.write_bytes(b"VALUE = 1\n")
    path = world.task_root / "work" / "probes" / "alternative" / ALT_FILE
    record = json.loads(path.read_text(encoding="utf-8"))
    record["mutated_files"] = list(record["mutated_files"]) + [{"path": "tests/helper_lib.py", "sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}]
    path.write_text(json.dumps(record), encoding="utf-8")
    assert report_row(world)["state"] == "proven", "the helper still holds the bytes the record ran on"
    helper.write_bytes(b"VALUE = 2\n")
    row = report_row(world)
    assert row["state"] == "stale" and "changed" in row["why"], row
    helper.write_bytes(b"VALUE = 1\n")
    assert report_row(world)["state"] == "proven"
    helper.unlink()
    row = report_row(world)
    assert row["state"] == "stale" and "tests/helper_lib.py" in row["why"] and "cannot be read" in row["why"], row
    old = dict(record)
    del old["mutated_files"]
    path.write_text(json.dumps(old), encoding="utf-8")
    assert report_row(world)["state"] == "proven", "an old record with only `mutated_file` is compared as before"


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_report_names_the_new_call_form(tmp_path, monkeypatch, language):
    """A reading not yet probed names the NEW call form and the model file's entry shape, whatever the language of the test (the old row
    offered a skeleton for `.py` only and the flag `--mutation alternative`). Killed by: the old flags text, or a skeleton for `.py` only."""
    world = story(tmp_path, monkeypatch, language)
    row = report_row(world)
    assert row["flags"] == f"--alternative {TOKEN} [--model work/probe-models/<any name>.json]" and "--mutation" not in row["flags"], row["flags"]
    shape = json.loads(row["skeleton"])["models"][0]
    assert shape["alternative"] == TOKEN and {"check", "supposes", "actual"} <= set(shape), shape
    gap = json.loads(row["skeleton_gap"])["models"][0]
    assert gap == {"alternative": TOKEN, "gap": "<why B cannot be modelled in the test>"}, gap


def test_gap_skeleton_is_read_by_the_road(tmp_path, monkeypatch):
    """The gap skeleton the report prints is a model file the call reads (producer and reader agree, AR-22): written as printed it gives
    a gap record and no run. Killed by: a skeleton shape `load_models` refuses."""
    world = story(tmp_path, monkeypatch)
    path = world.task_root / "work" / "probe-models" / "D.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_row(world)["skeleton_gap"], encoding="utf-8")
    record = alt_call(world)
    assert record["verdict"] == "gap" and world.runs == [], record


def test_old_alt_record_reads(tmp_path, monkeypatch):
    """An alternative RECORD of the old road (its own keys: `model_find`, `model_replace`, `superseded[]`, no `checks`) reads as today:
    `proven`, the model shown, the superseded verdicts listed, and stale when the test changed. Killed by: the report reading only the
    new aggregate's keys."""
    world = story(tmp_path, monkeypatch)
    manifest = world.task_root / "work" / "automation-manifest.json"
    doc = json.loads(manifest.read_text())
    doc["then_bindings"][1]["assertion_ref"] = "tests/test_t.py:4"        # a single-line ref, as the old road bound its Then
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    item = {"then": 2, "reading": "the stamp is taken at completion"}
    sha = hashlib.sha256(world.original).hexdigest()
    record = {"instance_id": "i1", "case": "TC-1", "alternative": TOKEN, "then": 2, "reading": item["reading"], "reading_sha": PBC._reading_sha(item),
              "verdict": "intended_failure", "test_file_sha256": sha, "instance_content_sha": "", "model_find": "a = 1", "model_replace": "a = 3",
              "mutated_file": {"path": "tests/test_t.py", "sha256": sha}, "assertion_refs": [["tests/test_t.py", 4]],
              "superseded": [{"verdict": "no_failure", "reason": "r"}], "recorded_at": "2026-10-01T00:00:00+00:00"}
    out = world.task_root / "work" / "probes" / "alternative" / ALT_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record), encoding="utf-8")
    row = report_row(world)
    assert row["state"] == "proven" and row["model_find"] == "a = 1" and row["superseded"] == ["no_failure"], row
    world.path.write_bytes(world.original + b"# edited\n")
    assert report_row(world)["state"] == "stale"


def test_old_model_shape_refused_names_new_shape(tmp_path, monkeypatch):
    """The old one-object model file (`alternative` + `find` + `replace`) handed to the new call is P3's refusal naming the new shape, and
    nothing moves. Killed by: reading the old shape as an entry (a run), or a refusal that does not name `models`."""
    world = story(tmp_path, monkeypatch)
    path = world.task_root / "work" / "probe-models" / "D.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"alternative": TOKEN, "find": "a = 1", "replace": "a = 3"}), encoding="utf-8")
    before = EC.flip_snapshot(world.root, world.task_root)
    text = EC.flip_refusal(world, mutation="model", alternative=TOKEN)
    assert '{"models": [' in text and "`alternative`" in text and "Nothing was changed" in text and world.runs == [], text
    assert EC.flip_snapshot(world.root, world.task_root) == before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
