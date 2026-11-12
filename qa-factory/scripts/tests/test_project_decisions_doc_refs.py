"""OH2-6 (b): a deferred-decision row can name a DOCUMENT (`doc:<path under qa-factory>[#<anchor>]`) instead of a config key.

The risk-areas answer is a paragraph in two strategy files; before this node its row named `/risk_areas`, and `resolve` wrote
that key into config.json where nothing reads it. A document ref is a field_ref that `resolve` writes nothing for: it needs no
value, config.json stays byte for byte as it was, the markers still come out and the row still closes (AR-25), and a
malformed one is refused naming the form (FR-1). The producer (phases/p4-generate.md step 8) and this reader change together.

K6b-1 `_refs` normalizes the form. K6b-2 a doc-only row: add and resolve leave config.json's bytes equal, markers removed, row
closed, receipt complete (the CLI, with no --field-values: F-13). K6b-3 a mixed row needs only the pointer's value. K6b-4 a
pointer that merely contains `doc:` stays a pointer. K6b-5 the malformed forms, AT (`doc:a`) and BEYOND (`doc:`).
K6b-6 the edges: an older `/risk_areas` row is not migrated (a second row), several classes are one row that needs every value.

Runnable on its own: `python -B scripts/tests/test_project_decisions_doc_refs.py`.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_decisions as PD  # noqa: E402

DOC = "doc:strategy/test-strategy.md#risk-and-impact-scale"
FORM = "doc:<path under qa-factory>[#<anchor>]"
MARKER = "[DEFERRED: risk areas not named]"
ESSENCE = "risk areas not named: strategy/test-strategy.md (Risk and impact scale), strategy/aspect-profile.md"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project(compact_config: bool = True) -> Path:
    """A project with the two strategy files carrying the marker, and a config.json written COMPACT (a rewrite through
    `json.dumps(indent=2)` changes its bytes, so 'untouched' is observable)."""
    root = temp_project("qa-factory-doc-refs-")
    strategy = root / "qa-factory" / "strategy"
    strategy.mkdir(parents=True, exist_ok=True)
    for name in ("test-strategy.md", "aspect-profile.md"):
        (strategy / name).write_text(f"# {name}\n\n{MARKER}\n\nbody\n", encoding="utf-8")
    if compact_config:
        (root / "qa-factory" / "config.json").write_text('{"app_root":".","impact_scale":{"degraded":{"priority":"P2","severity":"minor"}}}',
                                                         encoding="utf-8")
    return root


def refused(call) -> str:
    try:
        call()
    except ValueError as exc:
        return str(exc)
    return ""


def rows(root: Path) -> list:
    return PD.parse_rows((root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8"))


def receipt(root: Path, decision_id: str) -> dict:
    return json.loads((root / "qa-factory" / "state" / "decision-transactions" / f"{decision_id}.json").read_text(encoding="utf-8"))


def k6b_1_refs_form() -> None:
    check_eq("K6b-1: backslashes become `/` and the form is kept", PD._refs("doc:strategy\\x.md#a"), ["doc:strategy/x.md#a"])
    check_eq("K6b-1: the prefix is case-insensitive, normalized to lower case; path and anchor keep their case",
             PD._refs("DOC:Strategy/X.md#Anchor"), ["doc:Strategy/X.md#Anchor"])
    check_eq("K6b-1: the anchor is optional", PD._refs("doc:strategy/x.md"), ["doc:strategy/x.md"])
    check_eq("K6b-1: a doc ref is not given a leading `/` (M1)", [r.startswith("/") for r in PD._refs(DOC)], [False])
    check_eq("K6b-1: a list mixes the forms, sorted and de-duplicated; the pointer keeps today's normalization",
             PD._refs([DOC, "gate_a/x", "Doc:" + DOC[4:], "/a"]), ["/a", "/gate_a/x", DOC])
    check_eq("K6b-1: the comma-separated string form reads the same (the stored cell)", PD._refs(f"/a,{DOC}"), ["/a", DOC])
    check_eq("K6b-1: whitespace around the path part is not part of the path", PD._refs("doc: a "), ["doc:a"])
    check_eq("K6b-1: a name that merely contains two dots is a name, not `..`", PD._refs("doc:a..b/c..d.md"), ["doc:a..b/c..d.md"])


def k6b_2_doc_only_row() -> None:
    root = project()
    try:
        config = root / "qa-factory" / "config.json"
        before = sha(config)
        added = run_script("project_decisions.py", "--root", root, "add", "--field-ref", DOC, "--essence", ESSENCE,
                           "--asked", "batch 1: which parts of the product would hurt most if they broke?",
                           "--trigger-type", "story_count", "--trigger-value", "3")
        check_eq("K6b-2: the CLI `add` with a doc ref exits 0", added.returncode, 0)
        check_eq("K6b-2: the row holds the doc ref as its field_refs", [r["field_refs"] for r in rows(root)], [DOC])
        again = run_script("project_decisions.py", "--root", root, "add", "--field-ref", DOC.replace("doc:", "DOC:", 1),
                           "--essence", "other prose", "--asked", "batch 1: q")
        check_eq("K6b-2: the same ref again (other case of the prefix) is the same open row", (again.returncode, len(rows(root))), (0, 1))
        done = run_script("project_decisions.py", "--root", root, "resolve", "--id", "DD-1", "--decision", "areas written",
                          "--resolution-ref", "batch 2: answered",
                          "--marker-file", "qa-factory/strategy/test-strategy.md", "--marker-file", "qa-factory/strategy/aspect-profile.md",
                          "--marker-text", MARKER)
        check_eq("K6b-2: the CLI `resolve` with NO --field-values exits 0 (F-13)", done.returncode, 0)
        check_eq("K6b-2: config.json is byte for byte as it was (sha256)", sha(config), before)
        for name in ("test-strategy.md", "aspect-profile.md"):
            check_not_in(f"K6b-2: the marker is removed from {name}",
                         MARKER, (root / "qa-factory" / "strategy" / name).read_text(encoding="utf-8"))
        row = rows(root)[0]
        check_eq("K6b-2: the row is closed with its decision and resolution ref",
                 (row["status"], row["decision with witness"], row["resolution_ref"]), ("closed", "areas written", "batch 2: answered"))
        rec = receipt(root, "DD-1")
        check_eq("K6b-2: the receipt is complete and names the markers and the token",
                 (rec["status"], rec["field_values"], rec["marker_text"], len(rec["marker_files"])), ("complete", {}, MARKER, 2))
    finally:
        cleanup(root)
    # no config.json at all: nothing is written, no error
    root = project(compact_config=False)
    try:
        config = root / "qa-factory" / "config.json"
        config.unlink()
        PD.upsert(root, field_refs=[DOC], essence=ESSENCE, asked="batch 1: q", scope="project", owner="user")
        closed = PD.resolve(root, "DD-1", "areas written", "batch 2", None,
                           ["qa-factory/strategy/test-strategy.md", "qa-factory/strategy/aspect-profile.md"], MARKER)
        check_eq("K6b-2: a doc-only row with no config.json closes", closed["status"], "closed")
        check("K6b-2: ...and writes no config.json", not config.exists())
    finally:
        cleanup(root)
    # a value given for a doc ref is kept in the receipt only
    root = project()
    try:
        config = root / "qa-factory" / "config.json"
        before = sha(config)
        PD.upsert(root, field_refs=[DOC], essence=ESSENCE, asked="batch 1: q", scope="project", owner="user")
        PD.resolve(root, "DD-1", "areas written", "batch 2", {DOC: "strategy/test-strategy.md#risk-and-impact-scale"},
                   ["qa-factory/strategy/test-strategy.md", "qa-factory/strategy/aspect-profile.md"], MARKER)
        check_eq("K6b-2: a value given for a doc ref leaves config.json untouched", sha(config), before)
        check_eq("K6b-2: ...and sits in the receipt", receipt(root, "DD-1")["field_values"],
                 {DOC: "strategy/test-strategy.md#risk-and-impact-scale"})
    finally:
        cleanup(root)


def k6b_3_mixed_row() -> None:
    root = project()
    try:
        PD.upsert(root, field_refs=[DOC, "/x/y"], essence=ESSENCE, asked="batch 1: q", scope="project", owner="user")
        message = refused(lambda: PD.resolve(root, "DD-1", "d", "r", {}, ["qa-factory/strategy/test-strategy.md"], MARKER))
        check_in("K6b-3: a mixed row still needs the pointer's value", "/x/y", message)
        check_not_in("K6b-3: ...and does not ask for a value for the doc ref (M3)", "doc:", message)
        check_eq("K6b-3: the refused resolve closed nothing", rows(root)[0]["status"], "open")
        PD.resolve(root, "DD-1", "d", "r", {"/x/y": 7}, ["qa-factory/strategy/test-strategy.md", "qa-factory/strategy/aspect-profile.md"], MARKER)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        check_eq("K6b-3: only the pointer is written; the other keys stay", (config.get("x"), config.get("app_root"), "doc:strategy" in json.dumps(config)),
                 ({"y": 7}, ".", False))
    finally:
        cleanup(root)


def k6b_4_pointer_with_doc_in_it() -> None:
    check_eq("K6b-4: `/doc:x` stays a pointer", PD._refs("/doc:x"), ["/doc:x"])
    check_eq("K6b-4: so does a pointer whose later segment is `doc:`", PD._refs("/a/doc:b"), ["/a/doc:b"])
    root = project()
    try:
        PD.upsert(root, field_refs=["/doc:x"], essence="e", asked="batch 1: q", scope="project", owner="user")
        check_in("K6b-4: a pointer row still needs its value", "/doc:x",
                 refused(lambda: PD.resolve(root, "DD-1", "d", "r", {}, [], "[DEFERRED: none]")))
        PD.resolve(root, "DD-1", "d", "r", {"/doc:x": "v"}, [], "[DEFERRED: none]")
        check_eq("K6b-4: ...and is written into config", json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")).get("doc:x"), "v")
    finally:
        cleanup(root)


def k6b_5_malformed() -> None:
    bad = (("an empty path", "doc:"), ("blanks only", "doc:   "), ("an anchor and no path", "doc:#risk"), ("a root", "doc:/abs"),
           ("a backslash root", "doc:\\abs"), ("a parent", "doc:../out"), ("a parent in the middle", "doc:a/../b"),
           ("a parent by backslash", "doc:..\\out"), ("a bare parent", "doc:.."), ("a drive", "doc:C:/x"),
           ("a drive by backslash", "doc:C:\\x"), ("a drive-relative path", "doc:C:x"), ("upper-case prefix, a parent", "DOC:../out"))
    for label, ref in bad:
        message = refused(lambda ref=ref: PD._refs(ref))
        check(f"K6b-5 ({label}): `{ref}` is refused naming the form", FORM in message and "e.g. doc:strategy/test-strategy.md#risk-and-impact-scale" in message, message)
    check_in("K6b-5: the refusal shows what was refused", "'doc:../out'", refused(lambda: PD._refs("doc:../out")))
    check_eq("K6b-5 AT the boundary: `doc:a` is accepted", PD._refs("doc:a"), ["doc:a"])
    check_eq("K6b-5 BEYOND it: `doc:` is refused", bool(refused(lambda: PD._refs("doc:"))), True)
    check_in("K6b-5: one bad ref among good ones refuses the whole list", FORM, refused(lambda: PD._refs(["/a", DOC, "doc:../x"])))
    root = project()
    try:
        message = refused(lambda: PD.upsert(root, field_refs=["doc:../out"], essence="e", asked="a", scope="project", owner="user"))
        check_in("K6b-5: `upsert` refuses it naming the form", FORM, message)
        check("K6b-5: ...and writes no row", not (root / "qa-factory" / "factory-backlog.md").exists())
        cli = run_script("project_decisions.py", "--root", root, "add", "--field-ref", "doc:/abs", "--essence", "e", "--asked", "a")
        check("K6b-5: the CLI refuses it (non-zero) with the form on stderr, writing nothing",
              cli.returncode != 0 and FORM in cli.stderr and not (root / "qa-factory" / "factory-backlog.md").exists(), cli.stderr[-300:])
    finally:
        cleanup(root)


def k6b_5b_stored_cell() -> None:
    """A hand-edited STORED cell (`doc:../x`) is refused by the next `add`, naming the row id and the file and the fix (FR-1, FR-2);
    never skipped (FR-59); a stored row with a valid doc ref passes as before."""
    root = project()
    try:
        row = PD.upsert(root, field_refs=[DOC], essence=ESSENCE, asked="batch 1: q", scope="project", owner="user")
        backlog = root / "qa-factory" / "factory-backlog.md"
        text = backlog.read_text(encoding="utf-8")
        check_in("K6b-5b: the fixture row carries the valid doc cell", DOC, text)
        again = PD.upsert(root, field_refs=[DOC], essence=ESSENCE, asked="batch 2: q", scope="project", owner="user")
        check_eq("K6b-5b: a stored row with a VALID doc ref is reused as before", (again["id"], len(rows(root))), (row["id"], 1))
        backlog.write_text(text.replace(DOC, "doc:../x"), encoding="utf-8")
        message = refused(lambda: PD.upsert(root, field_refs=["/other"], essence="e", asked="a", scope="project", owner="user"))
        check("K6b-5b: the refusal names the row id, the file, the cell to correct and the form",
              "DD-1" in message and "qa-factory/factory-backlog.md" in message and "correct that cell" in message and FORM in message, message)
        check_eq("K6b-5b: ...and no row was added (a refusal, not a skip)", len(rows(root)), 1)
    finally:
        cleanup(root)


def k6b_6_edges() -> None:
    root = project()
    try:
        old = PD.upsert(root, field_refs=["/risk_areas"], essence=ESSENCE, asked="batch 1: q", scope="project", owner="user")
        new = PD.upsert(root, field_refs=[DOC], essence=ESSENCE, asked="batch 3: q", scope="project", owner="user")
        check_eq("K6b-6: an open `/risk_areas` row is not migrated: the doc ref is a second row (F-14)",
                 (old["id"], new["id"], len(rows(root))), ("DD-1", "DD-2", 2))
    finally:
        cleanup(root)
    root = project()
    try:
        refs = ["/impact_scale/data-loss", "/impact_scale/money"]
        PD.upsert(root, field_refs=refs, essence="impact scale not set: strategy/test-strategy.md (Risk and impact scale)",
                  asked="batch 1: q", scope="project", owner="user", trigger_type="manual")
        check_eq("K6b-6: several numeric classes are ONE row with every ref", [r["field_refs"] for r in rows(root)], [",".join(refs)])
        message = refused(lambda: PD.resolve(root, "DD-1", "d", "r", {refs[0]: {"priority": "P0", "severity": "blocker"}},
                                              ["qa-factory/strategy/test-strategy.md"], MARKER))
        check_in("K6b-6: resolve needs every class's value", "/impact_scale/money", message)
    finally:
        cleanup(root)


k6b_1_refs_form()
k6b_2_doc_only_row()
k6b_3_mixed_row()
k6b_4_pointer_with_doc_in_it()
k6b_5_malformed()
k6b_5b_stored_cell()
k6b_6_edges()
finish("project_decisions_doc_refs (OH2-6 b)")
