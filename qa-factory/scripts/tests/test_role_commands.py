"""P3: a refusal is an instruction, never a traceback — and never a silent pass.

Every command in `references/role-commands.json` takes a file a ROLE wrote. This runs each one
against a deliberately broken file and holds three rules on what comes back:

  1. it does not raise — a role cannot act on `KeyError: 'case'`;
  2. it does not accept it either — exit 0 on a broken input is the worse half, because the
     role goes on believing the file landed (an empty fragment bumped a manifest revision and
     printed a receipt);
  3. the refusal carries what to write and how to prove it — the registry's own two lines.

The registry is also checked for the things it claims: the script exists, `roles` names roles
that exist, and every command of a script whose `--help` we can read is in that help.

HF1-12 (the class of EP1-8: a card describes a form its parser refuses): the broken input proves only that
a refusal quotes the card. The other half is held here, for EVERY card: the card's own example - a spec
written exactly as the card says - is fed to its command, through `role_cli.run_guarded`, and ACCEPTED
(`accepted_example` keys, one per card). Where the card names a required item, removing it from the
example is a refusal that says so (a negative control per card); where the parser takes a different form
than the old card said, the key that pins the new form is named in a comment beside it. The card equals
`--help` word for word (the epilog). A card that promises less or more than its parser fails here.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import (PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project)

REGISTRY = json.loads((PLUGIN_ROOT / "references" / "role-commands.json").read_text(
    encoding="utf-8"))
COMMANDS = REGISTRY["commands"]

# One broken call per registered command. The file is the same empty object every time: the
# point is not to be creative, it is that the cheapest possible mistake a role makes must come
# back as an instruction. `args` is templated with the temp project's paths.
BROKEN = {
    "manual_evidence.py prepare": ["prepare", "--task-root", "{task}", "--input", "{bad}"],
    "manual_evidence.py write-block": ["write-block", "--task-root", "{task}", "--input", "{bad}"],
    "manual_evidence.py build": ["build", "--task-root", "{task}", "--case", "X", "--result", "pass", "--actual", "x"],
    "manual_evidence.py rejudge": ["rejudge", "--task-root", "{task}", "--case", "X", "--result", "pass", "--actual", "x"],
    "manual_capture.py ui": ["ui", "--task-root", "{task}", "--case", "X", "--steps-file", "{bad}"],
    "manual_capture.py app": ["app", "--task-root", "{task}", "--case", "X", "--steps-file", "{bad}"],
    "manual_capture.py http": ["http", "--task-root", "{task}", "--case", "X", "--method", "GET",
                               "--url", "http://localhost:1/"],
    # t-2003: the answer of the S7 analyst for a place; the broken call is the missing --dispatch/--place (a refusal through RefusingParser, with the card)
    "place_answers.py write": ["write", "--task-root", "{task}", "--file", "{bad}"],
    # t-2003: the walker's commands (qa-runner); `open`, `close` and `serve` are the driver's and have no row. The broken call is the missing
    # --walk (and --item) - a refusal through RefusingParser with the card; a walk that was never opened is held in walk_examples
    "walk_session.py open": ["open", "--task-root", "{task}"],
    "walk_session.py item": ["item", "--task-root", "{task}"],
    "walk_session.py step": ["step", "--task-root", "{task}"],
    "walk_session.py look": ["look", "--task-root", "{task}"],
    "walk_session.py final": ["final", "--task-root", "{task}"],
    "walk_session.py verdict": ["verdict", "--task-root", "{task}"],
    "walk_session.py claim": ["claim", "--task-root", "{task}"],
    "walk_session.py done": ["done", "--task-root", "{task}"],
    "walk_session.py status": ["status", "--task-root", "{task}"],
    # t-2277 FL-2: the walker's first look. `put`'s broken call is neither --file nor --null (the card shows --file only: --null is the driver's);
    # `show` without --task-root is a refusal through RefusingParser (with the card)
    "first_look.py put": ["put", "--task-root", "{task}"],
    "first_look.py show": ["show"],
    # t-2181 PC-9b: the runner's `reference_snapshot.py put`; the broken call is the missing --reference/--items-file (a refusal through RefusingParser, with the card)
    "reference_snapshot.py put": ["put", "--task-root", "{task}"],
    "manual_evidence.py export": ["export", "--task-root", "{task}", "--input", "{bad}",
                                  "--output", "{root}/exported.json"],
    "artifact_producer.py publish": ["publish", "--kind", "triage", "--task-root", "{task}",
                                     "--input", "{bad}"],
    # SC1-7: the broken call is the missing --input (a refusal through RefusingParser, with the card); a batch with a bad item
    # is a validator RESULT (valid: false), not a refusal, and is held in subprocess_examples
    "artifact_producer.py validate-batch": ["validate-batch", "--task-root", "{task}"],
    "manifest_put.py --fragment": ["--task", "QA-1", "--fragment", "{bad}"],
    "critic_rollcall.py --store": ["--task-root", "{task}", "--store", "{bad}"],
    "external_writes.py --record": ["--record", "{bad}"],
    "case_versions.py --pin": ["--task-root", "{task}", "--pin", "--case-file", "{bad}"],
    "plan_row.py": ["--task", "QA-1", "--task-root", "{task}", "--row", "TS-404",
                    "--set", "source_conflict=true"],
    # Both of these used to end in a traceback, which is why they are here: an empty object is a
    # specification with every field missing, and a bundle with nothing in it.
    "execution_fingerprint.py": ["{bad}"],
    "context_bundle.py": ["--validate", "{bad}"],
    # the request `{}` has none of the five keys: the refusal is the JSON line AND the card (R4, Q1)
    "red_sandbox.py --diagnostic": ["--diagnostic", "--repo", "{root}", "--request", "{bad}", "--task-root", "{task}"],
}


ACCEPTED: list = []        # the commands whose own example was fed to them and accepted (one key each)


def card(command: str) -> str:
    return COMMANDS[command]["input"]


def names(command: str, word: str) -> bool:
    """The card names `word` as a whole word - a flag, a field: `ref` is not `evidence_ref`."""
    return re.search(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", card(command)) is not None


def seen(proc) -> tuple:
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def accepted_example(command: str, code, text: str) -> None:
    """The one key per card: a spec written exactly as the card says goes through the command and lands."""
    ACCEPTED.append(command)
    check(f"{command}: its own example, written as the card says, is ACCEPTED", code == 0 and "Traceback" not in text,
          f"exit {code}: {text[-500:]}")


def refused(label: str, command: str, code, text: str, needle: str, quotes: bool = True) -> None:
    """A negative control: the example with one required item taken out is refused, and the refusal names it
    (and, where the command refuses through role_cli, quotes the card)."""
    check(f"{label}: refused (exit {code}), not accepted and not a traceback",
          code not in (0, None) and "Traceback" not in text, text[-400:])
    check_in(f"{label}: and the refusal names {needle!r}", needle, text)
    if quotes:
        check_in(f"{label}: and quotes the card", card(command), text)


def card_names(command: str, *words: str) -> None:
    for word in words:
        check(f"{command}: the card names {word}", names(command, word), card(command))


def subprocess_examples(root: Path) -> None:
    """The cards whose command is a script run: each gets the minimal story its example needs."""
    import os
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))

    def story(ticket: str, pipeline: dict | None = None) -> Path:
        path = root / "qa-factory" / "artifacts" / ticket
        (path / "work").mkdir(parents=True)
        (path / "pipeline.json").write_text(json.dumps(pipeline or {"ticket": ticket}), encoding="utf-8")
        return path

    # --- manifest_put.py --fragment: a fragment with one manifest key -----------------------------------------
    command = "manifest_put.py --fragment"
    story("QA-2")
    fragment = root / "fragment.json"
    fragment.write_text(json.dumps({"review_receipt_ref": "work/review.md"}), encoding="utf-8")
    accepted_example(command, *seen(run_script("manifest_put.py", "--task", "QA-2", "--fragment", fragment, cwd=root)))
    fragment.write_text(json.dumps({"revision": 9, "note": "no rows"}), encoding="utf-8")
    refused("manifest_put: a fragment with only its bookkeeping keys", command,
            *seen(run_script("manifest_put.py", "--task", "QA-2", "--fragment", fragment, cwd=root)), "no manifest keys")

    # --- critic_rollcall.py --store: only together with --apply-fixes -----------------------------------------
    command = "critic_rollcall.py --store"
    task = root / "qa-factory" / "artifacts" / "QA-2"
    accepted_example(command, *seen(run_script("critic_rollcall.py", "--task-root", task, "--apply-fixes", "--store",
                                               root / "case-store", cwd=root)))
    refused("critic_rollcall: --store without --apply-fixes", command,
            *seen(run_script("critic_rollcall.py", "--task-root", task, "--store", root / "case-store", cwd=root)),
            "--apply-fixes")
    card_names(command, "--apply-fixes")

    # --- case_versions.py --pin: a case id and a version that already exists in the store ---------------------
    command = "case_versions.py --pin"
    import case_versions as V
    source = root / "authoring" / "TC-100.md"
    source.parent.mkdir()
    source.write_text("---\nid: TC-100\nstatus: Draft\ntask: QA-2\n---\nRequirements: R-1\nPlan row: TS-1\n# one\n",
                      encoding="utf-8")
    store = root / "case-versions"
    version = V.create_version(store, source)["version"]
    accepted_example(command, *seen(run_script("case_versions.py", "--task-root", task, "--store", store,
                                               "--pin", "TC-100", version, cwd=root)))
    refused("case_versions: a version the store does not hold", command,
            *seen(run_script("case_versions.py", "--task-root", task, "--store", store, "--pin", "TC-100", "cv_nope",
                             cwd=root)), "no immutable version cv_nope")
    card_names(command, "--case-file")

    # --- execution_fingerprint.py: the six keys, paths or {path, sha256} records ------------------------------
    command = "execution_fingerprint.py"
    test_file, config_file = root / "test_one.py", root / "config.json"
    test_file.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    config_file.write_text("{}", encoding="utf-8")
    spec = {"source_revision": "abc", "test_files": [str(test_file)], "config_files": [str(config_file)],
            "dependency_files": [], "runtime_provenance": {
                "result": "not_applicable", "profile_id": "unit", "environment_id": "local",
                "expected_source_revision": "abc", "timestamp": "2026-10-23T00:00:00Z", "evidence_refs": []},
            "profile_id": "unit"}
    spec_file = root / "spec.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")
    accepted_example(command, *seen(run_script("execution_fingerprint.py", spec_file, cwd=root)))
    for key in ("source_revision", "test_files", "config_files", "dependency_files", "runtime_provenance",
                "profile_id"):
        spec_file.write_text(json.dumps({k: v for k, v in spec.items() if k != key}), encoding="utf-8")
        refused(f"execution_fingerprint: the spec without {key}", command,
                *seen(run_script("execution_fingerprint.py", spec_file, cwd=root)), key)
        card_names(command, key)

    # --- context_bundle.py: built from a v2 manifest, then --validate ------------------------------------------
    command = "context_bundle.py"
    import context_bundle as C
    (root / "src").mkdir()
    (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    manifest = {"ticket": "QA-2", "implementations": [{"repo_id": "app", "source_sha": "abc"}], "changed_areas": ["src"],
                "existing_coverage": [{"test": "tests/test_a.py"}], "constraints": [],
                "facts": [{"id": "R-1", "path": "src/a.py", "range": "1"}],
                "known_paths": ["src/a.py"], "unresolved_facts": [],
                "requirement_sources": [{"source_id": "SRC-1", "relation": "subject", "ref": "STORY-1", "revision": "7",
                                         "status": "read", "evidence_ref": "snapshot.json"}],
                "coverage_search": [{"repo": "app", "revision": "abc", "changed_area": "src", "searched_paths": ["tests"],
                                     "status": "complete", "reason": "bounded changed area"}],
                "existing_test_candidates": [{"candidate_id": "C-1", "repo": "app", "revision": "abc",
                                              "path": "tests/test_a.py", "selector": "test_a", "parameter_ids": [],
                                              "level": "unit", "assertion_refs": ["tests/test_a.py:4"],
                                              "candidate_requirement_refs": ["R-1"], "origin": "existing",
                                              "result_candidate_refs": []}]}
    manifest_file, bundle_file = root / "context-manifest.json", root / "work" / "context-bundle.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    built = run_script("context_bundle.py", "--manifest", manifest_file, "--output", bundle_file, "--root", root, cwd=root)
    check_eq("context_bundle: the manifest of the card builds a v2 bundle (exit 0)", built.returncode, 0)
    accepted_example(command, *seen(run_script("context_bundle.py", "--validate", bundle_file, cwd=root)))
    bundle = json.loads(bundle_file.read_text(encoding="utf-8"))
    # The card lists the fields the parser requires: taking out any one field of a record is refused exactly when the
    # card names it (a field refused but not named = the card promises less; named but not refused = it promises more).
    for list_key in ("requirement_sources", "coverage_search", "existing_test_candidates"):
        for field in manifest[list_key][0]:
            record = {k: v for k, v in bundle[list_key][0].items() if k != field}
            try:
                C.validate_bundle(dict(bundle, **{list_key: [record]}))
                said = False
            except ValueError as exc:
                said = field in str(exc)
            check(f"context_bundle: {list_key}.{field} is {'refused when missing' if names(command, field) else 'not required'}"
                  " exactly as the card says", said == names(command, field),
                  f"card names it: {names(command, field)}; the parser refuses without it by name: {said}")
    for list_key in ("requirement_sources", "coverage_search", "existing_test_candidates"):
        check_in(f"context_bundle: the card names {list_key}", list_key, card(command))
    broken = dict(bundle, requirement_sources=[dict(bundle["requirement_sources"][0], relation="mentioned")])
    bad_file = root / "work" / "bad-bundle.json"
    bad_file.write_text(json.dumps(broken), encoding="utf-8")
    refused("context_bundle: a relation outside the closed list", command,
            *seen(run_script("context_bundle.py", "--validate", bad_file, cwd=root)),
            "relation must be one of " + ", ".join(sorted(C.SOURCE_RELATIONS)))

    # --- artifact_producer.py publish ---------------------------------------------------------------------------
    command = "artifact_producer.py publish"
    task4 = story("QA-4")
    record = root / "triage-record.json"
    record.write_text(json.dumps({"triage": []}), encoding="utf-8")

    def publish(*extra, kind="triage", path="work/triage.json"):
        return seen(run_script("artifact_producer.py", "publish", "--kind", kind, "--task-root", task4, "--path", path,
                               "--input", record, *extra, cwd=root))

    accepted_example(command, *publish())
    refused("publish: over a file that exists, with no --expected-hash", command, *publish(), "previous sha256")
    existing = hashlib.sha256((task4 / "work" / "triage.json").read_bytes()).hexdigest()
    code, text = publish("--expected-hash", existing)
    check("publish: --expected-hash <sha256 of the current bytes> replaces the file, as the card says",
          code == 0 and '"valid": true' in text, text[-300:])
    refused("publish: a path outside work/", command, *publish(path="triage.json"), "under task/work")
    refused("publish: a name that is not the canonical one", command, *publish(path="work/other.json"),
            "canonical artifact filename")
    code, text = publish(kind="bug", path="bugs/BUG-1.md")
    check("publish: bugs/ is a legal place for a bug (the refusal, if any, is about the name or the record)",
          "under task/work" not in text, text[-300:])
    refused("publish: bugs/ is not a place for anything but a bug", command, *publish(path="bugs/triage.json"),
            "under task/work")
    refused("publish: without --path", command, *seen(run_script(
        "artifact_producer.py", "publish", "--kind", "triage", "--task-root", task4, "--input", record, cwd=root)),
        "--path is missing")
    code, text = seen(run_script("artifact_producer.py", "publish", "--task-root", task4, "--path", "work/triage.json",
                                 "--input", record, cwd=root))
    refused("publish: without --kind (argparse's own refusal)", command, code, text, "--kind", quotes=False)
    card_names(command, "--kind", "--task-root", "--path", "--input", "--expected-hash", "requirements-readiness.json",
               "triage.json")

    # --- artifact_producer.py validate-batch: {"artifacts": [{kind, path, data}]} (SC1-7, E14) ---------------------
    command = "artifact_producer.py validate-batch"
    batch = root / "batch.json"
    batch.write_text(json.dumps({"artifacts": [{"kind": "triage", "path": "work/triage.json", "data": {"triage": []}}]}),
                     encoding="utf-8")
    code, text = seen(run_script("artifact_producer.py", "validate-batch", "--task-root", task4, "--input", batch, cwd=root))
    accepted_example(command, code, text)
    check_in("validate-batch: the card's batch is valid", '"valid": true', text)
    batch.write_text(json.dumps({"artifacts": [{"kind": "triage", "path": "work/triage.json", "input": "x.json"}]}),
                     encoding="utf-8")
    refused("validate-batch: an item keyed input, with no data", command,
            *seen(run_script("artifact_producer.py", "validate-batch", "--task-root", task4, "--input", batch, cwd=root)),
            'keys given: input, kind, path', quotes=False)
    card_names(command, "--task-root", "--input", "artifacts", "kind", "path", "data")

    # --- external_writes.py --record -----------------------------------------------------------------------------
    command = "external_writes.py --record"
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))

    def record_story(ticket: str, approved: bool, extra: dict | None = None) -> Path:
        art = story(ticket, {"ticket": ticket, "gates": ({"B": {"decision": "approve"}} if approved else {})})
        (art / "proposals").mkdir()
        proposal = art / "proposals" / "bug-1.json"
        proposal.write_text(json.dumps(dict({"kind": "bug", "bug_file": "bugs/BUG-9.md", "action": "create",
                                             "fields": {}, "witness": {}}, **(extra or {}))), encoding="utf-8")
        return proposal

    def record(proposal: Path, *extra):
        return seen(run_script("external_writes.py", "--record", proposal, *extra, cwd=root, env=env))

    proposal = record_story("QA-5", True)
    refused("external_writes: --record with no --external-id", command, *record(proposal), "--external-id", quotes=False)
    code, text = record(proposal, "--external-id", "TP1-4242", "--url", "http://tracker.example/TP1-4242")
    accepted_example(command, code, text)
    check_eq("external_writes: the id is on the proposal as the result",
             json.loads(proposal.read_text(encoding="utf-8")).get("result", {}).get("external_id"), "TP1-4242")
    code, text = record(proposal, "--external-id", "TP1-4242")
    check("external_writes: a proposal that already holds a result is skipped (exit 0), as the card says",
          code == 0 and "already recorded" in text, text[-300:])
    refused("external_writes: before the write is authorized (no gate decision)", command,
            *record(record_story("QA-6", False), "--external-id", "X-1"), "REFUSED", quotes=False)
    keyed = record_story("QA-7", True, {"publication_key": "key-1"})
    refused("external_writes: a proposal with a publication_key and no --remote-revision", command,
            *record(keyed, "--external-id", "X-2"), "--remote-revision", quotes=False)
    code, text = record(keyed, "--external-id", "X-2", "--remote-revision", "r1")
    check("external_writes: with --remote-revision the keyed proposal is recorded", code == 0, text[-300:])
    refused("external_writes: a proposal outside any story", command,
            *record(root / "broken.json", "--external-id", "X-3"), "not inside a story")
    card_names(command, "--external-id", "--url", "--remote-revision", "publication_key", "lifecycle_key")

    # --- plan_row.py ---------------------------------------------------------------------------------------------
    command = "plan_row.py"
    task8 = story("QA-8")
    words = {"w_yes": "yes", "w_on": "on", "w_one": "1", "w_true": "true", "w_no": "no", "w_off": "off", "w_zero": "0",
             "w_false": "false", "w_seven": "7", "w_negative": "-3", "w_text": "hello"}
    rows = [{"id": "TS-1", "title": "a", **{key: None for key in words}},
            {"id": "TS-2", "title": "b", **{key: None for key in words}}]
    plan = task8 / "work" / "test-plan.json"
    plan.write_text("{\n \"rows\": [\n" + ",\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n ]\n}\n",
                    encoding="utf-8")

    def plan_row(*extra, task="QA-8"):
        return seen(run_script("plan_row.py", *(["--task", task] if task else []), "--task-root", task8, *extra, cwd=root))

    sets = [part for key, word in words.items() for part in ("--set", f"{key}={word}")]
    accepted_example(command, *plan_row("--row", "TS-1", *sets))
    row = json.loads(plan.read_text(encoding="utf-8"))["rows"][0]
    for key, word, expected in (("w_yes", "yes", True), ("w_on", "on", True), ("w_one", "1", True), ("w_true", "true", True),
                                ("w_no", "no", False), ("w_off", "off", False), ("w_zero", "0", False),
                                ("w_false", "false", False), ("w_seven", "7", 7), ("w_negative", "-3", -3),
                                ("w_text", "hello", "hello")):
        check_eq(f"plan_row: --set {key}={word} is written as {expected!r}", row[key], expected)
        if word not in ("7", "-3", "hello"):
            check(f"plan_row: the card lists `{word}` among the words it turns into a boolean",
                  names(command, f"`{word}`"), card(command))
    check_not_in("plan_row: the card does not say digits become numbers (1 and 0 are booleans)", "digits as numbers",
                 card(command))
    check_eq("plan_row: the other row is untouched", json.loads(plan.read_text(encoding="utf-8"))["rows"][1]["w_yes"], None)
    refused("plan_row: a field the row does not have", command, *plan_row("--row", "TS-2", "--set", "nope=1"), "nope")
    refused("plan_row: without --task (argparse's own refusal)", command, *plan_row("--row", "TS-2", task=""), "--task",
            quotes=False)
    code, text = plan_row("--add-row", json.dumps({"id": "TS-3", "title": "c", **{key: None for key in words}}))
    check("plan_row: --add-row appends the row you wrote, as the card says", code == 0 and "TS-3" in text, text[-300:])
    refused("plan_row: --add-row of a row without a field every other row carries", command,
            *plan_row("--add-row", json.dumps({"id": "TS-4", "w_yes": True})), "title")
    card_names(command, "--task", "--task-root", "--row", "--set", "--add-row")

    # --- place_answers.py write: an answer of the analyst for a place of its own (t-2003) ------------------------------------
    command = "place_answers.py write"
    task9 = story("QA-9")
    place = "new-role-cmd"
    folder = task9 / "work" / "evidence" / "manual" / f"settle-{place}" / "a1"
    folder.mkdir(parents=True)
    (folder / "001-page.txt").write_text("Total: 10.5 EUR", encoding="utf-8")
    row = {"path": (folder / "001-page.txt").relative_to(task9).as_posix(), "kind": "page", "phase": "post_action",
           "content_hash": hashlib.sha256((folder / "001-page.txt").read_bytes()).hexdigest()}
    (folder / "captures.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    answer = {"place": place, "answer": "impossible", "expectation": {"source": "none", "id": "", "quote": ""},
              "seen": {"quote": "Total: 10.5", "capture": row["path"]}, "why": "the stand has no such page"}
    answer_file = root / "answer.json"

    def place_write(record, *extra):
        answer_file.write_text(json.dumps(record), encoding="utf-8")
        return seen(run_script("place_answers.py", "write", "--task-root", task9, "--dispatch", "S7-qa-failure-analyst-1",
                               "--place", place, "--file", answer_file, *extra, cwd=root))

    refused("place_answers: an impossible answer with no `why`", command,
            *place_write({k: v for k, v in answer.items() if k != "why"}), "why")
    accepted_example(command, *place_write(answer))
    check("place_answers: the record the card names is on disk",
          (task9 / "evidence" / f"place-answer-{place}.json").is_file())
    refused("place_answers: a second answer for the same place without --replace", command, *place_write(answer), "--replace")
    card_names(command, "--task-root", "--dispatch", "--place", "--file", "--replace", "expectation", "seen", "question", "why", "draft")


def first_look_examples() -> None:
    """The cards of `first_look.py put` and `first_look.py show` (t-2277 FL-2): a story with a register, an opened first-look attempt and a
    capture of the walk is fed the rows file exactly as the `put` card says and ACCEPTED (exit 0, written true); a file with one requirement
    missing is a refusal with its door; `show` prints the record. The calls go through `first_look.main` (`role_cli.run_guarded`)."""
    import contextlib
    import io
    import tempfile
    import test_first_look as T
    FL = T.FL

    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = FL.main(list(argv))
        return code, out.getvalue(), err.getvalue()
    with tempfile.TemporaryDirectory() as tmp:
        s = T.Story(tmp)
        caps = s.ready()
        base = ["--task-root", str(s.task)]
        command = "first_look.py put"
        rows = s.rows(caps)
        code, out, err = run("put", *base, "--file", str(s.file({"rows": rows[:1]})))
        refused("first_look put: a file with no row for R-2", command, code, out + err, "no row for R-2", quotes=False)
        code, out, err = run("put", *base, "--file", str(s.file({"rows": rows})))
        accepted_example(command, code, out + err)
        check_in("first_look put: the printed JSON says written true", '"written": true', out)
        check("first_look put: the record the card names is on disk", FL._record_path(s.task).is_file())
        card_names(command, "--task-root", "--file", "rows", "blocked_by", "evidence", "quote", "gaps")
        check("first_look put: the card does not offer --null to the walker", not names(command, "--null") or "no --null for you" in card(command))
        command = "first_look.py show"
        code, out, err = run("show", *base)
        accepted_example(command, code, out + err)
        check_in("first_look show: a line per requirement", "R-1 | confirms", out)
        card_names(command, "--task-root", "--json")


def reference_snapshot_example() -> None:
    """The card of `reference_snapshot.py put` (t-2181 PC-9b): an items file with one item that cites an old test, written as the card says,
    is ACCEPTED (exit 0, the snapshot is on disk); an item with no evidence and no old test is a refusal that writes nothing."""
    import contextlib
    import io
    import tempfile
    import reference_snapshot as RS
    command = "reference_snapshot.py put"
    item = {"id": "cart-total", "area": "cart", "user_path": "open the cart", "observed": "total 10", "old_test": "tests/cart.spec.ts:3",
            "locators_portable": "unknown"}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "qa-factory" / "artifacts" / "QA-1"
        (root / "work").mkdir(parents=True)
        (root / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")

        def run(items):
            f = Path(tmp) / "items.json"
            f.write_text(json.dumps(items), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = RS.main(["put", "--task-root", str(root), "--reference", "old", "--items-file", str(f)])
            return code, out.getvalue(), err.getvalue()
        code, out, err = run({"items": [{k: v for k, v in item.items() if k != "old_test"}], "gaps": []})
        check("reference_snapshot put: an item with no capture and no old test is refused, nothing written",
              code == 2 and not (root / "work" / "reference-snapshot.yaml").exists(), out + err)
        code, out, err = run({"items": [item], "gaps": []})
        accepted_example(command, code, out + err)
        check("reference_snapshot put: the snapshot the card names is on disk", (root / "work" / "reference-snapshot.yaml").is_file())
        card_names(command, "--task-root", "--reference", "--items-file", "--replace", "items", "gaps", "evidence", "old_test")


def diagnostic_example() -> None:
    """The card of `red_sandbox.py --diagnostic` (t-1508 R4, Q1), end to end on the world of test_red_sandbox_diagnostic: the
    request written exactly as the card says is ACCEPTED (a real run in a copy, exit 0, status passed); with one key of the five
    taken out it is refused, naming that key and quoting the card."""
    import test_red_sandbox_diagnostic as D
    command = "red_sandbox.py --diagnostic"
    root = D.world(D.TEST_RED)
    try:
        env = dict(__import__("os").environ, CLAUDE_PROJECT_DIR=str(root), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1",
                   PYTHONDONTWRITEBYTECODE="1")

        def call(path):
            import subprocess
            proc = subprocess.run([D.PYTHON, "-B", str(D.SELF), "--diagnostic", "--repo", str(root), "--request", str(path),
                                   "--task-root", str(D.P.task_of(root))], cwd=str(root), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=300, env=env)
            return seen(proc)
        path = D.request(root)
        card_names(command, *json.loads(path.read_text(encoding="utf-8")).keys())       # the card names every key the example holds
        code, text = call(path)
        accepted_example(command, code, text)
        check_in("red_sandbox --diagnostic: the accepted example ran and the Thens it kept are held", '"status": "passed"', text)
        doc = json.loads(path.read_text(encoding="utf-8"))
        for key in doc:
            path.write_text(json.dumps({k: v for k, v in doc.items() if k != key}), encoding="utf-8")
            code, text = call(path)
            refused(f"red_sandbox --diagnostic: the example without {key}", command, code, text, key)
    finally:
        D.P.finish_project(root)


class _FakeDevice:
    """The smallest scripted backend `manual_capture.py app` needs for two steps (a click and a post_action capture); the wiring
    is the factory's own, the device is a fake (nothing here proves a real driver, FR-33)."""

    def open(self, timeout_s, hosts, local_storage=None, element_wait_s=None):
        pass

    def close(self):
        pass

    def click(self, sel):
        return 0.1

    def screenshot(self, path):
        import manual_capture
        Path(path).write_bytes(manual_capture.PNG_SIGNATURE + b"fake-screen")
        return 0.1

    def page_words(self, mode=None):
        return "Home"

    def current_url(self):
        return "app://screen"

    def drain_failures(self):
        return {}


def app_example() -> None:
    """The card of `manual_capture.py app` (EP1-41f): the steps file written as the card says (a click, a capture) is ACCEPTED over a
    fake device on a project that describes a device stand; the same file with a web step the card does not list is refused."""
    import test_manual_capture as TMC
    S, MC = TMC.S, TMC.MC
    command = "manual_capture.py app"
    cfg = S.config()
    cfg["profiles"] = [{"profile_id": "android", "capabilities": ["native"],
                        "commands": {"one_test": {"argv": ["./gradlew", "test"], "cwd": "."}}}]
    cfg["execution"]["runtime_probes"]["android"] = {"argv": ["probe-android"], "cwd": ".", "timeout_s": 5}
    cfg["environments"] = [*cfg["environments"], {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:1"},
                                                  "app": {"id": "com.example.app"}}]
    t = S.make_task(cfg=cfg)
    try:
        MC.BACKEND_FACTORY, MC.HTTP, MC.MONOTONIC, MC.SLEEP = (lambda: _FakeDevice()), None, None, None
        MC.PROBE, MC.NOW = (lambda spec: S.probe("android")), S.Clock()
        steps = t.task / "steps-app.txt"
        steps.write_text("click id=submit\ncapture post_action completion\n", encoding="utf-8")
        code, out, err = S.run(["app", "--task-root", str(t.task), "--case", S.CASES["ui"], "--steps-file", str(steps)])
        accepted_example(command, code, out + err)
        card_names(command, "--task-root", "--case", "--steps-file", "--surface", "--attempt")
        steps.write_text("goto http://localhost:5173\n", encoding="utf-8")
        code, out, err = S.run(["app", "--task-root", str(t.task), "--case", S.CASES["ui"], "--steps-file", str(steps)])
        refused("manual_capture app: a web step the card does not list", command, code, out + err, "no such step on this surface",
                quotes=False)
    finally:
        S.cleanup(t)


def manual_examples() -> None:
    """The six manual-evidence cards, end to end on the scaffold of test_manual_capture (a fake browser and a fake
    HTTP client, a real task folder, the controller's state faked): prepare -> ui -> build -> write-block -> export,
    and http on the second case. Everything runs through `role_cli.run_guarded`, the way a role's call ends."""
    import test_manual_capture as TMC
    S, M = TMC.S, TMC.M
    t = S.make_task(manual=("ui", "api"))
    try:
        TMC.seed_runtime_records(t)
        # --- manual_evidence.py prepare: {case, obligation_ids} ---------------------------------------------------
        command = "manual_evidence.py prepare"
        wanted = t.task / "prepare-input.json"
        wanted.write_text(json.dumps({"case": TMC.UI_CASE, "obligation_ids": TMC.OBLIGATIONS[TMC.UI_CASE]}), encoding="utf-8")
        with t.patched():
            code, out, err = S.run(["prepare", "--task-root", str(t.task), "--input", str(wanted)], main=M.main, command=command)
        accepted_example(command, code, out + err)
        check("manual_evidence prepare: the request is where the runner reads it",
              (TMC.MC.case_root(t.task, TMC.UI_CASE) / "request.json").is_file())
        for key in ("case", "obligation_ids"):
            wanted.write_text(json.dumps({k: v for k, v in {"case": TMC.UI_CASE, "obligation_ids": ["OB-7"]}.items()
                                          if k != key}), encoding="utf-8")
            with t.patched():
                code, out, err = S.run(["prepare", "--task-root", str(t.task), "--input", str(wanted)], main=M.main,
                                       command=command)
            refused(f"manual_evidence prepare: the example without {key}", command, code, out + err, key)

        # --- manual_capture.py ui: the steps file --------------------------------------------------------------------
        command = "manual_capture.py ui"
        code, out, err, _ = TMC.ui_run(t)
        accepted_example(command, code, out + err)
        # HF1-12: the old card said the file STARTS with a goto; the parser takes a goto anywhere (and every goto must be
        # on a configured stand). The card follows the parser, and this pins both sides.
        check_not_in("manual_capture ui: the card no longer says the file starts with a goto", "starts with a goto", card(command))
        check_in("manual_capture ui: it says at least one goto, every goto on a configured stand", "at least one goto", card(command))
        code, out, err, _ = TMC.ui_run(t, steps=f"click \"button\"\ngoto {TMC.UI}\ncapture post_action completion\n")
        check("manual_capture ui: a file whose goto is not its first step is accepted, as the card says",
              code == 0, (out + err)[-300:])
        code, out, err, _ = TMC.ui_run(t, steps=f"goto {TMC.UI}\ngoto http://evil.example.test/\n")
        refused("manual_capture ui: a second goto off the configured stands", command, code, out + err, "Allowed hosts")
        code, out, err, _ = TMC.ui_run(t, steps="click \"button\"\ncapture post_action completion\n")
        refused("manual_capture ui: a file with no goto at all", command, code, out + err, "goto")

        # --- manual_evidence.py build: flags only ----------------------------------------------------------------------
        command = "manual_evidence.py build"
        # the attempt a3 is the last: build takes the latest attempt unless told. Refusals come first - the pass is last.
        for flag, args in (("--masked", ("--result", "pass", "--actual", "x")),
                           ("--actual", ("--result", "pass", "--masked")),
                           ("--result", ("--actual", "x", "--masked"))):
            with t.patched():
                code, out, err = S.run(["build", "--task-root", str(t.task), "--case", TMC.UI_CASE, *args], main=M.main,
                                       command=command)
            refused(f"manual_evidence build: the example without {flag}", command, code, out + err, flag)
        code, out, err = TMC.build(t, TMC.UI_CASE, "--result", "pass", "--actual", "the scale grew from 1 to 1.2", "--masked",
                                   "--attempt", "a1")
        accepted_example(command, code, out + err)
        card_names(command, "--masked", "--limitation", "--attempt", "--result", "--actual", "--then-quote", "--then-seen",
                   "--then-unreached", "--with-attempt")
        # a pass with no quote at all is refused and the refusal names the Then and its door (HF8-19: the card says so)
        with t.patched():
            code, out, err = S.run(["build", "--task-root", str(t.task), "--case", TMC.UI_CASE, "--result", "pass", "--actual", "x",
                                    "--masked"], main=M.main, command=command)
        refused("manual_evidence build: the example without a quote for a Then", command, code, out + err, "--then-quote")

        # --- manual_evidence.py rejudge: a new verdict over the evidence of the attempt `build` wrote ------------------------
        command = "manual_evidence.py rejudge"
        quote_flags = ["--then-seen", "1=the page after the action shows it", "--then-unreached", "2", "--then-unreached", "3"]
        base = ["--of-attempt", "a1", "--result", "fail", "--actual", "the pane did not move", "--reason", "the first look was wrong"]
        for flag, args in (("--reason", [a for a in base if a not in ("--reason", "the first look was wrong")]),
                           ("--of-attempt", base[2:]),
                           ("--result", [a for a in base if a not in ("--result", "fail")])):
            with t.patched():
                code, out, err = S.run(["rejudge", "--task-root", str(t.task), "--case", TMC.UI_CASE, *args, *quote_flags],
                                       main=M.main, command=command)
            refused(f"manual_evidence rejudge: the example without {flag}", command, code, out + err, flag)
        with t.patched():
            code, out, err = S.run(["rejudge", "--task-root", str(t.task), "--case", TMC.UI_CASE, *base, *quote_flags],
                                   main=M.main, command=command)
        accepted_example(command, code, out + err)
        card_names(command, "--of-attempt", "--reason", "--result", "--actual", "--then-quote", "--then-seen",
                   "--then-unreached", "--completion", "--limitation")
        # HF8-19 F6a: the card says --completion takes a PATH (the code refuses words), and an inconclusive needs --limitation
        check(f"{command}: the card says --completion is a path", "--completion <path>" in card(command), card(command))
        with t.patched():
            code, out, err = S.run(["rejudge", "--task-root", str(t.task), "--case", TMC.UI_CASE, "--of-attempt", "a1",
                                    "--result", "inconclusive", "--actual", "x", "--reason", "r"], main=M.main, command=command)
        refused("manual_evidence rejudge: an inconclusive without --limitation", command, code, out + err, "--limitation")

        # --- manual_evidence.py write-block / export: the record `build` wrote --------------------------------------------
        record_path = t.attempt_dir(TMC.UI_CASE, "a1") / "record.json"
        good = json.loads(record_path.read_text(encoding="utf-8"))

        def block(records, name="write-block"):
            path = t.task / "records.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            with t.patched():
                return S.run([name, "--task-root", str(t.task), "--input", str(path),
                              *(["--output", str(t.task / "exported.json")] if name == "export" else [])],
                             main=M.main, command=f"manual_evidence.py {name}")

        command = "manual_evidence.py write-block"
        code, out, err = block([good])
        accepted_example(command, code, out + err)
        code, out, err = block({"manual_checks": [good]})
        check("manual_evidence write-block: an object with manual_checks is the same input, as the card says",
              code == 0, (out + err)[-300:])
        # The card lists the fields of a record: taking out any one is refused exactly when the card names it.
        for field in good:
            code, out, err = block([{k: v for k, v in good.items() if k != field}])
            check(f"manual_evidence write-block: {field} is {'refused when missing' if names(command, field) else 'not required'}"
                  " exactly as the card says", (code != 0) == names(command, field),
                  f"card names it: {names(command, field)}; exit {code}: {(out + err)[-200:]}")
        for field in good["evidence_refs"][0]:
            refs = [{k: v for k, v in good["evidence_refs"][0].items() if k != field}, *good["evidence_refs"][1:]]
            code, out, err = block([dict(good, evidence_refs=refs)])
            check(f"manual_evidence write-block: evidence_refs[].{field} is {'refused when missing' if names(command, field) else 'not required'}"
                  " exactly as the card says", (code != 0) == names(command, field), (out + err)[-200:])
        code, out, err = block([good, dict(good, attempt_ended_at="2999-01-01T00:00:00+00:00")])
        refused("manual_evidence write-block: two records that do not share their timestamps", command, code, out + err,
                "share dispatch, attempt timestamps and head")

        # t-1711: `--observations-file` (the card names it); a list lands, a broken file is refused by name, no file = as before
        (t.task / "records.json").write_text(json.dumps([good]), encoding="utf-8")
        obs = t.task / "obs.json"
        for label, body, needle in (("a malformed file", "{", "obs.json"), ("an object, not a list", "{}", "JSON list")):
            obs.write_text(body, encoding="utf-8")
            with t.patched():
                code, out, err = S.run(["write-block", "--task-root", str(t.task), "--input", str(t.task / "records.json"),
                                        "--observations-file", str(obs)], main=M.main, command=command)
            refused(f"manual_evidence write-block --observations-file: {label}", command, code, out + err, needle)
        obs.write_text("[]", encoding="utf-8")
        with t.patched():
            code, out, err = S.run(["write-block", "--task-root", str(t.task), "--input", str(t.task / "records.json"),
                                    "--observations-file", str(obs)], main=M.main, command=command)
        check("manual_evidence write-block --observations-file: a list ([]) is accepted", code == 0, (out + err)[-300:])
        card_names(command, "--observations-file")
        card_names("manual_evidence.py build", "--observations-file")
        # t-1754 (critic F11): the cards say what --session does -- calls of one --profile join one open attempt; `http` carries
        # the cookies only in that attempt and opens its own (signing in again) without --profile
        card_names("manual_capture.py ui", "--session", "session close", "calls of one --profile join one open attempt")
        card_names("manual_capture.py http", "--session", "only in the same --profile's open attempt", "signs in again")

        command = "manual_evidence.py export"
        code, out, err = block([good], "export")
        accepted_example(command, code, out + err)
        check("manual_evidence export: --output holds the public copies, one row for the record",
              len(json.loads((t.task / "exported.json").read_text(encoding="utf-8"))["rows"]) == 1)
        path = t.task / "records.json"
        with t.patched():
            code, out, err = S.run(["export", "--task-root", str(t.task), "--input", str(path)], main=M.main, command=command)
        refused("manual_evidence export: the example without --output (argparse's own refusal)", command, code, out + err,
                "--output", quotes=False)
        card_names(command, "--output", "--input", "validate")
        code, out, err = block([], "export")
        refused("manual_evidence export: an empty list", command, code, out + err, "nothing to export")

        # --- manual_capture.py http: flags only ----------------------------------------------------------------------------
        command = "manual_capture.py http"
        get = f"{TMC.LOCAL}/v1/workflows/w1"
        login = f"{TMC.LOCAL}/v1/local-auth/login"
        http = S.FakeHttp({("POST", login): S.ok_json({"access_token": S.TOKEN}),
                           ("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = TMC.http_run(t, http, "--method", "GET", "--url", get, "--state-url", get, "--proves", "completion")
        accepted_example(command, code, out + err)
        code, out, err = TMC.http_run(t, http, "--method", "GET")
        refused("manual_capture http: the example without --url", command, code, out + err, "--url")
        card_names(command, "--method", "--url", "--state-url", "--proves", "--phase", "--body-file", "--header")
    finally:
        S.cleanup(t)


def walk_examples() -> None:
    """The cards of the walker's seven commands (t-2003), end to end over a REAL loopback server (the walk is opened the way
    test_walk_session opens it: the server runs in a thread of this process, the recorder is the scripted fake of that test - no browser,
    no network). Every call goes through `role_cli.run_guarded` like a role's call. `close` is the driver's: no row; `open` has the analyst's
    reopen row (t-1991 U3b; the example opens a case lane, the card's call differs only by `--place settle`)."""
    import threading
    import test_walk_record as WR
    import test_walk_session as W
    WS, S, CASE = W.WS, W.S, W.CASE
    rig = W.Rig()
    try:
        def spawn(argv, log):
            thread = threading.Thread(target=WS.main, args=(argv[3:],), daemon=True)
            thread.start()
            return thread
        WS.SEAMS["spawn"] = spawn
        WR.request(rig, thens=("1",))
        base = ["--task-root", str(rig.t.task), "--walk", W.WALK]

        def go(name, *extra):
            return S.run([name, *base, *extra], main=WS.main, command=f"walk_session.py {name}")

        command = "walk_session.py open"
        code, out, err = S.run(["open", *base, "--actor", "user"], main=WS.main, command=command)
        refused("walk open: the example without --items", command, code, out + err, "--items")
        code, out, err = go("open", "--items", CASE, "--actor", "user")
        accepted_example(command, code, out + err)
        card_names(command, "--task-root", "--walk", "--place", "--items", "--actor")

        command = "walk_session.py item"
        code, out, err = go("item", "--item", CASE)
        accepted_example(command, code, out + err)
        code, out, err = go("item", "--item", "TC-NOT-IN-THE-WALK")
        refused("walk item: an item that is not in the walk", command, code, out + err, "is not in walk")
        card_names(command, "--task-root", "--walk", "--item", "--as")

        command = "walk_session.py step"
        code, out, err = go("step", "--item", CASE)
        refused("walk step: neither --line nor --steps-file", command, code, out + err, "--steps-file")
        code, out, err = go("step", "--item", CASE, "--line", W.GO.strip())
        accepted_example(command, code, out + err)
        check_in("walk step: the answer is ONE JSON object with status done", '"status": "done"', out)
        card_names(command, "--task-root", "--walk", "--item", "--line", "--steps-file", "--as", "--stop-on", "--final")

        command = "walk_session.py look"
        code, out, err = go("look", "--item", CASE)
        accepted_example(command, code, out + err)
        card_names(command, "--task-root", "--walk", "--item", "--as", "--selector")

        steps = rig.t.task / "steps.txt"
        steps.write_text('click "#a"\n', encoding="utf-8")
        code, out, err = go("step", "--item", CASE, "--steps-file", str(steps))
        check("walk step: a --steps-file, as the card says, is accepted", code == 0, (out + err)[-300:])

        command = "walk_session.py final"
        code, out, err = go("final", "--item", CASE)
        accepted_example(command, code, out + err)
        card_names(command, "--task-root", "--walk", "--item", "--as")

        command = "walk_session.py claim"
        code, out, err = go("claim", "--item", CASE, "--instance", "17")
        refused("walk claim: the example without --kind", command, code, out + err, "--kind")
        code, out, err = go("claim", "--item", CASE, "--kind", "book", "--instance", "17")
        accepted_example(command, code, out + err)
        card_names(command, "--task-root", "--walk", "--item", "--kind", "--instance", "--all")

        command = "walk_session.py verdict"
        verdict = rig.t.task / "verdict.json"
        verdict.write_text(json.dumps({"thens": [{"n": 1, "result": "pass"}]}), encoding="utf-8")
        code, out, err = go("verdict", "--item", CASE, "--file", str(verdict))
        refused("walk verdict: a pass with no quote", command, code, out + err, "quote the capture")
        verdict.write_text(json.dumps({"thens": [{"n": 1, "result": "pass", "quote": "button: Pay"}], "observations": [], "teardown": "none"}),
                           encoding="utf-8")
        code, out, err = go("verdict", "--item", CASE, "--file", str(verdict))
        accepted_example(command, code, out + err)
        check("walk verdict: the result record the card names is on disk",
              (rig.t.task / "work" / "walks" / W.WALK / f"{CASE}.json").is_file())
        card_names(command, "--task-root", "--walk", "--item", "--file", "thens", "observations", "teardown", "pass", "unreached")

        command = "walk_session.py done"
        code, out, err = go("done")
        accepted_example(command, code, out + err)
        card_names(command, "--task-root", "--walk")

        command = "walk_session.py status"
        code, out, err = go("status")
        accepted_example(command, code, out + err)
        check_in("walk status: the printed JSON says status ok and the walk's state", '"state": "ready"', out)
        code, out, err = S.run(["status", "--task-root", str(rig.t.task), "--walk", "S6-never-opened"], main=WS.main, command=command)
        refused("walk status: a walk that was never opened", command, code, out + err, "is unknown here")
        card_names(command, "--task-root", "--walk")

        code, out, err = go("close")
        check_eq("walk: the driver's close ends 0 (no row of its own)", code, 0)
    finally:
        WS.SEAMS.update(clock=None, spawn=None)
        rig.done()


def main() -> int:
    root = temp_project()
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
        bad = root / "broken.json"
        bad.write_text("{}", encoding="utf-8")
        fill = {"task": task, "bad": bad, "root": root}

        check("every registered command has a broken call to check it with",
              set(COMMANDS) == set(BROKEN),
              f"registry only: {sorted(set(COMMANDS) - set(BROKEN))}; "
              f"test only: {sorted(set(BROKEN) - set(COMMANDS))}")

        for command, row in sorted(COMMANDS.items()):
            script = command.split()[0]
            check(f"{command}: the script it names exists",
                  (PLUGIN_ROOT / "scripts" / script).is_file())
            check(f"{command}: it says what to write and how to prove it",
                  bool(row.get("input")) and bool(row.get("verify")))
            check(f"{command}: it names the roles that call it", bool(row.get("roles")))
            for role in row.get("roles") or []:
                check(f"{command}: {role} is a role of this factory",
                      (PLUGIN_ROOT / "agents" / f"{role}.md").is_file())

            args = [str(a).format(**fill) for a in BROKEN.get(command, [])]
            result = run_script(script, *args, cwd=root)
            output = (result.stdout or "") + (result.stderr or "")
            check(f"{command}: a broken input does not raise", "Traceback" not in output,
                  output[-400:])
            check(f"{command}: nor is it accepted", result.returncode != 0, output[-400:])
            # The instruction itself, by the registry's own words: the first sentence of each
            # line is enough to prove the role got the registry and not a bare message.
            check_in(f"{command}: the refusal says what to write",
                     row["input"].split(".")[0][:60], output)
            check_in(f"{command}: and how to prove it",
                     row["verify"].split(".")[0][:60], output)

        # --help before the first call, so the shape does not have to be learned by refusal.
        for script in sorted({c.split()[0] for c in COMMANDS}):
            helped = run_script(script, "--help", cwd=root)
            if helped.returncode != 0:
                continue                      # a script with no argparse --help is its own row
            for command, row in COMMANDS.items():
                if command.split()[0] != script:
                    continue
                check_in(f"{script} --help carries the shape of {command}",
                         row["input"].split(".")[0][:40], helped.stdout or "")
                # HF1-2/HF1-12: the whole card, word for word - the epilog repeats it, it is not a second text.
                check_in(f"{script} --help repeats the card of {command} word for word", row["input"],
                         helped.stdout or "")

        # --- HF1-12: every card's own example, fed to its command, is ACCEPTED -----------------------------------
        subprocess_examples(root)
    finally:
        cleanup(root)
    manual_examples()
    app_example()
    diagnostic_example()
    walk_examples()
    first_look_examples()
    reference_snapshot_example()
    check_eq("every one of the cards had its own example fed to its command and accepted (one key each)",
             sorted(ACCEPTED), sorted(COMMANDS))
    return finish("test_role_commands")


if __name__ == "__main__":
    sys.exit(main())
