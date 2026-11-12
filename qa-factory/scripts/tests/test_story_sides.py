"""t-2181 PC-1a: the story's sides (one reader over the story record), the `stage_done --set sides.*` door, the hold readers.

The reality words are read ONLY from `references/side-realities.json` (AR-1); side names are open (AR-2: `kiosk`).
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract  # noqa: E402
import stage_done  # noqa: E402

DATA = json.loads((harness.PLUGIN_ROOT / "references" / "side-realities.json").read_text(encoding="utf-8"))
# Test words are picked BY NAME, never by list position; `word_cases` pins that each is in the data file.
REAL, ABSENT, SUBSTITUTED = "real", contract.PARKING_REALITY, "substituted"


def side(reality, deliverable=True, **extra):
    return {"reality": reality, "deliverable": deliverable, **extra}


def refusal(spec):
    try:
        stage_done.parse_sets([spec])
        return ""
    except ValueError as exc:
        return str(exc)


def reader_cases():
    expected = {name: {**row, "reference": None, "source": "default"} for name, row in DATA["default"].items()}
    for label, record in (("no pipeline.sides", {}), ("an empty sides record", {"sides": {}}),
                          ("an unreadable pipeline (None)", None), ("sides that is not a dict", {"sides": "x"})):
        check_eq(f"default: {label}", stderr_of(lambda: contract.story_sides(record, {}))[0], expected)
    sides = contract.story_sides({"sides": {"kiosk": side(SUBSTITUTED, False, settles_by="platform team", source="launch"),
                                            "api": side(ABSENT, settles_by=None)}}, {})
    check_eq("pipeline.sides is read, settles_by kept", sides["kiosk"]["settles_by"], "platform team")
    check_eq("settles_by empty reads ''", sides["api"]["settles_by"], "")
    check_eq("an entry with no deliverable reads true; no reality reads unknown, never real",
             (contract.story_sides({"sides": {"x": {}}})["x"]["deliverable"], contract.story_sides({"sides": {"x": {}}})["x"]["reality"]),
             (True, ""))
    check("a recorded side wins over the default (product is not implied)", "product" not in sides)


def parks_cases():
    def parks(*entries):
        return contract.parks_after_s5({"sides": {f"s{i}": e for i, e in enumerate(entries)}})
    check_eq("absent + deliverable parks", parks(side(ABSENT, True)), True)
    check_eq("substituted + deliverable does not", parks(side(SUBSTITUTED, True)), False)
    check_eq("absent + not deliverable does not", parks(side(ABSENT, False)), False)
    check_eq("real does not", parks(side(REAL, True)), False)
    check_eq("an unrecorded story does not park", contract.parks_after_s5({}), False)


def awaiting_cases():
    check_eq("no record -> none", contract.awaiting({})["state"], "none")
    check_eq("an unreadable pipeline -> none", contract.awaiting(None)["state"], "none")
    old = contract.awaiting({"awaiting": {"since": "2026-11-01T10:00:00", "sides": ["api"], "packet": "interim-report.md"}})
    check_eq("a record without cause/held_from (old shape) reads s5_absent_side / S6",
             (old["state"], old["cause"], old["held_from"], old["packet"]), ("awaiting", "s5_absent_side", "S6", "interim-report.md"))
    new = contract.awaiting({"awaiting": {"since": "t", "cause": "first_look_stop", "held_from": "S3"}})
    check_eq("a record with first_look_stop / S3 is returned as given", (new["state"], new["cause"], new["held_from"]),
             ("awaiting", "first_look_stop", "S3"))
    stopped = contract.awaiting({"awaiting": {"since": "t", "stopped": {"at": "t2", "words": "stop"}}})
    check_eq("a stopped mark -> stopped", (stopped["state"], stopped["stopped"]["words"]), ("stopped", "stop"))


def stage_done_cases():
    check_eq("a data word is accepted and is the word", stage_done.parse_sets([f"sides.api.reality={ABSENT}"]),
             {"sides.api.reality": ABSENT})
    message = refusal("sides.api.reality=mocked")
    check("an unknown reality is refused, naming every allowed word and the data file",
          all(w in message for w in DATA["realities"]) and "side-realities.json" in message, message)
    check_eq("a side `kiosk` outside any list passes (open variety)",
             stage_done.parse_sets([f"sides.kiosk.reality={SUBSTITUTED}"]), {"sides.kiosk.reality": SUBSTITUTED})
    check_eq("deliverable is a bool, settles_by empty is ''",
             stage_done.parse_sets(["sides.kiosk.deliverable=false", "sides.kiosk.settles_by="]),
             {"sides.kiosk.deliverable": False, "sides.kiosk.settles_by": ""})
    check("deliverable `maybe` is refused", "true or false" in refusal("sides.kiosk.deliverable=maybe"))
    check("an unknown attribute is refused naming the attributes", "reality" in refusal("sides.kiosk.colour=red"))
    check_eq("sides_unknown= clears", stage_done.parse_sets(["sides_unknown="]), {"sides_unknown": None})
    pipeline = {"sides_unknown": {"at": "t", "why": "x"}}
    stage_done.apply_facts(pipeline, stage_done.parse_sets([f"sides.kiosk.reality={ABSENT}", "sides.kiosk.deliverable=true"]), [])
    check_eq("a set lands as a nested record the reader reads", contract.story_sides(pipeline)["kiosk"]["reality"], ABSENT)


class pointed_at:
    """`contract.SIDE_REALITIES_PATH` pointed elsewhere for a block (a temp copy or a missing path - never the live file)."""
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.old, contract.SIDE_REALITIES_PATH = contract.SIDE_REALITIES_PATH, self.path

    def __exit__(self, *exc):
        contract.SIDE_REALITIES_PATH = self.old


def stderr_of(call):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        value = call()
    return value, buf.getvalue()


def word_cases():
    check("the test words are in the data file", all(w in DATA["realities"] for w in (REAL, ABSENT, SUBSTITUTED)))


def note_cases():
    value, err = stderr_of(lambda: contract.story_sides(None))
    check("an unreadable pipeline reads the default and says why on stderr (one line)",
          "pipeline.json could not be read" in err and err.count("\n") == 1 and "product" in err, err)
    check("the default is still returned", "product" in value)
    value, err = stderr_of(lambda: contract.story_sides({}))
    check_eq("an empty readable record is the default and prints nothing", ("product" in value, err), (True, ""))
    value, err = stderr_of(lambda: contract.story_sides("not a dict"))
    check("a pipeline that is not a dict is unreadable too", "pipeline.json could not be read" in err)
    with tempfile.TemporaryDirectory(prefix="qa-sides-") as td, pointed_at(Path(td) / "missing.json"):
        value, err = stderr_of(lambda: contract.story_sides({}))
        check_eq("an unreadable data file: {} and a note naming it", (value, "side-realities.json" in err), ({}, True))
        value, err = stderr_of(lambda: contract.story_sides({"sides": {"api": side(ABSENT)}}))
        check_eq("a recorded side needs no data file and prints nothing", ("api" in value, err), (True, ""))
        message = refusal(f"sides.api.reality={ABSENT}")
        check("coerce_value refuses when the data file cannot be read (AR-28)",
              "cannot be read" in message and "side-realities.json" in message, message)


def edge_cases():
    sides = contract.story_sides({"sides": {"api": "absent"}})
    check_eq("a non-dict entry reads unknown reality", sides["api"]["reality"], "")
    check_eq("and does not park", contract.parks_after_s5({"sides": {"api": "absent"}}), False)
    check_eq("a non-dict awaiting record -> none", contract.awaiting({"awaiting": "yes"})["state"], "none")
    check_eq("sides_unknown.at / .why land nested",
             _applied(["sides_unknown.at=t1", "sides_unknown.why=no access"], {"sides_unknown": None})["sides_unknown"],
             {"at": "t1", "why": "no access"})
    check("sides_unknown=x is refused naming the clear form", "--set sides_unknown=" in refusal("sides_unknown=x"))


def _applied(specs, pipeline):
    stage_done.apply_facts(pipeline, stage_done.parse_sets(specs), [])
    return pipeline


def bom_cases():
    with tempfile.TemporaryDirectory(prefix="qa-sides-") as td:
        copy = Path(td) / "side-realities.json"
        copy.write_bytes(b"\xef\xbb\xbf" + (harness.PLUGIN_ROOT / "references" / "side-realities.json").read_bytes())
        with pointed_at(copy):
            value, err = stderr_of(lambda: contract.story_sides({}))
            check_eq("a BOM copy: the reader gives the default", ("product" in value, err), (True, ""))
            check_eq("a BOM copy: the --set door accepts a data word",
                     stage_done.parse_sets([f"sides.x.reality={ABSENT}"]), {"sides.x.reality": ABSENT})
            check_eq("both read the same words", contract.side_realities().get("realities"), DATA["realities"])


def transition_cases():
    import hooklib
    with tempfile.TemporaryDirectory(prefix="qa-sides-") as td:
        proj = Path(td)
        art = proj / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        (proj / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        old = hooklib._PROJECT_ROOT_CACHE
        hooklib._PROJECT_ROOT_CACHE = proj
        try:
            (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}, "gates": {}}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                stage_done.set_facts("QA-1", stage_done.parse_sets(
                    [f"sides.kiosk.reality={ABSENT}", "sides_unknown.at=t1", "sides_unknown.why=w"]), [])
                code = stage_done.run("QA-1", "S1", "done", "qa-scout", "one fact", True)
            written = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
            check_eq("a stage transition ran", (code, written["stages"]["S1"]["status"]), (0, "done"))
            check_eq("and kept sides on disk", written.get("sides", {}).get("kiosk", {}).get("reality"), ABSENT)
            check_eq("and sides_unknown", written.get("sides_unknown"), {"at": "t1", "why": "w"})
        finally:
            hooklib._PROJECT_ROOT_CACHE = old


def registry_cases():
    """t-2181 PC-1b: the registry leg of the reader (through `project_knowledge.subjects` + `state`), its order, its unknowns and
    the `registry_key` each registry side carries."""
    import project_knowledge as PK

    def put(root, key, element, value, environment="", scope=None):
        row, problem, _ = PK.record(root, key=key, environment=environment, element=element, state="known",
                                    scope=scope or ("project" if key == PK.SIDES_KEY else "stand"), value=value, words="the person said",
                                    source="person", story="S-1", by="conductor")
        check(f"fixture row {key} {element}", row is not None, problem)

    def read(root, record=None, env=None):
        return stderr_of(lambda: contract.story_sides(record if record is not None else {}, {}, env, root=root))

    with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
        root = Path(td)
        check_eq("no registry file: the default, as before", (read(root)[0]["product"]["source"], read(root)[1]), ("default", ""))
        put(root, PK.SIDES_KEY, "ui", {"deliverable": False, "settles_by": "platform team"})
        sides, _ = read(root)
        check_eq("a project row: source registry, registry_key product.sides, deliverable and settles_by read",
                 {k: sides["ui"][k] for k in ("source", "registry_key", "deliverable", "settles_by", "reality")},
                 {"source": "registry", "registry_key": PK.SIDES_KEY, "deliverable": False, "settles_by": "platform team", "reality": REAL})
        check("a product.sides row of a real side that is another team's (deliverable false) does not name this team's part: `product` is implied",
              "product" in sides, sorted(sides))
        put(root, PK.STAND_SIDES_KEY, "backend", {"reality": SUBSTITUTED}, environment="dev")
        sides, _ = read(root, env="dev")
        check_eq("a stand row of the chosen stand: reality read, registry_key environments.sides; deliverable unknown reads true",
                 {k: sides["backend"][k] for k in ("reality", "registry_key", "deliverable", "source")},
                 {"reality": SUBSTITUTED, "registry_key": PK.STAND_SIDES_KEY, "deliverable": True, "source": "registry"})
        check_eq("another stand's row is not read for this stand", "backend" in read(root, env="prod")[0], False)
        check_eq("no stand chosen: no stand row is read", "backend" in read(root)[0], False)
        put(root, PK.REFERENCE_KEY, "ui", {"reference": True}, environment="old")
        check_eq("a reference found on another stand's row (all stands are read), the key stays the one that set the side",
                 (read(root, env="dev")[0]["ui"]["reference"], read(root, env="dev")[0]["ui"]["registry_key"]), ("old", PK.SIDES_KEY))
        check_eq("pipeline.sides wins over the registry, and carries no registry_key",
                 ("registry_key" in read(root, {"sides": {"ui": side(ABSENT)}}, "dev")[0]["ui"],
                  read(root, {"sides": {"ui": side(ABSENT)}}, "dev")[0]["ui"]["reality"]), (False, ABSENT))
        check_eq("the default product carries no registry_key", "registry_key" in contract.story_sides({})["product"], False)
    with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
        root = Path(td)
        put(root, PK.REFERENCE_KEY, "ui", {"reference": True}, environment="old")
        sides, _ = read(root)
        check_eq("a reference row alone: registry_key environments.reference_for, reality real, deliverable reads true: no implicit product",
                 ({k: sides["ui"][k] for k in ("registry_key", "reference", "reality")}, "product" in sides),
                 ({"registry_key": PK.REFERENCE_KEY, "reference": "old", "reality": REAL}, False))
    with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
        root = Path(td)
        put(root, PK.SIDES_KEY, "UI", {"deliverable": True})
        put(root, PK.SIDES_KEY, "ui", {"deliverable": False})
        sides, _ = read(root)
        check_eq("`UI` and `ui` are two sides", sorted(sides), ["UI", "ui"])
        check_eq("registry_sides names every recorded side", contract.registry_sides(root)["names"], ["UI", "ui"])
    for label, body in (("a malformed value", {"deliverable": "maybe"}), ("a word outside the data file", None)):
        with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
            root = Path(td)
            put(root, PK.SIDES_KEY, "ui", {"deliverable": True})
            path = PK.record_path(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["facts"].append({"id": "PK-9", "key": PK.STAND_SIDES_KEY, "environment": "dev", "element": "backend", "state": "known",
                                  "scope": "stand", "value": {"reality": "mocked"} if body is None else body, "provenance": {}, "at": "2026-12-01T10:00:00+00:00"})
            path.write_text(json.dumps(data), encoding="utf-8")
            got = contract.registry_sides(root, "dev")
            check_eq(f"{label} on a side row: the side reads unknown (never real, never 'no row') and the problem is said",
                     (got["sides"]["backend"]["reality"], bool(got["problem"]), got["unreadable"]), ("", True, False))
    with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
        root = Path(td)
        put(root, PK.SIDES_KEY, "ui", {"deliverable": True})
        path = PK.record_path(root)
        data = json.loads(path.read_text(encoding="utf-8"))
        for number, bad in enumerate(("web.app", "a=b")):       # a hand-edited row the writer would refuse (F3)
            data["facts"].append({"id": f"PK-{number + 8}", "key": PK.SIDES_KEY, "environment": "", "element": bad, "state": "known",
                                  "scope": "project", "value": {"deliverable": True}, "provenance": {}, "at": "2026-12-01T10:00:00+00:00"})
        path.write_text(json.dumps(data), encoding="utf-8")
        got = contract.registry_sides(root)
        check_eq("F3: a side name holding a dot or an equals sign reads malformed (unknown, problem said), never real",
                 (got["sides"]["web.app"]["reality"], got["sides"]["a=b"]["reality"], bool(got["problem"]), got["unreadable"],
                  got["sides"]["ui"]["reality"]), ("", "", True, False, REAL))
    for label, content in (("the file unreadable", "{not json"), ("a foreign schema_version", json.dumps({"schema_version": 99, "facts": []}))):
        with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
            root = Path(td)
            PK.record_path(root).parent.mkdir(parents=True)
            PK.record_path(root).write_text(content, encoding="utf-8")
            sides, err = read(root)
            check_eq(f"{label}: the default side reads unknown, never real, one line on stderr",
                     (sides["product"]["reality"], "unknown" in err, err.count("\n")), ("", True, 1))
            check_eq(f"{label}: registry_sides says unreadable", contract.registry_sides(root)["unreadable"], True)
    with tempfile.TemporaryDirectory(prefix="qa-sides-reg-") as td:
        root = Path(td)
        put(root, PK.STAND_SIDES_KEY, "backend", {"reality": SUBSTITUTED}, environment="Dev")
        check_eq("stand names are exact: `Dev` is not `dev`", "backend" in read(root, env="dev")[0], False)
        put(root, PK.REFERENCE_KEY, "ui", {"reference": True}, environment="a")
        put(root, PK.REFERENCE_KEY, "ui", {"reference": True}, environment="b")
        check_eq("two reference stands for one side read unknown, not a pick",
                 (contract.registry_sides(root)["sides"]["ui"]["reality"], bool(contract.registry_sides(root)["problem"])), ("", True))


def copy_registry(root, root2):
    """A second story of the same project: the project's registry file is copied to `root2` (the registry is the project's, not the story's)."""
    import shutil
    import project_knowledge as PK
    PK.record_path(root2).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(PK.record_path(root), PK.record_path(root2))


def driver_cases():
    """t-2181 PC-1b in the driver at S0: the second story is not asked; the answer is recorded once (writer 2); a no_trace story
    keeps it in `pipeline.sides` with the line; C15; an unreadable registry is `sides_unknown`."""
    import project_knowledge as PK
    from story_run_common import eq as check_eq   # this one takes a detail text (the process output) as a fourth argument
    from story_run_common import s0_answer, s0_pipeline, s0_project, s0_run, s0_state, stub_calls
    repos = {"code_repos": [{"name": "app", "path": "app"}]}
    # PC2-7 (t-043): ONE table - the implicit `product` is carried exactly when no side of the story is a real side of this team, whatever the
    # registry holds from earlier stories and with or without `--no-trace`. Each S0 row runs traced AND `--no-trace` and the two records are
    # equal without `at`; the id of the row names the case in every label. `second-story` has no `--no-trace` half (that flow asks again).
    product_default = {"reality": "real", "deliverable": True, "source": "default"}
    ours, theirs = (("ui", True, ""),), (("backend", False, "platform team"),)
    # id, registry rows (name, deliverable, settles_by), launch flags, the answer to sides.deliverable (None: not asked), `product`, `backend`
    rows = (
        ("own-answer", (), ("--side", "backend=substituted"), "another team's", product_default, (SUBSTITUTED, False, "")),
        ("other-story-row", theirs, ("--side", "backend=substituted"), None, product_default, (SUBSTITUTED, False, "platform team")),
        ("real-side-named", ours, ("--side", "backend=substituted"), "another team's", None, None),
        ("other-team-real", (("ui", False, ""),), ("--side", "backend=substituted"), "another team's", product_default, None),
        ("reference-only", (), ("--reference", "ui=old"), None, None, None),
        ("second-story", (), ("--side", "backend=substituted"), "another team's", product_default, (SUBSTITUTED, False, "")),
    )

    def strip(sides):
        return {name: {k: v for k, v in entry.items() if k != "at"} for name, entry in sides.items()}

    def story_one(row, *extra):
        """A fresh project, the registry rows seeded, the launch and the answer; `(root, task_root, env, out)` - the caller cleans up."""
        root, task_root, env = s0_project("PROJ-1", config=repos)
        for name, deliverable, settles_by in row[1]:
            PK.record(root, key=PK.SIDES_KEY, environment="", element=name, state="known", scope="project",
                      value={"deliverable": deliverable, "settles_by": settles_by}, words="the person said", source="person", story="S-0", by="conductor")
        out = s0_run(root, env, "PROJ-1", *extra, *row[2])
        if row[3]:
            out = s0_answer(root, env, "PROJ-1", row[3], *extra)
        return root, task_root, env, out

    for row in rows:
        name, found = row[0], {}
        for mode, extra in (("traced", ()), ("no-trace", ("--no-trace",))):
            if name == "second-story" and extra:
                continue
            root, task_root, env, out = story_one(row, *extra)
            try:
                found[mode] = strip(s0_pipeline(task_root)["sides"])
                check_eq(f"{name} ({mode}): S0 ends and nothing is left asked", (out.returncode, s0_state(task_root).get("s0_block")), (0, None),
                         out.stdout[-500:] + out.stderr[-300:])
                check_eq(f"{name} ({mode}): `product` is as the rule says", found[mode].get("product"), row[4])
                if row[5]:
                    got = found[mode]["backend"]
                    check_eq(f"{name} ({mode}): the registry's deliverable and settles_by are recorded with the launch's reality",
                             (got["reality"], got["deliverable"], got.get("settles_by", "")), row[5])
                if name == "second-story":      # story 2 of the project: the same launch, a copy of the registry, nothing asked
                    root2, task_root2, env2 = s0_project("PROJ-2", config=repos)
                    try:
                        copy_registry(root, root2)
                        out2 = s0_run(root2, env2, "PROJ-2", *row[2])
                        second = strip(s0_pipeline(task_root2)["sides"])
                        check_eq(f"{name}: story 2 is not asked", (out2.returncode, s0_state(task_root2).get("s0_block")), (0, None),
                                 out2.stdout[-500:] + out2.stderr[-300:])
                        check_eq(f"{name}: story 2 carries story 1's `product`, whole", second.get("product"), found[mode]["product"])
                        check_eq(f"{name}: story 2's backend equals story 1's on reality and deliverable (its source differs by design)",
                                 {k: second["backend"][k] for k in ("reality", "deliverable")},
                                 {k: found[mode]["backend"][k] for k in ("reality", "deliverable")})
                    finally:
                        harness.cleanup(root2)
            finally:
                harness.cleanup(root)
        if "no-trace" in found:
            check_eq(f"{name}: the traced and the `--no-trace` records are equal without `at`", found["traced"], found["no-trace"])
    root, task_root, env = s0_project("PROJ-1", config=repos)
    try:
        s0_run(root, env, "PROJ-1", "--side", "backend=substituted")
        out = s0_answer(root, env, "PROJ-1", "another team's")
        row = PK.state(root, PK.SIDES_KEY, "", "backend")["row"] or {}
        check_eq("writer 2: the answer is a project row, by driver, source person, state known",
                 (out.returncode, row.get("value"), (row.get("provenance") or {}).get("by"), (row.get("provenance") or {}).get("source"), row.get("state")),
                 (0, {"deliverable": False, "settles_by": ""}, "driver", "person", "known"))
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project("PROJ-1", config=repos)
    try:
        s0_run(root, env, "PROJ-1", "--no-trace", "--side", "backend=substituted")
        out = s0_answer(root, env, "PROJ-1", "ours", "--no-trace")
        check_eq("a no_trace story keeps the answer in pipeline.sides (source person)",
                 (out.returncode, {k: s0_pipeline(task_root)["sides"]["backend"][k] for k in ("deliverable", "source")}),
                 (0, {"deliverable": True, "source": "person"}), out.stdout[-400:] + out.stderr[-300:])
        line = "your answer about backend was kept for this story only (an experiment leaves no trace)"
        check("... says the one line", line in out.stdout, out.stdout[-400:])
        check("... and the line is a warning of the story's record too (F5)", line in s0_pipeline(task_root)["warnings"],
              s0_pipeline(task_root)["warnings"])
        check_eq("... and records nothing in the registry", PK.record_path(root).exists(), False)
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project("PROJ-1", config=repos)
    try:
        PK.record(root, key=PK.SIDES_KEY, environment="", element="ui", state="known", scope="project", value={"deliverable": True},
                  words="ours", source="person", story="S-0", by="conductor")
        out = s0_run(root, env, "PROJ-1", "--side", "UI=substituted")
        check_eq("C15: `UI` beside a recorded `ui` is refused, S0 is not recorded", (task_root / "pipeline.json").exists(), False,
                 out.stdout[-400:] + out.stderr[-300:])
        # the guard hands a refusal to the conductor, so the refusal text is the prompt of the conductor call (no default that holds the name)
        prompts = [call.get("prompt", "") for call in stub_calls(root) if call.get("kind") == "conductor"]
        check("... the refusal (the conductor's prompt) names the recorded name and the flag that is the door",
              any("`ui`" in text and "Start again with --side" in text for text in prompts), prompts[-1][-600:] if prompts else "no conductor call")
        check_eq("... the offending name is not kept in launch (the corrected flag is the door)",
                 "UI" in ((s0_state(task_root).get("launch") or {}).get("side") or {}), False)
        out = s0_run(root, env, "PROJ-1", "--side", "ui=real")
        check_eq("... and the recorded spelling goes through", (out.returncode, (task_root / "pipeline.json").exists()), (0, True),
                 out.stdout[-400:] + out.stderr[-300:])
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project("PROJ-1", config=repos)
    try:
        PK.record_path(root).parent.mkdir(parents=True, exist_ok=True)
        PK.record_path(root).write_text("{not json", encoding="utf-8")
        out = s0_run(root, env, "PROJ-1", "--side", "ui=real")
        pipeline = s0_pipeline(task_root)
        check_eq("an unreadable registry: S0 ends with pipeline.sides_unknown written and no side recorded as real",
                 (out.returncode, sorted(pipeline.get("sides_unknown") or {}), "sides" in pipeline), (0, ["at", "why"], False),
                 out.stdout[-400:] + out.stderr[-300:])
        first_at = pipeline["sides_unknown"]["at"]
        out = s0_run(root, env, "PROJ-1")
        check_eq("F1 (b): the file still unreadable on the relaunch: the mark is kept, its `at` unchanged",
                 (out.returncode, (s0_pipeline(task_root).get("sides_unknown") or {}).get("at")), (0, first_at),
                 out.stdout[-400:] + out.stderr[-300:])
    finally:
        harness.cleanup(root)
    stands = {"code_repos": [{"name": "app", "path": "app"}], "environments": [{"name": "dev"}]}
    root, task_root, env = s0_project("PROJ-1", config=stands)
    try:
        PK.record_path(root).parent.mkdir(parents=True, exist_ok=True)
        PK.record_path(root).write_text("{not json", encoding="utf-8")
        s0_run(root, env, "PROJ-1")
        check_eq("F1 (a): S0 over an unreadable registry gives sides_unknown", bool(s0_pipeline(task_root).get("sides_unknown")), True)
        PK.record_path(root).unlink()
        PK.record(root, key=PK.SIDES_KEY, environment="", element="backend", state="known", scope="project",
                  value={"deliverable": False, "settles_by": "platform team"}, words="theirs", source="person", story="S-0", by="conductor")
        PK.record(root, key=PK.STAND_SIDES_KEY, environment="dev", element="backend", state="known", scope="stand",
                  value={"reality": SUBSTITUTED}, words="the stand", source="person", story="S-0", by="conductor")
        out = s0_run(root, env, "PROJ-1")
        pipeline = s0_pipeline(task_root)
        entry = (pipeline.get("sides") or {}).get("backend") or {}
        check_eq("F1 (a): the repaired registry on the relaunch clears the mark and records the substituted side (source registry)",
                 (out.returncode, bool(pipeline.get("sides_unknown")), entry.get("reality"), entry.get("deliverable"), entry.get("source")),
                 (0, False, SUBSTITUTED, False, "registry"), out.stdout[-400:] + out.stderr[-300:])
        check_eq("F1 (a): ... and the re-read carries the implicit `product` as the default, as S0 spells it (K-b2, AR-19)",
                 {k: v for k, v in ((pipeline.get("sides") or {}).get("product") or {}).items() if k != "at"}, product_default)
        check_eq("... and a third launch with no mark does nothing more (the record is as it was)", (s0_run(root, env, "PROJ-1").returncode,
                 s0_pipeline(task_root)["sides"]), (0, pipeline["sides"]))
    finally:
        harness.cleanup(root)
    # t-2277 batch 2b W2 (4): a relaunch re-read of a side with NO recorded deliverable answer keeps the default `ours` (the owner accepted it)
    root, task_root, env = s0_project("PROJ-1", config=stands)
    try:
        PK.record_path(root).parent.mkdir(parents=True, exist_ok=True)
        PK.record_path(root).write_text("{not json", encoding="utf-8")
        s0_run(root, env, "PROJ-1")
        PK.record_path(root).unlink()
        PK.record(root, key=PK.STAND_SIDES_KEY, environment="dev", element="backend", state="known", scope="stand",
                  value={"reality": SUBSTITUTED}, words="the stand", source="person", story="S-0", by="conductor")
        out = s0_run(root, env, "PROJ-1")
        pipeline = s0_pipeline(task_root)
        entry = (pipeline.get("sides") or {}).get("backend") or {}
        check_eq("W2 (4): the re-read records the stand's reality and writes NO deliverable for a side nobody answered (source registry)",
                 (out.returncode, bool(pipeline.get("sides_unknown")), entry.get("reality"), "deliverable" in entry, entry.get("source")),
                 (0, False, SUBSTITUTED, False, "registry"), out.stdout[-400:] + out.stderr[-300:])
        import contract
        check_eq("... and the readers take it as ours (default true), the question is not raised by the re-read",
                 (contract.story_sides(pipeline)["backend"]["deliverable"], s0_state(task_root).get("s0_block")), (True, None))
    finally:
        harness.cleanup(root)
    # t-2277 batch 2b W2 (1, 2): the answer is the PROJECT's (a registry row) and a later word overwrites it; the next story reads the latest
    root, task_root, env = s0_project("PROJ-1", config=repos)
    try:
        PK.record(root, key=PK.SIDES_KEY, environment="", element="backend", state="known", scope="project", value={"deliverable": False, "settles_by": ""},
                  words="another team's", source="person", story="S-0", by="driver")
        PK.record(root, key=PK.SIDES_KEY, environment="", element="backend", state="known", scope="project", value={"deliverable": True, "settles_by": ""},
                  words="no, this backend is ours", source="person", story="S-1", by="conductor")
        out = s0_run(root, env, "PROJ-1", "--side", "backend=substituted")
        entry = s0_pipeline(task_root)["sides"]["backend"]
        check_eq("W2 (2): the later word overwrites: the story reads `ours`, and is asked nothing",
                 (out.returncode, s0_state(task_root).get("s0_block"), entry["deliverable"]), (0, None, True), out.stdout[-400:] + out.stderr[-300:])
        row = PK.state(root, PK.SIDES_KEY, "", "backend")["row"]
        check_eq("... the registry's latest row carries the person's words, who and when",
                 (row["provenance"]["words"], row["provenance"]["story"], bool(row["at"])), ("no, this backend is ours", "S-1", True))
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project("PROJ-1", config=stands)
    try:
        PK.record(root, key=PK.SIDES_KEY, environment="", element="backend", state="known", scope="project",
                  value={"deliverable": False, "settles_by": ""}, words="theirs", source="person", story="S-0", by="conductor")
        PK.record(root, key=PK.STAND_SIDES_KEY, environment="dev", element="backend", state="known", scope="stand",
                  value={"reality": SUBSTITUTED}, words="the stand", source="person", story="S-0", by="conductor")
        out = s0_run(root, env, "PROJ-1")
        pipeline = s0_pipeline(task_root)
        entry = (pipeline.get("sides") or {}).get("backend") or {}
        check_eq("F2: no --env, the stand `dev` selected: its substituted row reaches pipeline.sides (never read as real)",
                 (out.returncode, pipeline.get("environment"), entry.get("reality"), entry.get("deliverable")),
                 (0, "dev", SUBSTITUTED, False), out.stdout[-500:] + out.stderr[-300:])
        check("F6: no side of the story is a real side of this team (backend is substituted, another team's), so `product` is implied in pipeline.sides",
              "product" in (pipeline.get("sides") or {}), sorted(pipeline.get("sides") or {}))
    finally:
        harness.cleanup(root)
    root, task_root, env = s0_project("PROJ-1", config=stands)
    try:
        PK.record(root, key=PK.STAND_SIDES_KEY, environment="dev", element="backend", state="known", scope="stand",
                  value={"reality": ABSENT}, words="the stand", source="person", story="S-0", by="conductor")
        out = s0_run(root, env, "PROJ-1")
        check_eq("F2 sibling: a side known only from the selected stand's row is asked sides.deliverable (never silently ours)",
                 (out.returncode != 0 or s0_state(task_root).get("s0_block") is not None, (task_root / "pipeline.json").exists(),
                  str(s0_state(task_root).get("s0_block"))), (True, False, "deliverable:backend"), out.stdout[-500:] + out.stderr[-300:])
    finally:
        harness.cleanup(root)


def absent_story(task, sides=("api",)):
    """t-2559 (W2 B3): a seeded story whose `sides` are absent and this story's own; the driver runs the hold's body (`_act_await_implementation`)
    and the hold is recorded by the real controller. Returns `(root, task_root, env, driver, person)`; `person` is the question raised."""
    import story_run
    from story_run_common import driver_for, seed
    root, task_root, env = seed(task)
    sets = [part for name in sides for attr, value in (("reality", ABSENT), ("deliverable", "true"), ("source", "person"))
            for part in ("--set", f"sides.{name}.{attr}={value}")]
    harness.run_script("stage_done.py", "--task", task, *sets, cwd=root, env=env)
    driver = driver_for(root, env, task)
    person = None
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            driver._act_await_implementation({"action": "await_implementation", "cause": "s5_absent_side", "held_from": "S6", "sides": {}})
        except story_run.Person as raised:
            person = raised
    return root, task_root, env, driver, person


def answer_of(driver, root, words):
    """The person's answer taken by the real `take_answer` over the open question; returns what it printed."""
    driver.state["asked"] = {"kind": "absent_side", "stage": "S6", "dispatch": ""}
    driver.state.setdefault("pending_words", {})
    path = root / "answer-words.txt"
    path.write_text(words, encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        driver.take_answer(path)
    return out.getvalue()


def pipeline_of(task_root):
    return json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))


def absent_side_cases():
    """t-2559 (W2 B3): the S5 hold for an absent side asks whose the side is. The owner's flow end to end, then the edges."""
    import project_knowledge as PK
    import story_run
    from story_run_common import s0_pipeline, s0_project, s0_run, s0_state
    # the owner's flow: parks, is asked, answers `not ours`, the row says deliverable false with the person's words, the hold is lifted
    root, task_root, env, driver, person = absent_story("QA-5")
    try:
        check_eq("B3: the hold is recorded and a closed question is raised over the side",
                 (person is not None and person.kind, bool(pipeline_of(task_root).get("awaiting")), driver.state.get("absent_side")),
                 ("absent_side", True, "api"))
        for needle in ("`api` does not exist yet", "waits for its code", "`not ours`", "`relaunch`", "stand-in"):
            check(f"B3: the question says {needle}", needle in str(person.text), str(person.text)[:400])
        words = "not ours\nthe api is the platform team's, test on mocks"
        said = answer_of(driver, root, words)
        record = pipeline_of(task_root)
        side = record["sides"]["api"]
        check_eq("B3: the story's side is substituted, not deliverable, by the person", (side["reality"], side["deliverable"], side["source"]),
                 (SUBSTITUTED, False, "person"))
        check_eq("B3: the hold is lifted and the story no longer parks", ("awaiting" in record, contract.parks_after_s5(record)), (False, False))
        row = PK.state(root, PK.SIDES_KEY, "", "api")["row"] or {}
        check_eq("B3: the registry row says deliverable false, with the person's words, by the driver",
                 (row.get("value"), (row.get("provenance") or {}).get("words"), (row.get("provenance") or {}).get("by"),
                  (row.get("provenance") or {}).get("source")),
                 ({"deliverable": False, "settles_by": ""}, words, "driver", "person"))
        check("B3: the person is told in words that the wait is over", "`api` is another team's at your word" in said, said[-300:])
        check_eq("B3: the answer left no open question and no kept side name", (driver.state.get("asked"), "absent_side" in driver.state), ({}, False))
        # a second story of the same project is not asked (the registry row is the project's)
        root2, task_root2, env2 = s0_project("PROJ-2", config={"code_repos": [{"name": "app", "path": "app"}]})
        try:
            copy_registry(root, root2)
            out = s0_run(root2, env2, "PROJ-2", "--side", "api=absent")
            entry = (s0_pipeline(task_root2).get("sides") or {}).get("api") or {}
            check_eq("B3: a second story of the project is not asked: no stop, the side is not deliverable (W2 (3))",
                     (out.returncode, s0_state(task_root2).get("s0_block"), entry.get("deliverable"), entry.get("reality")),
                     (0, None, False, ABSENT))
        finally:
            harness.cleanup(root2)
        # a later word `it is ours` overwrites it, and the history is kept (W2)
        PK.record(root, key=PK.SIDES_KEY, environment="", element="api", state=PK.KNOWN, scope="project", value={"deliverable": True, "settles_by": ""},
                  words="no, the api is ours after all", source="person", story="QA-9", by="conductor")
        rows, _problem = PK.load(root)
        mine = [r for r in rows if r.get("key") == PK.SIDES_KEY and r.get("element") == "api"]
        check_eq("B3: the later word overwrites (the latest row reads ours) and both rows are kept",
                 (PK.state(root, PK.SIDES_KEY, "", "api")["row"]["value"]["deliverable"], len(mine)), (True, 2))
    finally:
        harness.cleanup(root)
    # `relaunch`: today's behaviour exactly - nothing changes, the hold stands
    root, task_root, env, driver, person = absent_story("QA-5")
    try:
        answer_of(driver, root, "relaunch")
        record = pipeline_of(task_root)
        check_eq("B3: `relaunch` changes nothing: the hold stands, the side is still absent and ours, no registry row",
                 (bool(record.get("awaiting")), record["sides"]["api"]["reality"], record["sides"]["api"]["deliverable"], PK.record_path(root).exists()),
                 (True, ABSENT, True, False))
        check_eq("B3: ... every side answered, in the process of the answer nothing more is asked (exit 0, the packet)",
                 _bare_relaunch(driver), story_run.EXIT_DONE)
        first_text = str(person.text)
        # B-1 (t-2562): a bare relaunch in a LATER process re-offers the door, with a lead that names the earlier answer (FR-7)
        from story_run_common import driver_for
        later = driver_for(root, env, "QA-5")
        again = _bare_relaunch(later)
        check_eq("B3 B-1: a later bare relaunch re-offers the question over the same side", (getattr(again, "kind", again), later.state.get("absent_side")),
                 ("absent_side", "api"))
        check("B3 B-1: ... with a changed lead that names the earlier answer and its date (never the same text twice)",
              str(again.text) != first_text and "you said you would start" in str(again.text) and _today() in str(again.text), str(again.text)[:300])
        check("B3 B-1: ... and the `not ours` door is in it", "`not ours`" in str(again.text))
        said = answer_of(later, root, "not ours")
        check_eq("B3 B-1: `not ours` after a `relaunch` lifts the hold", (pipeline_of(task_root)["sides"]["api"]["deliverable"],
                                                                       "awaiting" in pipeline_of(task_root)), (False, False))
    finally:
        harness.cleanup(root)
    # B-1 (b)/(d): a hold met again with NO answer for it (a crash after the `await`, a lost question file) asks again, with today's text
    root, task_root, env, driver, person = absent_story("QA-5")
    try:
        from story_run_common import driver_for
        later = driver_for(root, env, "QA-5")
        again = _bare_relaunch(later)
        check_eq("B3 B-1: no answer was recorded for this hold: the bare relaunch asks again, over the side, with the original text",
                 (getattr(again, "kind", again), str(again.text) == str(person.text)), ("absent_side", True))
        # edge (a): a hold with no `opened` still asks and records under the empty key
        blind = driver_for(root, env, "QA-5")
        blind.state.pop("absent_side_answers", None)
        real = pipeline_of(task_root)
        blind.pipeline = lambda: {**real, "awaiting": {"since": "t", "cause": "s5_absent_side", "held_from": "S6"}}
        asked = _bare_relaunch(blind)
        check_eq("B3 edge (a): a hold with no `opened` asks, never skips, and records under the empty key",
                 (getattr(asked, "kind", asked), blind.state["absent_side_answers"]["opened"]), ("absent_side", ""))
    finally:
        harness.cleanup(root)
    # other words are the conductor's: nothing is changed by code
    root, task_root, env, driver, person = absent_story("QA-5")
    try:
        unread = []
        driver.unread = lambda *a, **k: unread.append((a, k))
        got = driver._answer_absent_side("the platform team might finish it next week", "q", "S6")
        check_eq("B3: other words are read by no code: the conductor once, the hold and the side stand",
                 (got, len(unread), bool(pipeline_of(task_root).get("awaiting")), pipeline_of(task_root)["sides"]["api"]["deliverable"]),
                 (False, 1, True, True))
    finally:
        harness.cleanup(root)
    # several absent sides: the question is about ONE side and the answer never changes another (edge 2)
    root, task_root, env, driver, person = absent_story("QA-5", sides=("api", "ui"))
    try:
        check_eq("B3: two absent sides: one question, over the first by name", driver.state.get("absent_side"), "api")
        answer_of(driver, root, "not ours")
        record = pipeline_of(task_root)
        check_eq("B3: the answer for `api` leaves `ui` absent and ours (it parks the story again, asked on its own)",
                 (record["sides"]["api"]["deliverable"], record["sides"]["ui"]["reality"], record["sides"]["ui"]["deliverable"],
                  contract.parks_after_s5(record)), (False, ABSENT, True, True))
    finally:
        harness.cleanup(root)
    # B-2 (t-2562): `relaunch` on the first side still asks the second, in the same process; `not ours` on it leaves the first waiting
    root, task_root, env, driver, person = absent_story("QA-5", sides=("api", "ui"))
    try:
        answer_of(driver, root, "relaunch")
        second = _bare_relaunch(driver)
        check_eq("B3 B-2: after `relaunch` on `api` the next `where` asks about `ui` in the same process",
                 (getattr(second, "kind", second), driver.state.get("absent_side")), ("absent_side", "ui"))
        check("B3 B-2: ... with the original text over `ui`", "called `ui`" in str(second.text) and "you said" not in str(second.text), str(second.text)[:300])
        answer_of(driver, root, "not ours")
        record = pipeline_of(task_root)
        check_eq("B3 B-2: `not ours` on `ui` makes `ui` substituted and leaves `api` waiting (absent, ours, the story parks again)",
                 (record["sides"]["ui"]["reality"], record["sides"]["ui"]["deliverable"], record["sides"]["api"]["reality"],
                  record["sides"]["api"]["deliverable"], contract.parks_after_s5(record)), (SUBSTITUTED, False, ABSENT, True, True))
        # all sides answered `relaunch` in one process: nothing more is asked there (today's exit)
        root2, task_root2, env2, driver2, person2 = absent_story("QA-6", sides=("api", "ui"))
        try:
            answer_of(driver2, root2, "relaunch")
            _bare_relaunch(driver2)                       # asks about `ui`
            answer_of(driver2, root2, "relaunch")
            check_eq("B3 B-2: every side answered `relaunch`: nothing is asked, exit 0", _bare_relaunch(driver2), story_run.EXIT_DONE)
        finally:
            harness.cleanup(root2)
    finally:
        harness.cleanup(root)
    # an experiment keeps the answer in the story only; an unreadable registry is said in words and the answer stays in the story (AR-28)
    for label, prepare, line in (("--no-trace", lambda r, d: d.state.setdefault("launch", {}).update(no_trace=True),
                                  "your answer about api was kept for this story only (an experiment leaves no trace)"),
                                 ("an unreadable registry", lambda r, d: (PK.record_path(r).parent.mkdir(parents=True, exist_ok=True),
                                                                          PK.record_path(r).write_text("{not json", encoding="utf-8")),
                                  "your answer about api was kept for this story only: the project's record of sides")):
        root, task_root, env, driver, person = absent_story("QA-5")
        try:
            prepare(root, driver)
            said = answer_of(driver, root, "not ours")
            record = pipeline_of(task_root)
            check_eq(f"B3 {label}: the answer is kept in the story and the hold is lifted",
                     (record["sides"]["api"]["deliverable"], "awaiting" in record), (False, False))
            check(f"B3 {label}: and one line says it was kept for this story only", line in said, said[-400:])
            check(f"B3 {label} (F-1): ... and the line is in pipeline.warnings, where the report and gate A read it",
                  any(line in str(w) for w in record.get("warnings") or []), str(record.get("warnings"))[:300])
            if label == "--no-trace":
                check_eq("B3 --no-trace: nothing is written to the registry", PK.record_path(root).exists(), False)
        finally:
            harness.cleanup(root)


def _today() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d")


def _bare_relaunch(driver):
    """The recorded hold met again with no flag (`awaiting_implementation`): the exit code of the `Stop` (the packet, nothing asked), or the
    `Person` raised (the question)."""
    import story_run
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            driver._act_await_implementation({"action": "awaiting_implementation", "cause": "s5_absent_side", "held_from": "S6"})
    except story_run.Stop as stop:
        return stop.code
    except story_run.Person as raised:
        return raised
    return -2


word_cases()
reader_cases()
registry_cases()
driver_cases()
absent_side_cases()
parks_cases()
awaiting_cases()
stage_done_cases()
note_cases()
edge_cases()
bom_cases()
transition_cases()
harness.finish("test_story_sides")
